#!/usr/bin/env python3
"""Run a complete event ledger through the FlowSim fluid data-plane model."""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serving.core.flowsim_backend import FlowSpec, FluidFlowNetwork


_EVENT_TYPES = {
    "1": "P2D_KV",
    "2": "EP_DISPATCH",
    "3": "EP_COMBINE",
}


def _path_override(row):
    value = str(row.get("path_override", "")).strip()
    if not value:
        return ()
    links = []
    for item in value.split(";"):
        endpoints = item.split("->")
        if len(endpoints) != 2:
            raise ValueError("invalid path_override %r" % value)
        links.append((int(endpoints[0]), int(endpoints[1])))
    return tuple(links)


def _read(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = []
        for index, row in enumerate(csv.DictReader(stream)):
            row = dict(row)
            row.setdefault("event_id", str(index))
            event_type = str(row.get("event_type", ""))
            row["event_type"] = _EVENT_TYPES.get(event_type, event_type)
            rows.append(row)
        return rows


def _read_events(path, traffic_class, coalesce_window_us):
    """Read an event ledger, streaming EP aggregation when requested.

    Large model-derived ledgers are intentionally not materialized as one
    Python dict per peer flow.  The coalesced path retains request-level KV
    rows and aggregates EP rows directly from the CSV stream, which keeps a
    25k-request replay bounded by the number of time buckets and KV rows.
    """
    wanted = None
    if traffic_class != "FULL":
        wanted = {"KV_ONLY": {"P2D_KV", "REMOTE_KV_FETCH"},
                  "EP_ONLY": {"EP_DISPATCH", "EP_COMBINE"}}[traffic_class]
    if coalesce_window_us <= 0:
        rows = _read(path)
        return [row for row in rows if wanted is None or row["event_type"] in wanted]

    window_ns = int(coalesce_window_us * 1000)
    grouped = {}
    retained = []
    with path.open(newline="", encoding="utf-8") as stream:
        for index, raw in enumerate(csv.DictReader(stream)):
            row = dict(raw)
            row.setdefault("event_id", str(index))
            event_type = _EVENT_TYPES.get(str(row.get("event_type", "")),
                                          str(row.get("event_type", "")))
            row["event_type"] = event_type
            if wanted is not None and event_type not in wanted:
                continue
            if event_type not in {"EP_DISPATCH", "EP_COMBINE"}:
                retained.append(row)
                continue
            start_ns = int(row["start_ns"])
            bucket = (start_ns // window_ns) * window_ns
            key = (bucket, row["src"], row["dst"], event_type)
            entry = grouped.setdefault(key, {
                "start_ns": str(bucket),
                "src": row["src"],
                "dst": row["dst"],
                "bytes": 0,
                "event_type": event_type,
                "request_id": "-1",
                "collective_id": "aggregate:%d:%s:%s:%s" % (
                    bucket, row["src"], row["dst"], event_type),
                "layer_id": row.get("layer_id", "0"),
                "active_request_ids": "",
                "_active_request_ids_set": set(),
                "serving_role": "decode_aggregate",
            })
            entry["bytes"] += int(row["bytes"])
            entry["_active_request_ids_set"].update(
                request_id for request_id in str(
                    row.get("active_request_ids", "")).split(";")
                if request_id)
    rows = retained + list(grouped.values())
    for row in rows:
        request_ids = row.pop("_active_request_ids_set", None)
        if request_ids is not None:
            row["active_request_ids"] = ";".join(
                sorted(request_ids, key=str))
    for index, row in enumerate(rows):
        row.setdefault("event_id", "aggregate:%d" % index)
    rows.sort(key=lambda row: (int(row["start_ns"]), row["event_type"],
                               str(row.get("event_id", ""))))
    return rows


def run(args):
    events = _read_events(args.events, args.traffic_class,
                           args.coalesce_ep_window_us)
    requests = _read(args.requests)
    for index, request in enumerate(requests):
        request.setdefault("request_id", request.get("replay_request_id", str(index)))
    network_mode = ("AGGREGATE" if args.parallel_link_model ==
                    "SINGLE_PHYSICAL_LEGACY" else args.parallel_link_model)
    network = FluidFlowNetwork(
        str(args.topology), args.policy,
        parallel_link_mode=network_mode)
    if args.critical_flow_file is not None:
        critical_path = args.critical_flow_file.resolve()
        if not critical_path.is_file():
            raise FileNotFoundError("critical-flow oracle does not exist: %s" % critical_path)
        with critical_path.open(encoding="utf-8") as stream:
            network.critical_flow_ids = {
                line.strip() for line in stream
                if line.strip() and not line.lstrip().startswith("#")
            }
    if args.parallel_link_model == "SINGLE_PHYSICAL_LEGACY":
        # Historical sensitivity only.  This intentionally restores the old
        # under-capacity interpretation and is not a physical aggregate model.
        for edge in network.edges.values():
            if edge["physical_link_count"] > 1:
                edge["capacity_Bps"] = edge["physical_capacity_Bps"][0]
    specs = []
    by_flow_id = {}
    for row in events:
        flow_id = "event:%s" % row["event_id"]
        traffic_class = "KV_MOVEMENT" if row["event_type"] in {"P2D_KV", "REMOTE_KV_FETCH"} else "EP"
        spec = FlowSpec(
            flow_id=flow_id,
            src=int(row["src"]),
            dst=int(row["dst"]),
            bytes=int(row["bytes"]),
            start_ns=int(row["start_ns"]),
            traffic_class=traffic_class,
            traffic_subtype=row["event_type"],
            path_override=_path_override(row),
        )
        specs.append(spec)
        by_flow_id[flow_id] = row
    finishes = network.simulate(specs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    flow_fields = []
    if events:
        seen_fields = set()
        for source in events:
            for field in source:
                if field not in seen_fields:
                    seen_fields.add(field)
                    flow_fields.append(field)
        for field in ("flow_id", "traffic_class", "traffic_subtype",
                      "requested_start_ns", "end_ns", "queueing_ns",
                      "service_ns", "fct_ns", "path"):
            if field not in seen_fields:
                seen_fields.add(field)
                flow_fields.append(field)
    with (args.output_dir / "flows.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=flow_fields)
        if flow_fields:
            writer.writeheader()
        for record in network.last_flows:
            source = by_flow_id[record["flow_id"]]
            row = dict(source)
            row["flow_id"] = record["flow_id"]
            row["traffic_class"] = record["traffic_class"]
            row["traffic_subtype"] = record["traffic_subtype"]
            row["end_ns"] = int(record["end_ns"])
            requested_start = int(record.get("requested_start_ns", source["start_ns"]))
            actual_start = int(record["start_ns"])
            row["requested_start_ns"] = requested_start
            row["queueing_ns"] = max(0, actual_start - requested_start)
            row["service_ns"] = max(0, int(record["end_ns"]) - actual_start)
            row["fct_ns"] = int(record["end_ns"]) - requested_start
            row["path"] = ";".join(record["path"])
            writer.writerow(row)
    request_metrics = []
    by_request_kv = defaultdict(list)
    by_collective = defaultdict(list)
    records_by_flow = {
        record["flow_id"]: record for record in network.last_flows
    }
    for flow_id, finish in finishes.items():
        source = by_flow_id[flow_id]
        record = records_by_flow.get(flow_id)
        if record is None:
            continue
        if source["event_type"] in {"P2D_KV", "REMOTE_KV_FETCH"}:
            by_request_kv[source["request_id"]].append((source, record))
        else:
            by_collective[source["collective_id"]].append((source, record))
    collective_cct = {}
    for collective_id, flow_values in by_collective.items():
        starts = [int(source["start_ns"]) for source, _ in flow_values]
        actual_starts = [int(record["start_ns"]) for _, record in flow_values]
        finishes_for_collective = [int(record["end_ns"])
                                   for _, record in flow_values]
        active_request_ids = sorted({
            request_id
            for source, _ in flow_values
            for request_id in str(source.get("active_request_ids", "")).split(";")
            if request_id
        }, key=str)
        collective_cct[collective_id] = {
            "start_ns": min(starts) if starts else None,
            "actual_start_ns": min(actual_starts) if actual_starts else None,
            "end_ns": max(finishes_for_collective),
            "cct_ns": max(finishes_for_collective) - (min(starts) if starts else max(finishes_for_collective)),
            "queueing_ns": max(
                0,
                min(actual_starts) - min(starts),
            ) if starts and actual_starts else 0,
            "service_span_ns": max(finishes_for_collective) - min(actual_starts),
            "flow_count": len(flow_values),
            "bytes": sum(int(source["bytes"]) for source, _ in flow_values),
            "active_request_ids": ";".join(active_request_ids),
        }
    # Build the request-to-collective index once.  The previous implementation
    # scanned every event for every request and every collective.  That is
    # harmless for a tiny gate, but becomes O(requests * collectives * events)
    # on an S64 trace and can consume more memory than the network simulation.
    collectives_for_request = defaultdict(set)
    for row in events:
        collective_id = row.get("collective_id", "")
        if not collective_id or collective_id not in collective_cct:
            continue
        for request_id in str(row.get("active_request_ids", "")).split(";"):
            if request_id:
                collectives_for_request[request_id].add(collective_id)
    for request in requests:
        req_id = request["request_id"]
        kv_records = by_request_kv.get(req_id, [])
        kv_finish = max(
            (int(record["end_ns"]) for _, record in kv_records),
            default=int(request["decode_start_anchor_ns"]),
        )
        kv_requested_start = min(
            (int(source["start_ns"]) for source, _ in kv_records),
            default=int(request["decode_start_anchor_ns"]),
        )
        kv_actual_start = min(
            (int(record["start_ns"]) for _, record in kv_records),
            default=kv_requested_start,
        )
        decode_start = max(int(request["decode_start_anchor_ns"]), kv_finish)
        first_token = decode_start + int(request["decode_period_ns"])
        req_collectives = [collective_cct[collective_id]
                           for collective_id in collectives_for_request.get(req_id, ())]
        max_cct = max((item["cct_ns"] for item in req_collectives), default=0)
        request_metrics.append({
            **request,
            "policy": args.policy,
            "traffic_class": args.traffic_class,
            "kv_completion_time_ns": kv_finish,
            "kv_requested_start_ns": kv_requested_start,
            "kv_actual_start_ns": kv_actual_start,
            "kv_queueing_ns": max(0, kv_actual_start - kv_requested_start),
            "kv_fct_ns": max(0, kv_finish - kv_requested_start),
            "kv_service_span_ns": max(0, kv_finish - kv_actual_start),
            "kv_flow_count": len(kv_records),
            "kv_bytes": sum(int(source["bytes"]) for source, _ in kv_records),
            "decode_start_time_ns": decode_start,
            "first_token_time_ns": first_token,
            "ttft_data_plane_proxy_ns": first_token - int(request["arrival_time_ns"]),
            "max_ep_cct_ns": max_cct,
            "ep_collective_count": len(req_collectives),
        })
    request_fields = list(request_metrics[0]) if request_metrics else []
    with (args.output_dir / "request_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=request_fields)
        if request_fields:
            writer.writeheader()
            writer.writerows(request_metrics)
    with (args.output_dir / "collectives.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["collective_id", "start_ns", "actual_start_ns", "end_ns",
                  "cct_ns", "queueing_ns", "service_span_ns", "flow_count",
                  "bytes", "active_request_ids"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for collective_id, info in sorted(collective_cct.items(), key=lambda item: str(item[0])):
            writer.writerow({"collective_id": collective_id, **info})
    with (args.output_dir / "link_telemetry.jsonl").open("w", encoding="utf-8") as stream:
        for row in network.telemetry:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    manifest = {
        "policy": args.policy,
        "traffic_class": args.traffic_class,
        "event_count": len(events),
        "completed_flow_count": len(finishes),
        "request_count": len(request_metrics),
        "telemetry_rows": len(network.telemetry),
        "telemetry_truncated": network.telemetry_truncated,
        "coalesce_ep_window_us": args.coalesce_ep_window_us,
        "parallel_link_model": args.parallel_link_model,
        "queue_semantics": "residual fluid, not packet queue",
        "serving_metric_semantics": "ttft_data_plane_proxy is a replay-derived lower-level anchor, not integrated scheduler E2E TTFT",
        "flow_metric_semantics": {
            "queueing_ns": "actual fluid-flow service start minus requested event start",
            "service_ns": "flow completion minus actual fluid-flow service start",
            "kv_fct_ns": "last required KV-flow completion minus first requested KV-flow start",
            "collective_cct_ns": "last EP-flow completion minus collective requested start",
        },
        "files": {
            "flows": "flows.csv",
            "request_metrics": "request_metrics.csv",
            "collectives": "collectives.csv",
            "link_telemetry": "link_telemetry.jsonl",
        },
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--policy", choices=("FAIR", "EP_FIRST", "KV_FIRST", "CRITICAL_ONLY"), default="FAIR")
    parser.add_argument(
        "--critical-flow-file", type=Path, default=None,
        help="offline EP flow-id oracle for CRITICAL_ONLY; no effect for other policies"
    )
    parser.add_argument("--traffic-class", choices=("FULL", "KV_ONLY", "EP_ONLY"), default="FULL")
    parser.add_argument(
        "--coalesce-ep-window-us", type=float, default=0.0,
        help="large-trace optimization: merge EP flows per directed pair and time window")
    parser.add_argument(
        "--parallel-link-model", choices=(
            "AGGREGATE", "HASHED_PHYSICAL", "SINGLE_PHYSICAL_LEGACY"),
        default="AGGREGATE",
        help="topology sensitivity; HASHED_PHYSICAL assigns each flow to one "
             "physical parallel link; SINGLE_PHYSICAL_LEGACY is historical "
             "under-capacity only")
    args = parser.parse_args()
    if args.coalesce_ep_window_us < 0:
        parser.error("--coalesce-ep-window-us must be non-negative")
    run(args)


if __name__ == "__main__":
    main()
