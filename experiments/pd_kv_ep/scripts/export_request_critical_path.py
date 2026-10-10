#!/usr/bin/env python3
"""Export request-level serving and P2D event timelines from matched replays.

The exporter keeps native absolute simulator timestamps and reports overlapping
KV network activity separately from additive TTFT segments. It never attributes
aggregate multi-request bytes to individual requests.
"""

import argparse
import csv
import gzip
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES = [
    ("azure_conversation_w7421_first16",
     "experiments/pd_kv_ep/workloads/real/slices/azure2024_conversation/30s__window_007421.jsonl",
     "experiments/pd_kv_ep/results/pd_moe_phase_search/real_azure_conversation_w7421_first16"),
    ("azure_code_w13818_first32",
     "experiments/pd_kv_ep/workloads/real/slices/azure2024_code/30s__window_013818.jsonl",
     "experiments/pd_kv_ep/results/pd_moe_phase_search/real_azure_code_w13818_first32"),
]


def read_jsonl(path, limit=None):
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
                if limit is not None and len(rows) >= limit:
                    break
    return rows


def read_events(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.lstrip().startswith("{"):
                yield json.loads(line)


def number(row, key):
    value = row.get(key)
    if value in (None, "", "None", "-1"):
        return None
    return int(float(value))


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    return values[max(0, math.ceil(q * len(values)) - 1)]


def event_index(path):
    by_request = {}
    for event in read_events(path):
        if event.get("event") not in ("KV_REQUESTED", "KV_COMPLETED"):
            continue
        ids = event.get("request_ids") or []
        for request_id in ids:
            item = by_request.setdefault(int(request_id), {
                "requested": [], "completed": [],
                "shared_request_events": 0,
            })
            if len(ids) > 1:
                item["shared_request_events"] += 1
            if event["event"] == "KV_REQUESTED":
                item["requested"].append(event)
            else:
                item["completed"].append(event)
    return by_request


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(
        "experiments/pd_kv_ep/results/pd_moe_phase_search"))
    args = parser.parse_args()
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    trace_rows = []
    serving_rows = []
    cases = []

    for case_name, workload_rel, result_rel in DEFAULT_CASES:
        workload = ROOT / workload_rel
        result_dir = ROOT / result_rel
        if not workload.is_file() or not result_dir.is_dir():
            raise FileNotFoundError(f"missing input for {case_name}")
        requests_by_policy = {}
        events_by_policy = {}
        source_limit = None
        for policy in ("fair", "ep_first"):
            request_path = result_dir / policy / "requests.csv"
            if not request_path.is_file():
                raise FileNotFoundError(request_path)
            with request_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            source_limit = len(rows)
            requests_by_policy[policy] = rows
            events_by_policy[policy] = event_index(
                result_dir / policy / "kv_events.jsonl.gz")
        source = read_jsonl(workload, source_limit)
        if len(source) != source_limit:
            raise ValueError(f"source/request count mismatch for {case_name}")

        for policy, requests in requests_by_policy.items():
            events = events_by_policy[policy]
            for index, (row, src) in enumerate(zip(requests, source)):
                rid = int(row["request id"])
                if (int(row["input"]) != int(src["input_toks"]) or
                        int(row["output"]) != int(src["output_toks"]) or
                        int(row["arrival"]) != int(src["arrival_time_ns"])):
                    raise ValueError(f"source mismatch {case_name}/{policy}/{rid}")
                arrival = int(row["arrival"])
                prefill = number(row, "prefill_completion_time_ns")
                ready = number(row, "p2d_kv_ready_time_ns")
                control_admit = number(row, "decode_admit_time_ns")
                sched_admit = number(row, "decode_scheduler_admit_time_ns")
                first_token = number(row, "decode_first_token_time_ns")
                ttft = number(row, "TTFT")
                record = events.get(rid, {"requested": [], "completed": [],
                                           "shared_request_events": 0})
                req_events = record["requested"]
                comp_events = record["completed"]
                req_times = [int(e.get("timestamp_ns", e.get("start_ns", 0)))
                             for e in req_events]
                comp_times = [int(e.get("end_ns", e.get("timestamp_ns", 0)))
                              for e in comp_events]
                first_issue = min(req_times) if req_times else None
                last_issue = max(req_times) if req_times else None
                last_complete = max(comp_times) if comp_times else None
                first_complete = min(comp_times) if comp_times else None
                first_token_delta = (None if first_token is None else
                                     first_token - arrival)
                ttft_consistency = (None if ttft is None or first_token_delta is None
                                    else ttft - first_token_delta)
                critical = {
                    "case": case_name,
                    "policy": policy.upper(),
                    "source_request_id": src.get("request_id",
                                                  src.get("source_request_id", "")),
                    "source_record_index": src.get("source_record_index", ""),
                    "sim_request_id": rid,
                    "decode_instance_id": number(row, "decode_instance_id"),
                    "input_tokens": int(src["input_toks"]),
                    "output_tokens": int(src["output_toks"]),
                    "arrival_ns": arrival,
                    "prefill_completion_ns": prefill,
                    "first_kv_issue_ns": first_issue,
                    "last_kv_issue_ns": last_issue,
                    "first_kv_complete_ns": first_complete,
                    "last_kv_complete_ns": last_complete,
                    "kv_event_count": len(comp_events),
                    "kv_shared_request_event_count_not_byte_attributed":
                        record["shared_request_events"],
                    "request_kv_issue_to_last_complete_ns": (
                        None if first_issue is None or last_complete is None
                        else last_complete - first_issue),
                    "last_kv_complete_to_prefill_done_ns": (
                        None if last_complete is None or prefill is None
                        else prefill - last_complete),
                    "p2d_ready_ns": ready,
                    "decode_control_handoff_ns": control_admit,
                    "decode_queue_arrival_ns": number(
                        row, "decode_queue_arrival_time_ns"),
                    "decode_scheduler_admit_ns": sched_admit,
                    "decode_boundary_wait_ns": number(row, "decode_admission_wait_ns"),
                    "decode_capacity_queue_enter_ns": number(
                        row, "decode_capacity_queue_enter_time_ns"),
                    "decode_capacity_queue_wait_ns": number(
                        row, "decode_capacity_queue_wait_ns"),
                    "decode_running_at_handoff": number(
                        row, "decode_running_at_handoff"),
                    "decode_max_num_seqs_at_handoff": number(
                        row, "decode_max_num_seqs_at_handoff"),
                    "decode_iteration_id": number(row, "decode_iteration_id"),
                    "active_decode_sequences_at_first_batch": number(
                        row, "decode_active_sequences_at_first_batch"),
                    "decode_waiting_queue_length_at_first_batch": number(
                        row, "decode_waiting_queue_length_at_first_batch"),
                    "decode_batch_size_at_first_batch": number(
                        row, "decode_batch_size_at_first_batch"),
                    "decode_num_decode_at_first_batch": number(
                        row, "decode_num_decode_at_first_batch"),
                    "decode_missed_iteration_count": number(
                        row, "decode_missed_iteration_count"),
                    "blocking_iteration_start_ns": number(
                        row, "decode_handoff_blocking_batch_start_ns"),
                    "blocking_iteration_finish_ns": number(
                        row, "decode_handoff_blocking_batch_finish_ns"),
                    "first_token_ns": first_token,
                    "TTFT_ns": ttft,
                    "first_token_minus_arrival_ns": first_token_delta,
                    "TTFT_minus_first_token_delta_ns": ttft_consistency,
                    "trace_record_status": row.get("trace_record_status", ""),
                }
                trace_rows.append(critical)

                prefill_lifecycle = (None if prefill is None else prefill - arrival)
                ready_gap = (None if prefill is None or ready is None
                             else ready - prefill)
                ready_to_sched = (None if ready is None or sched_admit is None
                                  else sched_admit - ready)
                scheduler_to_first = (None if sched_admit is None or
                                      first_token is None else first_token - sched_admit)
                accounted = None
                residual = None
                if all(v is not None for v in
                       (prefill_lifecycle, ready_gap, ready_to_sched,
                        scheduler_to_first)):
                    accounted = (prefill_lifecycle + ready_gap +
                                 ready_to_sched + scheduler_to_first)
                    residual = (None if ttft is None else ttft - accounted)
                tbt = json.loads(row.get("TBT") or "[]")
                tbt_ns = [int(x) for x in tbt]
                serving_rows.append({
                    "case": case_name,
                    "policy": policy.upper(),
                    "source_request_id": critical["source_request_id"],
                    "sim_request_id": rid,
                    "trace_record_status": row.get("trace_record_status", ""),
                    "TTFT_ns": ttft,
                    "arrival_to_prefill_completion_ns": prefill_lifecycle,
                    "prefill_completion_to_p2d_ready_ns": ready_gap,
                    "p2d_ready_to_decode_scheduler_admit_ns": ready_to_sched,
                    "scheduler_admit_to_first_token_ns": scheduler_to_first,
                    "decode_capacity_queue_enter_ns": number(
                        row, "decode_capacity_queue_enter_time_ns"),
                    "decode_capacity_queue_wait_ns": number(
                        row, "decode_capacity_queue_wait_ns"),
                    "decode_iteration_id": number(row, "decode_iteration_id"),
                    "active_decode_sequences_at_first_batch": number(
                        row, "decode_active_sequences_at_first_batch"),
                    "decode_waiting_queue_length_at_first_batch": number(
                        row, "decode_waiting_queue_length_at_first_batch"),
                    "decode_batch_size_at_first_batch": number(
                        row, "decode_batch_size_at_first_batch"),
                    "decode_num_decode_at_first_batch": number(
                        row, "decode_num_decode_at_first_batch"),
                    "sum_of_event_segments_ns": accounted,
                    "TTFT_minus_event_segments_ns": residual,
                    "p2d_ready_to_decode_scheduler_admit_fraction_of_TTFT": (
                        None if ttft in (None, 0) or ready_to_sched is None
                        else ready_to_sched / ttft),
                    "tbt_sample_count": len(tbt_ns),
                    "TBT_mean_ns": (sum(tbt_ns) / len(tbt_ns) if tbt_ns else None),
                    "TBT_P95_ns": quantile(tbt_ns, 0.95),
                    "TBT_P99_ns": quantile(tbt_ns, 0.99),
                    "TTFT_definition_note": (
                        "integrated CSV TTFT; event segments are scheduler timestamps; "
                        "KV flows may overlap arrival-to-prefill lifecycle"),
                })

        cases.append({"case": case_name, "source_records": source_limit,
                      "policies": list(requests_by_policy)})

    trace_path = output / "REQUEST_CRITICAL_PATH_TRACE.csv"
    serving_path = output / "SERVING_CRITICAL_PATH_BREAKDOWN.csv"
    write_csv(trace_path, list(trace_rows[0]), trace_rows)
    write_csv(serving_path, list(serving_rows[0]), serving_rows)
    print(json.dumps({"cases": cases, "request_rows": len(trace_rows),
                      "serving_rows": len(serving_rows),
                      "request_trace_csv": str(trace_path),
                      "serving_breakdown_csv": str(serving_path)}, indent=2))


if __name__ == "__main__":
    main()
