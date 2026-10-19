#!/usr/bin/env python3
"""Screen public Bailian arrivals against an optimistic single P/D NIC cut."""

import json
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "workloads/qwen_bailian_raw"
OUT = Path(__file__).with_suffix(".json")
MODEL = Path(__file__).resolve().parents[2] / "configs/model/Qwen/Qwen3-32B.json"
WINDOWS = (0.2, 1.0)
LINK_GBPS = (100, 200)


def main():
    model = json.loads(MODEL.read_text())
    bytes_per_token = (2 * model["num_hidden_layers"] *
                       model["num_key_value_heads"] * model["head_dim"] * 2)
    result = {
        "model_assumed_for_sizing": "Qwen/Qwen3-32B BF16",
        "aggregate_kv_bytes_per_prompt_token": bytes_per_token,
        "assumptions": [
            "The released original Qwen model and physical topology are unknown.",
            "Every request's entire prompt KV crosses the same cut once.",
            "Decode has no prefix KV and no cache-aware placement is applied.",
            "Arrival-window byte sums are a load screen, not transfer schedules, TTFT, or gain.",
        ],
        "traces": {},
    }
    for trace in sorted(TRACES.glob("*.jsonl")):
        windows = {width: defaultdict(lambda: [0, 0]) for width in WINDOWS}
        count = 0
        input_tokens = 0
        last_time = 0
        within_profile = 0
        for line in trace.open():
            row = json.loads(line)
            count += 1
            input_tokens += row["input_length"]
            last_time = max(last_time, row["timestamp"])
            within_profile += row["input_length"] <= 16384
            for width, bins in windows.items():
                bucket = math.floor(row["timestamp"] / width)
                bins[bucket][0] += 1
                bins[bucket][1] += row["input_length"] * bytes_per_token
        data = {
            "requests": count,
            "seconds": last_time,
            "input_tokens": input_tokens,
            "within_16384_tokens": within_profile,
            "mean_full_kv_gbps_on_one_cut":
                input_tokens * bytes_per_token * 8 / last_time / 1e9,
            "windows": {},
        }
        for width, bins in windows.items():
            bucket_result = {}
            for gbps in LINK_GBPS:
                capacity = gbps * 1e9 / 8 * width
                overloaded = [value for value in bins.values() if value[1] > capacity]
                bucket_result[str(gbps)] = {
                    "buckets_exceeding_capacity": len(overloaded),
                    "requests_in_exceeding_buckets": sum(value[0] for value in overloaded),
                    "fraction_of_requests_in_exceeding_buckets":
                        sum(value[0] for value in overloaded) / count,
                    "maximum_overload_bytes":
                        max((value[1] - capacity for value in overloaded), default=0),
                }
            data["windows"][str(width)] = bucket_result
        result["traces"][trace.stem] = data
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
