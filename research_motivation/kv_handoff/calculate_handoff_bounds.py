#!/usr/bin/env python3
"""Calculate an ideal fixed-capacity request-handoff bound.

This is a network-only fluid bound, not a Serving latency prediction. The
resource grouping is deliberately explicit: the tested placement maps one
request to each of two TP ranks on the same 200-Gbps rail; the four-request
case has two independent rails with two requests on each rail.
"""

import argparse
import csv
import json
import math
from pathlib import Path


def calculate(model_path, output_path, input_tokens, tp_size, dtype_bytes,
              capacity_gbps, propagation_ns):
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    layers = int(model["num_hidden_layers"])
    kv_heads = int(model["num_key_value_heads"])
    head_dim = int(model.get(
        "head_dim", model["hidden_size"] // model["num_attention_heads"]))
    total_bytes = 2 * kv_heads * head_dim * dtype_bytes * layers * input_tokens
    shard_bytes = total_bytes / tp_size
    capacity_Bps = capacity_gbps * 1e9 / 8
    service_ns_per_request = math.ceil(total_bytes * 1e9 / capacity_Bps)

    # These are the actual endpoint-rail groups in the saved 1P2D placement.
    scenarios = ((1, (1,)), (2, (2,)), (4, (2, 2)))
    fields = [
        "request_count", "topology_resource_groups",
        "requests_per_resource_group", "per_request_kv_bytes",
        "tp_shard_bytes", "bottleneck_capacity_Bps",
        "path_propagation_ns", "ideal_simultaneous_release_fair_mean_handoff_ns",
        "ideal_simultaneous_release_grouped_mean_handoff_ns",
        "ideal_simultaneous_release_mean_gain_pct", "interpretation",
    ]
    rows = []
    for request_count, group_sizes in scenarios:
        fair_completions = []
        grouped_completions = []
        for group_size in group_sizes:
            fair_service_ns = math.ceil(
                total_bytes * group_size * 1e9 / capacity_Bps)
            fair_completions.extend(
                [fair_service_ns + propagation_ns]
                * group_size)
            grouped_completions.extend(
                rank * service_ns_per_request + propagation_ns
                for rank in range(1, group_size + 1))
        fair_mean = sum(fair_completions) / len(fair_completions)
        grouped_mean = sum(grouped_completions) / len(grouped_completions)
        gain = (100 * (fair_mean - grouped_mean) / fair_mean
                if fair_mean else 0)
        rows.append({
            "request_count": request_count,
            "topology_resource_groups": len(group_sizes),
            "requests_per_resource_group": ";".join(
                ",".join(str(i) for i in range(start, start + size))
                for start, size in _group_ranges(group_sizes)),
            "per_request_kv_bytes": int(total_bytes),
            "tp_shard_bytes": int(shard_bytes),
            "bottleneck_capacity_Bps": capacity_Bps,
            "path_propagation_ns": propagation_ns,
            "ideal_simultaneous_release_fair_mean_handoff_ns": fair_mean,
            "ideal_simultaneous_release_grouped_mean_handoff_ns": grouped_mean,
            "ideal_simultaneous_release_mean_gain_pct": gain,
            "interpretation": "simultaneous-release network-only upper bound; not serving prediction",
        })

    with Path(output_path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _group_ranges(group_sizes):
    start = 0
    for size in group_sizes:
        yield start, size
        start += size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-config", default=(
        "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--input-tokens", type=int, default=2048)
    parser.add_argument("--tp-size", type=int, default=2)
    parser.add_argument("--dtype-bytes", type=int, default=2)
    parser.add_argument("--capacity-gbps", type=float, default=200.0)
    parser.add_argument("--propagation-ns", type=float, default=10200.0)
    args = parser.parse_args()
    calculate(args.model_config, args.output, args.input_tokens, args.tp_size,
              args.dtype_bytes, args.capacity_gbps, args.propagation_ns)


if __name__ == "__main__":
    main()
