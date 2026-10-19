#!/usr/bin/env python3
"""Export compact, provenance-preserving ledgers from completed batch-miss runs."""

import argparse
import csv
import json
import math
from pathlib import Path


def read_jsonl(path):
    rows = []
    if not path or not Path(path).exists():
        return rows
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def read_requests(path):
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def nearest_rank(values, percentile):
    values = sorted(float(value) for value in values)
    if not values:
        return ""
    return values[max(0, math.ceil(percentile * len(values)) - 1)]


def dump_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def event_index(graph_rows):
    submits, completes = {}, {}
    for row in graph_rows:
        batch_ids = [int(value) for value in row.get("batch_ids", [])]
        if row.get("event") == "submit":
            for batch_id in batch_ids:
                submits.setdefault(batch_id, row)
        elif row.get("event") == "graph_completed":
            for batch_id in batch_ids:
                completes.setdefault(batch_id, row)
    return submits, completes


def one_run(name, policy, requests_path, flow_path, collective_path=None,
            scheduler_path=None, graph_path=None, request_id=24):
    requests = read_requests(requests_path)
    target = next(row for row in requests
                  if int(row["request id"]) == request_id)
    flows = read_jsonl(flow_path)
    kv = [row for row in flows
          if row.get("traffic_class") == "KV_MOVEMENT" and
          row.get("traffic_subtype") == "P2D" and
          request_id in [int(value) for value in row.get("request_ids", [])]]
    kv.sort(key=lambda row: (int(row.get("layer_id", -1)),
                             int(row.get("requested_start_ns", -1))))
    if kv:
        first_release = min(int(row["requested_start_ns"]) for row in kv)
        last_release = max(int(row["requested_start_ns"]) for row in kv)
        last_flow = max(kv, key=lambda row: int(row["end_ns"]))
        last_finish = int(last_flow["end_ns"])
        shard_fct = [int(row["end_ns"]) - int(row["requested_start_ns"])
                     for row in kv]
        p2d_span = last_finish - first_release
        post_last_release = last_finish - last_release
    else:
        first_release = last_release = last_finish = p2d_span = post_last_release = ""
        last_flow = {}
        shard_fct = []

    sched = read_jsonl(scheduler_path)
    first_batch_id = int(target.get("decode_first_batch_id", -1))
    prefill_start = next((int(row["timestamp_ns"]) for row in sched
                          if row.get("event") == "PREFILL_STARTED" and
                          int(row.get("request_id", -1)) == request_id), -1)
    selected = next((row for row in sched
                     if row.get("event") == "BATCH_SELECTED" and
                     int(row.get("batch_id", -1)) == first_batch_id and
                     request_id in [int(value) for value in
                                    row.get("request_ids", [])]), {})
    graph_rows = read_jsonl(graph_path)
    submits, completes = event_index(graph_rows)
    graph_submit = submits.get(first_batch_id, {})
    graph_complete = completes.get(first_batch_id, {})
    prefill_graph = next((row for row in graph_rows
                          if row.get("event") == "submit" and
                          request_id in [int(value) for value in
                                         row.get("request_ids", [])] and
                          int(row.get("p2p", 0)) > 0), {})
    prefill_graph_id = int(prefill_graph.get("graph_id", -1))
    sampler_nodes = [row for row in graph_rows
                     if row.get("event") == "compute_node_completed" and
                     int(row.get("graph_id", -1)) == prefill_graph_id and
                     "sampler" in str(row.get("node_name", "")).lower()]
    prefill_compute_finish = max(
        (int(row["finish_ns"]) for row in sampler_nodes), default="")
    if prefill_compute_finish == "":
        prefill_compute_finish = ""

    collectives = [row for row in read_jsonl(collective_path)
                   if row.get("event") == "COLLECTIVE_COMPLETED" and
                   row.get("traffic_class") == "EP"]
    ccts = [int(row["cct_ns"]) for row in collectives]
    ttst = int(target.get("ttst_ns", -1))
    arrival = int(target["arrival"])
    ttft = int(target.get("TTFT", -1))
    p2d_ready = int(target.get("p2d_kv_ready_time_ns", -1))
    first_visible = arrival + ttft if ttft >= 0 else -1
    return {
        "case": name, "policy": policy, "request_id": request_id,
        "request_count": len(requests),
        "input_tokens": int(target["input"]),
        "target_kv_flow_count": len(kv),
        "target_kv_bytes": sum(int(row["bytes"]) for row in kv),
        "first_kv_release_ns": first_release,
        "last_kv_release_ns": last_release,
        "last_kv_finish_ns": last_finish,
        "critical_kv_flow_id": last_flow.get("flow_id", ""),
        "critical_kv_layer": last_flow.get("layer_id", ""),
        "critical_kv_bytes": last_flow.get("bytes", ""),
        "critical_kv_path": "|".join(last_flow.get("path", [])),
        "critical_kv_fct_ns": (int(last_flow["end_ns"]) -
                                int(last_flow["requested_start_ns"])) if kv else "",
        "kv_handoff_span_ns": p2d_span,
        "kv_post_last_release_drain_ns": post_last_release,
        "prefill_start_ns": prefill_start,
        "prefill_compute_finish_ns": prefill_compute_finish,
        "prefill_graph_id": prefill_graph_id,
        "prefill_graph_finish_ns": int(target.get("TTFT", -1)) + arrival,
        "first_token_visible_ns": first_visible,
        "p2d_ready_ns": p2d_ready,
        "decode_handoff_ns": int(target.get("decode_admit_time_ns", -1)),
        "decode_eligible_ns": int(target.get("decode_eligible_time_ns", -1)),
        "first_batch_id": first_batch_id,
        "first_batch_decision_ns": int(target.get(
            "decode_first_batch_decision_ns", -1)),
        "first_batch_graph_submit_ns": (
            int(graph_submit["now_ns"]) if "now_ns" in graph_submit else ""),
        "first_batch_graph_finish_ns": (
            int(graph_complete["finish_ns"]) if "finish_ns" in graph_complete else ""),
        "ready_to_first_batch_decision_slack_ns": (
            int(target.get("decode_first_batch_decision_ns", -1)) - p2d_ready
            if p2d_ready >= 0 and int(target.get(
                "decode_first_batch_decision_ns", -1)) >= 0 else ""),
        "kv_hidden_slack_to_prefill_graph_ns": (
            int(target.get("TTFT", -1)) + arrival - last_finish
            if last_finish != "" and int(target.get("TTFT", -1)) >= 0 else ""),
        "network_wait_after_prefill_graph_ns": (
            max(0, int(last_finish) - (int(target.get("TTFT", -1)) + arrival))
            if last_finish != "" and int(target.get("TTFT", -1)) >= 0 else ""),
        "second_token_visible_ns": int(target.get("second_token_visible_ns", -1)),
        "TTFT_ns": ttft,
        "TTST_ns": ttst,
        "TPOT_ns": int(float(target.get("TPOT", -1))),
        "capacity_wait_ns": int(target.get("decode_capacity_queue_wait_ns", -1)),
        "active_at_handoff": int(target.get("decode_running_at_handoff", -1)),
        "max_num_seqs": int(target.get("decode_max_num_seqs_at_handoff", -1)),
        "kv_shard_fct_mean_ns": sum(shard_fct) / len(shard_fct) if shard_fct else "",
        "kv_shard_fct_p50_ns": nearest_rank(shard_fct, 0.50),
        "kv_shard_fct_p95_ns": nearest_rank(shard_fct, 0.95),
        "kv_shard_fct_p99_ns": nearest_rank(shard_fct, 0.99),
        "kv_shard_fct_max_ns": max(shard_fct) if shard_fct else "",
        "EP_collective_count": len(ccts),
        "EP_CCT_mean_ns": sum(ccts) / len(ccts) if ccts else "",
        "EP_CCT_p50_ns": nearest_rank(ccts, 0.50),
        "EP_CCT_p95_ns": nearest_rank(ccts, 0.95),
        "EP_CCT_p99_ns": nearest_rank(ccts, 0.99),
        "EP_CCT_max_ns": max(ccts) if ccts else "",
        "sample_note": "Controlled deterministic run; do not interpret request/phase P99 as production tail.",
    }, kv, flows, sched, graph_rows, collectives


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--e0-requests", required=True)
    parser.add_argument("--e0-flows", required=True)
    parser.add_argument("--e1-dir", required=True)
    parser.add_argument("--e2-dir", required=True)
    parser.add_argument("--e3a-dir", required=True)
    parser.add_argument("--e3b-dir", required=True)
    parser.add_argument("--e3-high-bandwidth-dir")
    parser.add_argument("--e4-staggered-dir")
    parser.add_argument("--output-dir", default="research_motivation/batch_miss/results")
    args = parser.parse_args()

    request_id = 24
    runs = []
    items = [
        ("E0_SINGLE", "FAIR", args.e0_requests, args.e0_flows,
         None, None, None, 0),
        ("E1_ONE_KV", "KV_ISOLATED", str(Path(args.e1_dir) / "requests.csv"),
         str(Path(args.e1_dir) / "flowsim.jsonl"),
         str(Path(args.e1_dir) / "collective_telemetry.jsonl"),
         str(Path(args.e1_dir) / "scheduler.jsonl"),
         str(Path(args.e1_dir) / "graph.jsonl"), 24),
        ("E2_ONE_KV", "FAIR", str(Path(args.e2_dir) / "requests.csv"),
         str(Path(args.e2_dir) / "flowsim.jsonl"),
         str(Path(args.e2_dir) / "collective_telemetry.jsonl"),
         str(Path(args.e2_dir) / "scheduler.jsonl"),
         str(Path(args.e2_dir) / "graph.jsonl"), 24),
        ("E3_MAX_4_KV", "KV_ISOLATED", str(Path(args.e3a_dir) / "requests.csv"),
         str(Path(args.e3a_dir) / "flowsim.jsonl"),
         str(Path(args.e3a_dir) / "collective_telemetry.jsonl"),
         str(Path(args.e3a_dir) / "scheduler.jsonl"),
         str(Path(args.e3a_dir) / "graph.jsonl"), 24),
        ("E3_MAX_4_KV", "FAIR", str(Path(args.e3b_dir) / "requests.csv"),
         str(Path(args.e3b_dir) / "flowsim.jsonl"),
         str(Path(args.e3b_dir) / "collective_telemetry.jsonl"),
         str(Path(args.e3b_dir) / "scheduler.jsonl"),
         str(Path(args.e3b_dir) / "graph.jsonl"), 24),
    ]
    for case, option in (("E3_400G_HIGH_BANDWIDTH", args.e3_high_bandwidth_dir),
                         ("E4_R2_STAGGERED", args.e4_staggered_dir)):
        if option:
            run_dir = Path(option)
            items.append((
                case, "FAIR", str(run_dir / "requests.csv"),
                str(run_dir / "flowsim.jsonl"),
                str(run_dir / "collective_telemetry.jsonl"),
                str(run_dir / "scheduler.jsonl"),
                str(run_dir / "graph.jsonl"), 24))
    details = {}
    for item in items:
        summary, kv, flows, scheduler, graph, collectives = one_run(*item)
        runs.append(summary)
        details[summary["case"] + ":" + summary["policy"]] = (
            kv, flows, scheduler, graph, collectives)

    out = Path(args.output_dir)
    columns = list(runs[0])
    dump_csv(out / "06_EXPERIMENT_RESULTS.csv", runs, columns)
    # Keep the required one-file summary at the experiment root while the
    # detailed ledgers remain grouped under results/.
    dump_csv(out.parent / "06_EXPERIMENT_RESULTS.csv", runs, columns)

    candidate_rows = []
    request_sources = [
        ("E1_ONE_KV", "KV_ISOLATED", args.e1_dir),
        ("E2_ONE_KV", "FAIR", args.e2_dir),
        ("E3_MAX_4_KV", "KV_ISOLATED", args.e3a_dir),
        ("E3_MAX_4_KV", "FAIR", args.e3b_dir),
    ]
    if args.e3_high_bandwidth_dir:
        request_sources.append(("E3_400G_HIGH_BANDWIDTH", "FAIR",
                                args.e3_high_bandwidth_dir))
    if args.e4_staggered_dir:
        request_sources.append(("E4_R2_STAGGERED", "FAIR",
                                args.e4_staggered_dir))
    references = {
        "E1_ONE_KV": next(row["TTST_ns"] for row in runs
                          if row["case"] == "E1_ONE_KV"),
        "E3_MAX_4_KV": next(row["TTST_ns"] for row in runs
                            if row["case"] == "E3_MAX_4_KV" and
                            row["policy"] == "KV_ISOLATED"),
    }
    for case, policy, run_dir in request_sources:
        reference_key = ("E1_ONE_KV" if case in ("E1_ONE_KV", "E2_ONE_KV")
                         else "E3_MAX_4_KV")
        reference = float(references[reference_key])
        source_flows = read_jsonl(Path(run_dir) / "flowsim.jsonl")
        source_scheduler = read_jsonl(Path(run_dir) / "scheduler.jsonl")
        source_graph = read_jsonl(Path(run_dir) / "graph.jsonl")
        for req in read_requests(Path(run_dir) / "requests.csv"):
            rid = int(req["request id"])
            is_multi_candidate = case in ("E3_MAX_4_KV", "E3_400G_HIGH_BANDWIDTH")
            if (is_multi_candidate and rid < 24) or (
                    not is_multi_candidate and rid != 24):
                continue
            if case == "E4_R2_STAGGERED" and rid != 24:
                continue
            ttst = int(req.get("ttst_ns", -1))
            first_batch_id = int(req.get("decode_first_batch_id", -1))
            selected_event = next((event for event in source_scheduler
                                   if event.get("event") == "BATCH_SELECTED" and
                                   int(event.get("batch_id", -1)) == first_batch_id and
                                   rid in [int(value) for value in
                                           event.get("request_ids", [])]), {})
            graph_submit = next((event for event in source_graph
                                 if event.get("event") == "submit" and
                                 first_batch_id in [int(value) for value in
                                                    event.get("batch_ids", [])]), {})
            prefill_start_event = next((event for event in source_scheduler
                                        if event.get("event") == "PREFILL_STARTED" and
                                        int(event.get("request_id", -1)) == rid), {})
            request_kv = [flow for flow in source_flows
                          if flow.get("traffic_class") == "KV_MOVEMENT" and
                          flow.get("traffic_subtype") == "P2D" and
                          rid in [int(value) for value in flow.get("request_ids", [])]]
            kv_last = max((int(flow["end_ns"]) for flow in request_kv),
                          default=-1)
            first_visible_ns = (int(req["arrival"]) + int(req.get("TTFT", -1))
                                if int(req.get("TTFT", -1)) >= 0 else -1)
            kv_hidden_slack_ns = (max(0, first_visible_ns - kv_last)
                                  if first_visible_ns >= 0 and kv_last >= 0 else -1)
            network_wait_ns = (max(0, kv_last - first_visible_ns)
                               if first_visible_ns >= 0 and kv_last >= 0 else -1)
            candidate_rows.append({
                "case": case, "policy": policy, "request_id": rid,
                "input_tokens": int(req["input"]), "arrival_ns": int(req["arrival"]),
                "prefill_start_ns": int(prefill_start_event.get("timestamp_ns", -1)),
                "TTFT_ns": int(req.get("TTFT", -1)),
                "first_token_visible_ns": first_visible_ns,
                "prefill_graph_finish_ns": first_visible_ns,
                "p2d_ready_ns": int(req.get("p2d_kv_ready_time_ns", -1)),
                "decode_handoff_ns": int(req.get("decode_admit_time_ns", -1)),
                "decode_eligible_ns": int(req.get("decode_eligible_time_ns", -1)),
                "first_batch_id": int(req.get("decode_first_batch_id", -1)),
                "first_batch_decision_ns": int(req.get("decode_first_batch_decision_ns", -1)),
                "first_batch_start_ns": (
                    int(graph_submit["now_ns"]) if "now_ns" in graph_submit else ""),
                "first_batch_graph_finish_ns": (
                    int(req["decode_first_batch_finish_ns"])
                    if int(req.get("decode_first_batch_finish_ns", -1)) >= 0 else ""),
                "max_num_seqs_at_decision": int(selected_event.get("max_num_seqs", -1)),
                "active_sequences_at_decision": int(selected_event.get("active_sequences", -1)),
                "free_kv_blocks_at_decision": int(selected_event.get("free_kv_blocks", -1)),
                "token_budget_used_at_decision": int(selected_event.get("token_budget_used", -1)),
                "token_budget_limit_at_decision": int(selected_event.get("max_num_batched_tokens", -1)),
                "second_token_visible_ns": int(req.get("second_token_visible_ns", -1)),
                "TTST_ns": ttst, "TPOT_ns": int(float(req.get("TPOT", -1))),
                "capacity_wait_ns": int(req.get("decode_capacity_queue_wait_ns", -1)),
                "kv_last_required_finish_ns": kv_last,
                "kv_required_flow_count": len(request_kv),
                "kv_hidden_slack_to_prefill_graph_ns": kv_hidden_slack_ns,
                "network_wait_after_prefill_graph_ns": network_wait_ns,
                "max_num_seqs_at_handoff": int(req.get("decode_max_num_seqs_at_handoff", -1)),
                "active_decode_at_handoff": int(req.get("decode_running_at_handoff", -1)),
                "kv_last_required_finish_ns": max(
                    (int(flow["end_ns"]) for flow in read_jsonl(
                        Path(run_dir) / "flowsim.jsonl")
                     if flow.get("traffic_class") == "KV_MOVEMENT" and
                     flow.get("traffic_subtype") == "P2D" and
                     rid in [int(value) for value in flow.get("request_ids", [])]),
                    default=-1),
                "TTST_reference_ns": int(reference),
                "SLO_1p25x_ns": int(reference * 1.25),
                "SLO_1p5x_ns": int(reference * 1.5),
                "SLO_2x_ns": int(reference * 2),
                "meets_1p25x": int(ttst <= reference * 1.25),
                "meets_1p5x": int(ttst <= reference * 1.5),
                "meets_2x": int(ttst <= reference * 2),
                "note": "Controlled workload sample; SLO ratios are sensitivity, not production SLOs.",
            })
    dump_csv(out / "06_CANDIDATE_REQUESTS.csv", candidate_rows,
             list(candidate_rows[0]) if candidate_rows else ["request_id"])

    # Per-flow P2D ledger for R1 and the three simultaneous R2 requests.
    flow_rows = []
    overlap_rows = []
    selected = [
        ("E1_ONE_KV", "KV_ISOLATED"), ("E2_ONE_KV", "FAIR"),
        ("E3_MAX_4_KV", "KV_ISOLATED"), ("E3_MAX_4_KV", "FAIR")]
    if args.e3_high_bandwidth_dir:
        selected.append(("E3_400G_HIGH_BANDWIDTH", "FAIR"))
    if args.e4_staggered_dir:
        selected.append(("E4_R2_STAGGERED", "FAIR"))
    for case, policy in selected:
        kv, flows, *_ = details[case + ":" + policy]
        target_ids = {24} if "ONE_KV" in case else {24, 25, 26, 27}
        target_kv = [row for row in flows
                     if row.get("traffic_class") == "KV_MOVEMENT" and
                     row.get("traffic_subtype") == "P2D" and
                     target_ids.intersection(int(v) for v in row.get("request_ids", []))]
        eps = [row for row in flows if row.get("traffic_class") == "EP"]
        for row in target_kv:
            flow_rows.append({
                "case": case, "policy": policy,
                "request_ids": ";".join(map(str, row.get("request_ids", []))),
                "flow_id": row.get("flow_id"), "layer_id": row.get("layer_id"),
                "src": row.get("src"), "dst": row.get("dst"),
                "bytes": row.get("bytes"),
                "release_ns": row.get("requested_start_ns"),
                "start_ns": row.get("start_ns"), "finish_ns": row.get("end_ns"),
                "FCT_ns": int(row["end_ns"]) - int(row["requested_start_ns"]),
                "path": "|".join(row.get("path", [])),
            })
            if 24 not in [int(v) for v in row.get("request_ids", [])]:
                continue
            for ep in eps:
                shared = sorted(set(row.get("path", [])) & set(ep.get("path", [])))
                overlap = max(0, min(int(row["end_ns"]), int(ep["end_ns"])) -
                             max(int(row["start_ns"]), int(ep["start_ns"])))
                if overlap and shared:
                    overlap_rows.append({
                        "case": case, "policy": policy,
                        "kv_flow_id": row.get("flow_id"),
                        "kv_request_ids": ";".join(map(str, row.get("request_ids", []))),
                        "ep_flow_id": ep.get("flow_id"),
                        "ep_request_ids": ";".join(map(str, ep.get("request_ids", []))),
                        "shared_directed_links": ";".join(shared),
                        "overlap_start_ns": max(int(row["start_ns"]), int(ep["start_ns"])),
                        "overlap_end_ns": min(int(row["end_ns"]), int(ep["end_ns"])),
                        "overlap_ns": overlap,
                    })
    flow_cols = ["case", "policy", "request_ids", "flow_id", "layer_id",
                 "src", "dst", "bytes", "release_ns", "start_ns", "finish_ns",
                 "FCT_ns", "path"]
    dump_csv(out / "07_KV_FLOW_LEDGER.csv", flow_rows, flow_cols)
    overlap_cols = ["case", "policy", "kv_flow_id", "kv_request_ids",
                    "ep_flow_id", "ep_request_ids", "shared_directed_links",
                    "overlap_start_ns", "overlap_end_ns", "overlap_ns"]
    dump_csv(out / "07_KV_EP_SHARED_LINK_OVERLAPS.csv", overlap_rows, overlap_cols)

    # Compact shared-link telemetry for matched, four-P2D cases. Fluid backlog
    # is analytical residual work, not packet-buffer occupancy.
    link_ids = {"24->30", "30->26", "26->8", "30->28", "28->16", "28->17"}
    link_rows = []
    telemetry_sources = [
        ("E3_MAX_4_KV", "KV_ISOLATED", args.e3a_dir),
        ("E3_MAX_4_KV", "FAIR", args.e3b_dir),
    ]
    if args.e3_high_bandwidth_dir:
        telemetry_sources.append(("E3_400G_HIGH_BANDWIDTH", "FAIR",
                                  args.e3_high_bandwidth_dir))
    if args.e4_staggered_dir:
        telemetry_sources.append(("E4_R2_STAGGERED", "FAIR",
                                  args.e4_staggered_dir))
    for case, policy, run_dir in telemetry_sources:
        end_ns = 205_000_000 if case == "E4_R2_STAGGERED" else 131_000_000
        for row in read_jsonl(Path(run_dir) / "link_telemetry.jsonl"):
            if row.get("link_id") not in link_ids:
                continue
            if not 54_000_000 <= int(row.get("timestamp_ns", 0)) <= end_ns:
                continue
            link_rows.append({
                "case": case, "policy": policy,
                **{key: row.get(key) for key in (
                    "interval_start_ns", "timestamp_ns", "interval_duration_ns",
                    "link_id", "active_flows", "active_kv_flows", "active_ep_flows",
                    "allocated_rate_Bps", "kv_allocated_rate_Bps",
                    "ep_allocated_rate_Bps", "released_kv_bytes", "released_ep_bytes",
                    "utilization", "fluid_outstanding_bytes")}})
    link_columns = [
        "case", "policy", "interval_start_ns", "timestamp_ns",
        "interval_duration_ns", "link_id", "active_flows", "active_kv_flows",
        "active_ep_flows", "allocated_rate_Bps", "kv_allocated_rate_Bps",
        "ep_allocated_rate_Bps", "released_kv_bytes", "released_ep_bytes",
        "utilization", "fluid_outstanding_bytes"]
    dump_csv(out / "07_LINK_FLUID_TIMESERIES.csv", link_rows, link_columns)

    # A unified R1 timeline joins scheduler transitions to actual graph submit/
    # completion and the last P2D shard. Compute sampler timestamps are present
    # for the two max-concurrency runs; earlier controls use graph completion.
    timeline = []
    for case, policy in selected:
        kv, flows, sched, graph, _ = details[case + ":" + policy]
        summary = next(item for item in runs
                       if item["case"] == case and item["policy"] == policy)
        for row in sched:
            if (int(row.get("request_id", -1)) == request_id or
                    request_id in [int(value) for value in row.get("request_ids", [])]):
                if row.get("event") in {
                        "PREFILL_STARTED", "BATCH_SELECTED", "BATCH_COMPLETED",
                        "P2D_READY", "DECODE_ELIGIBLE", "SECOND_TOKEN_VISIBLE"}:
                    timeline.append({
                        "case": case, "policy": policy,
                        "timestamp_ns": row.get("timestamp_ns"),
                        "event": row.get("event"),
                        "request_id": row.get("request_id", request_id),
                        "batch_id": row.get("batch_id", ""),
                        "request_ids": ";".join(map(str, row.get("request_ids", []))),
                        "detail": "scheduler ledger"})
        target_prefill_graph = summary.get("prefill_graph_id", -1)
        target_batch = summary.get("first_batch_id", -1)
        for row in graph:
            if (row.get("event") == "compute_node_completed" and
                    int(row.get("graph_id", -1)) == target_prefill_graph and
                    "sampler" in str(row.get("node_name", "")).lower()):
                timeline.append({
                    "case": case, "policy": policy,
                    "timestamp_ns": row["finish_ns"],
                    "event": "PREFILL_LAST_SAMPLER_COMPLETE",
                    "request_id": request_id, "batch_id": "",
                    "request_ids": "", "detail": row.get("node_name", "")})
            if row.get("event") == "submit" and target_batch in [
                    int(value) for value in row.get("batch_ids", [])]:
                timeline.append({
                    "case": case, "policy": policy,
                    "timestamp_ns": row.get("now_ns"),
                    "event": "DECODE_BATCH_GRAPH_SUBMIT",
                    "request_id": request_id, "batch_id": target_batch,
                    "request_ids": ";".join(map(str, row.get("request_ids", []))),
                    "detail": "FlowSim submit"})
            if row.get("event") == "graph_completed" and target_batch in [
                    int(value) for value in row.get("batch_ids", [])]:
                timeline.append({
                    "case": case, "policy": policy,
                    "timestamp_ns": row.get("finish_ns"),
                    "event": "DECODE_BATCH_GRAPH_COMPLETE",
                    "request_id": request_id, "batch_id": target_batch,
                    "request_ids": ";".join(map(str, row.get("request_ids", []))),
                    "detail": "FlowSim graph completion"})
        if kv:
            last = max(kv, key=lambda row: int(row["end_ns"]))
            timeline.append({
                "case": case, "policy": policy,
                "timestamp_ns": last["end_ns"], "event": "LAST_REQUIRED_KV_SHARD_COMPLETE",
                "request_id": request_id, "batch_id": last.get("batch_id", ""),
                "request_ids": ";".join(map(str, last.get("request_ids", []))),
                "detail": last.get("flow_id", "")})
    timeline.sort(key=lambda row: (row["case"], row["policy"],
                                   int(row.get("timestamp_ns") or -1)))
    dump_csv(out / "07_EVENT_TIMELINE.csv", timeline,
             ["case", "policy", "timestamp_ns", "event", "request_id",
              "batch_id", "request_ids", "detail"])

    # Preserve the complete scheduler and graph-event provenance for every
    # matched case; these files are compact compared with packet logs.
    for case, policy in selected:
        _, _, scheduler, graph, _ = details[case + ":" + policy]
        stem = case + "_" + policy
        (out / (stem + "_SCHEDULER_LEDGER.jsonl")).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in scheduler),
            encoding="utf-8")
        (out / (stem + "_GRAPH_LEDGER.jsonl")).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in graph),
            encoding="utf-8")

    print(json.dumps({
        "summary_rows": len(runs),
        "kv_flow_rows": len(flow_rows),
        "directed_kv_ep_overlap_pairs": len(overlap_rows),
        "output_dir": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
