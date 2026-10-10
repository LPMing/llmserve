#!/usr/bin/env python3
"""Select and materialize representative windows from converted traces.

Selection is based only on observable source workload pressure (arrival count,
input tokens, and burstiness), never on a later slowdown metric.  The output
retains each row's provenance and uses a new relative arrival origin.
"""

import argparse
import csv
import json
import heapq
from collections import defaultdict
from pathlib import Path


INPUTS = {
    "azure2024_code": "azure2024/code/converted.jsonl",
    "azure2024_conversation": "azure2024/conversation/converted.jsonl",
    "burstgpt": "burstgpt/converted.jsonl",
    "mooncake_conversation": "mooncake_fast25/conversation/converted.jsonl",
    "mooncake_toolagent": "mooncake_fast25/toolagent/converted.jsonl",
}
WINDOWS_S = (30, 60, 300)


def _scan(path, durations_ns):
    buckets_by_duration = {duration_ns: {} for duration_ns in durations_ns}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            arrival = int(row["arrival_time_ns"])
            for duration_ns in durations_ns:
                bucket_id = arrival // duration_ns
                buckets = buckets_by_duration[duration_ns]
                bucket = buckets.setdefault(bucket_id, {
                    "window_id": bucket_id,
                    "start_ns": bucket_id * duration_ns,
                    "end_ns": (bucket_id + 1) * duration_ns,
                    "request_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "max_one_second_count": 0,
                    "one_second_counts": {},
                })
                bucket["request_count"] += 1
                bucket["input_tokens"] += int(row["input_toks"])
                bucket["output_tokens"] += int(row["output_toks"])
                second = arrival // 1_000_000_000
                bucket["one_second_counts"][second] = (
                    bucket["one_second_counts"].get(second, 0) + 1)
    for buckets in buckets_by_duration.values():
        for bucket in buckets.values():
            bucket["max_one_second_count"] = max(
                bucket["one_second_counts"].values(), default=0)
            del bucket["one_second_counts"]
            bucket["rps"] = bucket["request_count"] / max(
                (bucket["end_ns"] - bucket["start_ns"]) / 1e9, 1e-9)
            bucket["input_tokens_per_s"] = bucket["input_tokens"] / max(
                (bucket["end_ns"] - bucket["start_ns"]) / 1e9, 1e-9)
            bucket["burst_ratio"] = bucket["max_one_second_count"] / max(
                bucket["rps"], 1e-9)
    return buckets_by_duration


def _select(buckets, top_k):
    selected = {}
    metrics = {
        "arrival_count": lambda b: b["request_count"],
        "input_pressure": lambda b: b["input_tokens"],
        "burstiness": lambda b: (b["max_one_second_count"], b["request_count"]),
    }
    for reason, score in metrics.items():
        for bucket in sorted(buckets.values(), key=score, reverse=True)[:top_k]:
            selected.setdefault(bucket["window_id"], set()).add(reason)
    return selected


def _materialize(path, target_root, dataset, selected_by_duration):
    handles = {}
    try:
        for duration_ns, selected in selected_by_duration.items():
            for window_id in selected:
                out = target_root / dataset / f"{duration_ns // 1_000_000_000}s__window_{window_id:06d}.jsonl"
                out.parent.mkdir(parents=True, exist_ok=True)
                handles[(duration_ns, window_id)] = out.open("w", encoding="utf-8")
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                arrival = int(row["arrival_time_ns"])
                for duration_ns, selected in selected_by_duration.items():
                    window_id = arrival // duration_ns
                    handle = handles.get((duration_ns, window_id))
                    if handle is None:
                        continue
                    sliced = dict(row)
                    sliced["arrival_time_ns"] = arrival - window_id * duration_ns
                    sliced["trace_slice_window_id"] = window_id
                    sliced["trace_slice_duration_ns"] = duration_ns
                    handle.write(json.dumps(sliced, ensure_ascii=False) + "\n")
    finally:
        for handle in handles.values():
            handle.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path("experiments/pd_kv_ep/workloads/real"))
    parser.add_argument("--output", type=Path,
                        default=Path("experiments/pd_kv_ep/workloads/real/slices"))
    parser.add_argument("--top-k", type=int, default=2)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    candidates = []
    for dataset, relative in INPUTS.items():
        source = root / relative
        durations_ns = [duration_s * 1_000_000_000 for duration_s in WINDOWS_S]
        buckets_by_duration = _scan(source, durations_ns)
        selected_by_duration = {}
        for duration_s, duration_ns in zip(WINDOWS_S, durations_ns):
            buckets = buckets_by_duration[duration_ns]
            selected = _select(buckets, args.top_k)
            selected_by_duration[duration_ns] = selected
            for window_id, reasons in selected.items():
                bucket = buckets[window_id]
                candidates.append({
                    "dataset": dataset,
                    "source": str(source),
                    "duration_s": duration_s,
                    "window_id": window_id,
                    "start_ns": bucket["start_ns"],
                    "end_ns": bucket["end_ns"],
                    "request_count": bucket["request_count"],
                    "rps": bucket["rps"],
                    "input_tokens": bucket["input_tokens"],
                    "output_tokens": bucket["output_tokens"],
                    "input_tokens_per_s": bucket["input_tokens_per_s"],
                    "max_one_second_count": bucket["max_one_second_count"],
                    "burst_ratio": bucket["burst_ratio"],
                    "selection_reason": "+".join(sorted(reasons)),
                })
        _materialize(source, output, dataset, selected_by_duration)
    candidates.sort(key=lambda row: (row["dataset"], row["duration_s"], row["window_id"]))
    candidate_path = output / "window_candidates.csv"
    with candidate_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(candidates[0]))
        writer.writeheader()
        writer.writerows(candidates)
    with (output / "window_selection_policy.json").open("w", encoding="utf-8") as stream:
        json.dump({
            "windows_s": list(WINDOWS_S),
            "top_k_per_metric": args.top_k,
            "metrics": ["arrival_count", "input_pressure", "burstiness"],
            "selection_is_counterfactual_free": True,
            "arrival_rebased_within_slice": True,
        }, stream, indent=2)
    print(json.dumps({"candidate_count": len(candidates),
                      "candidate_csv": str(candidate_path)}, indent=2))


if __name__ == "__main__":
    main()
