from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
from collections import defaultdict
import re
from typing import Optional


NAMESPACES = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "otel": "http://opentelemetry.io/bpmn/extensions",
}


def to_number(value: str | None) -> int | float | None:
    if value is None:
        return None

    number = float(value)
    return int(number) if number.is_integer() else number


def shape_map_from_root(root: ET.Element) -> dict[str, dict[str, int | float | str | None]]:
    shape_map: dict[str, dict[str, int | float | str | None]] = {}

    for shape in root.findall(".//bpmndi:BPMNShape", NAMESPACES):
        bpmn_element_id = shape.get("bpmnElement")
        if not bpmn_element_id:
            continue

        bounds = shape.find("dc:Bounds", NAMESPACES)
        if bounds is None:
            continue

        shape_info = {
            "x": to_number(bounds.get("x")),
            "y": to_number(bounds.get("y")),
            "width": to_number(bounds.get("width")),
            "height": to_number(bounds.get("height")),
            "stroke": shape.get("stroke"),
        }
        # Recognize Task_* as rectangle
        if bpmn_element_id.startswith("Task_"):
            shape_info["shape"] = "rectangle"
        shape_map[bpmn_element_id] = shape_info

    return shape_map


def edge_data_map_from_root(
    root: ET.Element,
) -> dict[str, dict[str, object]]:
    edge_map: dict[str, dict[str, object]] = {}

    for edge in root.findall(".//bpmndi:BPMNEdge", NAMESPACES):
        bpmn_element_id = edge.get("bpmnElement")
        if not bpmn_element_id:
            continue

        waypoints: list[dict[str, int | float | None]] = []
        for waypoint in edge.findall("di:waypoint", NAMESPACES):
            waypoints.append(
                {
                    "x": to_number(waypoint.get("x")),
                    "y": to_number(waypoint.get("y")),
                }
            )

        edge_map[bpmn_element_id] = {
            "waypoints": waypoints,
            "stroke": edge.get("stroke"),
        }

    return edge_map


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def gateway_type_from_tag(tag: str) -> str:
    name = local_name(tag)
    if not name.endswith("Gateway"):
        return "gateway"

    gateway_type = name[: -len("Gateway")]
    return gateway_type[:1].lower() + gateway_type[1:]


def collapse_task_file_map_from_process(process: ET.Element) -> dict[str, str]:
    mapping: dict[str, str] = {}

    for element in process.iter():
        element_name = local_name(element.tag)
        if element_name not in {"collapseTaskFile", "collapsedTaskFile"}:
            continue

        task_ref = (element.get("taskRef") or "").strip()
        file_name = (element.get("fileName") or "").strip()

        if file_name.lower().endswith(".xml"):
            file_name = f"{file_name[:-4]}.json"

        if task_ref and file_name:
            mapping[task_ref] = file_name

    return mapping


def documentation_task_file_map_from_process(process: ET.Element) -> dict[str, str]:
    """Extract task/subProcess file mapping from documentation text like: 'See: some_flow.xml'."""
    mapping: dict[str, str] = {}
    supported_elements = {
        "task",
        "serviceTask",
        "userTask",
        "manualTask",
        "scriptTask",
        "businessRuleTask",
        "sendTask",
        "receiveTask",
        "subProcess",
        "callActivity",
    }
    see_pattern = re.compile(r"^\s*see\s*:\s*(?P<file>[^\s]+)", re.IGNORECASE)

    for element in process.iter():
        element_name = local_name(element.tag)
        if element_name not in supported_elements:
            continue

        element_id = (element.get("id") or "").strip()
        if not element_id:
            continue

        doc = element.find("bpmn:documentation", NAMESPACES)
        doc_text = (doc.text or "").strip() if doc is not None else ""
        if not doc_text:
            continue

        match = see_pattern.match(doc_text)
        if not match:
            continue

        file_name = match.group("file").strip()
        if file_name.lower().endswith(".xml"):
            file_name = f"{file_name[:-4]}.json"
        if file_name:
            mapping[element_id] = file_name

    return mapping


def task_file_map_from_process(process: ET.Element) -> dict[str, str]:
    """Combine explicit collapseTaskFile mappings with documentation-derived mappings."""
    mapping = collapse_task_file_map_from_process(process)
    mapping.update(documentation_task_file_map_from_process(process))
    return mapping


def parent_task_map_from_process(process: ET.Element) -> dict[str, str]:
    """Map each BPMN element id to its nearest parent task-like container id."""
    supported_elements = {
        "task",
        "serviceTask",
        "userTask",
        "manualTask",
        "scriptTask",
        "businessRuleTask",
        "sendTask",
        "receiveTask",
        "subProcess",
        "callActivity",
    }
    parent_map: dict[str, str] = {}

    def walk(element: ET.Element, current_parent_id: Optional[str]) -> None:
        for child in element:
            child_id = (child.get("id") or "").strip()
            child_name = local_name(child.tag)

            if child_id and current_parent_id:
                parent_map[child_id] = current_parent_id

            next_parent_id = current_parent_id
            if child_id and child_name in supported_elements:
                next_parent_id = child_id

            walk(child, next_parent_id)

    walk(process, None)
    return parent_map


def grouped_task_file_map(
    process: ET.Element,
    task_file_map: dict[str, str],
    base_dir: Path,
) -> tuple[dict[str, list[str]], set[str]]:
    """Group nested linked files under the nearest parent task/subProcess."""
    parent_map = parent_task_map_from_process(process)
    grouped_files: dict[str, list[str]] = defaultdict(list)
    suppressed_ids: set[str] = set()

    for element_id, file_name in task_file_map.items():
        full_path = str((base_dir / file_name).resolve())
        parent_id = parent_map.get(element_id)

        owner_id = parent_id if parent_id else element_id
        if full_path not in grouped_files[owner_id]:
            grouped_files[owner_id].append(full_path)

        if parent_id:
            suppressed_ids.add(element_id)

    return dict(grouped_files), suppressed_ids


def _is_duration_metric_annotation(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized.startswith("duarationdataset") or normalized.startswith("durationdataset")


def task_annotation_maps_from_process(process: ET.Element) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    annotation_text_map: dict[str, str] = {}

    for annotation in process.findall(".//bpmn:textAnnotation", NAMESPACES):
        annotation_id = (annotation.get("id") or "").strip()
        if not annotation_id:
            continue

        text_element = annotation.find("bpmn:text", NAMESPACES)
        annotation_text_map[annotation_id] = (text_element.text or "").strip() if text_element is not None else ""

    task_to_applications: dict[str, list[str]] = {}
    task_to_metrics: dict[str, list[str]] = {}
    association_paths = [".//bpmn:association", ".//bpmn:textAssociation"]

    for association_path in association_paths:
        for association in process.findall(association_path, NAMESPACES):
            source_ref = (association.get("sourceRef") or "").strip()
            target_ref = (association.get("targetRef") or "").strip()
            if not source_ref or not target_ref:
                continue

            annotation_text = annotation_text_map.get(source_ref)
            if annotation_text is None:
                continue

            if _is_duration_metric_annotation(annotation_text):
                metrics = task_to_metrics.get(target_ref, [])
                metrics.append(annotation_text)
                task_to_metrics[target_ref] = metrics
                continue

            applications: list[str] = []
            for token in annotation_text.split(","):
                app_name = token.strip()
                if app_name:
                    applications.append(app_name)

            if applications:
                task_to_applications[target_ref] = applications

    return task_to_applications, task_to_metrics


def task_errors_map_from_process(process: ET.Element) -> dict[str, list[dict[str, str]]]:
    """Extract span-level SQL error attributes into a per-task errors map."""
    task_to_errors: dict[str, list[dict[str, str]]] = {}
    task_paths = [
        ".//bpmn:task",
        ".//bpmn:serviceTask",
        ".//bpmn:userTask",
        ".//bpmn:manualTask",
        ".//bpmn:scriptTask",
        ".//bpmn:businessRuleTask",
        ".//bpmn:sendTask",
        ".//bpmn:receiveTask",
        ".//bpmn:subProcess",
    ]

    for task_path in task_paths:
        for task in process.findall(task_path, NAMESPACES):
            task_id = (task.get("id") or "").strip()
            if not task_id:
                continue

            errors: list[dict[str, str]] = []
            seen = set()
            for span in task.findall(".//bpmn:extensionElements/otel:spanDataSet/otel:spanData", NAMESPACES):
                status = (span.get("status") or "").strip().upper()
                attrs: dict[str, str] = {}

                attrs_elem = span.find("otel:attributes", NAMESPACES)
                if attrs_elem is not None:
                    for attr in attrs_elem.findall("otel:attribute", NAMESPACES):
                        key = (attr.get("key") or "").strip()
                        value = (attr.get("value") or "").strip()
                        if key:
                            attrs[key] = value

                error_message = attrs.get("error.message", "")
                error_type = attrs.get("error.type", "")
                has_error = bool(error_message or error_type or (status and status != "OK"))
                if not has_error:
                    continue

                error_obj = {
                    "db.name": attrs.get("db.name", ""),
                    "statement": attrs.get("db.statement", ""),
                    "error_message": error_message,
                    "type": error_type,
                }
                dedup_key = (
                    error_obj["db.name"],
                    error_obj["statement"],
                    error_obj["error_message"],
                    error_obj["type"],
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                errors.append(error_obj)

            if errors:
                task_to_errors[task_id] = errors

    return task_to_errors


def parse_bpmn_file(xml_path: Path, base_dir: Optional[Path] = None) -> list[dict[str, object]]:
    root = ET.parse(xml_path).getroot()
    process = root.find("bpmn:process", NAMESPACES)
    if process is None:
        return []

    if base_dir is None:
        base_dir = xml_path.parent

    shapes = shape_map_from_root(root)
    edge_data = edge_data_map_from_root(root)
    task_file_map = task_file_map_from_process(process)
    grouped_file_map, suppressed_ids = grouped_task_file_map(process, task_file_map, base_dir)
    task_applications_map, task_metrics_map = task_annotation_maps_from_process(process)
    task_errors_map = task_errors_map_from_process(process)
    rows: list[dict[str, object]] = []
    incoming_gateway_refs: dict[str, list[str]] = defaultdict(list)
    outgoing_gateway_refs: dict[str, list[str]] = defaultdict(list)

    sequence_flows = []
    for flow in process.findall(".//bpmn:sequenceFlow", NAMESPACES):
        source_ref = flow.get("sourceRef", "")
        target_ref = flow.get("targetRef", "")
        if source_ref in suppressed_ids or target_ref in suppressed_ids:
            continue
        sequence_flows.append(flow)

    for flow in sequence_flows:
        source_ref = flow.get("sourceRef", "")
        target_ref = flow.get("targetRef", "")

        if target_ref:
            incoming_gateway_refs[target_ref].append(source_ref)
        if source_ref:
            outgoing_gateway_refs[source_ref].append(target_ref)

    for lane in process.findall(".//bpmn:lane", NAMESPACES):
        lane_id = lane.get("id", "")
        lane_shape = shapes.get(lane_id, {})
        rows.append(
            {
                "id": lane_id,
                "type": "lane",
                "name": lane.get("name", ""),
                "x": lane_shape.get("x"),
                "y": lane_shape.get("y"),
                "height": lane_shape.get("height"),
                "width": lane_shape.get("width"),
                "shape": "rectangle",
                "color": lane_shape.get("stroke"),
            }
        )

    task_paths = (
        ".//bpmn:task",
        ".//bpmn:serviceTask",
        ".//bpmn:userTask",
        ".//bpmn:manualTask",
        ".//bpmn:scriptTask",
        ".//bpmn:businessRuleTask",
        ".//bpmn:sendTask",
        ".//bpmn:receiveTask",
    )
    seen_task_ids: set[str] = set()

    for task_path in task_paths:
        for task in process.findall(task_path, NAMESPACES):
            task_id = task.get("id", "")
            if not task_id or task_id in seen_task_ids:
                continue
            if task_id in suppressed_ids:
                continue
            seen_task_ids.add(task_id)

            task_shape = shapes.get(task_id, {})
            task_row: dict[str, object] = {
                "id": task_id,
                "type": "task",
                "name": task.get("name", ""),
                "x": task_shape.get("x"),
                "y": task_shape.get("y"),
                "height": task_shape.get("height"),
                "width": task_shape.get("width"),
                "shape": "rectangle",
                "color": task_shape.get("stroke"),
                "applications": task_applications_map.get(task_id, []),
                "metrics": task_metrics_map.get(task_id, []),
                "errors": task_errors_map.get(task_id, []),
            }

            # Explicitly force Task_* ids to rectangle.
            if task_id.startswith("Task_"):
                task_row["shape"] = "rectangle"

            sub_process_file_names = grouped_file_map.get(task_id)
            if sub_process_file_names:
                task_row["subProcessFileNames"] = sub_process_file_names
                task_row["subProcessDisplayNames"] = [
                    Path(file_name).name for file_name in sub_process_file_names
                ]

            rows.append(task_row)

    for sub_process in process.findall(".//bpmn:subProcess", NAMESPACES):
        sub_process_id = sub_process.get("id", "")
        if not sub_process_id or sub_process_id in suppressed_ids:
            continue
        sub_process_shape = shapes.get(sub_process_id, {})
        sub_process_row: dict[str, object] = {
            "id": sub_process_id,
            "type": "task",
            "name": sub_process.get("name", ""),
            "x": sub_process_shape.get("x"),
            "y": sub_process_shape.get("y"),
            "height": sub_process_shape.get("height"),
            "width": sub_process_shape.get("width"),
            "shape": "rectangle",
            "color": sub_process_shape.get("stroke"),
            "applications": task_applications_map.get(sub_process_id, []),
            "metrics": task_metrics_map.get(sub_process_id, []),
            "errors": task_errors_map.get(sub_process_id, []),
        }

        sub_process_file_names = grouped_file_map.get(sub_process_id)
        if sub_process_file_names:
            sub_process_row["subProcessFileNames"] = sub_process_file_names
            sub_process_row["subProcessDisplayNames"] = [
                Path(file_name).name for file_name in sub_process_file_names
            ]

        rows.append(sub_process_row)

    for start_event in process.findall(".//bpmn:startEvent", NAMESPACES):
        event_id = start_event.get("id", "")
        event_shape = shapes.get(event_id, {})
        rows.append(
            {
                "id": event_id,
                "type": "event",
                "name": start_event.get("name", ""),
                "x": event_shape.get("x"),
                "y": event_shape.get("y"),
                "height": event_shape.get("height"),
                "width": event_shape.get("width"),
                "shape": "circle",
                "color": event_shape.get("stroke"),
            }
        )

    for end_event in process.findall(".//bpmn:endEvent", NAMESPACES):
        event_id = end_event.get("id", "")
        event_shape = shapes.get(event_id, {})
        rows.append(
            {
                "id": event_id,
                "type": "event",
                "name": end_event.get("name", ""),
                "x": event_shape.get("x"),
                "y": event_shape.get("y"),
                "height": event_shape.get("height"),
                "width": event_shape.get("width"),
                "shape": "circle",
                "color": event_shape.get("stroke"),
            }
        )

    for element in process.iter():
        tag_name = local_name(element.tag)
        if not tag_name.endswith("Gateway"):
            continue

        gateway_id = element.get("id", "")
        gateway_shape = shapes.get(gateway_id, {})
        rows.append(
            {
                "id": gateway_id,
                "name": element.get("name", ""),
                "soureRef": incoming_gateway_refs.get(gateway_id, []),
                "targetRef": outgoing_gateway_refs.get(gateway_id, []),
                "type": gateway_type_from_tag(element.tag),
                "shape": "diamond",
                "x": gateway_shape.get("x"),
                "y": gateway_shape.get("y"),
                "width": gateway_shape.get("width"),
                "height": gateway_shape.get("height"),
                "color": gateway_shape.get("stroke"),
            }
        )

    for flow in sequence_flows:
        flow_id = flow.get("id", "")
        flow_di = edge_data.get(flow_id, {})
        rows.append(
            {
                "id": flow_id,
                "sourceRef": flow.get("sourceRef", ""),
                "targetRef": flow.get("targetRef", ""),
                "type": "flow",
                "shape": "line",
                "waypoints": flow_di.get("waypoints", []),
                "color": flow_di.get("stroke"),
            }
        )

    return rows


def run() -> None:
    # Read BPMN XML files from tests/output and write JSON files there too.
    tests_dir = Path(__file__).resolve().parent
    output_dir = tests_dir / "output"

    if not output_dir.exists():
        print(f"Output directory not found: {output_dir}")
        return

    xml_files = sorted(output_dir.glob("*.xml"))
    if not xml_files:
        print(f"No .xml files found under: {output_dir}")
        return

    converted_count = 0
    skipped_count = 0

    for xml_file in xml_files:
        try:
            rows = parse_bpmn_file(xml_file, base_dir=output_dir)
        except ET.ParseError as exc:
            skipped_count += 1
            print(f"Skipping malformed XML file {xml_file.name}: {exc}")
            continue

        output_file = xml_file.with_suffix('.json')
        output_file.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        converted_count += 1
        print(f"{xml_file.name} -> {output_file.name} ({len(rows)} records)")

    print(f"xml2json summary: converted={converted_count}, skipped={skipped_count}")


if __name__ == "__main__":
    run()