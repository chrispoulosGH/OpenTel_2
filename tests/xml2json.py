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

            # Also read from Loki-derived errorDataSet/errorRecord extensions
            for err_rec in task.findall(
                ".//bpmn:extensionElements/otel:errorDataSet/otel:errorRecord",
                NAMESPACES,
            ):
                event = (err_rec.get("event") or "").strip()
                err_attrs: dict[str, str] = {}
                attrs_elem = err_rec.find("otel:attributes", NAMESPACES)
                if attrs_elem is not None:
                    for attr in attrs_elem.findall("otel:attribute", NAMESPACES):
                        key = (attr.get("key") or "").strip()
                        value = (attr.get("value") or "").strip()
                        if key:
                            err_attrs[key] = value

                msg_elem = err_rec.find("otel:message", NAMESPACES)
                raw_message = (msg_elem.text or "").strip() if msg_elem is not None else ""

                error_obj = {
                    "db.name": err_attrs.get("db", err_attrs.get("db.name", "")),
                    "statement": err_attrs.get("db.statement", ""),
                    "error_message": err_attrs.get("message", raw_message),
                    "type": err_attrs.get("kind", event),
                    "event": event,
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


def _parse_transaction_count_from_name(name: str) -> Optional[int]:
    """Extract count from strings like 'ABPT / GET /d\n(57 traces, avg 5128ms)'."""
    match = re.search(r'\((\d+)\s+traces?', name or '')
    if match:
        return int(match.group(1))
    return None


def pool_items_from_root(
    root: ET.Element,
    shape_map: dict[str, dict],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Return (pool_items, processId→transactionCount) from bpmn:collaboration."""
    collaboration = root.find("bpmn:collaboration", NAMESPACES)
    if collaboration is None:
        return [], {}

    pool_items: list[dict[str, object]] = []
    process_count_map: dict[str, int] = {}

    for participant in collaboration.findall("bpmn:participant", NAMESPACES):
        participant_id = participant.get("id", "")
        process_ref = participant.get("processRef", "")
        name = participant.get("name", "")
        txn_count = _parse_transaction_count_from_name(name)
        shape = shape_map.get(participant_id, {})
        pool_items.append({
            "id": participant_id,
            "type": "pool",
            "name": name,
            "x": shape.get("x"),
            "y": shape.get("y"),
            "width": shape.get("width"),
            "height": shape.get("height"),
            "shape": "rectangle",
            "transactionCount": txn_count,
            "processRef": process_ref,
        })
        if process_ref and txn_count is not None:
            process_count_map[process_ref] = txn_count

    return pool_items, process_count_map


def dominant_chain_id_from_process(process: ET.Element) -> Optional[str]:
    """Find the most frequent chain_id value from spanData attributes within a process."""
    counts: dict[str, int] = defaultdict(int)
    for span in process.findall(".//otel:spanData", NAMESPACES):
        attrs = span.find("otel:attributes", NAMESPACES)
        if attrs is None:
            continue
        for attr in attrs.findall("otel:attribute", NAMESPACES):
            key = (attr.get("key") or "").strip().lower()
            if key not in {"chain_id", "chain.id"}:
                continue
            value = (attr.get("value") or "").strip()
            if value:
                counts[value] += 1
                break

    if not counts:
        return None

    return max(counts.items(), key=lambda item: item[1])[0]


def task_chain_counts_from_process(process: ET.Element, chain_id: str) -> dict[str, int]:
    """Count matching spans per task/subProcess for a chain_id."""
    task_paths = (
        ".//bpmn:task",
        ".//bpmn:serviceTask",
        ".//bpmn:userTask",
        ".//bpmn:manualTask",
        ".//bpmn:scriptTask",
        ".//bpmn:businessRuleTask",
        ".//bpmn:sendTask",
        ".//bpmn:receiveTask",
        ".//bpmn:subProcess",
    )
    result: dict[str, int] = {}

    for task_path in task_paths:
        for task in process.findall(task_path, NAMESPACES):
            task_id = (task.get("id") or "").strip()
            if not task_id:
                continue
            count = 0
            for span in task.findall(".//otel:spanData", NAMESPACES):
                attrs = span.find("otel:attributes", NAMESPACES)
                if attrs is None:
                    continue
                span_chain_id = None
                for attr in attrs.findall("otel:attribute", NAMESPACES):
                    key = (attr.get("key") or "").strip().lower()
                    if key in {"chain_id", "chain.id"}:
                        span_chain_id = (attr.get("value") or "").strip()
                        break
                if span_chain_id == chain_id:
                    count += 1
            result[task_id] = count

    return result


def flow_transaction_counts(process: ET.Element) -> dict[str, int]:
    """Estimate per-sequence-flow transaction counts from dominant chain activity."""
    dominant_chain = dominant_chain_id_from_process(process)
    if not dominant_chain:
        return {}

    task_counts = task_chain_counts_from_process(process, dominant_chain)
    flow_counts: dict[str, int] = {}

    for flow in process.findall(".//bpmn:sequenceFlow", NAMESPACES):
        flow_id = (flow.get("id") or "").strip()
        source_ref = (flow.get("sourceRef") or "").strip()
        target_ref = (flow.get("targetRef") or "").strip()
        if not flow_id:
            continue

        source_count = task_counts.get(source_ref, 0)
        target_count = task_counts.get(target_ref, 0)
        if source_count and target_count:
            flow_counts[flow_id] = min(source_count, target_count)
        elif source_count or target_count:
            flow_counts[flow_id] = max(source_count, target_count)
        else:
            flow_counts[flow_id] = 0

    return flow_counts


def unique_test_scenarios_in_process(process: ET.Element) -> set[str]:
    scenarios: set[str] = set()
    for span in process.findall(".//otel:spanData", NAMESPACES):
        attrs = span.find("otel:attributes", NAMESPACES)
        if attrs is None:
            continue
        for attr in attrs.findall("otel:attribute", NAMESPACES):
            key = (attr.get("key") or "").strip().lower()
            if key not in {"chain_id", "chain.id"}:
                continue
            value = (attr.get("value") or "").strip()
            if value.startswith("test_scenario_"):
                scenarios.add(value)
            break
    return scenarios


def select_best_process_for_flows_all(processes: list[ET.Element]) -> ET.Element:
    """Pick the process with the broadest test scenario coverage."""
    best = processes[0]
    best_score = len(unique_test_scenarios_in_process(best))
    for process in processes[1:]:
        score = len(unique_test_scenarios_in_process(process))
        if score > best_score:
            best = process
            best_score = score
    return best


def _chain_id_from_process(process: ET.Element) -> Optional[str]:
    doc = process.find("bpmn:documentation", NAMESPACES)
    text = (doc.text or "").strip() if doc is not None else ""
    for line in text.splitlines():
        normalized = line.strip()
        if normalized.startswith("Chain ID:"):
            value = normalized.split(":", 1)[1].strip()
            return value or None
    return dominant_chain_id_from_process(process)


def _ordered_task_names_from_process(
    process: ET.Element,
    shapes: dict[str, dict[str, int | float | str | None]],
) -> list[str]:
    task_paths = (
        ".//bpmn:task",
        ".//bpmn:serviceTask",
        ".//bpmn:userTask",
        ".//bpmn:manualTask",
        ".//bpmn:scriptTask",
        ".//bpmn:businessRuleTask",
        ".//bpmn:sendTask",
        ".//bpmn:receiveTask",
        ".//bpmn:subProcess",
    )

    seen_ids: set[str] = set()
    entries: list[tuple[float, float, str]] = []
    for task_path in task_paths:
        for task in process.findall(task_path, NAMESPACES):
            task_id = (task.get("id") or "").strip()
            if not task_id or task_id in seen_ids:
                continue
            seen_ids.add(task_id)

            name = (task.get("name") or "").strip()
            if not name:
                continue

            shape = shapes.get(task_id, {})
            x = float(shape.get("x") or 0)
            y = float(shape.get("y") or 0)
            entries.append((x, y, name))

    entries.sort(key=lambda item: (item[0], item[1], item[2]))
    names: list[str] = []
    for _, _, name in entries:
        if not names or names[-1] != name:
            names.append(name)
    return names


def _branch_rows_for_joined_flows_all(
    processes: list[ET.Element],
    shapes: dict[str, dict[str, int | float | str | None]],
    edge_data: dict[str, dict[str, object]],
    base_dir: Path,
    process_count_map: dict[str, int],
) -> list[dict[str, object]]:
    def chain_sort_key(item: dict[str, object]) -> tuple[int, str]:
        chain = str(item.get("chain_id") or "")
        match = re.search(r"test_scenario_(\d+)", chain)
        if match:
            return (int(match.group(1)), chain)
        return (10_000, chain)

    def _branch_label(chain_id: str) -> str:
        match = re.search(r"test_scenario_(\d+)", chain_id)
        if match:
            return f"test_{match.group(1)}"
        return chain_id

    def _copy_list(values: object) -> list[object]:
        return list(values) if isinstance(values, list) else []

    branch_infos: list[dict[str, object]] = []
    abpt_apps: list[str] = []
    abpt_metrics: list[str] = []
    abpt_errors: list[dict[str, str]] = []
    tdice_apps: list[str] = []
    tdice_metrics: list[str] = []
    tdice_errors: list[dict[str, str]] = []

    for index, process in enumerate(processes, start=1):
        process_id = process.get("id", "")
        chain_id = _chain_id_from_process(process) or f"flow_{index}"
        txn_count = process_count_map.get(process_id)
        if txn_count is None:
            process_vols = volumes_from_process(process)
            txn_count = int(process_vols.get("transaction_count") or 0)

        parsed_rows = _parse_process_items(process, shapes, edge_data, base_dir, txn_count)
        node_rows = {
            str(row.get("id") or ""): row
            for row in parsed_rows
            if row.get("type") != "flow" and row.get("type") != "lane"
        }
        flow_rows = [row for row in parsed_rows if row.get("type") == "flow"]

        abpt_row = next(
            (row for row in node_rows.values() if row.get("type") == "task" and row.get("name") == "ABPT"),
            None,
        )
        tdice_row = next(
            (row for row in node_rows.values() if row.get("type") == "task" and row.get("name") == "TDICE"),
            None,
        )
        if abpt_row is None or tdice_row is None:
            continue

        abpt_apps.extend(str(item) for item in _copy_list(abpt_row.get("applications")))
        abpt_metrics.extend(str(item) for item in _copy_list(abpt_row.get("metrics")))
        abpt_errors.extend(error for error in _copy_list(abpt_row.get("errors")) if isinstance(error, dict))
        tdice_apps.extend(str(item) for item in _copy_list(tdice_row.get("applications")))
        tdice_metrics.extend(str(item) for item in _copy_list(tdice_row.get("metrics")))
        tdice_errors.extend(error for error in _copy_list(tdice_row.get("errors")) if isinstance(error, dict))

        boundary_ids = {
            str(abpt_row.get("id") or ""),
            str(tdice_row.get("id") or ""),
        }
        boundary_ids.update(
            str(row.get("id") or "")
            for row in node_rows.values()
            if row.get("type") == "event"
        )

        internal_node_ids = [node_id for node_id in node_rows if node_id and node_id not in boundary_ids]
        internal_nodes = [node_rows[node_id] for node_id in internal_node_ids]
        internal_id_set = set(internal_node_ids)
        abpt_id = str(abpt_row.get("id") or "")
        tdice_id = str(tdice_row.get("id") or "")

        entry_ids = sorted(
            {
                str(flow.get("targetRef") or "")
                for flow in flow_rows
                if str(flow.get("sourceRef") or "") == abpt_id
                and str(flow.get("targetRef") or "") in internal_id_set
            }
        )
        tdice_inbound_sources = sorted(
            {
                str(flow.get("sourceRef") or "")
                for flow in flow_rows
                if str(flow.get("targetRef") or "") == tdice_id
                and str(flow.get("sourceRef") or "") in internal_id_set
            }
        )
        tdice_outbound_targets = sorted(
            {
                str(flow.get("targetRef") or "")
                for flow in flow_rows
                if str(flow.get("sourceRef") or "") == tdice_id
                and str(flow.get("targetRef") or "") in internal_id_set
            }
        )
        event_boundary_ids = {
            str(row.get("id") or "")
            for row in node_rows.values()
            if row.get("type") == "event"
        }
        exit_ids = sorted(
            {
                str(flow.get("sourceRef") or "")
                for flow in flow_rows
                if str(flow.get("sourceRef") or "") in internal_id_set
                and (
                    str(flow.get("targetRef") or "") in event_boundary_ids
                    or (
                        not tdice_outbound_targets
                        and str(flow.get("targetRef") or "") == tdice_id
                    )
                )
            }
        )

        internal_flows = [
            flow for flow in flow_rows
            if str(flow.get("sourceRef") or "") in internal_id_set
            and str(flow.get("targetRef") or "") in internal_id_set
        ]
        if tdice_inbound_sources and tdice_outbound_targets:
            for source_id in tdice_inbound_sources:
                source_row = node_rows.get(source_id)
                if source_row is None:
                    continue
                for target_id in tdice_outbound_targets:
                    target_row = node_rows.get(target_id)
                    if target_row is None:
                        continue
                    internal_flows.append(
                        {
                            "id": f"Bypass_TDICE_{source_id}_{target_id}",
                            "sourceRef": source_id,
                            "targetRef": target_id,
                            "type": "flow",
                            "shape": "line",
                            "waypoints": _orthogonal_flow_waypoints(source_row, target_row, "right", "left"),
                            "color": None,
                        }
                    )

        if internal_nodes:
            min_x = min(float(row.get("x") or 0) for row in internal_nodes)
            min_y = min(float(row.get("y") or 0) for row in internal_nodes)
            max_right = max(float(row.get("x") or 0) + float(row.get("width") or 0) for row in internal_nodes)
            max_bottom = max(float(row.get("y") or 0) + float(row.get("height") or 0) for row in internal_nodes)
        else:
            min_x = 0.0
            min_y = 0.0
            max_right = 0.0
            max_bottom = 0.0

        branch_infos.append(
            {
                "chain_id": chain_id,
                "transaction_count": int(txn_count or 0),
                "nodes": internal_nodes,
                "flows": internal_flows,
                "entry_ids": entry_ids,
                "exit_ids": exit_ids,
                "min_x": min_x,
                "min_y": min_y,
                "width": max(0.0, max_right - min_x),
                "height": max(64.0, max_bottom - min_y) if internal_nodes else 64.0,
            }
        )

    if not branch_infos:
        return []

    branch_infos.sort(key=chain_sort_key)

    task_w = 120.0
    task_h = 64.0
    gw_w = 50.0
    gw_h = 50.0
    x_start = 20.0
    x_abpt = 180.0
    x_fork = 400.0
    x_branch_start = 610.0
    branch_gap_y = 120.0
    branch_top = 140.0

    total_branch_height = sum(float(branch.get("height") or 64.0) for branch in branch_infos)
    total_branch_height += branch_gap_y * max(0, len(branch_infos) - 1)
    y_mid = branch_top + (total_branch_height / 2.0)

    max_branch_width = max(float(branch.get("width") or 0.0) for branch in branch_infos)
    x_join = x_branch_start + max_branch_width + 230.0
    x_tdice = x_join + 220.0
    x_end = x_tdice + 220.0

    def _unique_strings(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    rows: list[dict[str, object]] = []
    start_id = "Start_Shared"
    abpt_id = "Task_ABPT_Shared"
    tdice_id = "Task_TDICE_Shared"
    fork_id = "ParGW_Fork_Shared"
    join_id = "ParGW_Join_Shared"
    end_id = "End_Shared"

    rows.append(
        {
            "id": start_id,
            "type": "event",
            "name": "Request\nReceived",
            "x": x_start,
            "y": y_mid - 18.0,
            "height": 36,
            "width": 36,
            "shape": "circle",
            "color": None,
        }
    )
    rows.append(
        {
            "id": abpt_id,
            "type": "task",
            "name": "ABPT",
            "x": x_abpt,
            "y": y_mid - (task_h / 2.0),
            "height": task_h,
            "width": task_w,
            "shape": "rectangle",
            "color": None,
            "applications": _unique_strings(abpt_apps),
            "metrics": _unique_strings(abpt_metrics),
            "errors": abpt_errors,
        }
    )
    rows.append(
        {
            "id": fork_id,
            "name": "Fork",
            "soureRef": [abpt_id],
            "targetRef": [],
            "type": "parallelGateway",
            "shape": "diamond",
            "x": x_fork,
            "y": y_mid - (gw_h / 2.0),
            "width": gw_w,
            "height": gw_h,
            "color": None,
        }
    )
    rows.append(
        {
            "id": join_id,
            "name": "Join",
            "soureRef": [],
            "targetRef": [tdice_id],
            "type": "parallelGateway",
            "shape": "diamond",
            "x": x_join,
            "y": y_mid - (gw_h / 2.0),
            "width": gw_w,
            "height": gw_h,
            "color": None,
        }
    )
    rows.append(
        {
            "id": tdice_id,
            "type": "task",
            "name": "TDICE",
            "x": x_tdice,
            "y": y_mid - (task_h / 2.0),
            "height": task_h,
            "width": task_w,
            "shape": "rectangle",
            "color": None,
            "applications": _unique_strings(tdice_apps),
            "metrics": _unique_strings(tdice_metrics),
            "errors": tdice_errors,
        }
    )
    rows.append(
        {
            "id": end_id,
            "type": "event",
            "name": "Completed",
            "x": x_end,
            "y": y_mid - 18.0,
            "height": 36,
            "width": 36,
            "shape": "circle",
            "color": None,
        }
    )

    total_txn = sum(int(branch.get("transaction_count") or 0) for branch in branch_infos)
    rows.append(
        {
            "id": "Flow_Start_to_ABPT",
            "sourceRef": start_id,
            "targetRef": abpt_id,
            "type": "flow",
            "shape": "line",
            "waypoints": [
                {"x": x_start + 18.0, "y": y_mid},
                {"x": x_abpt, "y": y_mid},
            ],
            "color": None,
            "transactionCount": total_txn,
        }
    )
    rows.append(
        {
            "id": "Flow_ABPT_to_Fork",
            "sourceRef": abpt_id,
            "targetRef": fork_id,
            "type": "flow",
            "shape": "line",
            "waypoints": [
                {"x": x_abpt + task_w, "y": y_mid},
                {"x": x_fork, "y": y_mid},
            ],
            "color": None,
            "transactionCount": total_txn,
        }
    )
    rows.append(
        {
            "id": "Flow_Join_to_TDICE",
            "sourceRef": join_id,
            "targetRef": tdice_id,
            "type": "flow",
            "shape": "line",
            "waypoints": [
                {"x": x_join + gw_w, "y": y_mid},
                {"x": x_tdice, "y": y_mid},
            ],
            "color": None,
            "transactionCount": total_txn,
        }
    )
    rows.append(
        {
            "id": "Flow_TDICE_to_End",
            "sourceRef": tdice_id,
            "targetRef": end_id,
            "type": "flow",
            "shape": "line",
            "waypoints": [
                {"x": x_tdice + task_w, "y": y_mid},
                {"x": x_end, "y": y_mid},
            ],
            "color": None,
            "transactionCount": total_txn,
        }
    )

    shared_node_map = {str(row.get("id") or ""): row for row in rows if row.get("type") != "flow"}
    fork_targets: list[str] = []
    join_sources: list[str] = []
    next_branch_top = branch_top

    for branch_index, branch in enumerate(branch_infos, start=1):
        branch_chain = str(branch.get("chain_id") or f"flow_{branch_index}")
        branch_txn = int(branch.get("transaction_count") or 0)
        branch_nodes = list(branch.get("nodes") or [])
        branch_flows = list(branch.get("flows") or [])
        entry_ids = [str(value) for value in list(branch.get("entry_ids") or []) if str(value)]
        exit_ids = [str(value) for value in list(branch.get("exit_ids") or []) if str(value)]

        if not branch_nodes:
            rows.append(
                {
                    "id": f"Flow_{branch_chain}_ForkToJoin".replace("-", "_"),
                    "sourceRef": fork_id,
                    "targetRef": join_id,
                    "type": "flow",
                    "shape": "line",
                    "waypoints": _orthogonal_flow_waypoints(shared_node_map[fork_id], shared_node_map[join_id], "right", "left"),
                    "color": None,
                    "transactionCount": branch_txn,
                    "chain_id": branch_chain,
                }
            )
            continue

        offset_x = x_branch_start - float(branch.get("min_x") or 0.0)
        offset_y = next_branch_top - float(branch.get("min_y") or 0.0)
        next_branch_top += float(branch.get("height") or 64.0) + branch_gap_y

        id_map: dict[str, str] = {}
        branch_node_map: dict[str, dict[str, object]] = {}

        for node_index, source_row in enumerate(branch_nodes, start=1):
            source_id = str(source_row.get("id") or "")
            node_type = str(source_row.get("type") or "")
            prefix = "Task" if node_type == "task" else "GW"
            new_id = f"{prefix}_{branch_chain}_{node_index}".replace("-", "_")
            id_map[source_id] = new_id

        for source_row in branch_nodes:
            source_id = str(source_row.get("id") or "")
            new_row = dict(source_row)
            new_row["id"] = id_map[source_id]
            new_row["x"] = float(source_row.get("x") or 0.0) + offset_x
            new_row["y"] = float(source_row.get("y") or 0.0) + offset_y
            if "soureRef" in source_row:
                new_row["soureRef"] = [
                    id_map.get(str(value), str(value))
                    for value in list(source_row.get("soureRef") or [])
                    if str(value) in id_map
                ]
            if "targetRef" in source_row:
                new_row["targetRef"] = [
                    id_map.get(str(value), str(value))
                    for value in list(source_row.get("targetRef") or [])
                    if str(value) in id_map
                ]
            branch_node_map[new_row["id"]] = new_row
            rows.append(new_row)

        for source_flow in branch_flows:
            new_flow = dict(source_flow)
            source_ref = str(source_flow.get("sourceRef") or "")
            target_ref = str(source_flow.get("targetRef") or "")
            new_flow["id"] = f"Flow_{branch_chain}_{source_flow.get('id') or len(rows)}".replace("-", "_")
            new_flow["sourceRef"] = id_map[source_ref]
            new_flow["targetRef"] = id_map[target_ref]
            new_flow["waypoints"] = [
                {
                    "x": float(point.get("x") or 0.0) + offset_x,
                    "y": float(point.get("y") or 0.0) + offset_y,
                }
                for point in list(source_flow.get("waypoints") or [])
                if isinstance(point, dict)
            ]
            new_flow["transactionCount"] = branch_txn
            new_flow["chain_id"] = branch_chain
            rows.append(new_flow)

        label_added = False
        for entry_index, entry_id in enumerate(entry_ids, start=1):
            mapped_entry_id = id_map.get(entry_id)
            entry_row = branch_node_map.get(mapped_entry_id or "")
            if entry_row is None:
                continue
            fork_targets.append(mapped_entry_id)
            flow_row = {
                "id": f"Flow_{branch_chain}_Entry_{entry_index}".replace("-", "_"),
                "sourceRef": fork_id,
                "targetRef": mapped_entry_id,
                "type": "flow",
                "shape": "line",
                "waypoints": _orthogonal_flow_waypoints(shared_node_map[fork_id], entry_row, "right", "left"),
                "color": None,
                "transactionCount": branch_txn,
                "chain_id": branch_chain,
            }
            rows.append(flow_row)

            if not label_added:
                entry_left_x = float(entry_row.get("x") or 0.0)
                entry_center_y = float(entry_row.get("y") or 0.0) + (float(entry_row.get("height") or 0.0) / 2.0)
                label_width = 60
                vertical_x = None
                waypoints = list(flow_row.get("waypoints") or [])
                if len(waypoints) >= 3:
                    first = waypoints[0]
                    second = waypoints[1]
                    third = waypoints[2]
                    if abs(float(second.get("x") or 0.0) - float(third.get("x") or 0.0)) < 0.5:
                        vertical_x = float(second.get("x") or 0.0)
                if vertical_x is None:
                    vertical_x = entry_left_x - 80.0
                label_x = vertical_x + 10.0
                label_x = min(label_x, entry_left_x - label_width - 10.0)
                rows.append(
                    {
                        "id": f"Label_{branch_chain}".replace("-", "_"),
                        "type": "label",
                        "name": _branch_label(branch_chain),
                        "x": max(20.0, label_x),
                        "y": entry_center_y - 12.0,
                        "height": 24,
                        "width": label_width,
                        "shape": "text",
                        "color": None,
                        "chain_id": branch_chain,
                        "attachedToFlowId": flow_row["id"],
                    }
                )
                label_added = True

        if not label_added:
            fallback_y = offset_y + (float(branch.get("height") or 64.0) / 2.0) - 12.0
            rows.append(
                {
                    "id": f"Label_{branch_chain}".replace("-", "_"),
                    "type": "label",
                    "name": _branch_label(branch_chain),
                    "x": 70.0,
                    "y": fallback_y,
                    "height": 24,
                    "width": 120,
                    "shape": "text",
                    "color": None,
                    "chain_id": branch_chain,
                }
            )

        for exit_index, exit_id in enumerate(exit_ids, start=1):
            mapped_exit_id = id_map.get(exit_id)
            exit_row = branch_node_map.get(mapped_exit_id or "")
            if exit_row is None:
                continue
            join_sources.append(mapped_exit_id)
            flow_row = {
                "id": f"Flow_{branch_chain}_Exit_{exit_index}".replace("-", "_"),
                "sourceRef": mapped_exit_id,
                "targetRef": join_id,
                "type": "flow",
                "shape": "line",
                "waypoints": _orthogonal_flow_waypoints(exit_row, shared_node_map[join_id], "right", "left"),
                "color": None,
                "transactionCount": branch_txn,
                "chain_id": branch_chain,
            }
            rows.append(flow_row)

    shared_node_map[fork_id]["targetRef"] = fork_targets
    shared_node_map[join_id]["soureRef"] = join_sources
    rows = _align_join_incoming_verticals(rows)
    rows = _normalize_gateway_vertex_routing(rows)
    return rows


def _parse_int(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


def _parse_float(text: str) -> Optional[float]:
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None


def volumes_from_process(process: ET.Element) -> dict[str, object]:
    """Extract transaction volume metadata from the process-level <documentation> element."""
    doc = process.find("bpmn:documentation", NAMESPACES)
    text = (doc.text or "").strip() if doc is not None else ""
    if not text:
        return {}

    volumes: dict[str, object] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Service:"):
            volumes["service"] = line.split(":", 1)[1].strip()
        elif line.startswith("Root span:"):
            volumes["root_span"] = line.split(":", 1)[1].strip()
        elif line.startswith("Traces analyzed:"):
            value = _parse_int(line.split(":", 1)[1])
            if value is not None:
                volumes["transaction_count"] = value
        elif line.startswith("Avg duration:"):
            raw = line.split(":", 1)[1].strip().replace("ms", "").strip()
            value = _parse_float(raw)
            if value is not None:
                volumes["avg_duration_ms"] = value
        elif line.startswith("Error rate:"):
            raw = line.split(":", 1)[1].strip().replace("%", "").strip()
            value = _parse_float(raw)
            if value is not None:
                volumes["error_rate_pct"] = value
        elif line.startswith("Primary trace ID:"):
            volumes["primary_trace_id"] = line.split(":", 1)[1].strip()
    return volumes


def aggregate_process_volumes(processes: list[ET.Element]) -> dict[str, object]:
    """Combine per-process volume metadata for a multi-process BPMN file."""
    collected = [volumes_from_process(process) for process in processes]
    collected = [volumes for volumes in collected if volumes]
    if not collected:
        return {}

    total_transactions = sum(int(volumes.get("transaction_count") or 0) for volumes in collected)
    total_duration_ms = sum(
        float(volumes.get("avg_duration_ms") or 0.0) * int(volumes.get("transaction_count") or 0)
        for volumes in collected
    )
    total_errors = sum(
        (float(volumes.get("error_rate_pct") or 0.0) / 100.0) * int(volumes.get("transaction_count") or 0)
        for volumes in collected
    )

    aggregate: dict[str, object] = {
        "transaction_count": total_transactions,
        "process_count": len(collected),
    }

    if total_transactions:
        aggregate["avg_duration_ms"] = round(total_duration_ms / total_transactions, 1)
        aggregate["error_rate_pct"] = round((total_errors / total_transactions) * 100.0, 1)

    services = []
    for volumes in collected:
        service_name = str(volumes.get("service") or "").strip()
        if service_name and service_name not in services:
            services.append(service_name)
    if services:
        aggregate["services"] = services

    return aggregate


def _node_anchor(row: dict[str, object], side: str) -> tuple[float, float]:
    x = float(row.get("x") or 0)
    y = float(row.get("y") or 0)
    width = float(row.get("width") or 0)
    height = float(row.get("height") or 0)

    if side == "left":
        return x, y + (height / 2)
    if side == "right":
        return x + width, y + (height / 2)
    if side == "top":
        return x + (width / 2), y
    if side == "bottom":
        return x + (width / 2), y + height
    return x + (width / 2), y + (height / 2)


def _orthogonal_flow_waypoints(
    source_row: dict[str, object],
    target_row: dict[str, object],
    source_side: str,
    target_side: str,
) -> list[dict[str, float]]:
    src_x, src_y = _node_anchor(source_row, source_side)
    dst_x, dst_y = _node_anchor(target_row, target_side)

    if abs(src_y - dst_y) < 0.5 or abs(src_x - dst_x) < 0.5:
        return [
            {"x": src_x, "y": src_y},
            {"x": dst_x, "y": dst_y},
        ]

    # When routing backward (target is left of source), use a padded right corridor
    # so the vertical segment is pushed away from dense horizontal lanes.
    if dst_x < src_x:
        span_y = abs(src_y - dst_y)
        right_pad = max(180.0, min(700.0, span_y * 0.35))
        mid_x = max(src_x, dst_x) + right_pad
    else:
        mid_x = src_x + ((dst_x - src_x) / 2)

    return [
        {"x": src_x, "y": src_y},
        {"x": mid_x, "y": src_y},
        {"x": mid_x, "y": dst_y},
        {"x": dst_x, "y": dst_y},
    ]


def _align_join_incoming_verticals(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    node_map = {
        str(row.get("id") or ""): row
        for row in rows
        if row.get("type") != "flow"
    }
    flow_rows = [row for row in rows if row.get("type") == "flow"]

    join_ids: list[str] = []
    for row in rows:
        if row.get("type") == "flow":
            continue

        row_id = str(row.get("id") or "")
        incoming = [
            flow for flow in flow_rows
            if str(flow.get("targetRef") or "") == row_id
        ]
        if len(incoming) < 2:
            continue

        row_type = str(row.get("type") or "")
        if "gateway" in row_type.lower() or row.get("shape") == "diamond":
            join_ids.append(row_id)

    for join_id in join_ids:
        join_row = node_map.get(join_id)
        if join_row is None:
            continue

        join_left_x, join_center_y = _node_anchor(join_row, "left")
        incoming_flows = [
            flow for flow in flow_rows
            if str(flow.get("targetRef") or "") == join_id
        ]
        if len(incoming_flows) < 2:
            continue

        source_right_anchors: list[float] = []
        for flow in incoming_flows:
            source_id = str(flow.get("sourceRef") or "")
            source_row = node_map.get(source_id)
            if source_row is None:
                continue
            source_right_x, _ = _node_anchor(source_row, "right")
            source_right_anchors.append(source_right_x)

        if not source_right_anchors:
            continue

        boundary_x = max(source_right_anchors) + 210.0
        boundary_x = min(boundary_x, join_left_x - 30.0)

        for flow in incoming_flows:
            source_id = str(flow.get("sourceRef") or "")
            source_row = node_map.get(source_id)
            if source_row is None:
                continue

            src_x, src_y = _node_anchor(source_row, "right")
            waypoints = [
                {"x": src_x, "y": src_y},
                {"x": boundary_x, "y": src_y},
                {"x": boundary_x, "y": join_center_y},
                {"x": join_left_x, "y": join_center_y},
            ]
            deduped_waypoints: list[dict[str, float]] = []
            for point in waypoints:
                if deduped_waypoints and deduped_waypoints[-1] == point:
                    continue
                deduped_waypoints.append(point)
            flow["waypoints"] = deduped_waypoints

    return rows


def _center_of_row(row: dict[str, object]) -> tuple[float, float]:
    x = float(row.get("x") or 0)
    y = float(row.get("y") or 0)
    width = float(row.get("width") or 0)
    height = float(row.get("height") or 0)
    return x + (width / 2.0), y + (height / 2.0)


def _gateway_vertex_side_for_source(source_gateway: dict[str, object], target_row: dict[str, object]) -> str:
    gw_cx, gw_cy = _center_of_row(source_gateway)
    target_cx, target_cy = _center_of_row(target_row)
    if target_cy < gw_cy - 1.0:
        return "top"
    if target_cy > gw_cy + 1.0:
        return "bottom"
    return "right" if target_cx >= gw_cx else "left"


def _gateway_vertex_side_for_target(source_row: dict[str, object], target_gateway: dict[str, object]) -> str:
    src_cx, src_cy = _center_of_row(source_row)
    gw_cx, gw_cy = _center_of_row(target_gateway)
    if src_cy < gw_cy - 1.0:
        return "top"
    if src_cy > gw_cy + 1.0:
        return "bottom"
    return "left" if src_cx <= gw_cx else "right"


def _route_orthogonal_points(
    src_x: float,
    src_y: float,
    dst_x: float,
    dst_y: float,
    prefer_src_vertical: bool,
    prefer_dst_vertical: bool,
) -> list[dict[str, float]]:
    if abs(src_x - dst_x) < 0.5 or abs(src_y - dst_y) < 0.5:
        return [
            {"x": src_x, "y": src_y},
            {"x": dst_x, "y": dst_y},
        ]

    if prefer_src_vertical and not prefer_dst_vertical:
        return [
            {"x": src_x, "y": src_y},
            {"x": src_x, "y": dst_y},
            {"x": dst_x, "y": dst_y},
        ]

    if prefer_dst_vertical and not prefer_src_vertical:
        return [
            {"x": src_x, "y": src_y},
            {"x": dst_x, "y": src_y},
            {"x": dst_x, "y": dst_y},
        ]

    if prefer_src_vertical and prefer_dst_vertical:
        mid_y = src_y + ((dst_y - src_y) / 2.0)
        return [
            {"x": src_x, "y": src_y},
            {"x": src_x, "y": mid_y},
            {"x": dst_x, "y": mid_y},
            {"x": dst_x, "y": dst_y},
        ]

    mid_x = src_x + ((dst_x - src_x) / 2.0)
    return [
        {"x": src_x, "y": src_y},
        {"x": mid_x, "y": src_y},
        {"x": mid_x, "y": dst_y},
        {"x": dst_x, "y": dst_y},
    ]


def _normalize_gateway_vertex_routing(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    node_map = {
        str(row.get("id") or ""): row
        for row in rows
        if row.get("type") != "flow"
    }

    for row in rows:
        if row.get("type") != "flow":
            continue

        source_id = str(row.get("sourceRef") or "")
        target_id = str(row.get("targetRef") or "")
        source_row = node_map.get(source_id)
        target_row = node_map.get(target_id)
        if source_row is None or target_row is None:
            continue

        source_is_gateway = source_row.get("shape") == "diamond"
        target_is_gateway = target_row.get("shape") == "diamond"
        if not source_is_gateway and not target_is_gateway:
            continue

        src_cx, _ = _center_of_row(source_row)
        dst_cx, _ = _center_of_row(target_row)

        if source_is_gateway:
            # Per diagram rule: every gateway exit leaves from the east vertex.
            source_side = "right"
        else:
            source_side = "right" if dst_cx >= src_cx else "left"

        if target_is_gateway:
            target_side = _gateway_vertex_side_for_target(source_row, target_row)
        else:
            target_side = "left" if src_cx <= dst_cx else "right"

        src_x, src_y = _node_anchor(source_row, source_side)
        dst_x, dst_y = _node_anchor(target_row, target_side)

        waypoints = _route_orthogonal_points(
            src_x,
            src_y,
            dst_x,
            dst_y,
            prefer_src_vertical=(source_is_gateway and source_side in {"top", "bottom"}),
            prefer_dst_vertical=(target_is_gateway and target_side in {"top", "bottom"}),
        )

        deduped: list[dict[str, float]] = []
        for point in waypoints:
            if deduped and deduped[-1] == point:
                continue
            deduped.append(point)
        row["waypoints"] = deduped

    return rows


def collapse_shared_entry_exit_applications(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Collapse duplicate Start/End events plus ABPT and TDICE boundary nodes."""
    boundary_rows = [
        row for row in rows
        if (
            (row.get("type") == "task" and row.get("name") in {"ABPT", "TDICE"})
            or (row.get("type") == "event" and row.get("id") in {"Start_1", "End_1"})
            or (row.get("type") == "event" and row.get("name") in {"Request\nReceived", "Completed"})
        )
    ]
    if not boundary_rows:
        return rows

    shared_specs = (
        ("task", "ABPT"),
        ("task", "TDICE"),
        ("event", "Request\nReceived"),
        ("event", "Completed"),
    )
    node_map = {str(row.get("id") or ""): row for row in rows}
    duplicate_id_map: dict[str, str] = {}

    for row_type, shared_name in shared_specs:
        candidates = [
            row for row in rows
            if row.get("type") == row_type and row.get("name") == shared_name
        ]
        if len(candidates) <= 1:
            continue

        if shared_name in {"ABPT", "Request\nReceived"}:
            canonical = min(candidates, key=lambda row: (float(row.get("x") or 0), float(row.get("y") or 0)))
            canonical["x"] = min(float(candidate.get("x") or 0) for candidate in candidates)
        else:
            canonical = max(candidates, key=lambda row: (float(row.get("x") or 0), -float(row.get("y") or 0)))
            canonical["x"] = max(float(candidate.get("x") or 0) for candidate in candidates)

        canonical["y"] = sum(float(candidate.get("y") or 0) for candidate in candidates) / len(candidates)
        if row_type == "task":
            canonical["metrics"] = list(dict.fromkeys(
                metric
                for candidate in candidates
                for metric in candidate.get("metrics", [])
            ))
            canonical["errors"] = [
                error
                for candidate in candidates
                for error in candidate.get("errors", [])
            ]

        canonical_id = str(canonical.get("id") or "")
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or "")
            if candidate_id and candidate_id != canonical_id:
                duplicate_id_map[candidate_id] = canonical_id

    if not duplicate_id_map:
        return rows

    updated_rows: list[dict[str, object]] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        if row_id in duplicate_id_map and row.get("type") in {"task", "event"}:
            continue

        if row.get("type") == "flow":
            source_ref = str(row.get("sourceRef") or "")
            target_ref = str(row.get("targetRef") or "")
            rerouted_to_join = False
            new_source_ref = duplicate_id_map.get(source_ref, source_ref)
            new_target_ref = duplicate_id_map.get(target_ref, target_ref)

            if new_source_ref != source_ref or new_target_ref != target_ref:
                row["sourceRef"] = new_source_ref
                row["targetRef"] = new_target_ref

                source_row = node_map.get(new_source_ref)
                target_row = node_map.get(new_target_ref)
                if source_row is not None and target_row is not None:
                    source_side = "right"
                    target_side = "left"
                    if source_row.get("type") == "event":
                        source_side = "right"
                    if target_row.get("type") == "event":
                        target_side = "left"
                    row["waypoints"] = _orthogonal_flow_waypoints(source_row, target_row, source_side, target_side)

        updated_rows.append(row)

    return updated_rows


def collapse_shared_abpt_only(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Collapse duplicate ABPT task nodes into one shared ABPT while preserving all other topology."""
    abpt_candidates = [
        row for row in rows
        if row.get("type") == "task" and row.get("name") == "ABPT"
    ]
    if len(abpt_candidates) <= 1:
        return rows

    # Use the leftmost ABPT as canonical so existing layout remains familiar.
    canonical = min(abpt_candidates, key=lambda row: (float(row.get("x") or 0), float(row.get("y") or 0)))
    canonical_id = str(canonical.get("id") or "")

    canonical["x"] = min(float(candidate.get("x") or 0) for candidate in abpt_candidates)
    # Place ABPT at the vertical centre of all diagram rows.
    all_ys = [
        float(row.get("y") or 0) + float(row.get("height") or 0) / 2
        for row in rows
        if row.get("type") in {"task", "event"} and str(row.get("id") or "") != canonical_id
    ]
    centre_y = (min(all_ys) + max(all_ys)) / 2 if all_ys else 0.0
    abpt_h = float(canonical.get("height") or 64)
    canonical["y"] = centre_y - abpt_h / 2
    canonical["metrics"] = list(dict.fromkeys(
        metric
        for candidate in abpt_candidates
        for metric in candidate.get("metrics", [])
    ))
    canonical["errors"] = [
        error
        for candidate in abpt_candidates
        for error in candidate.get("errors", [])
    ]

    duplicate_id_map: dict[str, str] = {}
    for candidate in abpt_candidates:
        candidate_id = str(candidate.get("id") or "")
        if candidate_id and candidate_id != canonical_id:
            duplicate_id_map[candidate_id] = canonical_id

    if not duplicate_id_map:
        return rows

    # Build a mutable node map including canonical updates.
    node_map = {str(row.get("id") or ""): row for row in rows}
    node_map[canonical_id] = canonical

    updated_rows: list[dict[str, object]] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        if row_id in duplicate_id_map and row.get("type") == "task":
            continue

        if row.get("type") == "flow":
            source_ref = str(row.get("sourceRef") or "")
            target_ref = str(row.get("targetRef") or "")
            new_source_ref = duplicate_id_map.get(source_ref, source_ref)
            new_target_ref = duplicate_id_map.get(target_ref, target_ref)

            if new_source_ref != source_ref or new_target_ref != target_ref:
                row["sourceRef"] = new_source_ref
                row["targetRef"] = new_target_ref

            # Recalculate waypoints whenever canonical ABPT is an endpoint (position changed).
            if new_source_ref == canonical_id or new_target_ref == canonical_id:
                source_row = node_map.get(new_source_ref)
                target_row = node_map.get(new_target_ref)
                if source_row is not None and target_row is not None:
                    source_side = "right"
                    target_side = "left"
                    if source_row.get("type") == "event":
                        source_side = "right"
                    if target_row.get("type") == "event":
                        target_side = "left"
                    row["waypoints"] = _orthogonal_flow_waypoints(source_row, target_row, source_side, target_side)

        updated_rows.append(row)

    return updated_rows


def collapse_shared_start_only(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Collapse duplicate start events into one shared start and keep a single Start->ABPT flow."""
    start_candidates = [
        row for row in rows
        if row.get("type") == "event"
        and (
            str(row.get("id") or "").startswith("Start_")
            or row.get("name") == "Request\nReceived"
        )
    ]
    if not start_candidates:
        return rows

    abpt_row = next(
        (row for row in rows if row.get("type") == "task" and row.get("name") == "ABPT"),
        None,
    )
    if abpt_row is None:
        return rows

    canonical_start = min(start_candidates, key=lambda row: (float(row.get("x") or 0), float(row.get("y") or 0)))
    canonical_start_id = str(canonical_start.get("id") or "")
    abpt_x = float(abpt_row.get("x") or 0)
    start_w = float(canonical_start.get("width") or 36)
    # Force an obvious left placement so Start is visually separated from ABPT.
    canonical_start["x"] = max(20.0, abpt_x - (start_w + 180.0))

    # Keep start horizontally level with ABPT by matching centerline.
    start_h = float(canonical_start.get("height") or 36)
    abpt_y = float(abpt_row.get("y") or 0)
    abpt_h = float(abpt_row.get("height") or 64)
    canonical_start["y"] = abpt_y + (abpt_h / 2) - (start_h / 2)

    if not str(canonical_start.get("name") or "").strip():
        canonical_start["name"] = "Request\nReceived"

    abpt_id = str(abpt_row.get("id") or "")

    duplicate_id_map: dict[str, str] = {}
    for candidate in start_candidates:
        candidate_id = str(candidate.get("id") or "")
        if candidate_id and candidate_id != canonical_start_id:
            duplicate_id_map[candidate_id] = canonical_start_id

    node_map = {str(row.get("id") or ""): row for row in rows}
    node_map[canonical_start_id] = canonical_start

    updated_rows: list[dict[str, object]] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        if row_id in duplicate_id_map and row.get("type") == "event":
            continue

        if row.get("type") == "flow":
            source_ref = str(row.get("sourceRef") or "")
            target_ref = str(row.get("targetRef") or "")
            new_source_ref = duplicate_id_map.get(source_ref, source_ref)
            new_target_ref = duplicate_id_map.get(target_ref, target_ref)

            if new_source_ref != source_ref or new_target_ref != target_ref:
                row["sourceRef"] = new_source_ref
                row["targetRef"] = new_target_ref

                source_row = node_map.get(new_source_ref)
                target_row = node_map.get(new_target_ref)
                if source_row is not None and target_row is not None:
                    row["waypoints"] = _orthogonal_flow_waypoints(source_row, target_row, "right", "left")

        updated_rows.append(row)

    # De-duplicate resulting parallel flow rows; keep first per (source,target).
    deduped_rows: list[dict[str, object]] = []
    seen_flow_keys: set[tuple[str, str]] = set()
    for row in updated_rows:
        if row.get("type") != "flow":
            deduped_rows.append(row)
            continue

        key = (str(row.get("sourceRef") or ""), str(row.get("targetRef") or ""))
        if key in seen_flow_keys:
            continue
        seen_flow_keys.add(key)
        deduped_rows.append(row)

    # Enforce one direct Start -> ABPT edge with horizontal waypoints.
    start_center_x, start_center_y = _node_anchor(canonical_start, "right")
    abpt_left_x, abpt_left_y = _node_anchor(abpt_row, "left")
    direct_waypoints = [
        {"x": start_center_x, "y": start_center_y},
        {"x": abpt_left_x, "y": abpt_left_y},
    ]

    direct_flow_seen = False
    final_rows: list[dict[str, object]] = []
    for row in deduped_rows:
        if row.get("type") != "flow":
            final_rows.append(row)
            continue

        source_ref = str(row.get("sourceRef") or "")
        target_ref = str(row.get("targetRef") or "")
        if source_ref != canonical_start_id:
            final_rows.append(row)
            continue

        if target_ref != abpt_id:
            continue

        if direct_flow_seen:
            continue

        row["waypoints"] = direct_waypoints
        direct_flow_seen = True
        final_rows.append(row)

    if not direct_flow_seen:
        final_rows.append(
            {
                "id": f"Flow_{canonical_start_id}_to_{abpt_id}",
                "sourceRef": canonical_start_id,
                "targetRef": abpt_id,
                "type": "flow",
                "shape": "line",
                "waypoints": direct_waypoints,
                "color": None,
            }
        )

    return final_rows


def collapse_shared_tdice_only(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Collapse duplicate TDICE task nodes into one shared TDICE (fan-in) with a single exit to a shared End event."""
    tdice_candidates = [
        row for row in rows
        if row.get("type") == "task" and row.get("name") == "TDICE"
    ]
    if len(tdice_candidates) <= 1:
        return rows

    # Canonical TDICE = rightmost (end of flows) to preserve natural diagram direction.
    canonical = max(tdice_candidates, key=lambda row: (float(row.get("x") or 0), float(row.get("y") or 0)))
    canonical_id = str(canonical.get("id") or "")

    # Rightmost x, vertical centre of all other nodes.
    canonical["x"] = max(float(c.get("x") or 0) for c in tdice_candidates)
    all_ys = [
        float(row.get("y") or 0) + float(row.get("height") or 0) / 2
        for row in rows
        if row.get("type") in {"task", "event"} and str(row.get("id") or "") != canonical_id
    ]
    centre_y = (min(all_ys) + max(all_ys)) / 2 if all_ys else 0.0
    tdice_h = float(canonical.get("height") or 64)
    canonical["y"] = centre_y - tdice_h / 2

    canonical["metrics"] = list(dict.fromkeys(
        metric
        for c in tdice_candidates
        for metric in c.get("metrics", [])
    ))
    canonical["errors"] = [
        error
        for c in tdice_candidates
        for error in c.get("errors", [])
    ]

    tdice_all_ids = {str(c.get("id") or "") for c in tdice_candidates}
    duplicate_id_map: dict[str, str] = {
        cid: canonical_id
        for cid in tdice_all_ids
        if cid != canonical_id
    }

    # Track duplicate TDICE nodes that originally fed a join gateway.
    # Their incoming branch should reconnect to the join before reaching shared TDICE.
    tdice_to_join_target: dict[str, str] = {}
    for flow_row in rows:
        if flow_row.get("type") != "flow":
            continue
        source_ref = str(flow_row.get("sourceRef") or "")
        target_ref = str(flow_row.get("targetRef") or "")
        if source_ref not in duplicate_id_map:
            continue
        target_row = next((r for r in rows if str(r.get("id") or "") == target_ref), None)
        if target_row is None:
            continue
        if target_row.get("type") == "parallel":
            tdice_to_join_target[source_ref] = target_ref

    join_ids_before_tdice = set(tdice_to_join_target.values())

    # End events that were attached to joins now feeding shared TDICE should be removed.
    remove_join_end_ids: set[str] = set()
    for flow_row in rows:
        if flow_row.get("type") != "flow":
            continue
        source_ref = str(flow_row.get("sourceRef") or "")
        target_ref = str(flow_row.get("targetRef") or "")
        if source_ref not in join_ids_before_tdice:
            continue
        target_row = next((r for r in rows if str(r.get("id") or "") == target_ref), None)
        if target_row is not None and target_row.get("type") == "event":
            remove_join_end_ids.add(target_ref)

    # Collect End events directly fed by any TDICE candidate → collapse to one canonical End.
    end_candidates = [
        row for row in rows
        if row.get("type") == "event" and str(row.get("id") or "").startswith("End_")
        and any(
            str(f.get("sourceRef") or "") in tdice_all_ids
            for f in rows
            if f.get("shape") == "line" and str(f.get("targetRef") or "") == str(row.get("id") or "")
        )
    ]

    canonical_end: dict[str, object] | None = None
    canonical_end_id: str = ""
    end_dup_map: dict[str, str] = {}
    if end_candidates:
        canonical_end = min(end_candidates, key=lambda e: float(e.get("y") or 0))
        canonical_end_id = str(canonical_end.get("id") or "")
        tdice_w = float(canonical.get("width") or 120)
        end_h = float(canonical_end.get("height") or 36)
        canonical_end["x"] = canonical["x"] + tdice_w + 80.0
        canonical_end["y"] = canonical["y"] + tdice_h / 2.0 - end_h / 2.0
        if not str(canonical_end.get("name") or "").strip():
            canonical_end["name"] = "Completed"
        end_dup_map = {
            str(e.get("id") or ""): canonical_end_id
            for e in end_candidates
            if str(e.get("id") or "") != canonical_end_id
        }

    all_dup_map = {**duplicate_id_map, **end_dup_map}

    node_map = {str(row.get("id") or ""): row for row in rows}
    node_map[canonical_id] = canonical
    if canonical_end:
        node_map[canonical_end_id] = canonical_end

    seen_flow_pairs: set[tuple[str, str]] = set()
    updated_rows: list[dict[str, object]] = []
    required_join_to_tdice: set[str] = set()

    for row in rows:
        row_id = str(row.get("id") or "")

        # Drop duplicate TDICE task nodes.
        if row_id in duplicate_id_map and row.get("type") == "task":
            continue

        # Drop duplicate End events.
        if row_id in end_dup_map and row.get("type") == "event":
            continue

        # Drop flow-join Completed events that should no longer exist.
        if row_id in remove_join_end_ids and row.get("type") == "event":
            continue

        if row.get("type") == "flow":
            source_ref = str(row.get("sourceRef") or "")
            target_ref = str(row.get("targetRef") or "")
            rerouted_to_join = False

            # For joins that should feed shared TDICE, remove any alternate exits (e.g. join -> End).
            if source_ref in join_ids_before_tdice:
                target_row = next((r for r in rows if str(r.get("id") or "") == target_ref), None)
                if target_row is not None and target_row.get("type") == "event":
                    continue

            # Remove any flows targeting deleted join-end events.
            if target_ref in remove_join_end_ids:
                continue

            # If this duplicate TDICE originally fed a join, we will invert that relation
            # to join -> shared TDICE and drop duplicate TDICE -> join edges.
            if source_ref in tdice_to_join_target and target_ref == tdice_to_join_target[source_ref]:
                continue

            new_source = all_dup_map.get(source_ref, source_ref)
            new_target = all_dup_map.get(target_ref, target_ref)

            # For branch paths that used to end at a duplicate TDICE that then joined,
            # route the branch to the join first, then add join -> shared TDICE later.
            if target_ref in tdice_to_join_target:
                new_target = tdice_to_join_target[target_ref]
                required_join_to_tdice.add(new_target)
                rerouted_to_join = True

            # Drop non-End outflows from canonical TDICE (e.g. orphaned gateway edges).
            if new_source == canonical_id:
                tgt_row = node_map.get(new_target)
                if tgt_row is None or tgt_row.get("type") != "event":
                    continue

            # Deduplicate (source, target) pairs.
            pair = (new_source, new_target)
            if pair in seen_flow_pairs:
                continue
            seen_flow_pairs.add(pair)

            if new_source != source_ref or new_target != target_ref:
                row["sourceRef"] = new_source
                row["targetRef"] = new_target

            # Recalculate waypoints for all edges touching canonical TDICE or its End.
            if new_source == canonical_id or new_target == canonical_id or \
                    (canonical_end_id and (new_source == canonical_end_id or new_target == canonical_end_id)) or \
                    rerouted_to_join:
                src_row = node_map.get(new_source)
                tgt_row = node_map.get(new_target)
                if src_row is not None and tgt_row is not None:
                    src_side = "right" if src_row.get("type") == "event" else "right"
                    tgt_side = "left" if tgt_row.get("type") == "event" else "left"
                    row["waypoints"] = _orthogonal_flow_waypoints(src_row, tgt_row, src_side, tgt_side)

        updated_rows.append(row)

    for join_id in required_join_to_tdice:
        join_row = node_map.get(join_id)
        if join_row is None:
            continue

        pair = (join_id, canonical_id)
        if pair in seen_flow_pairs:
            continue
        seen_flow_pairs.add(pair)

        updated_rows.append(
            {
                "id": f"Flow_{join_id}_to_{canonical_id}",
                "sourceRef": join_id,
                "targetRef": canonical_id,
                "type": "flow",
                "shape": "line",
                "waypoints": _orthogonal_flow_waypoints(join_row, canonical, "right", "left"),
                "color": None,
            }
        )

    # For each join feeding shared TDICE, route all incoming branch edges through one
    # common padded boundary line based on the longest branch endpoint.
    if required_join_to_tdice:
        updated_node_map = {
            str(row.get("id") or ""): row
            for row in updated_rows
            if row.get("type") != "flow"
        }

        for join_id in required_join_to_tdice:
            join_row = updated_node_map.get(join_id)
            if join_row is None:
                continue

            join_left_x, join_center_y = _node_anchor(join_row, "left")
            incoming_flows = [
                flow
                for flow in updated_rows
                if flow.get("type") == "flow"
                and str(flow.get("targetRef") or "") == join_id
                and str(flow.get("sourceRef") or "") != join_id
            ]
            if not incoming_flows:
                continue

            source_right_anchors: list[float] = []
            for flow in incoming_flows:
                source_id = str(flow.get("sourceRef") or "")
                source_row = updated_node_map.get(source_id)
                if source_row is None:
                    continue
                source_right_x, _ = _node_anchor(source_row, "right")
                source_right_anchors.append(source_right_x)

            if not source_right_anchors:
                continue

            # Longest branch defines boundary; pad right so all vertical turns align
            # away from dense horizontal lanes.
            boundary_x = max(source_right_anchors) + 210.0
            boundary_x = min(boundary_x, join_left_x - 30.0)

            for flow in incoming_flows:
                source_id = str(flow.get("sourceRef") or "")
                source_row = updated_node_map.get(source_id)
                if source_row is None:
                    continue

                src_x, src_y = _node_anchor(source_row, "right")
                if abs(src_y - join_center_y) < 0.5:
                    flow["waypoints"] = [
                        {"x": src_x, "y": src_y},
                        {"x": join_left_x, "y": join_center_y},
                    ]
                else:
                    flow["waypoints"] = [
                        {"x": src_x, "y": src_y},
                        {"x": boundary_x, "y": src_y},
                        {"x": boundary_x, "y": join_center_y},
                        {"x": join_left_x, "y": join_center_y},
                    ]

    # Ensure exactly one TDICE → canonical_End edge exists.
    if canonical_end:
        has_exit = any(
            str(r.get("sourceRef") or "") == canonical_id and str(r.get("targetRef") or "") == canonical_end_id
            for r in updated_rows
            if r.get("type") == "flow"
        )
        if not has_exit:
            tdice_right_x, tdice_right_y = _node_anchor(canonical, "right")
            end_left_x, end_left_y = _node_anchor(canonical_end, "left")
            updated_rows.append({
                "id": f"Flow_{canonical_id}_to_{canonical_end_id}",
                "sourceRef": canonical_id,
                "targetRef": canonical_end_id,
                "type": "flow",
                "shape": "line",
                "waypoints": [
                    {"x": tdice_right_x, "y": tdice_right_y},
                    {"x": end_left_x, "y": end_left_y},
                ],
                "color": None,
            })

    return updated_rows


def _parse_process_items(
    process: ET.Element,
    shapes: dict,
    edge_data: dict,
    base_dir: Path,
    transaction_count: Optional[int] = None,
) -> list[dict[str, object]]:
    """Parse all BPMN items from a single process element."""
    task_file_map = task_file_map_from_process(process)
    grouped_file_map, suppressed_ids = grouped_task_file_map(process, task_file_map, base_dir)
    task_applications_map, task_metrics_map = task_annotation_maps_from_process(process)
    task_errors_map = task_errors_map_from_process(process)
    rows: list[dict[str, object]] = []
    incoming_gateway_refs: dict[str, list[str]] = defaultdict(list)
    outgoing_gateway_refs: dict[str, list[str]] = defaultdict(list)

    flow_txn_counts = flow_transaction_counts(process)
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
        computed_txn_count = int(flow_txn_counts.get(flow_id, 0) or 0)
        fallback_txn_count = int(transaction_count or 0)
        flow_row: dict[str, object] = {
            "id": flow_id,
            "sourceRef": flow.get("sourceRef", ""),
            "targetRef": flow.get("targetRef", ""),
            "type": "flow",
            "shape": "line",
            "waypoints": flow_di.get("waypoints", []),
            "color": flow_di.get("stroke"),
        }
        flow_row["transactionCount"] = max(computed_txn_count, fallback_txn_count)
        rows.append(flow_row)

    return rows


def parse_bpmn_file(xml_path: Path, base_dir: Optional[Path] = None) -> list[dict[str, object]]:
    root = ET.parse(xml_path).getroot()
    processes = root.findall("bpmn:process", NAMESPACES)
    if not processes:
        return []

    if base_dir is None:
        base_dir = xml_path.parent

    shapes = shape_map_from_root(root)
    edge_data = edge_data_map_from_root(root)

    _, process_count_map = pool_items_from_root(root, shapes)

    # For flows_all files or multi-process files with ABPT/TDICE patterns, create synthetic combined diagram
    # with factored-out ABPT/TDICE, fork/join gateways, and parallel branches.
    if (xml_path.name == "flows_all_bpmn2.0.xml" or "flows_all" in xml_path.name) and len(processes) > 1:
        return _branch_rows_for_joined_flows_all(processes, shapes, edge_data, base_dir, process_count_map)

    # Non-flows_all files keep a single process view.
    process = select_best_process_for_flows_all(processes)
    process_id = process.get("id", "")
    txn_count: Optional[int] = process_count_map.get(process_id)
    if txn_count is None:
        process_vols = volumes_from_process(process)
        txn_count = process_vols.get("transaction_count")  # type: ignore[assignment]

    rows: list[dict[str, object]] = _parse_process_items(process, shapes, edge_data, base_dir, txn_count)

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

        root = ET.parse(xml_file).getroot()
        process_elems = root.findall("bpmn:process", NAMESPACES)
        if len(process_elems) > 1:
            volumes = aggregate_process_volumes(process_elems)
        else:
            process_elem = process_elems[0] if process_elems else None
            volumes = volumes_from_process(process_elem) if process_elem is not None else {}

        output_payload: dict[str, object] = {"diagram": rows}
        if volumes:
            output_payload["volumes"] = volumes

        output_file = xml_file.with_suffix('.json')
        output_file.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
        converted_count += 1
        print(f"{xml_file.name} -> {output_file.name} ({len(rows)} records)")

    print(f"xml2json summary: converted={converted_count}, skipped={skipped_count}")


if __name__ == "__main__":
    run()