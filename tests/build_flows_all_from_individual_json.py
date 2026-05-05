from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional

from xml2json import (
    _align_join_incoming_verticals,
    _node_anchor,
    _normalize_gateway_vertex_routing,
    _orthogonal_flow_waypoints,
)


def _chain_sort_key(item: dict[str, object]) -> tuple[int, str]:
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


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _chain_id_from_payload(payload: dict[str, object], input_file: Path) -> str:
    rows = payload.get("diagram")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            chain = str(row.get("chain_id") or "").strip()
            if chain:
                return chain

    match = re.search(r"test_scenario_\d+", input_file.stem)
    if match:
        return match.group(0)

    return input_file.stem


def _txn_count_from_payload(payload: dict[str, object]) -> int:
    volumes = payload.get("volumes")
    if isinstance(volumes, dict):
        value = volumes.get("transaction_count")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)

    rows = payload.get("diagram")
    if isinstance(rows, list):
        counts: list[int] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get("transactionCount")
            if isinstance(raw, int):
                counts.append(raw)
            elif isinstance(raw, float):
                counts.append(int(raw))
        if counts:
            return max(counts)

    return 0


def _aggregate_output_volumes(payloads: list[dict[str, object]]) -> dict[str, object]:
    collected: list[dict[str, object]] = []
    for payload in payloads:
        volumes = payload.get("volumes")
        if isinstance(volumes, dict) and volumes:
            collected.append(volumes)

    if not collected:
        return {}

    total_transactions = 0
    total_duration_ms = 0.0
    total_errors = 0.0
    services: list[str] = []

    for volumes in collected:
        txn = int(volumes.get("transaction_count") or 0)
        total_transactions += txn
        total_duration_ms += float(volumes.get("avg_duration_ms") or 0.0) * txn
        total_errors += (float(volumes.get("error_rate_pct") or 0.0) / 100.0) * txn

        service_name = str(volumes.get("service") or "").strip()
        if service_name and service_name not in services:
            services.append(service_name)

    output: dict[str, object] = {
        "transaction_count": total_transactions,
        "process_count": len(collected),
    }

    if total_transactions:
        output["avg_duration_ms"] = round(total_duration_ms / total_transactions, 1)
        output["error_rate_pct"] = round((total_errors / total_transactions) * 100.0, 1)

    if services:
        output["services"] = services

    return output


def _line_width_for_transactions(transaction_count: int) -> float:
    """Map transaction count to a visible flow line width.

    Baseline uses count/5 with a minimum of 1.0 so low-volume flows remain
    visible while high-volume flows scale proportionally.
    Example: 57 transactions -> 11.4 line width.
    """
    width = float(transaction_count) / 5.0
    if width < 1.0:
        width = 1.0
    return round(width, 2)


def build_flows_all_from_individual_payloads(
    items: list[tuple[Path, dict[str, object]]],
) -> list[dict[str, object]]:
    branch_infos: list[dict[str, object]] = []
    abpt_apps: list[str] = []
    abpt_metrics: list[str] = []
    abpt_errors: list[dict[str, str]] = []
    tdice_apps: list[str] = []
    tdice_metrics: list[str] = []
    tdice_errors: list[dict[str, str]] = []

    for input_file, payload in items:
        rows = payload.get("diagram")
        if not isinstance(rows, list):
            continue

        parsed_rows = [row for row in rows if isinstance(row, dict)]
        node_rows = {
            str(row.get("id") or ""): row
            for row in parsed_rows
            if row.get("type") != "flow" and row.get("type") != "lane" and row.get("type") != "label"
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

        chain_id = _chain_id_from_payload(payload, input_file)
        txn_count = _txn_count_from_payload(payload)

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

    branch_infos.sort(key=_chain_sort_key)

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
            "lineWidth": _line_width_for_transactions(total_txn),
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
            "lineWidth": _line_width_for_transactions(total_txn),
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
            "lineWidth": _line_width_for_transactions(total_txn),
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
            "lineWidth": _line_width_for_transactions(total_txn),
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
                    "lineWidth": _line_width_for_transactions(branch_txn),
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
            if source_id not in id_map:
                continue
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
            branch_node_map[str(new_row["id"])] = new_row
            rows.append(new_row)

        for source_flow in branch_flows:
            source_ref = str(source_flow.get("sourceRef") or "")
            target_ref = str(source_flow.get("targetRef") or "")
            if source_ref not in id_map or target_ref not in id_map:
                continue

            new_flow = dict(source_flow)
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
            new_flow["lineWidth"] = _line_width_for_transactions(branch_txn)
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
                "lineWidth": _line_width_for_transactions(branch_txn),
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
            rows.append(
                {
                    "id": f"Flow_{branch_chain}_Exit_{exit_index}".replace("-", "_"),
                    "sourceRef": mapped_exit_id,
                    "targetRef": join_id,
                    "type": "flow",
                    "shape": "line",
                    "waypoints": _orthogonal_flow_waypoints(exit_row, shared_node_map[join_id], "right", "left"),
                    "color": None,
                    "transactionCount": branch_txn,
                    "lineWidth": _line_width_for_transactions(branch_txn),
                    "chain_id": branch_chain,
                }
            )

    shared_node_map[fork_id]["targetRef"] = fork_targets
    shared_node_map[join_id]["soureRef"] = join_sources

    rows = _align_join_incoming_verticals(rows)
    rows = _normalize_gateway_vertex_routing(rows)
    return rows


def _load_payload(path: Path) -> Optional[dict[str, object]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Skipping malformed JSON {path.name}: {exc}")
        return None


def run_from_files(scenario_json_files: list[Path], output_file: Path) -> None:
    files = sorted(scenario_json_files, key=lambda p: _chain_sort_key({"chain_id": p.stem}))
    if not files:
        raise FileNotFoundError("No scenario JSON files were provided")

    items: list[tuple[Path, dict[str, object]]] = []
    payloads: list[dict[str, object]] = []
    for file_path in files:
        payload = _load_payload(file_path)
        if payload is None:
            continue
        items.append((file_path, payload))
        payloads.append(payload)

    rows = build_flows_all_from_individual_payloads(items)
    if not rows:
        raise RuntimeError("No rows were generated from individual scenario JSON files")

    output_payload: dict[str, object] = {"diagram": rows}
    volumes = _aggregate_output_volumes(payloads)
    if volumes:
        output_payload["volumes"] = volumes

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
    print(f"Wrote {output_file} ({len(rows)} records) from {len(items)} scenario file(s)")


def run(input_dir: Path, output_file: Path) -> None:
    files = sorted(input_dir.glob("test_scenario_*_flow.json"), key=lambda p: _chain_sort_key({"chain_id": p.stem}))
    if not files:
        raise FileNotFoundError(f"No test_scenario_*_flow.json files under {input_dir}")
    run_from_files(files, output_file)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build flows_all_bpmn2.0.json from test_scenario_*_flow.json files using the same merge rules as xml2json flows_all logic"
    )
    parser.add_argument("--input-dir", default=str((Path(__file__).resolve().parent / "output").resolve()))
    parser.add_argument("--output", default=str((Path(__file__).resolve().parent / "output" / "flows_all_bpmn2.0.json").resolve()))
    args = parser.parse_args()

    run(Path(args.input_dir), Path(args.output))


if __name__ == "__main__":
    main()
