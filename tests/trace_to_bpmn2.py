def build_high_level_business_process_flow(output_dir: str = "."):
    """Generate a high-level BPMN2.0 XML with two abstract tasks: Lookup Customer and Troubleshoot."""
    output_dir_path = Path(output_dir)

    def discover_scenario_numbers() -> List[int]:
        scenario_numbers: List[int] = []
        for scenario_file in output_dir_path.glob("test_scenario_*_flow.xml"):
            parts = scenario_file.stem.split("_")
            if len(parts) >= 4 and parts[0] == "test" and parts[1] == "scenario":
                try:
                    scenario_numbers.append(int(parts[2]))
                except ValueError:
                    continue

        if scenario_numbers:
            return sorted(set(scenario_numbers))

        # Keep previous behavior when no scenario files are found.
        return list(range(1, 11))

    builder = BPMNBuilder()
    builder.proc_idx += 1
    proc_id = f"HighLevelProcess_{builder.proc_idx}"
    participant_id = f"HighLevelParticipant_{builder.proc_idx}"
    title_id = f"HighLevelTitle_{builder.proc_idx}"
    pool_label = "Business Process Flow (High Level)"
    ET.SubElement(builder.collaboration, f"{{{BPMN_NS}}}participant", {
        "id": participant_id,
        "name": pool_label,
        "processRef": proc_id,
    })
    process = ET.SubElement(builder.definitions, f"{{{BPMN_NS}}}process", {
        "id": proc_id, "isExecutable": "false",
    })
    doc = ET.SubElement(process, f"{{{BPMN_NS}}}documentation")
    doc.text = (
        "High-level business process abstraction.\n"
        "Tasks: Lookup Customer, Troubleshoot."
    )
    x = 180
    y = builder.y_offset + 130
    start_id = f"HighLevelStart_{builder.proc_idx}"
    builder._add_element(process, "startEvent", start_id, "Start")
    builder._add_shape(start_id, x, y - builder.event_size / 2, builder.event_size, builder.event_size)
    prev_ids = [start_id]
    x += builder.x_step - 80
    # Task 1: Lookup Customer as subProcess
    lookup_sub_id = f"HL_SubProcess_LookupCustomer_{builder.proc_idx}"
    lookup_sub = ET.SubElement(process, f"{{{BPMN_NS}}}subProcess", {
        "id": lookup_sub_id,
        "name": "Lookup Customer",
    })
    doc_lookup = ET.SubElement(lookup_sub, f"{{{BPMN_NS}}}documentation")
    doc_lookup.text = "See: lookup_customer_chain_flow.xml"
    builder._add_shape(lookup_sub_id, x, y - builder.task_height // 2, builder.task_width, builder.task_height)
    for pid in prev_ids:
        fid = _next_id("HL_Flow")
        builder._add_seq_flow(process, fid, pid, lookup_sub_id)
        builder._add_connection(fid, pid, lookup_sub_id)
    prev_ids = [lookup_sub_id]
    x += builder.x_step

    # Task 2: Troubleshoot as subProcess containing sequential subProcesses for each test_scenario_n_flow.xml
    troubleshoot_sub_id = f"HL_SubProcess_Troubleshoot_{builder.proc_idx}"
    troubleshoot_sub = ET.SubElement(process, f"{{{BPMN_NS}}}subProcess", {
        "id": troubleshoot_sub_id,
        "name": "Troubleshoot",
    })
    builder._add_shape(troubleshoot_sub_id, x, y - builder.task_height // 2, builder.task_width, builder.task_height)
    for pid in prev_ids:
        fid = _next_id("HL_Flow")
        builder._add_seq_flow(process, fid, pid, troubleshoot_sub_id)
        builder._add_connection(fid, pid, troubleshoot_sub_id)
    # Add sequential subProcesses inside Troubleshoot
    prev_sub_id = None
    for n in discover_scenario_numbers():
        scenario_id = f"HL_SubProcess_Troubleshoot_Scenario{n}_{builder.proc_idx}"
        scenario_sub = ET.SubElement(troubleshoot_sub, f"{{{BPMN_NS}}}subProcess", {
            "id": scenario_id,
            "name": f"Test Scenario {n}",
        })
        doc_scenario = ET.SubElement(scenario_sub, f"{{{BPMN_NS}}}documentation")
        doc_scenario.text = f"See: test_scenario_{n}_flow.xml"
        if prev_sub_id is not None:
            fid = _next_id("HL_Flow")
            ET.SubElement(troubleshoot_sub, f"{{{BPMN_NS}}}sequenceFlow", {
                "id": fid,
                "sourceRef": prev_sub_id,
                "targetRef": scenario_id,
            })
        prev_sub_id = scenario_id

    # Final selectable branch in the left tree: merged view of all scenarios.
    all_scenarios_id = f"HL_SubProcess_Troubleshoot_AllScenarios_{builder.proc_idx}"
    all_scenarios_sub = ET.SubElement(troubleshoot_sub, f"{{{BPMN_NS}}}subProcess", {
        "id": all_scenarios_id,
        "name": "All Scenarios (Merged)",
    })
    doc_all_scenarios = ET.SubElement(all_scenarios_sub, f"{{{BPMN_NS}}}documentation")
    doc_all_scenarios.text = "See: flows_all_bpmn2.0.xml"
    if prev_sub_id is not None:
        fid = _next_id("HL_Flow")
        ET.SubElement(troubleshoot_sub, f"{{{BPMN_NS}}}sequenceFlow", {
            "id": fid,
            "sourceRef": prev_sub_id,
            "targetRef": all_scenarios_id,
        })
    prev_sub_id = all_scenarios_id
    prev_ids = [troubleshoot_sub_id]
    x += builder.x_step
    # End event
    end_id = f"HighLevelEnd_{builder.proc_idx}"
    builder._add_element(process, "endEvent", end_id, "End")
    builder._add_shape(end_id, x, y - builder.event_size / 2, builder.event_size, builder.event_size)
    for pid in prev_ids:
        fid = _next_id("HL_Flow")
        builder._add_seq_flow(process, fid, pid, end_id)
        builder._add_connection(fid, pid, end_id)
    pool_width = int((x + 180) * builder.pool_width_scale)
    pool_height = max(300, int(320 * builder.pool_height_scale))
    title_text = "Business Process Flow (High Level)"
    title_width = min(max(320, len(title_text) * 8), max(320, pool_width - 240))
    title_x = 120 + (pool_width - 120 - title_width) / 2
    title_y = builder.y_offset + builder.title_margin_top
    builder._add_text_annotation(process, title_id, title_text, title_x, title_y, title_width, builder.title_height)
    builder._add_shape(participant_id, 60, builder.y_offset, pool_width, pool_height)
    builder.y_offset += pool_height + 40
    xml_output = builder.serialize()
    output_path = os.path.join(output_dir, "Business_Process_Flow_High_Level.xml")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_output)
    print(f"High-level business process BPMN 2.0 XML written to: {output_path}")
"""
Trace-to-BPMN 2.0 Generator (v2)
==================================
Queries Grafana Tempo for traces, groups them by (service, root span),
merges all observed paths into a single BPMN process per distinct flow,
and also emits every contiguous service segment of length two or more.

Usage:
    $env:NO_PROXY = "localhost,127.0.0.1"
    python trace_to_bpmn2.py

    # Options:
    python trace_to_bpmn2.py --tempo-url http://localhost:3200 --limit 60 --output flows.xml --segments-output service_segments.txt

Outputs:
    - BPMN 2.0 XML importable into Camunda Modeler, Bizagi, bpmn.js, etc.
    - Plain-text list of ordered service combinations.
"""

import argparse
import json
import io
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

try:
    from loki_error_extractor import query_errors_per_service, ErrorRecord, get_errors_for_service_if_any
except ImportError:
    # If loki_error_extractor is not available, define stub functions
    query_errors_per_service = lambda **kwargs: {}
    get_errors_for_service_if_any = lambda service_name, errors_by_service: []


# ═══════════════════════════════════════════════════════════════════════════
#  Span tree model
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SpanNode:
    span_id: str
    name: str
    service_name: str
    start_time_unix_ns: int
    duration_ms: float
    status_ok: bool
    fork_type: Optional[str]        # "parallel" | "exclusive" | None
    attributes: Dict[str, str] = field(default_factory=dict)
    children: List["SpanNode"] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
#  BPMN flow-graph model  (intermediate representation)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BPMNNode:
    """One node in the merged flow graph."""
    id: str
    kind: str          # "start","end","task","parallel_gw","exclusive_gw"
    label: str = ""
    span_data: List["SpanRecord"] = field(default_factory=list)
    # For gateways: direction — "fork" or "join"
    direction: str = ""
    # For exclusive gateways: branch labels
    branches: List[Tuple[str, List["BPMNNode"]]] = field(default_factory=list)
    # For parallel gateways: parallel branches
    parallel_branches: List[List["BPMNNode"]] = field(default_factory=list)
    # Stats annotation
    annotation: str = ""


# ═══════════════════════════════════════════════════════════════════════════
#  Tempo client
# ═══════════════════════════════════════════════════════════════════════════

def fetch_trace_ids(
    tempo_url: str,
    limit: int,
    start_unix_seconds: Optional[int] = None,
    end_unix_seconds: Optional[int] = None,
    traceql_query: Optional[str] = None,
) -> List[str]:
    params: Dict[str, Any] = {"limit": limit}
    if start_unix_seconds is not None:
        params["start"] = int(start_unix_seconds)
    if end_unix_seconds is not None:
        params["end"] = int(end_unix_seconds)
    if traceql_query:
        params["q"] = traceql_query

    query = urllib.parse.urlencode(params)
    url = f"{tempo_url}/api/search?{query}"
    print(f"[DEBUG] Tempo search URL: {url}")
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read().decode())
    return [t["traceID"] for t in data.get("traces", [])]


def fetch_trace_spans(tempo_url: str, trace_id: str) -> List[SpanNode]:
    url = f"{tempo_url}/api/traces/{trace_id}"
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read().decode())

    spans = []
    for batch in data.get("batches", []):
        svc = "unknown"
        for attr in batch.get("resource", {}).get("attributes", []):
            if attr["key"] == "service.name":
                svc = attr["value"].get("stringValue", "unknown")
        for scope_spans in batch.get("scopeSpans", []):
            for raw in scope_spans.get("spans", []):
                dur_ns = int(raw["endTimeUnixNano"]) - int(raw["startTimeUnixNano"])
                status = raw.get("status", {})
                status_ok = status.get("code", 0) != 2
                attrs = {}
                fork_type = None
                for a in raw.get("attributes", []):
                    val = (a["value"].get("stringValue")
                           or a["value"].get("intValue")
                           or a["value"].get("doubleValue")
                           or str(a["value"].get("boolValue", "")))
                    attrs[a["key"]] = str(val)
                    if a["key"] == "fork.type":
                        fork_type = str(val)
                spans.append(SpanNode(
                    span_id=raw["spanId"],
                    name=raw["name"],
                    service_name=svc,
                    start_time_unix_ns=int(raw.get("startTimeUnixNano", 0)),
                    duration_ms=dur_ns / 1e6,
                    status_ok=status_ok,
                    fork_type=fork_type,
                    attributes=attrs,
                ))
                # Store parentSpanId in attributes for tree building
                spans[-1].attributes["_parentSpanId"] = raw.get("parentSpanId", "")
    return spans


def build_span_tree(spans: List[SpanNode]) -> Optional[SpanNode]:
    """Build a tree from a flat list of spans. Returns root."""
    by_id = {s.span_id: s for s in spans}
    root = None
    for s in spans:
        pid = s.attributes.get("_parentSpanId", "")
        if not pid:
            root = s
        elif pid in by_id:
            by_id[pid].children.append(s)
    return root


# ═══════════════════════════════════════════════════════════════════════════
#  Pattern discovery & merging
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FlowGroup:
    """All traces sharing the same (service, root_span_name)."""
    service_name: str
    root_span_name: str
    trace_ids: List[str] = field(default_factory=list)
    trees: List[SpanNode] = field(default_factory=list)
    total_duration_ms: float = 0.0
    error_count: int = 0


@dataclass
class TraceFlow:
    """One processed trace with its root tree and summary fields."""
    trace_id: str
    chain_id: Optional[str]
    ticket_id: Optional[str]
    earliest_start_ns: int
    root: SpanNode
    service_name: str
    root_span_name: str
    duration_ms: float
    status_ok: bool


CHAIN_ID_KEYS = {"chain_id", "chain.id", "chain-id", "chainid"}
TICKET_ID_KEYS = {"ticket_id", "ticket.id", "ticket-id", "ticketid"}


def _extract_chain_id_from_baggage_value(raw_baggage: str) -> Optional[str]:
    """Parse a W3C baggage-style value and return chain id if present."""
    if not raw_baggage:
        return None

    for item in raw_baggage.split(","):
        part = item.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        if key in CHAIN_ID_KEYS:
            return urllib.parse.unquote(value.strip())
    return None


def extract_chain_id_from_tree(root: SpanNode) -> Optional[str]:
    """Find chain id from span attributes, preferring baggage keys."""
    stack = [root]
    while stack:
        span = stack.pop()

        for key, value in span.attributes.items():
            key_l = key.lower()
            if key_l.startswith("_"):
                continue

            if key_l in CHAIN_ID_KEYS:
                return str(value).strip()

            if "baggage" in key_l:
                from_baggage = _extract_chain_id_from_baggage_value(str(value))
                if from_baggage:
                    return from_baggage

            if "chain" in key_l and "id" in key_l:
                return str(value).strip()

        stack.extend(span.children)

    return None


def _extract_ticket_id_from_baggage_value(raw_baggage: str) -> Optional[str]:
    """Parse a W3C baggage-style value and return ticket id if present."""
    if not raw_baggage:
        return None
    for item in raw_baggage.split(","):
        part = item.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        if key in TICKET_ID_KEYS:
            return urllib.parse.unquote(value.strip())
    return None


def extract_ticket_id_from_tree(root: SpanNode) -> Optional[str]:
    """Find ticket id from span attributes, preferring baggage keys."""
    stack = [root]
    while stack:
        span = stack.pop()
        for key, value in span.attributes.items():
            key_l = key.lower()
            if key_l.startswith("_"):
                continue
            if key_l in TICKET_ID_KEYS:
                return str(value).strip()
            if "baggage" in key_l:
                from_baggage = _extract_ticket_id_from_baggage_value(str(value))
                if from_baggage:
                    return from_baggage
            if "ticket" in key_l and "id" in key_l:
                return str(value).strip()
        stack.extend(span.children)
    return None


def earliest_span_start_ns(root: SpanNode) -> int:
    """Return the minimum startTimeUnixNs across all spans in the tree."""
    min_t = root.start_time_unix_ns
    stack = list(root.children)
    while stack:
        s = stack.pop()
        if s.start_time_unix_ns and s.start_time_unix_ns < min_t:
            min_t = s.start_time_unix_ns
        stack.extend(s.children)
    return min_t


def group_traces(
    tempo_url: str,
    limit: int,
    start_unix_seconds: Optional[int] = None,
    end_unix_seconds: Optional[int] = None,
    traceql_query: Optional[str] = None,
) -> Tuple[Dict[str, FlowGroup], List[TraceFlow]]:
    """Fetch traces, build trees, group by (service, root span)."""
    trace_ids = fetch_trace_ids(
        tempo_url,
        limit,
        start_unix_seconds=start_unix_seconds,
        end_unix_seconds=end_unix_seconds,
        traceql_query=traceql_query,
    )
    if not trace_ids:
        print("No traces found in Tempo.")
        sys.exit(1)
    print(f"Fetched {len(trace_ids)} trace IDs from Tempo.")

    groups: Dict[str, FlowGroup] = {}
    trace_flows: List[TraceFlow] = []
    for tid in trace_ids:
        spans = fetch_trace_spans(tempo_url, tid)
        root = build_span_tree(spans)
        if root is None:
            continue

        trace_flows.append(TraceFlow(
            trace_id=tid,
            chain_id=extract_chain_id_from_tree(root),
            ticket_id=extract_ticket_id_from_tree(root),
            earliest_start_ns=earliest_span_start_ns(root),
            root=root,
            service_name=root.service_name,
            root_span_name=root.name,
            duration_ms=root.duration_ms,
            status_ok=root.status_ok,
        ))

        key = f"{root.service_name}::{root.name}"
        if key not in groups:
            groups[key] = FlowGroup(
                service_name=root.service_name,
                root_span_name=root.name,
            )
        g = groups[key]
        g.trace_ids.append(tid)
        g.trees.append(root)
        g.total_duration_ms += root.duration_ms
        if not root.status_ok:
            g.error_count += 1
    return groups, trace_flows


# ═══════════════════════════════════════════════════════════════════════════
#  Service-level call graph
# ═══════════════════════════════════════════════════════════════════════════

_id_counter = 0

def _next_id(prefix: str) -> str:
    global _id_counter
    _id_counter += 1
    return f"{prefix}_{_id_counter}"


@dataclass
class SpanRecord:
    """Serializable span metadata attached to generated BPMN tasks."""
    trace_id: str
    span_id: str
    parent_span_id: str
    span_name: str
    service_name: str
    duration_ms: float
    status: str
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class ServiceNode:
    """A service in the inter-service call graph."""
    service_name: str
    span_data: List[SpanRecord] = field(default_factory=list)
    downstream: List["ServiceNode"] = field(default_factory=list)


def span_to_record(span: SpanNode, trace_id: str) -> SpanRecord:
    """Convert a span into extension-friendly metadata."""
    attributes = {
        key: value for key, value in span.attributes.items()
        if not key.startswith("_")
    }
    return SpanRecord(
        trace_id=trace_id,
        span_id=span.span_id,
        parent_span_id=span.attributes.get("_parentSpanId", ""),
        span_name=span.name,
        service_name=span.service_name,
        duration_ms=span.duration_ms,
        status="OK" if span.status_ok else "ERROR",
        attributes=attributes,
    )


def extract_service_graph(root: SpanNode, trace_id: str) -> ServiceNode:
    """
    Walk the span tree and build a service-level call graph.
    Each cross-service boundary becomes an edge in the graph.
    """
    svc = ServiceNode(service_name=root.service_name)
    svc.span_data.append(span_to_record(root, trace_id))
    _collect_downstream(root, root.service_name, svc, trace_id)
    svc.downstream = _dedup_downstream(svc.downstream)
    return svc


def _collect_downstream(span: SpanNode, current_svc: str, svc_node: ServiceNode, trace_id: str):
    """Recursively find cross-service calls in the span tree."""
    for child in span.children:
        if child.service_name != current_svc:
            child_svc = ServiceNode(service_name=child.service_name)
            child_svc.span_data.append(span_to_record(child, trace_id))
            svc_node.downstream.append(child_svc)
            _collect_downstream(child, child.service_name, child_svc, trace_id)
        else:
            svc_node.span_data.append(span_to_record(child, trace_id))
            _collect_downstream(child, current_svc, svc_node, trace_id)


def merge_span_records(records: List[SpanRecord]) -> List[SpanRecord]:
    """Deduplicate span records while preserving first-seen order."""
    merged: List[SpanRecord] = []
    seen = set()
    for record in records:
        key = (record.trace_id, record.span_id)
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
    return merged


def _dedup_downstream(nodes: List[ServiceNode]) -> List[ServiceNode]:
    """Merge ServiceNodes with the same service name, combining downstream."""
    seen: Dict[str, ServiceNode] = {}
    result: List[ServiceNode] = []
    for node in nodes:
        if node.service_name in seen:
            existing = seen[node.service_name]
            existing.span_data.extend(node.span_data)
            existing.span_data = merge_span_records(existing.span_data)
            existing.downstream.extend(node.downstream)
            existing.downstream = _dedup_downstream(existing.downstream)
        else:
            node.span_data = merge_span_records(node.span_data)
            node.downstream = _dedup_downstream(node.downstream)
            seen[node.service_name] = node
            result.append(node)
    return result


def merge_service_graphs(graphs: List[ServiceNode]) -> ServiceNode:
    """Merge multiple service graphs (from different traces) into one."""
    if len(graphs) == 1:
        graphs[0].span_data = merge_span_records(graphs[0].span_data)
        return graphs[0]

    root_name = graphs[0].service_name
    merged = ServiceNode(service_name=root_name)
    merged.span_data = merge_span_records([
        record
        for graph in graphs
        for record in graph.span_data
    ])

    all_downstream: Dict[str, List[ServiceNode]] = defaultdict(list)
    for g in graphs:
        for ds in g.downstream:
            all_downstream[ds.service_name].append(ds)

    for svc_name in all_downstream:
        merged_child = merge_service_graphs(all_downstream[svc_name])
        merged.downstream.append(merged_child)

    return merged


def service_graph_to_bpmn(svc: ServiceNode) -> List[BPMNNode]:
    """
    Convert a service call graph into BPMNNodes.
    - Each service  ->  serviceTask
    - >1 downstream ->  parallelGateway fork / join
    """
    nodes: List[BPMNNode] = []

    task = BPMNNode(
        id=_next_id("Task"),
        kind="task",
        label=svc.service_name,
        span_data=list(svc.span_data),
    )
    nodes.append(task)

    if len(svc.downstream) > 1:
        gw = BPMNNode(id=_next_id("ParGW"), kind="parallel_gw",
                       label="", direction="fork")
        branches: List[List[BPMNNode]] = []
        for ds in svc.downstream:
            branch = service_graph_to_bpmn(ds)
            branches.append(branch)
        gw.parallel_branches = branches
        nodes.append(gw)
    elif len(svc.downstream) == 1:
        nodes.extend(service_graph_to_bpmn(svc.downstream[0]))

    return nodes


def merge_group_to_flow(group: FlowGroup) -> List[BPMNNode]:
    """Build service-level BPMN flow from a group of traces."""
    if not group.trees:
        return []

    svc_graphs = [extract_service_graph(tree, trace_id)
                  for tree, trace_id in zip(group.trees, group.trace_ids)]
    merged = merge_service_graphs(svc_graphs)
    return service_graph_to_bpmn(merged)


def extract_ordered_service_paths(root: SpanNode) -> List[List[str]]:
    """Return root-to-leaf service paths with consecutive duplicates collapsed."""
    paths: List[List[str]] = []

    def walk(span: SpanNode, current_path: List[str]):
        if not current_path or current_path[-1] != span.service_name:
            current_path = current_path + [span.service_name]

        if not span.children:
            if len(current_path) >= 2:
                paths.append(current_path)
            return

        for child in span.children:
            walk(child, current_path)

    walk(root, [])
    return paths


def service_segments_from_path(path: List[str]) -> List[List[str]]:
    """Return every contiguous ordered segment of length two or more."""
    segments: List[List[str]] = []
    for segment_length in range(2, len(path) + 1):
        for start_index in range(0, len(path) - segment_length + 1):
            segments.append(path[start_index:start_index + segment_length])
    return segments


def collect_service_segments(groups: Dict[str, FlowGroup]) -> List[List[str]]:
    """Collect unique ordered service segments across all grouped traces."""
    ordered_segments: List[List[str]] = []
    seen = set()

    ordered_keys = sorted(groups.keys(), key=lambda key: -len(groups[key].trees))
    for key in ordered_keys:
        group = groups[key]
        for tree in group.trees:
            for path in extract_ordered_service_paths(tree):
                for segment in service_segments_from_path(path):
                    segment_key = tuple(segment)
                    if segment_key in seen:
                        continue
                    seen.add(segment_key)
                    ordered_segments.append(segment)

    return ordered_segments


def serialize_service_segments(segments: List[List[str]]) -> str:
    """Serialize service segments as a plain-text list."""
    return "\n".join(" -> ".join(segment) for segment in segments) + ("\n" if segments else "")


def count_parallel_gateways(nodes: List[BPMNNode]) -> int:
    """Count parallel gateways recursively for reporting."""
    total = 0
    for node in nodes:
        if node.kind == "parallel_gw" and node.parallel_branches:
            total += 1
            for branch in node.parallel_branches:
                total += count_parallel_gateways(branch)
        elif node.kind == "exclusive_gw" and node.branches:
            for _, branch in node.branches:
                total += count_parallel_gateways(branch)
    return total


def branch_nested_fork_depth(nodes: List[BPMNNode]) -> int:
    """Return the maximum nested gateway depth inside a branch."""
    depth = 0
    for node in nodes:
        if node.kind == "parallel_gw" and node.parallel_branches:
            child_depth = 0
            for branch in node.parallel_branches:
                child_depth = max(child_depth, branch_nested_fork_depth(branch))
            depth = max(depth, 1 + child_depth)
        elif node.kind == "exclusive_gw" and node.branches:
            child_depth = 0
            for _, branch in node.branches:
                child_depth = max(child_depth, branch_nested_fork_depth(branch))
            depth = max(depth, 1 + child_depth)
    return depth


def sanitize_trace_id(trace_id: str) -> str:
    """Make a trace ID safe to use in a file name."""
    safe_chars = []
    for char in trace_id:
        if char.isalnum() or char in ("-", "_"):
            safe_chars.append(char)
        else:
            safe_chars.append("_")
    return "".join(safe_chars) or "trace"


def primary_trace_id(groups: Dict[str, FlowGroup]) -> Optional[str]:
    """Return the first trace ID from the largest discovered flow group."""
    if not groups:
        return None

    ordered_groups = sorted(groups.values(), key=lambda group: len(group.trees), reverse=True)
    for group in ordered_groups:
        if group.trace_ids:
            return group.trace_ids[0]
    return None


def output_path_with_trace_id(output_path: str, trace_id: Optional[str]) -> str:
    """Append the trace ID to the output file stem."""
    if not trace_id:
        return output_path

    path = Path(output_path)
    trace_suffix = sanitize_trace_id(trace_id)
    if path.stem.endswith(f"_{trace_suffix}"):
        return str(path)

    suffix = "".join(path.suffixes) or ".xml"
    stem = path.name[:-len(suffix)] if path.suffixes else path.name
    return str(path.with_name(f"{stem}_{trace_suffix}{suffix}"))


def individual_bpmn_output_path(base_output_path: str, chain_id: Optional[str], trace_id: str) -> str:
    """Build individual BPMN output path as <chain_id>_flow.xml."""
    base_path = Path(base_output_path)
    chain_token = sanitize_trace_id(chain_id) if chain_id else sanitize_trace_id(trace_id)
    return str(base_path.with_name(f"{chain_token}_flow.xml"))


def resolve_output_path(path_value: str) -> str:
    """Resolve relative output paths under tests/output."""
    path_obj = Path(path_value)
    if path_obj.is_absolute():
        return str(path_obj)

    script_dir = Path(__file__).resolve().parent
    return str((script_dir / "output" / path_obj).resolve())


# ═══════════════════════════════════════════════════════════════════════════
#  Business flow (ticket-level) grouping
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ChainSummary:
    """One E2EUX chain (all its traces collapsed) inside a ticket."""
    chain_id: str
    ticket_id: str
    earliest_start_ns: int
    root_span_names: List[str]
    trace_count: int
    total_duration_ms: float
    error_count: int


def group_by_ticket(trace_flows: List[TraceFlow]) -> Dict[str, List[ChainSummary]]:
    """
    Group trace flows by ticket_id, then collapse by chain_id.
    Returns {ticket_id: [ChainSummary, ...]} sorted by earliest_start_ns.
    Traces without a ticket_id or chain_id are skipped.
    """
    buckets: Dict[str, Dict[str, Dict]] = defaultdict(lambda: defaultdict(lambda: {
        "earliest_start_ns": 10 ** 18,
        "root_span_names": [],
        "trace_count": 0,
        "total_duration_ms": 0.0,
        "error_count": 0,
    }))

    for tf in trace_flows:
        if not tf.ticket_id or not tf.chain_id:
            continue
        acc = buckets[tf.ticket_id][tf.chain_id]
        if tf.earliest_start_ns and tf.earliest_start_ns < acc["earliest_start_ns"]:
            acc["earliest_start_ns"] = tf.earliest_start_ns
        if tf.root_span_name not in acc["root_span_names"]:
            acc["root_span_names"].append(tf.root_span_name)
        acc["trace_count"] += 1
        acc["total_duration_ms"] += tf.duration_ms
        if not tf.status_ok:
            acc["error_count"] += 1

    result: Dict[str, List[ChainSummary]] = {}
    for ticket_id, chains in buckets.items():
        summaries = [
            ChainSummary(
                chain_id=chain_id,
                ticket_id=ticket_id,
                earliest_start_ns=acc["earliest_start_ns"],
                root_span_names=acc["root_span_names"],
                trace_count=acc["trace_count"],
                total_duration_ms=acc["total_duration_ms"],
                error_count=acc["error_count"],
            )
            for chain_id, acc in chains.items()
        ]
        summaries.sort(key=lambda s: s.earliest_start_ns)
        result[ticket_id] = summaries
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  BPMN 2.0 XML generation
# ═══════════════════════════════════════════════════════════════════════════

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
OTEL_EXT_NS = "http://opentelemetry.io/bpmn/extensions"


class BPMNBuilder:
    """Builds BPMN 2.0 XML from merged flow graphs."""

    def __init__(self):
        ET.register_namespace("", BPMN_NS)
        ET.register_namespace("bpmndi", BPMNDI_NS)
        ET.register_namespace("dc", DC_NS)
        ET.register_namespace("di", DI_NS)
        ET.register_namespace("otel", OTEL_EXT_NS)

        self.definitions = ET.Element(f"{{{BPMN_NS}}}definitions", {
            "id": "Definitions_1",
            "targetNamespace": "http://opentelemetry.io/bpmn/generated",
        })
        self.diagram = ET.SubElement(self.definitions,
                                     f"{{{BPMNDI_NS}}}BPMNDiagram",
                                     {"id": "BPMNDiagram_1"})
        self.plane = ET.SubElement(self.diagram,
                                   f"{{{BPMNDI_NS}}}BPMNPlane",
                                   {"id": "BPMNPlane_1",
                                    "bpmnElement": "Collaboration_1"})
        self.collaboration = ET.SubElement(self.definitions,
                                           f"{{{BPMN_NS}}}collaboration",
                                           {"id": "Collaboration_1"})
        self.y_offset = 0
        self.proc_idx = 0
        self.shape_bounds: Dict[str, Tuple[float, float, float, float]] = {}
        self.task_width = 120
        self.task_height = 64
        self.gateway_size = 50
        self.event_size = 36
        self.x_step = 270
        self.branch_y_gap = 150
        self.branch_y_offset = 75
        self.nested_branch_extra_gap = 60
        self.branch_clearance = 10
        self.pool_width_scale = 1.5
        self.pool_height_scale = 1.5
        self.title_height = 36
        self.title_margin_top = 24
        self.title_gap = 24

    def add_process(self, group: FlowGroup, flow_nodes: List[BPMNNode], errors_by_service: Optional[Dict[str, List[ErrorRecord]]] = None):
        if errors_by_service is None:
            errors_by_service = {}
        self.proc_idx += 1
        proc_id = f"Process_{self.proc_idx}"
        participant_id = f"Participant_{self.proc_idx}"
        title_id = f"TraceTitle_{self.proc_idx}"
        plane_start_idx = len(self.plane)

        count = len(group.trees)
        avg_dur = group.total_duration_ms / count if count else 0
        err_pct = (group.error_count / count * 100) if count else 0
        trace_title = self._build_trace_title(group)

        pool_label = (
            f"{group.service_name} / {group.root_span_name}\n"
            f"({count} traces, avg {avg_dur:.0f}ms"
            f"{f', {err_pct:.0f}% errors' if group.error_count else ''})"
        )

        ET.SubElement(self.collaboration, f"{{{BPMN_NS}}}participant", {
            "id": participant_id,
            "name": pool_label,
            "processRef": proc_id,
        })

        process = ET.SubElement(self.definitions, f"{{{BPMN_NS}}}process", {
            "id": proc_id, "isExecutable": "false",
        })

        doc = ET.SubElement(process, f"{{{BPMN_NS}}}documentation")
        doc.text = (
            f"Auto-generated from OpenTelemetry trace data.\n"
            f"Service: {group.service_name}\n"
            f"Root span: {group.root_span_name}\n"
            f"Primary trace ID: {group.trace_ids[0] if group.trace_ids else 'n/a'}\n"
            f"Traces analyzed: {count}\n"
            f"Avg duration: {avg_dur:.1f}ms\n"
            f"Error rate: {err_pct:.1f}%"
        )
        service_avg_lines = self._service_avg_duration_lines(flow_nodes)
        if service_avg_lines:
            doc.text += "\nService average durations (ms):\n" + "\n".join(service_avg_lines)

        # Layout state
        x = 180
        y = self.y_offset + 130
        x_step = self.x_step
        max_y_used = y
        all_element_ids = []

        # Start event
        start_id = f"Start_{self.proc_idx}"
        self._add_element(process, "startEvent", start_id, "Request\nReceived")
        self._add_shape(start_id, x, y - (self.event_size / 2),
                self.event_size, self.event_size)
        prev_ids = [start_id]
        x += x_step - 80

        # Walk the flow nodes and emit BPMN elements
        x, max_y_used, prev_ids = self._emit_nodes(
            process, flow_nodes, x, y, x_step, prev_ids, max_y_used, errors_by_service)

        # End event
        end_id = f"End_{self.proc_idx}"
        self._add_element(process, "endEvent", end_id, "Completed")
        self._add_shape(end_id, x, y - (self.event_size / 2),
                        self.event_size, self.event_size)
        for pid in prev_ids:
            fid = _next_id("Flow")
            self._add_seq_flow(process, fid, pid, end_id)
            self._add_connection(fid, pid, end_id)

        # Center the generated content vertically inside the enlarged pool.
        content_top, content_bottom = self._content_vertical_bounds(plane_start_idx)
        content_height = content_bottom - content_top
        pool_width = int((x + 180) * self.pool_width_scale)
        title_band_height = self.title_margin_top + self.title_height + self.title_gap
        pool_height = int(max(300, max_y_used - self.y_offset + 180) * self.pool_height_scale)
        pool_height = max(pool_height, int(content_height + title_band_height + 120))
        content_area_height = max(content_height, pool_height - title_band_height)
        target_top = self.y_offset + title_band_height + (content_area_height - content_height) / 2
        self._shift_plane_items(plane_start_idx, target_top - content_top)

        title_width = min(max(320, len(trace_title) * 8), max(320, pool_width - 240))
        title_x = 120 + (pool_width - 120 - title_width) / 2
        title_y = self.y_offset + self.title_margin_top
        self._add_text_annotation(process, title_id, trace_title, title_x, title_y,
                      title_width, self.title_height)

        # Pool shape
        self._add_shape(participant_id, 60, self.y_offset,
                        pool_width, pool_height)

        self.y_offset += pool_height + 40

    def add_business_flow_process(self, ticket_id: str, chains: "List[ChainSummary]"):
        """Add one pool showing E2EUX chains in chronological order for a ticket."""
        self.proc_idx += 1
        proc_id = f"Process_{self.proc_idx}"
        participant_id = f"Participant_{self.proc_idx}"
        title_id = f"TraceTitle_{self.proc_idx}"

        chain_count = len(chains)
        err_count = sum(c.error_count for c in chains)
        pool_label = (
            f"Ticket: {ticket_id}\n"
            f"({chain_count} E2EUX chain(s)"
            f"{f', {err_count} error(s)' if err_count else ''})"
        )

        ET.SubElement(self.collaboration, f"{{{BPMN_NS}}}participant", {
            "id": participant_id,
            "name": pool_label,
            "processRef": proc_id,
        })

        process = ET.SubElement(self.definitions, f"{{{BPMN_NS}}}process", {
            "id": proc_id, "isExecutable": "false",
        })

        doc = ET.SubElement(process, f"{{{BPMN_NS}}}documentation")
        doc.text = (
            f"Business flow auto-generated from OpenTelemetry trace data.\n"
            f"Ticket ID: {ticket_id}\n"
            f"E2EUX chains: {chain_count}\n"
            f"Chains ordered by earliest observed span timestamp."
        )

        x = 180
        y = self.y_offset + 130
        start_id = f"Start_{self.proc_idx}"
        self._add_element(process, "startEvent", start_id, "Start")
        self._add_shape(start_id, x, y - self.event_size / 2, self.event_size, self.event_size)
        prev_ids = [start_id]
        x += self.x_step - 80

        for chain in chains:
            task_id = _next_id("BizTask")
            avg_dur = chain.total_duration_ms / chain.trace_count if chain.trace_count else 0
            span_names = ", ".join(sorted(set(chain.root_span_names)))
            label = f"{chain.chain_id}\n{span_names}\n(avg {avg_dur:.0f}ms)"
            self._add_element(process, "serviceTask", task_id, label)
            self._add_shape(task_id, x, y - self.task_height // 2, self.task_width, self.task_height)
            for pid in prev_ids:
                fid = _next_id("Flow")
                self._add_seq_flow(process, fid, pid, task_id)
                self._add_connection(fid, pid, task_id)
            prev_ids = [task_id]
            x += self.x_step

        end_id = f"End_{self.proc_idx}"
        self._add_element(process, "endEvent", end_id, "End")
        self._add_shape(end_id, x, y - self.event_size / 2, self.event_size, self.event_size)
        for pid in prev_ids:
            fid = _next_id("Flow")
            self._add_seq_flow(process, fid, pid, end_id)
            self._add_connection(fid, pid, end_id)

        pool_width = int((x + 180) * self.pool_width_scale)
        pool_height = max(300, int(320 * self.pool_height_scale))
        title_text = f"Ticket: {ticket_id}"
        title_width = min(max(320, len(title_text) * 8), max(320, pool_width - 240))
        title_x = 120 + (pool_width - 120 - title_width) / 2
        title_y = self.y_offset + self.title_margin_top
        self._add_text_annotation(process, title_id, title_text, title_x, title_y,
                                  title_width, self.title_height)
        self._add_shape(participant_id, 60, self.y_offset, pool_width, pool_height)
        self.y_offset += pool_height + 40

    def _branch_half_span(self, nodes: List[BPMNNode]) -> float:
        """Estimate vertical half-span needed to render a branch without overlaps."""
        half_span = max(self.task_height / 2, self.gateway_size / 2) + (self.branch_clearance / 2)

        for node in nodes:
            if node.kind == "parallel_gw" and node.parallel_branches:
                child_half_spans = [self._branch_half_span(branch) for branch in node.parallel_branches]
                child_depths = [branch_nested_fork_depth(branch) for branch in node.parallel_branches]
                base_gap = self.branch_y_gap + (max(child_depths) * self.nested_branch_extra_gap)
                branch_gap = self._branch_gap_for_children(base_gap, child_half_spans)
                branch_y_offset = branch_gap / 2
                branch_count = len(node.parallel_branches)
                branch_y_start = -(branch_count - 1) * branch_y_offset

                gw_half = (self.gateway_size / 2) + (self.branch_clearance / 2)
                for bi, child_half in enumerate(child_half_spans):
                    offset = branch_y_start + bi * branch_gap
                    gw_half = max(gw_half, abs(offset) + child_half)
                half_span = max(half_span, gw_half)

            elif node.kind == "exclusive_gw" and node.branches:
                child_branches = [branch_nodes for _, branch_nodes in node.branches]
                child_half_spans = [self._branch_half_span(branch_nodes) for branch_nodes in child_branches]
                child_depths = [branch_nested_fork_depth(branch_nodes) for branch_nodes in child_branches]
                base_gap = self.branch_y_gap + (max(child_depths) * self.nested_branch_extra_gap)
                branch_gap = self._branch_gap_for_children(base_gap, child_half_spans)
                branch_y_offset = branch_gap / 2
                branch_count = len(child_branches)
                branch_y_start = -(branch_count - 1) * branch_y_offset

                gw_half = (self.gateway_size / 2) + (self.branch_clearance / 2)
                for bi, child_half in enumerate(child_half_spans):
                    offset = branch_y_start + bi * branch_gap
                    gw_half = max(gw_half, abs(offset) + child_half)
                half_span = max(half_span, gw_half)

            else:
                half_span = max(half_span, self.task_height / 2)

        return half_span

    def _branch_gap_for_children(self, base_gap: float, child_half_spans: List[float]) -> float:
        """Choose a branch center gap large enough for adjacent branches to not overlap."""
        if len(child_half_spans) < 2:
            return base_gap

        required = base_gap
        for i in range(len(child_half_spans) - 1):
            adjacent_required = child_half_spans[i] + child_half_spans[i + 1] + (2 * self.branch_clearance)
            if adjacent_required > required:
                required = adjacent_required
        return required

    def _emit_nodes(self, process, nodes, x, y, x_step, prev_ids, max_y_used, errors_by_service: Optional[Dict[str, List[ErrorRecord]]] = None):
        """Recursively emit BPMN elements for a list of flow nodes."""
        if errors_by_service is None:
            errors_by_service = {}

        for node in nodes:
            if node.kind == "task":
                task_id = node.id
                # Extract service name from span data if available
                service_errors = []
                if node.span_data:
                    service_name = node.span_data[0].service_name
                    service_errors = get_errors_for_service_if_any(service_name, errors_by_service)
                
                self._add_element(process, "serviceTask", task_id, node.label,
                                  span_data=node.span_data, error_data=service_errors)
                self._add_shape(task_id, x, y - (self.task_height // 2),
                                self.task_width, self.task_height)
                self._add_duration_dataset_annotation(process, task_id, node.span_data)

                for pid in prev_ids:
                    fid = _next_id("Flow")
                    self._add_seq_flow(process, fid, pid, task_id)
                    self._add_connection(fid, pid, task_id)

                prev_ids = [task_id]
                x += x_step

            elif node.kind == "parallel_gw" and node.parallel_branches:
                # ── Parallel fork gateway ──
                fork_id = node.id + "_fork"
                self._add_element(process, "parallelGateway", fork_id, "")
                self._add_shape(fork_id, x, y - (self.gateway_size / 2),
                                self.gateway_size, self.gateway_size)

                for pid in prev_ids:
                    fid = _next_id("Flow")
                    self._add_seq_flow(process, fid, pid, fork_id)
                    self._add_connection(fid, pid, fork_id)

                x += x_step - 40

                # Emit parallel branches (spread vertically)
                branch_count = len(node.parallel_branches)
                branch_depths = [branch_nested_fork_depth(branch)
                                 for branch in node.parallel_branches]
                branch_half_spans = [self._branch_half_span(branch)
                                     for branch in node.parallel_branches]
                base_branch_gap = self.branch_y_gap + (
                    max(branch_depths) * self.nested_branch_extra_gap)
                branch_gap = self._branch_gap_for_children(base_branch_gap, branch_half_spans)
                branch_y_offset = branch_gap / 2
                branch_y_start = y - (branch_count - 1) * branch_y_offset
                branch_end_ids = []
                branch_max_x = x

                for bi, branch_nodes in enumerate(node.parallel_branches):
                    by = branch_y_start + bi * branch_gap
                    if by + 60 > max_y_used:
                        max_y_used = by + 60
                    bx = x
                    b_prev = [fork_id]

                    bx, max_y_used, b_prev = self._emit_nodes(
                        process, branch_nodes, bx, by, x_step, b_prev,
                        max_y_used, errors_by_service)

                    if branch_nodes:
                        first_branch_id = branch_nodes[0].id
                        edge_id = self._find_incoming_edge_id(process, fork_id, first_branch_id)
                        if edge_id:
                            self._retarget_branch_connection(
                                edge_id, fork_id, first_branch_id,
                                self._gateway_fork_exit_side(fork_id, first_branch_id),
                                "left",
                            )

                    branch_end_ids.extend(b_prev)
                    if bx > branch_max_x:
                        branch_max_x = bx

                # ── Parallel join gateway ──
                join_id = node.id + "_join"
                self._add_element(process, "parallelGateway", join_id, "")
                self._add_shape(join_id, branch_max_x, y - (self.gateway_size / 2),
                                self.gateway_size, self.gateway_size)

                for eid in branch_end_ids:
                    fid = _next_id("Flow")
                    self._add_seq_flow(process, fid, eid, join_id)
                    self._add_connection(fid, eid, join_id)

                for bi, eid in enumerate(branch_end_ids):
                    edge_id = self._find_incoming_edge_id(process, eid, join_id)
                    if edge_id:
                        self._retarget_branch_connection(
                            edge_id, eid, join_id,
                            "right",
                            self._gateway_join_entry_side(eid, join_id),
                        )

                prev_ids = [join_id]
                x = branch_max_x + x_step - 40

            elif node.kind == "exclusive_gw" and node.branches:
                # ── Exclusive OR fork gateway ──
                fork_id = node.id + "_fork"
                self._add_element(process, "exclusiveGateway", fork_id,
                                  node.label)
                self._add_shape(fork_id, x, y - (self.gateway_size / 2),
                                self.gateway_size, self.gateway_size)

                for pid in prev_ids:
                    fid = _next_id("Flow")
                    self._add_seq_flow(process, fid, pid, fork_id)
                    self._add_connection(fid, pid, fork_id)

                x += x_step - 40

                # Emit branches vertically spread
                branch_count = len(node.branches)
                branch_depths = [branch_nested_fork_depth(branch_nodes)
                                 for _, branch_nodes in node.branches]
                branch_half_spans = [self._branch_half_span(branch_nodes)
                                     for _, branch_nodes in node.branches]
                base_branch_gap = self.branch_y_gap + (
                    max(branch_depths) * self.nested_branch_extra_gap)
                branch_gap = self._branch_gap_for_children(base_branch_gap, branch_half_spans)
                branch_y_offset = branch_gap / 2
                branch_y_start = y - (branch_count - 1) * branch_y_offset
                branch_end_ids = []
                branch_max_x = x

                for bi, (branch_label, branch_nodes) in enumerate(node.branches):
                    by = branch_y_start + bi * branch_gap
                    if by + 60 > max_y_used:
                        max_y_used = by + 60
                    bx = x
                    b_prev = [fork_id]

                    # Emit branch label on the first flow
                    for bnode in branch_nodes:
                        if bnode.kind == "exclusive_gw" and bnode.branches:
                            # Nested XOR — recurse
                            bx, max_y_used, b_prev = self._emit_nodes(
                                process, [bnode], bx, by, x_step, b_prev,
                                max_y_used, errors_by_service)
                        elif bnode.kind == "parallel_gw" and bnode.parallel_branches:
                            bx, max_y_used, b_prev = self._emit_nodes(
                                process, [bnode], bx, by, x_step, b_prev,
                                max_y_used, errors_by_service)
                        else:
                            tid = bnode.id
                            # Extract service name from span data if available
                            service_errors = []
                            if bnode.span_data:
                                service_name = bnode.span_data[0].service_name
                                service_errors = get_errors_for_service_if_any(service_name, errors_by_service)
                            
                            self._add_element(process, "serviceTask", tid,
                                              bnode.label,
                                              span_data=bnode.span_data, error_data=service_errors)
                            self._add_shape(tid, bx, by - (self.task_height // 2),
                                            self.task_width, self.task_height)
                            for p in b_prev:
                                fid = _next_id("Flow")
                                self._add_seq_flow(process, fid, p, tid,
                                                   name=branch_label if p == fork_id else "")
                                self._add_connection(fid, p, tid)
                            b_prev = [tid]
                            bx += x_step

                    if branch_nodes:
                        first_branch_id = branch_nodes[0].id
                        edge_id = self._find_incoming_edge_id(process, fork_id, first_branch_id)
                        if edge_id:
                            self._retarget_branch_connection(
                                edge_id, fork_id, first_branch_id,
                                self._gateway_fork_exit_side(fork_id, first_branch_id),
                                "left",
                            )

                    branch_end_ids.extend(b_prev)
                    if bx > branch_max_x:
                        branch_max_x = bx

                # ── Exclusive OR join gateway ──
                join_id = node.id + "_join"
                self._add_element(process, "exclusiveGateway", join_id, "")
                self._add_shape(join_id, branch_max_x, y - (self.gateway_size / 2),
                                self.gateway_size, self.gateway_size)

                for eid in branch_end_ids:
                    fid = _next_id("Flow")
                    self._add_seq_flow(process, fid, eid, join_id)
                    self._add_connection(fid, eid, join_id)

                for bi, eid in enumerate(branch_end_ids):
                    edge_id = self._find_incoming_edge_id(process, eid, join_id)
                    if edge_id:
                        self._retarget_branch_connection(
                            edge_id, eid, join_id,
                            "right",
                            self._gateway_join_entry_side(eid, join_id),
                        )

                prev_ids = [join_id]
                x = branch_max_x + x_step - 40

            elif node.kind == "exclusive_gw":
                # XOR marker without branches (all traces took same path)
                # Just emit as an annotation task
                tid = node.id
                label = node.label
                if node.annotation:
                    label += f"\n[{node.annotation}]"
                self._add_element(process, "serviceTask", tid, label,
                                  span_data=node.span_data)
                self._add_shape(tid, x, y - (self.task_height // 2),
                                self.task_width, self.task_height)
                self._add_duration_dataset_annotation(process, tid, node.span_data)
                for pid in prev_ids:
                    fid = _next_id("Flow")
                    self._add_seq_flow(process, fid, pid, tid)
                    self._add_connection(fid, pid, tid)
                prev_ids = [tid]
                x += x_step

        return x, max_y_used, prev_ids

    def _add_element(self, process, tag, elem_id, name, span_data=None, error_data=None):
        if error_data is None:
            error_data = []
        element = ET.SubElement(process, f"{{{BPMN_NS}}}{tag}", {
            "id": elem_id, "name": name,
        })
        if tag == "serviceTask":
            if span_data:
                self._add_span_extensions(element, span_data)
            if error_data:
                self._add_error_extensions(element, error_data)
        return element

    def _add_span_extensions(self, element, span_data: List[SpanRecord]):
        extension_elements = ET.SubElement(element, f"{{{BPMN_NS}}}extensionElements")
        spans_elem = ET.SubElement(extension_elements, f"{{{OTEL_EXT_NS}}}spanDataSet")

        for record in span_data:
            span_elem = ET.SubElement(spans_elem, f"{{{OTEL_EXT_NS}}}spanData", {
                "traceId": record.trace_id,
                "spanId": record.span_id,
                "parentSpanId": record.parent_span_id,
                "name": record.span_name,
                "service": record.service_name,
                "durationMs": f"{record.duration_ms:.3f}",
                "status": record.status,
            })
            if not record.attributes:
                continue

            attrs_elem = ET.SubElement(span_elem, f"{{{OTEL_EXT_NS}}}attributes")
            for key in sorted(record.attributes.keys()):
                ET.SubElement(attrs_elem, f"{{{OTEL_EXT_NS}}}attribute", {
                    "key": key,
                    "value": record.attributes[key],
                })

    def _add_error_extensions(self, element, error_data: List["ErrorRecord"]):
        """Add error metadata to extension elements."""
        # Find or create extensionElements
        extension_elements = element.find(f"{{{BPMN_NS}}}extensionElements")
        if extension_elements is None:
            extension_elements = ET.SubElement(element, f"{{{BPMN_NS}}}extensionElements")

        # Create or find errorDataSet
        errors_elem = extension_elements.find(f"{{{OTEL_EXT_NS}}}errorDataSet")
        if errors_elem is None:
            errors_elem = ET.SubElement(extension_elements, f"{{{OTEL_EXT_NS}}}errorDataSet")

        for error in error_data:
            error_elem = ET.SubElement(errors_elem, f"{{{OTEL_EXT_NS}}}errorRecord", {
                "timestamp": error.timestamp,
                "service": error.service_name,
                "level": error.level,
                "event": error.event,
                "traceId": error.trace_id or "-",
                "spanId": error.span_id or "-",
            })
            
            # Add message as sub-element
            msg_elem = ET.SubElement(error_elem, f"{{{OTEL_EXT_NS}}}message")
            msg_elem.text = error.message
            
            # Add attributes if present
            if error.attributes:
                attrs_elem = ET.SubElement(error_elem, f"{{{OTEL_EXT_NS}}}attributes")
                for key in sorted(error.attributes.keys()):
                    ET.SubElement(attrs_elem, f"{{{OTEL_EXT_NS}}}attribute", {
                        "key": key,
                        "value": error.attributes[key],
                    })

    def _add_seq_flow(self, process, flow_id, source, target, name=""):
        attrs = {"id": flow_id, "sourceRef": source, "targetRef": target}
        if name:
            attrs["name"] = name
        ET.SubElement(process, f"{{{BPMN_NS}}}sequenceFlow", attrs)

    def _add_text_annotation(self, process, elem_id, text, x, y, w, h):
        annotation = ET.SubElement(process, f"{{{BPMN_NS}}}textAnnotation", {
            "id": elem_id,
        })
        text_elem = ET.SubElement(annotation, f"{{{BPMN_NS}}}text")
        text_elem.text = text
        self._add_shape(elem_id, x, y, w, h)

    def _add_duration_dataset_annotation(self, process, task_id: str, span_data: List[SpanRecord]):
        if not span_data or task_id not in self.shape_bounds:
            return

        avg_duration_ms = sum(record.duration_ms for record in span_data) / len(span_data)
        ann_id = _next_id("DurationAnnotation")
        text = (
            "duarationDataSet\n"
            "key=avg duration\n"
            f"value={avg_duration_ms:.1f} millisecs"
        )

        task_x, task_y, task_w, _ = self.shape_bounds[task_id]
        ann_w = 190
        ann_h = 54
        ann_x = task_x + (task_w - ann_w) / 2
        ann_y = task_y - ann_h - 16

        self._add_text_annotation(process, ann_id, text, ann_x, ann_y, ann_w, ann_h)

        assoc_id = _next_id("DurationAssociation")
        ET.SubElement(process, f"{{{BPMN_NS}}}association", {
            "id": assoc_id,
            "sourceRef": ann_id,
            "targetRef": task_id,
        })
        self._add_connection(assoc_id, ann_id, task_id)

    def _service_avg_duration_lines(self, nodes: List[BPMNNode]) -> List[str]:
        by_service: "OrderedDict[str, Tuple[float, int]]" = OrderedDict()

        def visit(current_nodes: List[BPMNNode]):
            for current in current_nodes:
                if current.kind == "task" and current.span_data:
                    total, count = by_service.get(current.label, (0.0, 0))
                    span_total = sum(record.duration_ms for record in current.span_data)
                    span_count = len(current.span_data)
                    by_service[current.label] = (total + span_total, count + span_count)

                if current.kind == "parallel_gw" and current.parallel_branches:
                    for branch in current.parallel_branches:
                        visit(branch)

                if current.kind == "exclusive_gw" and current.branches:
                    for _, branch_nodes in current.branches:
                        visit(branch_nodes)

        visit(nodes)

        lines: List[str] = []
        for service, (total_duration, count) in by_service.items():
            avg = (total_duration / count) if count else 0.0
            lines.append(f"- {service}: {avg:.1f}")
        return lines

    def _build_trace_title(self, group: FlowGroup) -> str:
        if not group.trace_ids:
            return "Trace ID: unavailable"
        if len(group.trace_ids) == 1:
            return f"Trace ID: {group.trace_ids[0]}"
        return f"Trace ID: {group.trace_ids[0]} (+{len(group.trace_ids) - 1} related traces merged)"

    def _add_shape(self, elem_id, x, y, w, h):
        self.shape_bounds[elem_id] = (x, y, w, h)
        shape = ET.SubElement(self.plane, f"{{{BPMNDI_NS}}}BPMNShape", {
            "id": f"{elem_id}_di", "bpmnElement": elem_id,
        })
        ET.SubElement(shape, f"{{{DC_NS}}}Bounds", {
            "x": str(x), "y": str(y), "width": str(w), "height": str(h),
        })

    def _add_connection(self, elem_id, source_id, target_id):
        x1, y1 = self._anchor_point(source_id, "right")
        x2, y2 = self._anchor_point(target_id, "left")

        if abs(y1 - y2) < 0.5:
            self._add_edge(elem_id, x1, y1, x2, y2)
            return

        mid_x = x1 + max(30, (x2 - x1) / 2)
        edge = ET.SubElement(self.plane, f"{{{BPMNDI_NS}}}BPMNEdge", {
            "id": f"{elem_id}_di", "bpmnElement": elem_id,
        })
        for px, py in ((x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)):
            ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {
                "x": str(px), "y": str(py),
            })

    def _anchor_point(self, elem_id, side):
        x, y, w, h = self.shape_bounds[elem_id]
        if side == "left":
            return x, y + h / 2
        if side == "right":
            return x + w, y + h / 2
        if side == "top":
            return x + w / 2, y
        if side == "bottom":
            return x + w / 2, y + h
        return x + w / 2, y + h / 2

    def _add_edge(self, elem_id, x1, y1, x2, y2):
        edge = ET.SubElement(self.plane, f"{{{BPMNDI_NS}}}BPMNEdge", {
            "id": f"{elem_id}_di", "bpmnElement": elem_id,
        })
        ET.SubElement(edge, f"{{{DI_NS}}}waypoint",
                      {"x": str(x1), "y": str(y1)})
        ET.SubElement(edge, f"{{{DI_NS}}}waypoint",
                      {"x": str(x2), "y": str(y2)})

    def _gateway_branch_side(self, mode, branch_index, branch_count):
        if branch_count % 2 == 0:
            return "top" if branch_index < (branch_count / 2) else "bottom"
        return "right" if mode == "fork" else "left"

    def _gateway_fork_exit_side(self, fork_id, target_id):
        """Choose fork exit side based on target vertical position."""
        _, fork_y, _, fork_h = self.shape_bounds[fork_id]
        _, target_y, _, target_h = self.shape_bounds[target_id]
        fork_center_y = fork_y + (fork_h / 2)
        target_center_y = target_y + (target_h / 2)
        epsilon = 0.5

        if target_center_y < (fork_center_y - epsilon):
            return "top"
        if target_center_y > (fork_center_y + epsilon):
            return "bottom"
        return "right"

    def _gateway_join_entry_side(self, source_id, join_id):
        """Choose join entry side based on source vertical position."""
        _, source_y, _, source_h = self.shape_bounds[source_id]
        _, join_y, _, join_h = self.shape_bounds[join_id]
        source_center_y = source_y + (source_h / 2)
        join_center_y = join_y + (join_h / 2)
        epsilon = 0.5

        if source_center_y < (join_center_y - epsilon):
            return "top"
        if source_center_y > (join_center_y + epsilon):
            return "bottom"
        return "left"

    def _find_incoming_edge_id(self, process, source_id, target_id):
        for flow in process.findall(f"{{{BPMN_NS}}}sequenceFlow"):
            if flow.attrib.get("sourceRef") == source_id and flow.attrib.get("targetRef") == target_id:
                return flow.attrib.get("id")
        return None

    def _retarget_branch_connection(self, edge_id, source_id, target_id, source_side, target_side):
        edge = None
        for item in self.plane.findall(f"{{{BPMNDI_NS}}}BPMNEdge"):
            if item.attrib.get("bpmnElement") == edge_id:
                edge = item
                break
        if edge is None:
            return

        x1, y1 = self._anchor_point(source_id, source_side)
        x2, y2 = self._anchor_point(target_id, target_side)

        for child in list(edge):
            edge.remove(child)

        if abs(y1 - y2) < 0.5 or abs(x1 - x2) < 0.5:
            # Straight line — same row or column
            points = ((x1, y1), (x2, y2))
        elif source_side in ("top", "bottom") and target_side == "left":
            # Exit North/South from gateway → go vertical first (perpendicular to face),
            # then horizontal to task (BPMN 2.0 cardinal rule)
            points = ((x1, y1), (x1, y2), (x2, y2))
        elif source_side == "right" and target_side in ("top", "bottom"):
            # Exit East from task → go horizontal first, then vertical into join gateway
            # (perpendicular entry into North/South face — BPMN 2.0 cardinal rule)
            points = ((x1, y1), (x2, y1), (x2, y2))
        elif source_side == "right" and target_side == "left":
            mid_x = x1 + max(30, (x2 - x1) / 2)
            points = ((x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2))
        else:
            mid_x = x1 + max(30, (x2 - x1) / 2)
            points = ((x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2))

        for px, py in points:
            ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {
                "x": str(px), "y": str(py),
            })

    def _content_vertical_bounds(self, start_idx):
        min_y = None
        max_y = None
        for item in list(self.plane)[start_idx:]:
            bounds = item.find(f"{{{DC_NS}}}Bounds")
            if bounds is not None:
                y = float(bounds.attrib["y"])
                h = float(bounds.attrib["height"])
                min_y = y if min_y is None else min(min_y, y)
                max_y = y + h if max_y is None else max(max_y, y + h)
                continue

            points = item.findall(f"{{{DI_NS}}}waypoint")
            for point in points:
                py = float(point.attrib["y"])
                min_y = py if min_y is None else min(min_y, py)
                max_y = py if max_y is None else max(max_y, py)

        if min_y is None or max_y is None:
            return self.y_offset, self.y_offset
        return min_y, max_y

    def _shift_plane_items(self, start_idx, delta_y):
        if abs(delta_y) < 1:
            return

        for item in list(self.plane)[start_idx:]:
            bpmn_elem = item.attrib.get("bpmnElement", "")
            if bpmn_elem.startswith("Participant_"):
                continue

            bounds = item.find(f"{{{DC_NS}}}Bounds")
            if bounds is not None:
                bounds.attrib["y"] = str(float(bounds.attrib["y"]) + delta_y)
                if bpmn_elem in self.shape_bounds:
                    x, y, w, h = self.shape_bounds[bpmn_elem]
                    self.shape_bounds[bpmn_elem] = (x, y + delta_y, w, h)
                continue

            points = item.findall(f"{{{DI_NS}}}waypoint")
            for point in points:
                point.attrib["y"] = str(float(point.attrib["y"]) + delta_y)

    def serialize(self) -> str:
        tree = ET.ElementTree(self.definitions)
        ET.indent(tree, space="  ")
        buf = io.BytesIO()
        tree.write(buf, xml_declaration=True, encoding="UTF-8")
        return buf.getvalue().decode("UTF-8")


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def build_business_flow_bpmn(ticket_id: str, chains: List[ChainSummary]) -> str:
    """Generate a ticket-level business flow BPMN showing E2EUX chains in order."""
    builder = BPMNBuilder()
    builder.add_business_flow_process(ticket_id, chains)
    return builder.serialize()


def main():

    parser = argparse.ArgumentParser(
        description="Generate BPMN 2.0 XML and ordered service segment combinations from OpenTelemetry traces in Tempo")
    parser.add_argument("--tempo-url", default="http://localhost:3200")
    parser.add_argument("--loki-url", default="http://localhost:3100", 
                        help="Loki backend URL for querying error logs")
    parser.add_argument("--loki-hours-back", type=int, default=2,
                        help="Look back N hours in Loki for error logs")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--output", default="flows_all_bpmn2.0.xml")
    parser.add_argument("--segments-output", default="service_segments.txt")
    parser.add_argument("--individual-limit", type=int, default=10,
                        help="Maximum number of individual trace BPMN files to write")
    parser.add_argument("--start", type=int, default=None,
                        help="Tempo search start time (Unix seconds)")
    parser.add_argument("--end", type=int, default=None,
                        help="Tempo search end time (Unix seconds)")
    parser.add_argument("--last-hours", type=float, default=None,
                        help="Shortcut to set start/end to the last N hours")
    parser.add_argument(
        "--traceql",
        nargs="+",
        default=None,
        help='Optional Tempo TraceQL search query, for example: { span."Business_Flow_ID" != nil }',
    )
    args = parser.parse_args()

    resolved_output = resolve_output_path(args.output)
    resolved_output_dir = os.path.dirname(resolved_output) or "."

    # Generate high-level business process flow (2 abstract tasks)
    build_high_level_business_process_flow(resolved_output_dir)

    start_unix_seconds = args.start
    end_unix_seconds = args.end
    if args.last_hours is not None:
        now = int(time.time())
        end_unix_seconds = now
        start_unix_seconds = now - int(args.last_hours * 3600)
        print(
            f"Using time window from --last-hours={args.last_hours}: "
            f"start={start_unix_seconds}, end={end_unix_seconds}"
        )

    if (start_unix_seconds is None) != (end_unix_seconds is None):
        print("Both --start and --end must be provided together (or use --last-hours).")
        sys.exit(2)

    global _id_counter
    _id_counter = 0

    print(f"Querying Tempo at {args.tempo_url} for up to {args.limit} traces...")
    groups, trace_flows = group_traces(
        args.tempo_url,
        args.limit,
        start_unix_seconds=start_unix_seconds,
        end_unix_seconds=end_unix_seconds,
        traceql_query=" ".join(args.traceql) if args.traceql else None,
    )

    # Query Loki for errors
    print(f"Querying Loki at {args.loki_url} for error logs (last {args.loki_hours_back} hours)...")
    errors_by_service = query_errors_per_service(
        loki_url=args.loki_url,
        hours_back=args.loki_hours_back,
        limit=100,
    )

    print(f"\nDiscovered {len(groups)} distinct flow(s):\n")

    builder = BPMNBuilder()

    for key in sorted(groups.keys(), key=lambda k: -len(groups[k].trees)):
        g = groups[key]
        avg = g.total_duration_ms / len(g.trees)
        err = f", {g.error_count} errors" if g.error_count else ""
        print(f"  [{len(g.trees)} traces{err}] {g.service_name} / {g.root_span_name}")
        print(f"    Avg duration: {avg:.1f}ms")

        flow_nodes = merge_group_to_flow(g)
        par_count = count_parallel_gateways(flow_nodes)
        if par_count:
            print(f"    Gateways: {par_count} parallel fork(s)")

        print()

        builder.add_process(g, flow_nodes, errors_by_service)

    segments = collect_service_segments(groups)
    output_text = serialize_service_segments(segments)
    primary_trace = primary_trace_id(groups)

    xml_output = builder.serialize()
    resolved_segments_output = resolve_output_path(
        output_path_with_trace_id(args.segments_output, primary_trace)
    )

    os.makedirs(os.path.dirname(resolved_output) or ".", exist_ok=True)
    with open(resolved_output, "w", encoding="utf-8") as f:
        f.write(xml_output)

    os.makedirs(os.path.dirname(resolved_segments_output) or ".", exist_ok=True)
    with open(resolved_segments_output, "w", encoding="utf-8") as f:
        f.write(output_text)

    individual_count = min(args.individual_limit, len(trace_flows))
    for trace in trace_flows[:individual_count]:
        individual_group = FlowGroup(
            service_name=trace.service_name,
            root_span_name=trace.root_span_name,
            trace_ids=[trace.trace_id],
            trees=[trace.root],
            total_duration_ms=trace.duration_ms,
            error_count=0 if trace.status_ok else 1,
        )
        individual_nodes = merge_group_to_flow(individual_group)
        individual_builder = BPMNBuilder()
        individual_builder.add_process(individual_group, individual_nodes, errors_by_service)
        individual_xml = individual_builder.serialize()
        individual_output = individual_bpmn_output_path(
            resolved_output,
            trace.chain_id,
            trace.trace_id,
        )
        os.makedirs(os.path.dirname(individual_output) or ".", exist_ok=True)
        with open(individual_output, "w", encoding="utf-8") as f:
            f.write(individual_xml)

    print(f"BPMN 2.0 XML written to: {resolved_output}")
    print(f"Wrote {individual_count} individual BPMN trace diagram(s) with pattern: <chain_id>_flow.xml")
    print(f"Wrote {len(segments)} service segment combination(s) to: {resolved_segments_output}")

    ticket_groups = group_by_ticket(trace_flows)
    business_flow_count = 0
    for ticket_id, chains in sorted(ticket_groups.items()):
        biz_xml = build_business_flow_bpmn(ticket_id, chains)
        biz_output = os.path.join(
            os.path.dirname(resolved_output) or ".",
            f"Business_Process_Flow_{sanitize_trace_id(ticket_id)}.xml",
        )
        with open(biz_output, "w", encoding="utf-8") as f:
            f.write(biz_xml)
        business_flow_count += 1
        print(f"  Business flow: {biz_output} ({len(chains)} E2EUX chain(s))")
    if business_flow_count:
        print(f"Wrote {business_flow_count} ticket business flow BPMN(s): <ticket_id>_business_flow.xml")
    else:
        print("No ticket_id found in traces — no business flow XMLs written.")

    print("Import the XML into Camunda Modeler, Bizagi, bpmn.js, or any BPMN 2.0 tool.")


if __name__ == "__main__":
    main()
