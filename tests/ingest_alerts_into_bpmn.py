#!/usr/bin/env python3
"""Ingest Grafana webhook events into a BPMN XML file.

The script reads newline-delimited JSON events produced by:
  central/bin/alert-webhook/alerts.ndjson

It then enriches BPMN processes/tasks with:
- Text annotations visible in BPMN diagram tools
- Extension metadata under the otel namespace
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
OTEL_EXT_NS = "http://opentelemetry.io/bpmn/extensions"

NS = {
    "bpmn": BPMN_NS,
    "bpmndi": BPMNDI_NS,
    "dc": DC_NS,
    "di": DI_NS,
}

TRACE_ID_DOC_PATTERNS = [
    re.compile(r"Primary trace ID:\s*([A-Za-z0-9_-]+)"),
    re.compile(r"Example trace ID:\s*([A-Za-z0-9_-]+)"),
    re.compile(r"Trace ID:\s*([A-Za-z0-9_-]+)"),
]

SERVICE_KEYS = (
    "service",
    "service_name",
    "service.name",
    "app",
    "application",
    "job",
)
TRACE_ID_KEYS = ("trace_id", "traceid", "traceId", "traceID")
SEVERITY_KEYS = ("severity", "level", "priority")
TITLE_KEYS = ("title", "summary", "alertname", "name")
MESSAGE_KEYS = ("message", "description", "details")


@dataclass
class NormalizedAlert:
    event_type: str
    received_at: str
    status: str
    title: str
    message: str
    severity: str
    service: str
    trace_id: str
    raw_payload: Dict[str, Any]


def normalize_keyed_string(mapping: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return str(mapping[key]).strip()
    return ""


def parse_grafana_alerts(payload: Dict[str, Any], received_at: str, event_type: str) -> List[NormalizedAlert]:
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        return []

    normalized: List[NormalizedAlert] = []
    top_status = str(payload.get("status", "")).strip()

    for item in alerts:
        if not isinstance(item, dict):
            continue

        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        annotations = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}

        title = (
            normalize_keyed_string(annotations, TITLE_KEYS)
            or normalize_keyed_string(labels, TITLE_KEYS)
            or normalize_keyed_string(payload, TITLE_KEYS)
            or "Grafana alert"
        )
        message = (
            normalize_keyed_string(annotations, MESSAGE_KEYS)
            or normalize_keyed_string(payload, MESSAGE_KEYS)
        )
        severity = (
            normalize_keyed_string(labels, SEVERITY_KEYS)
            or normalize_keyed_string(payload, SEVERITY_KEYS)
            or "unknown"
        )
        service = (
            normalize_keyed_string(labels, SERVICE_KEYS)
            or normalize_keyed_string(payload, SERVICE_KEYS)
        )
        trace_id = (
            normalize_keyed_string(labels, TRACE_ID_KEYS)
            or normalize_keyed_string(annotations, TRACE_ID_KEYS)
            or normalize_keyed_string(payload, TRACE_ID_KEYS)
        )
        status = str(item.get("status", top_status or "unknown")).strip() or "unknown"

        normalized.append(
            NormalizedAlert(
                event_type=event_type,
                received_at=received_at,
                status=status,
                title=title,
                message=message,
                severity=severity,
                service=service,
                trace_id=trace_id,
                raw_payload=item,
            )
        )

    return normalized


def parse_basic_event(payload: Dict[str, Any], received_at: str, event_type: str) -> NormalizedAlert:
    title = normalize_keyed_string(payload, TITLE_KEYS) or "Alert event"
    message = normalize_keyed_string(payload, MESSAGE_KEYS)
    severity = normalize_keyed_string(payload, SEVERITY_KEYS) or "unknown"
    service = normalize_keyed_string(payload, SERVICE_KEYS)
    trace_id = normalize_keyed_string(payload, TRACE_ID_KEYS)
    status = str(payload.get("status", "unknown")).strip() or "unknown"

    return NormalizedAlert(
        event_type=event_type,
        received_at=received_at,
        status=status,
        title=title,
        message=message,
        severity=severity,
        service=service,
        trace_id=trace_id,
        raw_payload=payload,
    )


def load_alerts(alerts_file: str) -> List[NormalizedAlert]:
    events: List[NormalizedAlert] = []
    with open(alerts_file, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[WARN] Skipping invalid JSON line {idx}: {exc}", file=sys.stderr)
                continue

            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            received_at = str(event.get("received_at", "")) or datetime.utcnow().isoformat() + "Z"
            event_type = str(event.get("event_type", "alert_event"))

            parsed_grafana = parse_grafana_alerts(payload, received_at, event_type)
            if parsed_grafana:
                events.extend(parsed_grafana)
            else:
                events.append(parse_basic_event(payload, received_at, event_type))

    return events


def normalize_service_name(value: str) -> str:
    return value.strip().lower()


def extract_trace_id_from_process_doc(process_elem: ET.Element) -> str:
    doc = process_elem.find("bpmn:documentation", NS)
    if doc is None or not doc.text:
        return ""

    for pattern in TRACE_ID_DOC_PATTERNS:
        match = pattern.search(doc.text)
        if match:
            return match.group(1).strip()
    return ""


def find_plane(root: ET.Element) -> Optional[ET.Element]:
    diagram = root.find("bpmndi:BPMNDiagram", NS)
    if diagram is None:
        return None
    return diagram.find("bpmndi:BPMNPlane", NS)


def build_shape_bounds(plane: Optional[ET.Element]) -> Dict[str, Tuple[float, float, float, float]]:
    if plane is None:
        return {}

    bounds: Dict[str, Tuple[float, float, float, float]] = {}
    for shape in plane.findall("bpmndi:BPMNShape", NS):
        elem_id = shape.attrib.get("bpmnElement", "")
        b = shape.find("dc:Bounds", NS)
        if not elem_id or b is None:
            continue
        bounds[elem_id] = (
            float(b.attrib.get("x", "0")),
            float(b.attrib.get("y", "0")),
            float(b.attrib.get("width", "0")),
            float(b.attrib.get("height", "0")),
        )
    return bounds


def next_id(existing_ids: set[str], prefix: str) -> str:
    i = 1
    while True:
        candidate = f"{prefix}_{i}"
        if candidate not in existing_ids:
            existing_ids.add(candidate)
            return candidate
        i += 1


def add_annotation_shape(
    plane: ET.Element,
    shape_id: str,
    bpmn_element: str,
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    shape = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNShape", {
        "id": shape_id,
        "bpmnElement": bpmn_element,
    })
    ET.SubElement(shape, f"{{{DC_NS}}}Bounds", {
        "x": f"{x:.1f}",
        "y": f"{y:.1f}",
        "width": f"{w:.1f}",
        "height": f"{h:.1f}",
    })


def add_association_edge(
    plane: ET.Element,
    edge_id: str,
    bpmn_element: str,
    source: Tuple[float, float],
    target: Tuple[float, float],
) -> None:
    edge = ET.SubElement(plane, f"{{{BPMNDI_NS}}}BPMNEdge", {
        "id": edge_id,
        "bpmnElement": bpmn_element,
    })
    ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": f"{source[0]:.1f}", "y": f"{source[1]:.1f}"})
    ET.SubElement(edge, f"{{{DI_NS}}}waypoint", {"x": f"{target[0]:.1f}", "y": f"{target[1]:.1f}"})


def format_annotation_text(alerts: List[NormalizedAlert], max_items: int) -> str:
    lines = [f"Alerts: {len(alerts)}"]
    sorted_alerts = sorted(alerts, key=lambda alert: alert.received_at, reverse=True)

    for alert in sorted_alerts[:max_items]:
        title = alert.title or "Alert"
        sev = alert.severity or "unknown"
        status = alert.status or "unknown"
        lines.append(f"- [{status}/{sev}] {title}")
        if alert.message:
            lines.append(f"  {alert.message[:120]}")

    if len(sorted_alerts) > max_items:
        lines.append(f"... +{len(sorted_alerts) - max_items} more")

    return "\n".join(lines)


def ensure_extension_alerts(task: ET.Element, alerts: List[NormalizedAlert], max_items: int) -> None:
    extension = task.find("bpmn:extensionElements", NS)
    if extension is None:
        extension = ET.SubElement(task, f"{{{BPMN_NS}}}extensionElements")

    existing = extension.find(f"{{{OTEL_EXT_NS}}}alertEvents")
    if existing is not None:
        extension.remove(existing)

    alert_events = ET.SubElement(extension, f"{{{OTEL_EXT_NS}}}alertEvents", {
        "count": str(len(alerts)),
    })

    sorted_alerts = sorted(alerts, key=lambda alert: alert.received_at, reverse=True)
    for alert in sorted_alerts[:max_items]:
        event_elem = ET.SubElement(alert_events, f"{{{OTEL_EXT_NS}}}alertEvent", {
            "receivedAt": alert.received_at,
            "eventType": alert.event_type,
            "status": alert.status,
            "severity": alert.severity,
            "service": alert.service,
            "traceId": alert.trace_id,
            "title": alert.title,
        })
        if alert.message:
            msg_elem = ET.SubElement(event_elem, f"{{{OTEL_EXT_NS}}}message")
            msg_elem.text = alert.message


def ingest_alerts_into_bpmn(
    bpmn_path: str,
    alerts_file: str,
    output_path: str,
    max_items: int,
) -> Tuple[int, int]:
    ET.register_namespace("", BPMN_NS)
    ET.register_namespace("bpmndi", BPMNDI_NS)
    ET.register_namespace("dc", DC_NS)
    ET.register_namespace("di", DI_NS)
    ET.register_namespace("otel", OTEL_EXT_NS)

    alerts = load_alerts(alerts_file)
    if not alerts:
        raise RuntimeError("No alert events were found in the alerts file.")

    tree = ET.parse(bpmn_path)
    root = tree.getroot()

    plane = find_plane(root)
    shape_bounds = build_shape_bounds(plane)

    existing_ids = {elem.attrib["id"] for elem in root.iter() if "id" in elem.attrib}

    alerts_by_service: Dict[str, List[NormalizedAlert]] = {}
    alerts_by_trace: Dict[str, List[NormalizedAlert]] = {}
    global_alerts: List[NormalizedAlert] = []

    for alert in alerts:
        has_service = bool(alert.service)
        has_trace = bool(alert.trace_id)

        if has_service:
            key = normalize_service_name(alert.service)
            alerts_by_service.setdefault(key, []).append(alert)
        if has_trace:
            alerts_by_trace.setdefault(alert.trace_id, []).append(alert)
        if not has_service and not has_trace:
            global_alerts.append(alert)

    total_task_annotations = 0
    total_process_annotations = 0

    for process in root.findall("bpmn:process", NS):
        process_id = process.attrib.get("id", "")
        process_trace_id = extract_trace_id_from_process_doc(process)
        process_trace_alerts = alerts_by_trace.get(process_trace_id, []) if process_trace_id else []

        process_global = list(global_alerts) + [
            alert for alert in process_trace_alerts if not alert.service
        ]

        if process_global and plane is not None:
            tasks = process.findall("bpmn:serviceTask", NS)
            anchor_id = tasks[0].attrib.get("id") if tasks else None
            anchor_bounds = shape_bounds.get(anchor_id, (180.0, 120.0, 120.0, 64.0)) if anchor_id else (180.0, 120.0, 120.0, 64.0)
            ax, ay, aw, ah = anchor_bounds
            ann_x = ax
            ann_y = ay - 85
            ann_w = max(240.0, aw + 60.0)
            ann_h = 70.0

            ann_id = next_id(existing_ids, "AlertProcessAnnotation")
            text_ann = ET.SubElement(process, f"{{{BPMN_NS}}}textAnnotation", {"id": ann_id})
            text_elem = ET.SubElement(text_ann, f"{{{BPMN_NS}}}text")
            text_elem.text = format_annotation_text(process_global, max_items=1)

            if anchor_id:
                assoc_id = next_id(existing_ids, "AlertProcessAssociation")
                ET.SubElement(process, f"{{{BPMN_NS}}}association", {
                    "id": assoc_id,
                    "sourceRef": anchor_id,
                    "targetRef": ann_id,
                })

                add_annotation_shape(plane, f"{ann_id}_di", ann_id, ann_x, ann_y, ann_w, ann_h)
                add_association_edge(
                    plane,
                    f"{assoc_id}_di",
                    assoc_id,
                    (ax + aw * 0.5, ay),
                    (ann_x + ann_w * 0.5, ann_y + ann_h),
                )
            total_process_annotations += 1

        for task in process.findall("bpmn:serviceTask", NS):
            task_id = task.attrib.get("id", "")
            task_name = task.attrib.get("name", "")
            task_service = normalize_service_name(task_name.split("\n", 1)[0])

            matched: List[NormalizedAlert] = []

            if process_trace_id and process_trace_id in alerts_by_trace:
                for alert in alerts_by_trace[process_trace_id]:
                    if not alert.service or normalize_service_name(alert.service) == task_service:
                        matched.append(alert)

            matched.extend(alerts_by_service.get(task_service, []))

            if not matched:
                continue

            # De-duplicate while preserving order.
            seen = set()
            deduped: List[NormalizedAlert] = []
            for alert in matched:
                key = (alert.received_at, alert.title, alert.service, alert.trace_id)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(alert)

            ensure_extension_alerts(task, deduped, max_items=max_items)

            if plane is not None and task_id in shape_bounds:
                tx, ty, tw, th = shape_bounds[task_id]
                ann_id = next_id(existing_ids, "AlertTaskAnnotation")
                assoc_id = next_id(existing_ids, "AlertTaskAssociation")

                text_ann = ET.SubElement(process, f"{{{BPMN_NS}}}textAnnotation", {"id": ann_id})
                text_elem = ET.SubElement(text_ann, f"{{{BPMN_NS}}}text")
                text_elem.text = format_annotation_text(deduped, max_items=max_items)

                ET.SubElement(process, f"{{{BPMN_NS}}}association", {
                    "id": assoc_id,
                    "sourceRef": task_id,
                    "targetRef": ann_id,
                })

                ann_w = 260.0
                ann_h = 82.0
                ann_x = tx + tw + 40.0
                ann_y = ty - 8.0
                add_annotation_shape(plane, f"{ann_id}_di", ann_id, ann_x, ann_y, ann_w, ann_h)
                add_association_edge(
                    plane,
                    f"{assoc_id}_di",
                    assoc_id,
                    (tx + tw, ty + th * 0.5),
                    (ann_x, ann_y + ann_h * 0.5),
                )

            total_task_annotations += 1

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    out_tree = ET.ElementTree(root)
    ET.indent(out_tree, space="  ")
    buf = io.BytesIO()
    out_tree.write(buf, encoding="UTF-8", xml_declaration=True)
    with open(output_path, "wb") as f:
        f.write(buf.getvalue())

    return total_task_annotations, total_process_annotations


def default_alerts_file() -> str:
    return str((Path(__file__).resolve().parent.parent / "central" / "bin" / "alert-webhook" / "alerts.ndjson").resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest alert webhook events into BPMN XML.")
    parser.add_argument("--bpmn", required=True, help="Input BPMN XML file path.")
    parser.add_argument("--alerts-file", default=default_alerts_file(), help="Alert NDJSON file.")
    parser.add_argument("--output", default="", help="Output BPMN XML path. Defaults to *_with_alerts.xml")
    parser.add_argument("--max-items", type=int, default=3, help="Max alert items shown per annotation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    bpmn_path = str(Path(args.bpmn).resolve())
    alerts_path = str(Path(args.alerts_file).resolve())

    if not os.path.exists(bpmn_path):
        print(f"Input BPMN file not found: {bpmn_path}", file=sys.stderr)
        return 2
    if not os.path.exists(alerts_path):
        print(f"Alerts file not found: {alerts_path}", file=sys.stderr)
        return 2

    if args.output:
        output_path = str(Path(args.output).resolve())
    else:
        p = Path(bpmn_path)
        output_path = str(p.with_name(f"{p.stem}_with_alerts{p.suffix}"))

    task_count, process_count = ingest_alerts_into_bpmn(
        bpmn_path=bpmn_path,
        alerts_file=alerts_path,
        output_path=output_path,
        max_items=max(1, args.max_items),
    )

    print(f"Alert-enriched BPMN written to: {output_path}")
    print(f"Task annotations added: {task_count}")
    print(f"Process annotations added: {process_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
