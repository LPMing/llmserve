#!/usr/bin/env python3
"""Size a Qwen3-32B Decode pool before testing a shared P/D network cut."""

import json
import math
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "research_autonomous/workloads/swissai_analysis/summary.json"
OUTPUT = Path(__file__).with_suffix(".json")
MODEL = ROOT / "configs/model/Qwen/Qwen3-32B.json"
BLOCK = ("layernorm", "qkv_proj", "qk_norm", "rotary_emb", "attention",
         "o_proj", "layernorm", "gate_up_proj", "act_fn", "down_proj")


def main():
    if not SOURCE.exists():
        raise FileNotFoundError("run mine_swissai.py before this capacity gate")
    summary = json.loads(SOURCE.read_text())
    model = json.loads(MODEL.read_text())
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT / "astra-sim")
    from serving.core.trace_generator import (
        _load_perf_db, _lookup_attention, _lookup_dense, _lookup_per_sequence)

    perf = _load_perf_db("RTXPRO6000", "Qwen/Qwen3-32B", "bf16", {2}, "qwen3")
    count = summary["counts"]["rows"]
    mean_input = summary["counts"]["effective_input_tokens"] / count
    mean_output = (summary["counts"]["reported_output_tokens"] /
                   summary["counts"]["valid_reported_output_rows"])
    kv_len = mean_input
    bytes_per_token = (2 * model["num_hidden_layers"] *
                       model["num_key_value_heads"] * model["head_dim"] * 2)
    capacities = {}
    for n in (16, 32, 64, 128):
        layer_ns = sum(
            _lookup_attention(perf, 2, 0, 0, n, kv_len)
            if name == "attention" else _lookup_dense(perf, name, 2, n)
            for name in BLOCK)
        step_ns = (
            _lookup_dense(perf, "embedding", 2, n) +
            model["num_hidden_layers"] * layer_ns +
            _lookup_dense(perf, "final_layernorm", 2, n) +
            _lookup_per_sequence(perf, "lm_head", 2, n) +
            _lookup_per_sequence(perf, "sampler", 2, n))
        throughput = n * 1e9 / step_ns
        capacity_rps = throughput / mean_output
        per_receiver_full_kv_gbps = (
            capacity_rps * mean_input * bytes_per_token * 8 / 1e9)
        capacities[str(n)] = {
            "step_ms_excluding_collectives": step_ns / 1e6,
            "decode_tokens_per_second_excluding_collectives": throughput,
            "requests_per_second_at_mean_output_length": capacity_rps,
            "full_kv_gbps_per_receiver_at_this_request_rate":
                per_receiver_full_kv_gbps,
        }
    peak_output = summary["arrival_1s"]["peak_arriving_output_tokens"]
    peak_input = summary["arrival_1s"]["peak_arriving_input_tokens"]
    peak_60s_output = summary["peak_arriving_output_tokens_60s"]
    peak_300s_output = summary["peak_arriving_output_tokens_300s"]
    optimistic_tokens_per_instance = capacities["128"][
        "decode_tokens_per_second_excluding_collectives"]
    result = {
        "source": str(SOURCE.relative_to(ROOT)),
        "hardware_profile": "RTXPRO6000/Qwen/Qwen3-32B/bf16/tp2",
        "mean_input_tokens": mean_input,
        "mean_output_tokens": mean_output,
        "kv_bytes_per_prompt_token_aggregate": bytes_per_token,
        "mean_kv_length_used_for_profile_lookup": kv_len,
        "batch_capacity": capacities,
        "peak_one_second_arrival_count": summary["arrival_1s"]["peak_requests"],
        "peak_one_second_arriving_output_tokens": peak_output,
        "peak_one_second_arriving_input_tokens": peak_input,
        "peak_one_minute_arriving_output_tokens": peak_60s_output,
        "peak_five_minute_arriving_output_tokens": peak_300s_output,
        "optimistic_minimum_tp2_decode_instances_to_drain_peak_arriving_output_work_in_one_second":
            math.ceil(peak_output / optimistic_tokens_per_instance),
        "optimistic_minimum_tp2_decode_instances_to_drain_peak_one_minute_work_within_one_minute":
            math.ceil(peak_60s_output / 60 / optimistic_tokens_per_instance),
        "optimistic_minimum_tp2_decode_instances_to_drain_peak_five_minute_work_within_five_minutes":
            math.ceil(peak_300s_output / 300 / optimistic_tokens_per_instance),
        "one_cut_full_kv_gbps_for_peak_arriving_input_tokens":
            peak_input * bytes_per_token * 8 / 1e9,
        "notes": [
            "The source production platform used heterogeneous hardware and no P/D split.",
            "RTXPRO6000 TP2 is an explicit hypothetical deployment using a local measured profile.",
            "Throughput omits TP collectives, scheduling, queueing and hardware interference.",
            "A one-second sum of arriving output tokens is workload work, not output tokens emitted in that second.",
            "The instance count is an optimistic capacity-sizing screen, not a production deployment estimate.",
            "Full-KV wire demand assumes a cold Decode and no layerwise overlap or prefix delta.",
        ],
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
