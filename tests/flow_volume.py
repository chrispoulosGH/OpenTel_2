"""
Transaction Volume by Distinct Flow
=====================================
Fetches traces from Tempo, extracts the full ordered service path
(entry application -> intermediate services -> exit application)
for every trace, then aggregates and reports transaction volumes
by distinct flow.

Usage:
    cd c:/code/openTel_2/tests
    python flow_volume.py

Options:
    --tempo-url        Tempo base URL          (default: http://localhost:3200)
    --limit            Max traces to fetch     (default: 200)
    --last-hours       Look back N hours       (default: 6)
    --output           Optional CSV output path
    --no-proxy         If set, clears http_proxy env vars before requests

Example:
    python flow_volume.py --limit 500 --last-hours 12 --output flow_volumes.csv
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────
#  Span tree
# ─────────────────────────────────────────────

@dataclass
class SpanNode:
    span_id: str
    service_name: str
    parent_span_id: str
    start_ns: int
    attributes: Dict[str, str] = field(default_factory=dict)
    children: List["SpanNode"] = field(default_factory=list)


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_trace_ids(
    tempo_url: str,
    limit: int,
    start_unix_sec: Optional[int] = None,
    end_unix_sec: Optional[int] = None,
) -> List[str]:
    params: Dict = {"limit": limit}
    if start_unix_sec:
        params["start"] = start_unix_sec
    if end_unix_sec:
        params["end"] = end_unix_sec
    url = f"{tempo_url}/api/search?{urllib.parse.urlencode(params)}"
    print(f"  [search] {url}", flush=True)
    data = _fetch_json(url)
    return [t["traceID"] for t in data.get("traces", [])]


def fetch_spans(tempo_url: str, trace_id: str) -> List[SpanNode]:
    url = f"{tempo_url}/api/traces/{trace_id}"
    data = _fetch_json(url)
    nodes: List[SpanNode] = []
    for batch in data.get("batches", []):
        svc = "unknown"
        for attr in batch.get("resource", {}).get("attributes", []):
            if attr["key"] == "service.name":
                svc = attr["value"].get("stringValue", "unknown")
        for scope in batch.get("scopeSpans", []):
            for raw in scope.get("spans", []):
                attributes: Dict[str, str] = {}
                for attr in raw.get("attributes", []):
                    value = attr.get("value", {})
                    attr_value = (
                        value.get("stringValue")
                        or value.get("intValue")
                        or value.get("doubleValue")
                        or str(value.get("boolValue", ""))
                    )
                    attributes[attr["key"]] = str(attr_value)
                nodes.append(SpanNode(
                    span_id=raw["spanId"],
                    service_name=svc,
                    parent_span_id=raw.get("parentSpanId", ""),
                    start_ns=int(raw.get("startTimeUnixNano", 0)),
                    attributes=attributes,
                ))
    return nodes


def build_tree(spans: List[SpanNode]) -> Optional[SpanNode]:
    by_id = {s.span_id: s for s in spans}
    root = None
    for s in spans:
        pid = s.parent_span_id
        if not pid or pid not in by_id:
            # Pick earliest-starting span as root if multiple candidates
            if root is None or s.start_ns < root.start_ns:
                root = s
        else:
            by_id[pid].children.append(s)
    return root


# ─────────────────────────────────────────────
#  Path extraction
# ─────────────────────────────────────────────

def extract_service_paths(root: SpanNode) -> List[List[str]]:
    """Return all root-to-leaf service paths with consecutive duplicates collapsed."""
    paths: List[List[str]] = []

    def walk(span: SpanNode, path: List[str]):
        # Collapse consecutive same-service spans
        if not path or path[-1] != span.service_name:
            path = path + [span.service_name]

        if not span.children:
            if len(path) >= 1:
                paths.append(path)
            return
        for child in span.children:
            walk(child, path)

    walk(root, [])
    return paths


def canonical_flow(paths: List[List[str]]) -> Tuple[str, str, str]:
    """
    Given root-to-leaf service paths from a single trace, derive:
      entry_service   — root service (first element in every path)
      exit_service    — all unique leaf services (last element of each path)
      full_signature  — ordered deduplicated service chain across all paths
    """
    if not paths:
        return ("unknown", "unknown", "unknown")

    entry = paths[0][0]

    # Collect all unique services in BFS order across paths (preserving first-seen)
    seen: Dict[str, int] = {}
    for path in paths:
        for svc in path:
            if svc not in seen:
                seen[svc] = len(seen)
    ordered = sorted(seen, key=lambda s: seen[s])
    signature = " -> ".join(ordered)

    # Exit services: leaf of each path, deduplicated preserving order
    exits_seen: Dict[str, int] = {}
    for path in paths:
        leaf = path[-1]
        if leaf not in exits_seen:
            exits_seen[leaf] = len(exits_seen)
    exit_svc = ", ".join(sorted(exits_seen, key=lambda s: exits_seen[s]))

    return (entry, exit_svc, signature)


def extract_chain_id(root: SpanNode) -> str:
    stack = [root]
    while stack:
        span = stack.pop()
        for key, value in span.attributes.items():
            key_lower = key.lower()
            if key_lower in {"chain_id", "chain.id", "chain-id", "chainid"} and value:
                return value
        stack.extend(span.children)
    return "unknown"


# ─────────────────────────────────────────────
#  Main aggregation
# ─────────────────────────────────────────────

@dataclass
class FlowStats:
    chain_id: str
    entry: str
    exit: str
    signature: str
    count: int = 0
    trace_ids: List[str] = field(default_factory=list)


def aggregate(
    tempo_url: str,
    limit: int,
    last_hours: float,
) -> List[FlowStats]:
    now_sec = int(time.time())
    start_sec = int(now_sec - last_hours * 3600)

    print(f"Fetching up to {limit} traces from the last {last_hours}h ...", flush=True)
    trace_ids = fetch_trace_ids(tempo_url, limit, start_sec, now_sec)
    print(f"Found {len(trace_ids)} traces.", flush=True)

    flow_map: Dict[Tuple[str, str], FlowStats] = {}
    errors = 0
    for i, tid in enumerate(trace_ids, 1):
        try:
            spans = fetch_spans(tempo_url, tid)
            root = build_tree(spans)
            if root is None:
                continue
            paths = extract_service_paths(root)
            chain_id = extract_chain_id(root)
            entry, exit_svc, sig = canonical_flow(paths)
            flow_key = (chain_id, sig)
            if flow_key not in flow_map:
                flow_map[flow_key] = FlowStats(chain_id=chain_id, entry=entry, exit=exit_svc, signature=sig)
            flow_map[flow_key].count += 1
            flow_map[flow_key].trace_ids.append(tid)
        except Exception as exc:
            errors += 1
            print(f"  [warn] trace {tid}: {exc}", flush=True)
        if i % 50 == 0:
            print(f"  processed {i}/{len(trace_ids)} ...", flush=True)

    if errors:
        print(f"  {errors} traces could not be processed.", flush=True)

    return sorted(flow_map.values(), key=lambda f: -f.count)


def print_table(stats: List[FlowStats]):
    if not stats:
        print("No flows found.")
        return

    col_chain  = max(len("Test Flow"),      max(len(f.chain_id)  for f in stats))
    col_entry  = max(len("Entry Service"),  max(len(f.entry)     for f in stats))
    col_exit   = max(len("Exit Service(s)"), max(len(f.exit)      for f in stats))
    col_count  = max(len("Transactions"),    max(len(str(f.count)) for f in stats))
    col_sig    = max(len("Flow Signature"),  max(len(f.signature) for f in stats))

    # Limit signature column width to avoid very wide tables
    col_sig = min(col_sig, 80)

    sep = f"+-{'-'*col_chain}-+-{'-'*col_entry}-+-{'-'*col_exit}-+-{'-'*col_count}-+-{'-'*col_sig}-+"
    hdr = f"| {'Test Flow':<{col_chain}} | {'Entry Service':<{col_entry}} | {'Exit Service(s)':<{col_exit}} | {'Transactions':>{col_count}} | {'Flow Signature':<{col_sig}} |"
    print(sep)
    print(hdr)
    print(sep)
    for f in stats:
        sig_display = f.signature if len(f.signature) <= col_sig else f.signature[:col_sig-3] + "..."
        row = f"| {f.chain_id:<{col_chain}} | {f.entry:<{col_entry}} | {f.exit:<{col_exit}} | {f.count:>{col_count}} | {sig_display:<{col_sig}} |"
        print(row)
    print(sep)
    print(f"\nTotal distinct flows : {len(stats)}")
    print(f"Total transactions   : {sum(f.count for f in stats)}")


def write_csv(stats: List[FlowStats], path: str):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["chain_id", "entry_service", "exit_services", "transaction_count", "flow_signature", "sample_trace_ids"])
        for f in stats:
            # Include up to 5 sample trace IDs
            samples = "|".join(f.trace_ids[:5])
            writer.writerow([f.chain_id, f.entry, f.exit, f.count, f.signature, samples])
    print(f"\nCSV written to: {path}")


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Transaction volume by distinct flow (Tempo)")
    parser.add_argument("--tempo-url",   default="http://localhost:3200")
    parser.add_argument("--limit",       type=int,   default=200)
    parser.add_argument("--last-hours",  type=float, default=6.0)
    parser.add_argument("--output",      default="",  help="Optional CSV output path")
    parser.add_argument("--no-proxy",    action="store_true")
    args = parser.parse_args()

    if args.no_proxy:
        for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            os.environ.pop(var, None)
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    stats = aggregate(args.tempo_url, args.limit, args.last_hours)
    print()
    print_table(stats)

    if args.output:
        write_csv(stats, args.output)


if __name__ == "__main__":
    main()
