#!/usr/bin/env python3
"""Screen a source-backed Llama ShareGPT window before a C policy run."""

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
WORKLOAD = ROOT / "workloads/sharegpt-llama-3.1-8b-300-sps10.jsonl"
PROFILE = ROOT / "profiler/perf/RTX4090/meta-llama/Llama-3.1-8B/bf16/tp1"
MODEL = ROOT / "configs/model/meta-llama/Llama-3.1-8B.json"
CUT_BYTES_PER_SECOND = 12_500_000_000
KV_BYTES_PER_TOKEN = 131_072


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rows = [json.loads(line) for line in WORKLOAD.open()][:50]
    if len(rows) != 50:
        raise ValueError("expected 50 ordered requests")
    minima = {}
    for name in ("dense.csv", "per_sequence.csv"):
        with (PROFILE / name).open() as stream:
            for point in csv.DictReader(stream):
                key = point["layer"]
                minima[key] = min(minima.get(key, float("inf")),
                                  float(point["time_us"]))
    with (PROFILE / "attention.csv").open() as stream:
        attention_min = min(float(point["time_us"])
                            for point in csv.DictReader(stream)
                            if int(point["prefill_chunk"]) == 0 and
                            int(point["n_decode"]) >= 1)
    block_sequence = (
        "layernorm", "qkv_proj", "rotary_emb", "o_proj",
        "layernorm", "gate_up_proj", "act_fn", "down_proj")
    per_block_us = sum(minima[name] for name in block_sequence) + attention_min
    layers = int(json.loads(MODEL.read_text())["num_hidden_layers"])
    decode_step_us = (minima["embedding"] + layers * per_block_us +
                      minima["final_layernorm"] + minima["lm_head"] +
                      minima["sampler"])
    prompt_tokens = sum(int(row["input_toks"]) for row in rows)
    last = rows[-1]
    last_decode_steps = int(last["output_toks"]) - 1
    earliest_last_completion_s = (int(last["arrival_time_ns"]) / 1e9 +
                                  last_decode_steps * decode_step_us / 1e6)
    full_transfer_floor_s = (prompt_tokens * KV_BYTES_PER_TOKEN /
                             CUT_BYTES_PER_SECOND)
    result = {
        "status": "THEORY_SCREEN_ONLY",
        "workload_sha256": digest(WORKLOAD),
        "model_sha256": digest(MODEL),
        "num_hidden_layers": layers,
        "profile_sha256": {name: digest(PROFILE / name) for name in (
            "dense.csv", "per_sequence.csv", "attention.csv")},
        "source_rows": 50,
        "prompt_tokens": prompt_tokens,
        "full_kv_bytes_upper_before_prefix_delta": prompt_tokens * KV_BYTES_PER_TOKEN,
        "full_transfer_cut_floor_s": full_transfer_floor_s,
        "first_arrival_s": int(rows[0]["arrival_time_ns"]) / 1e9,
        "last_arrival_s": int(last["arrival_time_ns"]) / 1e9,
        "last_output_tokens": int(last["output_toks"]),
        "min_profiled_decode_step_ms": decode_step_us / 1000,
        "last_request_unavoidable_decode_s": last_decode_steps * decode_step_us / 1e6,
        "earliest_last_completion_s": earliest_last_completion_s,
        "cut_time_over_earliest_last_completion_fraction": (
            full_transfer_floor_s / earliest_last_completion_s),
        "qualification": (
            "The ratio screens a fixed-work network-only change. It is not "
            "a global upper bound when network decisions change Decode "
            "batching, memory pressure or request order."),
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
