"""
Trace-to-BPMN 2.0 Generator
=============================
Queries Grafana Tempo for traces, discovers distinct flow patterns,
and generates BPMN 2.0 XML that can be imported into Camunda Modeler,
Bizagi, bpmn.js, or any other BPMN-compatible tool.

Usage:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
    python trace_to_bpmn.py

    # Options:
    python trace_to_bpmn.py --tempo-url http://localhost:3200 --limit 50 --output flows.bpmn

Output: BPMN 2.0 XML file with one process per distinct flow pattern.
"""

import argparse
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Span:
    span_id: str
    parent_span_id: str
    name: str
    service_name: str
    status_ok: bool
    duration_ms: float
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class FlowPattern:
    """A unique sequence of span names inside a root span, with stats."""
    service_name: str
    root_span_name: str
    # Ordered child span names (e.g. ["validate-order","check-inventory","process-payment","send-confirmation"])
    steps: Tuple[str, ...]
    # --- aggregated stats ---
    count: int = 0
    total_duration_ms: float = 0.0
    error_count: int = 0
    example_trace_id: str = ""


# ---------------------------------------------------------------------------
# Tempo client
# ---------------------------------------------------------------------------

def fetch_trace_ids(tempo_url: str, limit: int) -> List[str]:
    """Search Tempo and return trace IDs."""
    url = f"{tempo_url}/api/search?limit={limit}"
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read().decode())
    return [t["traceID"] for t in data.get("traces", [])]


def fetch_trace(tempo_url: str, trace_id: str) -> List[Span]:
    """Fetch a single trace and parse its spans."""
    url = f"{tempo_url}/api/traces/{trace_id}"
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read().decode())

    spans = []
    for batch in data.get("batches", []):
        # Extract service name from resource attributes
        svc = "unknown"
        for attr in batch.get("resource", {}).get("attributes", []):
            if attr["key"] == "service.name":
                svc = attr["value"].get("stringValue", "unknown")

        for scope_spans in batch.get("scopeSpans", []):
            for raw in scope_spans.get("spans", []):
                dur_ns = int(raw["endTimeUnixNano"]) - int(raw["startTimeUnixNano"])
                # Check status
                status = raw.get("status", {})
                status_ok = status.get("code", 0) != 2  # STATUS_CODE_ERROR = 2

                attrs = {}
                for a in raw.get("attributes", []):
                    val = (
                        a["value"].get("stringValue")
                        or a["value"].get("intValue")
                        or a["value"].get("doubleValue")
                        or str(a["value"].get("boolValue", ""))
                    )
                    attrs[a["key"]] = str(val)

                spans.append(Span(
                    span_id=raw["spanId"],
                    parent_span_id=raw.get("parentSpanId", ""),
                    name=raw["name"],
                    service_name=svc,
                    status_ok=status_ok,
                    duration_ms=dur_ns / 1e6,
                    attributes=attrs,
                ))
    return spans


# ---------------------------------------------------------------------------
# Pattern discovery
# ---------------------------------------------------------------------------

def discover_patterns(tempo_url: str, limit: int) -> Dict[str, FlowPattern]:
    """Fetch traces from Tempo and group them by their span-sequence pattern."""
    trace_ids = fetch_trace_ids(tempo_url, limit)
    if not trace_ids:
        print("No traces found in Tempo.")
        sys.exit(1)

    print(f"Fetched {len(trace_ids)} trace IDs from Tempo.")

    patterns: Dict[str, FlowPattern] = {}  # keyed by (svc, root, steps) hash

    for tid in trace_ids:
        spans = fetch_trace(tempo_url, tid)
        if not spans:
            continue

        # Build span tree
        by_id = {s.span_id: s for s in spans}
        children: Dict[str, List[Span]] = defaultdict(list)
        root: Optional[Span] = None

        for s in spans:
            if not s.parent_span_id:
                root = s
            else:
                children[s.parent_span_id].append(s)

        if root is None:
            continue

        # Get ordered child steps (sorted by original span order which is chronological)
        child_spans = children.get(root.span_id, [])
        steps = tuple(c.name for c in child_spans)

        # Pattern key
        key = f"{root.service_name}::{root.name}::{','.join(steps)}"

        root_ok = root.status_ok

        if key not in patterns:
            patterns[key] = FlowPattern(
                service_name=root.service_name,
                root_span_name=root.name,
                steps=steps,
                count=0,
                total_duration_ms=0.0,
                error_count=0,
                example_trace_id=tid,
            )

        p = patterns[key]
        p.count += 1
        p.total_duration_ms += root.duration_ms
        if not root_ok:
            p.error_count += 1

    return patterns


# ---------------------------------------------------------------------------
# BPMN 2.0 XML generation
# ---------------------------------------------------------------------------

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"


def generate_bpmn(patterns: Dict[str, FlowPattern]) -> str:
    """Generate BPMN 2.0 XML from discovered flow patterns."""

    ET.register_namespace("", BPMN_NS)
    ET.register_namespace("bpmndi", BPMNDI_NS)
    ET.register_namespace("dc", DC_NS)
    ET.register_namespace("di", DI_NS)

    definitions = ET.Element(f"{{{BPMN_NS}}}definitions", {
        "id": "Definitions_1",
        "targetNamespace": "http://opentelemetry.io/bpmn/generated",
    })

    diagram = ET.SubElement(definitions, f"{{{BPMNDI_NS}}}BPMNDiagram", {"id": "BPMNDiagram_1"})
    plane = ET.SubElement(diagram, f"{{{BPMNDI_NS}}}BPMNPlane", {
        "id": "BPMNPlane_1",
        "bpmnElement": "Collaboration_1",
    })

    collaboration = ET.SubElement(definitions, f"{{{BPMN_NS}}}collaboration", {"id": "Collaboration_1"})

    process_idx = 0
    y_offset = 0

    for key, pattern in sorted(patterns.items(), key=lambda kv: -kv[1].count):
        process_idx += 1
        proc_id = f"Process_{process_idx}"
        participant_id = f"Participant_{process_idx}"
        avg_dur = pattern.total_duration_ms / pattern.count if pattern.count else 0
        error_pct = (pattern.error_count / pattern.count * 100) if pattern.count else 0

        # Label for the pool
        pool_label = (
            f"{pattern.service_name} / {pattern.root_span_name}\n"
            f"({pattern.count} traces, avg {avg_dur:.0f}ms"
            f"{f', {error_pct:.0f}% errors' if pattern.error_count else ''})"
        )

        # Participant (pool)
        ET.SubElement(collaboration, f"{{{BPMN_NS}}}participant", {
            "id": participant_id,
            "name": pool_label,
            "processRef": proc_id,
        })

        # Process
        process = ET.SubElement(definitions, f"{{{BPMN_NS}}}process", {
            "id": proc_id,
            "isExecutable": "false",
        })

        # Add documentation with stats
        doc = ET.SubElement(process, f"{{{BPMN_NS}}}documentation")
        doc.text = (
            f"Auto-generated from OpenTelemetry trace data.\n"
            f"Service: {pattern.service_name}\n"
            f"Root span: {pattern.root_span_name}\n"
            f"Occurrences: {pattern.count}\n"
            f"Avg duration: {avg_dur:.1f}ms\n"
            f"Error rate: {error_pct:.1f}%\n"
            f"Example trace ID: {pattern.example_trace_id}"
        )

        # Build flow nodes
        x = 180
        x_step = 180
        lane_y = y_offset + 80

        # Start Event
        start_id = f"StartEvent_{process_idx}"
        ET.SubElement(process, f"{{{BPMN_NS}}}startEvent", {
            "id": start_id,
            "name": "Request\nReceived",
        })
        _add_shape(plane, start_id, x, lane_y, 36, 36)
        prev_id = start_id
        x += x_step - 50

        # Task for each step
        flow_idx = 0
        for step_name in pattern.steps:
            flow_idx += 1
            task_id = f"Task_{process_idx}_{flow_idx}"
            ET.SubElement(process, f"{{{BPMN_NS}}}serviceTask", {
                "id": task_id,
                "name": step_name,
            })
            _add_shape(plane, task_id, x, lane_y - 20, 140, 80)

            # Sequence flow
            flow_id = f"Flow_{process_idx}_{flow_idx}"
            ET.SubElement(process, f"{{{BPMN_NS}}}sequenceFlow", {
                "id": flow_id,
                "sourceRef": prev_id,
                "targetRef": task_id,
            })
            _add_edge(plane, flow_id, x - x_step + 140 + 36, lane_y + 18, x, lane_y + 18)

            prev_id = task_id
            x += x_step

        # If there are errors, add an error end event branch
        if pattern.error_count > 0:
            # Exclusive gateway before last task
            # For simplicity, add error end event after the flow
            err_end_id = f"ErrorEndEvent_{process_idx}"
            ET.SubElement(process, f"{{{BPMN_NS}}}endEvent", {
                "id": err_end_id,
                "name": f"Error\n({error_pct:.0f}%)",
            })
            err_terminate = ET.SubElement(
                process.find(f".//{{{BPMN_NS}}}endEvent[@id='{err_end_id}']"),
                f"{{{BPMN_NS}}}errorEventDefinition",
                {"id": f"ErrorDef_{process_idx}"},
            )
            _add_shape(plane, err_end_id, x - x_step, lane_y + 100, 36, 36)

            # Flow from last task to error end
            err_flow_id = f"ErrorFlow_{process_idx}"
            ET.SubElement(process, f"{{{BPMN_NS}}}sequenceFlow", {
                "id": err_flow_id,
                "name": "error",
                "sourceRef": prev_id,
                "targetRef": err_end_id,
            })
            _add_edge(plane, err_flow_id, x - x_step + 70, lane_y + 60, x - x_step + 18, lane_y + 100)

        # End Event
        end_id = f"EndEvent_{process_idx}"
        ET.SubElement(process, f"{{{BPMN_NS}}}endEvent", {
            "id": end_id,
            "name": "Completed",
        })
        _add_shape(plane, end_id, x, lane_y, 36, 36)

        # Final sequence flow
        flow_idx += 1
        flow_id = f"Flow_{process_idx}_{flow_idx}"
        ET.SubElement(process, f"{{{BPMN_NS}}}sequenceFlow", {
            "id": flow_id,
            "sourceRef": prev_id,
            "targetRef": end_id,
        })
        _add_edge(plane, flow_id, x - x_step + 140, lane_y + 18, x, lane_y + 18)

        # Pool shape (covers the full width)
        pool_width = x + 100
        _add_shape(plane, participant_id, 80, y_offset, pool_width, 250)

        y_offset += 300

    # Serialize
    tree = ET.ElementTree(definitions)
    ET.indent(tree, space="  ")

    import io
    buf = io.BytesIO()
    tree.write(buf, xml_declaration=True, encoding="UTF-8")
    return buf.getvalue().decode("UTF-8")


def _add_shape(plane, element_id, x, y, width, height):
    """Add a BPMNShape to the diagram."""
    shape = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNShape", {
        "id": f"{element_id}_di",
        "bpmnElement": element_id,
    })
    ET.SubElement(shape, f"{{{DC_NS}}}Bounds", {
        "x": str(x),
        "y": str(y),
        "width": str(width),
        "height": str(height),
    })


def _add_edge(plane, element_id, x1, y1, x2, y2):
    """Add a BPMNEdge to the diagram."""
    edge = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNEdge", {
        "id": f"{element_id}_di",
        "bpmnElement": element_id,
    })
    ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": str(x1), "y": str(y1)})
    ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": str(x2), "y": str(y2)})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate BPMN 2.0 XML from OpenTelemetry traces in Tempo")
    parser.add_argument("--tempo-url", default="http://localhost:3200", help="Tempo base URL")
    parser.add_argument("--limit", type=int, default=50, help="Max traces to fetch")
    parser.add_argument("--output", default="flows.xml", help="Output BPMN 2.0 XML file path")
    args = parser.parse_args()

    print(f"Querying Tempo at {args.tempo_url} for up to {args.limit} traces...")
    patterns = discover_patterns(args.tempo_url, args.limit)

    print(f"\nDiscovered {len(patterns)} distinct flow pattern(s):\n")
    for key, p in sorted(patterns.items(), key=lambda kv: -kv[1].count):
        avg = p.total_duration_ms / p.count
        err = f", {p.error_count} errors" if p.error_count else ""
        print(f"  [{p.count} traces{err}] {p.service_name} / {p.root_span_name}")
        print(f"    Steps: {' -> '.join(p.steps)}")
        print(f"    Avg duration: {avg:.1f}ms")
        print()

    bpmn_xml = generate_bpmn(patterns)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(bpmn_xml)

    print(f"BPMN 2.0 XML written to: {args.output}")
    print("Import into Camunda Modeler, Bizagi, bpmn.js, or any BPMN 2.0 tool.")


if __name__ == "__main__":
    main()
