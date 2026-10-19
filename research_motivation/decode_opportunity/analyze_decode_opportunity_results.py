#!/usr/bin/env python3
"""Compact and validate the Decode-opportunity FlowSim experiment outputs.

The script consumes completed diagnostic runs under /tmp and writes durable,
small CSV ledgers into this research directory.  FlowSim link backlog remains
analytical residual fluid; this exporter never labels it a packet queue.
"""

import ast
import csv
import hashlib
import json
import math
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
LEDGER_DIR = HERE / "ledgers"

MAIN_RUNS = [
    ("C0_KV_ONLY_NETWORK", "kvonly", "KV_ONLY_NETWORK_CLASSES", "FAIR", ""),
    ("S0_FAIR", "fair", "KV_MOVEMENT,EP", "FAIR", ""),
    ("S1_KV_FIRST_REQ3", "kvfirst-r3", "KV_MOVEMENT,EP", "KV_REQUEST_FIRST", "3"),
    ("S2_EP_FIRST", "epfirst", "KV_MOVEMENT,EP", "EP_FIRST", ""),
    ("S3_FIFO_COFLOW_TIE_REQ2", "eptier-r2", "KV_MOVEMENT,EP", "EP_THEN_KV_REQUEST_FIRST", "2"),
    ("S4_DECODE_OPPORTUNITY_REQ3", "eptier-r3", "KV_MOVEMENT,EP", "EP_THEN_KV_REQUEST_FIRST", "3"),
]

NEIGHBOR_RUNS = [
    ("B11_FAIR", "neighbor-o11-fair", "FAIR", 11),
    ("B11_OPPORTUNITY", "neighbor-o11-eptier", "EP_THEN_KV_REQUEST_FIRST", 11),
    ("B13_FAIR", "neighbor-o13-fair", "FAIR", 13),
    ("B13_OPPORTUNITY", "neighbor-o13-eptier", "EP_THEN_KV_REQUEST_FIRST", 13),
]

SEED_RUN = ("SEED_ONLY_LOW_LOAD", "crosscut-seeds", "FAIR")
PRIMARY_TARGET_IDS = {2, 3}


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(json.loads(line))
    return rows


def read_requests(path):
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def request_ids(row):
    result = set()
    for value in row.get("request_ids", []) or []:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def tbt_values(raw):
    if not raw:
        return []
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return []
    if isinstance(value, (int, float)):
        return [int(value)]
    return [int(item) for item in value]


def percentile_nearest_rank(values, q):
    ordered = sorted(values)
    if not ordered:
        return ""
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def percentile(values, q):
    return percentile_nearest_rank(values, q)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def collectives_by_request(rows):
    result = {}
    for request_id in range(4):
        values = [int(row["cct_ns"]) for row in rows
                  if request_id in request_ids(row)]
        result[request_id] = {
            "count": len(values),
            "mean": (sum(values) / len(values)) if values else "",
            "p99": percentile(values, 0.99),
            "max": max(values) if values else "",
        }
    return result


def build_run_rows(label, run_dir, policy, run_class, seed_d0_output="",
                   include_network=True):
    requests = read_requests(run_dir / "requests.csv")
    telemetry_dir = run_dir / "telemetry"
    flows_path = telemetry_dir / "flows.jsonl"
    flow_rows = read_jsonl(flows_path) if flows_path.exists() else []
    kv_rows = [row for row in flow_rows
                if row.get("traffic_class") == "KV_MOVEMENT"
                and row.get("traffic_subtype") == "P2D"]
    collective_path = telemetry_dir / "collective_telemetry.jsonl"
    collective_rows = (read_jsonl(collective_path)
                       if collective_path.exists() else [])
    ep_stats = collectives_by_request(collective_rows)
    rows = []

    for request in requests:
        rid = int(request["request id"])
        own_flows = [row for row in kv_rows if rid in request_ids(row)]
        first_release = (min(row["requested_start_ns"] for row in own_flows)
                         if own_flows else "")
        last_finish = (max(row["end_ns"] for row in own_flows)
                       if own_flows else "")
        handoff_fct = (last_finish - first_release
                       if own_flows else "")
        second = int(request["second_token_visible_ns"])
        arrival = int(request["arrival"])
        itls = tbt_values(request.get("ITL", ""))
        role = "active_decode_seed" if rid in (0, 1) else "new_p2d_target"
        p2d_ready = int(request.get("p2d_kv_ready_time_ns") or -1)
        # POST_PREFILL releases the P2D markers only after the sampler node.
        # This release timestamp is a causal boundary, not a callback proving
        # that the client observed the token at that instant.
        sampler_boundary = first_release if own_flows else ""
        reported_ttft = int(request.get("TTFT") or -1)
        e = ep_stats[rid]
        rows.append({
            "scenario": label,
            "run_id": label,
            "policy": policy,
            "network_classes": run_class,
            "seed_d0_output_tokens": seed_d0_output,
            "request_id": rid,
            "request_role": role,
            "instance_id": request.get("instance id", ""),
            "paired_decode_instance_id": request.get(
                "paired_decode_instance_id", ""),
            "input_tokens": request.get("input", ""),
            "output_tokens": request.get("output", ""),
            "request_kv_bytes": sum(row["bytes"] for row in own_flows),
            "p2d_flow_count": len(own_flows),
            "prefill_sampler_boundary_ns": sampler_boundary,
            "p2d_first_release_ns": first_release,
            "last_required_kv_finish_ns": last_finish,
            "p2d_kv_ready_time_ns": p2d_ready,
            "p2d_handoff_fct_ns": handoff_fct,
            "ttft_reported_ns": reported_ttft,
            "decode_admit_time_ns": request.get("decode_admit_time_ns", ""),
            "decode_capacity_queue_wait_ns": request.get(
                "decode_capacity_queue_wait_ns", ""),
            "decode_first_batch_id": request.get("decode_first_batch_id", ""),
            "decode_first_batch_start_ns": request.get(
                "decode_first_batch_start_ns", ""),
            "decode_first_batch_finish_ns": request.get(
                "decode_first_batch_finish_ns", ""),
            "second_token_visible_ns": second,
            "reported_ttst_ns": request.get("ttst_ns", ""),
            "sampler_to_second_diagnostic_ns": (
                second - sampler_boundary if sampler_boundary != "" else ""),
            "arrival_to_second_ns": second - arrival,
            "request_completion_ns": request.get("end_time", ""),
            "tbt_sample_count": len(itls),
            "tbt_mean_ns": (sum(itls) / len(itls)) if itls else "",
            "tbt_max_ns": max(itls) if itls else "",
            "tbt_sequence_ns": json.dumps(itls),
            "ep_collective_count": e["count"],
            "ep_cct_mean_ns": e["mean"],
            "ep_cct_p99_nearest_rank_ns": e["p99"],
            "ep_cct_max_ns": e["max"],
        })

    if include_network:
        for row in kv_rows:
            ids = sorted(request_ids(row))
            network_flow_rows.append({
                "scenario": label,
                "policy": policy,
                "network_classes": run_class,
                "flow_id": row.get("flow_id", ""),
                "request_ids": json.dumps(ids),
                "traffic_subtype": row.get("traffic_subtype", ""),
                "src_physical_endpoint": row.get("src", ""),
                "dst_physical_endpoint": row.get("dst", ""),
                "bytes": row.get("bytes", ""),
                "release_ns": row.get("requested_start_ns", ""),
                "start_ns": row.get("start_ns", ""),
                "finish_ns": row.get("end_ns", ""),
                "flow_fct_ns": (row.get("end_ns", 0) -
                                row.get("requested_start_ns", 0)),
                "path": "|".join(row.get("path", [])),
                "layer_id": row.get("layer_id", ""),
                "collective_id": row.get("collective_id", ""),
                "batch_id": row.get("batch_id", ""),
            })

        for row in collective_rows:
            collective_ledger_rows.append({
                "scenario": label,
                "policy": policy,
                "request_ids": json.dumps(sorted(request_ids(row))),
                "collective_id": row.get("collective_id", ""),
                "collective_batch_id": row.get("collective_batch_id", ""),
                "layer_id": row.get("layer_id", ""),
                "collective_type": row.get("collective_type", ""),
                "traffic_subtype": row.get("traffic_subtype", ""),
                "participant_count": row.get("participant_count", ""),
                "peer_flow_count": row.get("peer_flow_count", ""),
                "bytes_per_participant": row.get("bytes_per_participant", ""),
                "start_ns": row.get("start_ns", ""),
                "end_ns": row.get("end_ns", ""),
                "cct_ns": row.get("cct_ns", ""),
            })

        event_path = run_dir / "events.jsonl"
        if event_path.exists():
            interesting = {
                "PREFILL_STARTED", "P2D_READY", "DECODE_ELIGIBLE",
                "DECODE_CAPACITY_WAIT", "BATCH_SELECTED",
                "BATCH_GRAPH_SUBMITTED", "BATCH_COMPLETED",
                "SECOND_TOKEN_VISIBLE",
            }
            for event in read_jsonl(event_path):
                if event.get("event") not in interesting:
                    continue
                if event.get("pd_type") == "decode" and event.get(
                        "instance_id") not in (2, 3):
                    continue
                serving_event_rows.append({
                    "scenario": label,
                    "policy": policy,
                    "timestamp_ns": event.get("timestamp_ns", ""),
                    "event": event.get("event", ""),
                    "pd_type": event.get("pd_type", ""),
                    "instance_id": event.get("instance_id", ""),
                    "request_id": event.get("request_id", ""),
                    "request_ids": json.dumps(event.get("request_ids", [])),
                    "batch_id": event.get("batch_id", ""),
                    "payload_json": json.dumps(event, sort_keys=True),
                })

        link_path = telemetry_dir / "link_telemetry.jsonl"
        if link_path.exists():
            for row in read_jsonl(link_path):
                if row.get("record_type") != "link_timeseries":
                    continue
                link_ledger_rows.append({
                    "scenario": label,
                    "policy": policy,
                    "link_id": row.get("link_id", ""),
                    "interval_start_ns": row.get("interval_start_ns", ""),
                    "timestamp_ns": row.get("timestamp_ns", ""),
                    "interval_duration_ns": row.get("interval_duration_ns", ""),
                    "active_flows": row.get("active_flows", ""),
                    "active_kv_flows": row.get("active_kv_flows", ""),
                    "active_ep_flows": row.get("active_ep_flows", ""),
                    "utilization": row.get("utilization", ""),
                    "kv_allocated_rate_Bps": row.get("kv_allocated_rate_Bps", ""),
                    "ep_allocated_rate_Bps": row.get("ep_allocated_rate_Bps", ""),
                    "released_kv_bytes": row.get("released_kv_bytes", ""),
                    "released_ep_bytes": row.get("released_ep_bytes", ""),
                    "residual_fluid_bytes_not_packet_queue": row.get("queue_bytes", ""),
                })
    return rows


def summarize_links():
    grouped = {}
    for row in link_ledger_rows:
        key = (row["scenario"], row["policy"], row["link_id"])
        grouped.setdefault(key, []).append(row)
    summaries = []
    for (scenario, policy, link), rows in sorted(grouped.items()):
        durations = [int(row["interval_duration_ns"]) for row in rows]
        total_duration = sum(durations)
        if not total_duration:
            continue
        def weighted(field):
            return sum(float(row[field] or 0) * duration
                       for row, duration in zip(rows, durations)) / total_duration
        mixed_ns = sum(duration for row, duration in zip(rows, durations)
                       if int(row["active_kv_flows"] or 0) > 0 and
                       int(row["active_ep_flows"] or 0) > 0)
        summaries.append({
            "scenario": scenario,
            "policy": policy,
            "directed_link": link,
            "sample_count": len(rows),
            "covered_duration_ns": total_duration,
            "window_start_ns": min(int(row["interval_start_ns"]) for row in rows),
            "window_end_ns": max(int(row["timestamp_ns"]) for row in rows),
            "fraction_duration_kv_and_ep_active": mixed_ns / total_duration,
            "mean_utilization_time_weighted": weighted("utilization"),
            "mean_kv_rate_Bps_time_weighted": weighted("kv_allocated_rate_Bps"),
            "mean_ep_rate_Bps_time_weighted": weighted("ep_allocated_rate_Bps"),
            "max_residual_fluid_bytes_not_packet_queue": max(
                int(row["residual_fluid_bytes_not_packet_queue"] or 0)
                for row in rows),
            "mean_residual_fluid_bytes_time_weighted_not_packet_queue": weighted(
                "residual_fluid_bytes_not_packet_queue"),
            "intervals_with_positive_residual_fluid": sum(
                int(row["residual_fluid_bytes_not_packet_queue"] or 0) > 0
                for row in rows),
            "released_kv_bytes_on_link": sum(
                int(row["released_kv_bytes"] or 0) for row in rows),
            "released_ep_bytes_on_link": sum(
                int(row["released_ep_bytes"] or 0) for row in rows),
        })
    return summaries


def main():
    global network_flow_rows, collective_ledger_rows
    global serving_event_rows, link_ledger_rows
    network_flow_rows = []
    collective_ledger_rows = []
    serving_event_rows = []
    link_ledger_rows = []
    all_request_rows = []

    run_root = Path(os.environ.get("DECODEOPP_RUN_ROOT", "/tmp"))
    for label, dirname, network_classes, policy, selected in MAIN_RUNS:
        run_dir = run_root / ("decodeopp-linkwindow-" + dirname)
        all_request_rows.extend(build_run_rows(
            label, run_dir, policy, network_classes,
            seed_d0_output="12", include_network=True))

    for label, dirname, policy, seed_output in NEIGHBOR_RUNS:
        run_dir = run_root / ("decodeopp-" + dirname)
        all_request_rows.extend(build_run_rows(
            label, run_dir, policy, "KV_MOVEMENT,EP",
            seed_d0_output=str(seed_output), include_network=False))

    label, dirname, policy = SEED_RUN
    run_dir = run_root / ("decodeopp-" + dirname)
    all_request_rows.extend(build_run_rows(
        label, run_dir, policy, "KV_MOVEMENT,EP", seed_d0_output="",
        include_network=False))

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(HERE / "06_SERVING_INTEGRATED_RESULTS.csv",
              list(all_request_rows[0]), all_request_rows)
    write_csv(LEDGER_DIR / "P2D_REQUEST_FLOW_LEDGER.csv",
              list(network_flow_rows[0]), network_flow_rows)
    write_csv(LEDGER_DIR / "EP_COLLECTIVE_LEDGER.csv",
              list(collective_ledger_rows[0]), collective_ledger_rows)
    write_csv(LEDGER_DIR / "DECODE_BATCH_EVENT_LEDGER.csv",
              list(serving_event_rows[0]), serving_event_rows)
    write_csv(LEDGER_DIR / "SHARED_LINK_TIMESERIES.csv",
              list(link_ledger_rows[0]), link_ledger_rows)
    summaries = summarize_links()
    write_csv(LEDGER_DIR / "SHARED_LINK_SUMMARY.csv",
              list(summaries[0]), summaries)

    print("wrote %s (%d request rows)" % (
        HERE / "06_SERVING_INTEGRATED_RESULTS.csv", len(all_request_rows)))
    print("P2D flow rows=%d EP collective rows=%d serving events=%d link rows=%d" % (
        len(network_flow_rows), len(collective_ledger_rows),
        len(serving_event_rows), len(link_ledger_rows)))
    print("shared-link summary rows=%d" % len(summaries))


if __name__ == "__main__":
    main()
