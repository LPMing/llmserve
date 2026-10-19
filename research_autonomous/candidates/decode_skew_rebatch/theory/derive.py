#!/usr/bin/env python3
"""Bound skew-aware serial rebatching with measured alpha and GPU capacity."""

import csv
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from serving.core.memory_model import MemoryModel


PROFILE = ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-32B/bf16/tp2"
OUT = Path(__file__).with_suffix(".json")
BLOCK = ("layernorm", "qkv_proj", "qk_norm", "rotary_emb", "o_proj",
         "layernorm", "gate_up_proj", "act_fn", "down_proj")


def load(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def linear(table, x):
    xs = sorted(table)
    if x in table:
        return table[x]
    if not xs[0] <= x <= xs[-1]:
        raise ValueError("query outside measured axis")
    lo = max(value for value in xs if value < x)
    hi = min(value for value in xs if value > x)
    return table[lo] + (x - lo) * (table[hi] - table[lo]) / (hi - lo)


def main():
    dense = {}
    for row in load(PROFILE / "dense.csv"):
        dense.setdefault(row["layer"], {})[int(row["tokens"])] = float(row["time_us"])
    per = {}
    for row in load(PROFILE / "per_sequence.csv"):
        per.setdefault(row["layer"], {})[int(row["sequences"])] = float(row["time_us"])
    attention = {}
    for row in load(PROFILE / "attention.csv"):
        if int(row["prefill_chunk"]) or int(row["kv_prefill"]):
            continue
        attention[(int(row["n_decode"]), int(row["kv_decode"]))] = float(row["time_us"])
    n_axis = sorted(set(n for n, _ in attention))

    def attn(n, kv):
        n_lo = max(value for value in n_axis if value <= n)
        n_hi = min(value for value in n_axis if value >= n)
        for candidate in (n_lo, n_hi):
            if candidate == 0:
                raise ValueError("zero decode count is not a decode batch")
        def at_n(value):
            return linear({k: latency for (nn, k), latency in attention.items()
                           if nn == value}, kv)
        if n_lo == n_hi:
            return at_n(n_lo)
        return at_n(n_lo) + (n - n_lo) * (at_n(n_hi) - at_n(n_lo)) / (n_hi - n_lo)

    def dense_block(n):
        return sum(linear(dense[name], n) for name in BLOCK)

    def prologue(n):
        return (linear(dense["embedding"], n) +
                linear(dense["final_layernorm"], n) +
                linear(per["lm_head"], n) +
                linear(per["sampler"], n))

    def uniform_step(n, kv):
        return 64 * (dense_block(n) + attn(n, kv)) + prologue(n)

    memory = MemoryModel("Qwen/Qwen3-32B", 0, 0, 2, 2, 96, 512,
                         16, 16, False, False, None, None,
                         ep_size=1, pp_size=1,
                         npu_memory_utilization=0.9)
    capacity = memory.npu_pool.num_blocks * 16
    records = []
    excluded_memory = 0
    for row in load(PROFILE / "skew.csv"):
        if row["regime"] != "pure":
            continue
        n = int(row["n"])
        nb = int(row["nb"])
        small = int(row["kvs"])
        big = int(row["kv_big"])
        if n > 128:
            continue
        if nb * big + (n - nb) * small > capacity:
            excluded_memory += 1
            continue
        alpha = float(row["alpha"])
        mean = int(row["kv_mean"])
        t_mean = attn(n, mean)
        t_max = attn(n, big)
        skew_attention = t_mean + alpha * (t_max - t_mean)
        mixed = 64 * (dense_block(n) + skew_attention) + prologue(n)
        serial_split = uniform_step(n - nb, small) + uniform_step(nb, big)
        strong = min(mixed, serial_split)
        no_skew = 64 * (dense_block(n) + t_mean) + prologue(n)
        records.append({
            "n": n, "long_count": nb, "short_kv": small, "long_kv": big,
            "mean_kv": mean, "alpha": alpha,
            "mixed_step_ms": mixed / 1000,
            "serial_length_split_step_ms": serial_split / 1000,
            "zero_skew_step_ms": no_skew / 1000,
            "serial_split_gain": (mixed - serial_split) / mixed,
            "ideal_zero_skew_gain_over_strong":
                max(0.0, (strong - no_skew) / strong),
        })
    if not records:
        raise RuntimeError("no measured, memory-feasible skew rows")
    top = sorted(records, key=lambda row: row["serial_split_gain"], reverse=True)
    top_oracle = sorted(records,
                        key=lambda row: row["ideal_zero_skew_gain_over_strong"],
                        reverse=True)
    result = {
        "classification": {"latencies_and_alpha": "A: measured profile",
                           "GPU_memory": "A/C: model weights and configured 0.9 util",
                           "request_arrival_mix": "C: not present in profile"},
        "inputs_sha256": {str(path.relative_to(ROOT)):
                          hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (PROFILE / "dense.csv", PROFILE / "attention.csv",
                                       PROFILE / "per_sequence.csv", PROFILE / "skew.csv")},
        "gpu_kv_capacity_tokens_upper_bound": capacity,
        "profiled_pure_rows_feasible": len(records),
        "excluded_by_runtime_kv_capacity": excluded_memory,
        "max_serial_split_gain": top[0]["serial_split_gain"],
        "max_serial_split_case": top[0],
        "serial_split_rows_with_10pct_gain": sum(
            row["serial_split_gain"] >= 0.1 for row in records),
        "max_ideal_zero_skew_gain_over_strong":
            top_oracle[0]["ideal_zero_skew_gain_over_strong"],
        "max_ideal_zero_skew_case": top_oracle[0],
        "baseline": "best of ordinary mixed batch and serial length-bucket split",
        "oracle": "remove measured attention skew penalty without extra kernel or rebatched dense work",
        "status": "NO_GO for serial rebatching if max gain <10%; multi-D placement needs ordered workload evidence",
        "limits": [
            "Historical skew.csv t_mean/t_max/t_skew are sums of three attention timing samples; their alpha ratio is dimensionless, but the raw times are not per-layer latencies.",
            "The predicted skew latency uses that alpha with the separate uniform attention.csv, exactly as the simulator does.",
            "Attention and dense interpolation is linear within the measured grid; TP and scheduler overhead are omitted, favoring serial split.",
            "A GPU-memory upper bound filters impossible profile shots; actual activation/context reservations can only lower capacity.",
            "No arrival trace or per-request queue state is inferred from the profile.",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: result[key] for key in (
        "profiled_pure_rows_feasible", "excluded_by_runtime_kv_capacity",
        "max_serial_split_gain", "serial_split_rows_with_10pct_gain",
        "max_ideal_zero_skew_gain_over_strong", "status")}, indent=2))


if __name__ == "__main__":
    main()
