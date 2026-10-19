#!/usr/bin/env python3
"""Profile and memory bound for Qwen3-32B asymmetric P/D TP layouts."""

import csv
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from serving.core.memory_model import MemoryModel


BASE = ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-32B/bf16"
MODEL_PATH = ROOT / "configs/model/Qwen/Qwen3-32B.json"
OUT = Path(__file__).with_suffix(".json")
LAYER_NAMES = ("layernorm", "qkv_proj", "qk_norm", "rotary_emb",
               "o_proj", "layernorm", "gate_up_proj", "act_fn",
               "down_proj")


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def latency(tp, batch):
    folder = BASE / ("tp%d" % tp)
    dense = {row["layer"]: float(row["time_us"])
             for row in rows(folder / "dense.csv")
             if int(row["tokens"]) == batch}
    per = {row["layer"]: float(row["time_us"])
           for row in rows(folder / "per_sequence.csv")
           if int(row["sequences"]) == batch}
    attn = {int(row["n_decode"]): float(row["time_us"])
            for row in rows(folder / "attention.csv")
            if (int(row["prefill_chunk"]) == 0 and
                int(row["kv_prefill"]) == 0 and
                int(row["kv_decode"]) == 2048)}
    if batch in attn:
        attention = attn[batch]
    else:
        lo = max(n for n in attn if n < batch)
        hi = min(n for n in attn if n > batch)
        attention = attn[lo] + (batch - lo) * (attn[hi] - attn[lo]) / (hi - lo)
    block = sum(dense[name] for name in LAYER_NAMES) + attention
    return (64 * block + dense["embedding"] +
            dense["final_layernorm"] + per["lm_head"] +
            per["sampler"]) / 1000


def main():
    model = json.loads(MODEL_PATH.read_text())
    kv_total = (2048 * model["num_hidden_layers"] * 2 *
                model["num_key_value_heads"] * model["head_dim"] * 2)
    records = {}
    for tp in (1, 2):
        memory = MemoryModel("Qwen/Qwen3-32B", 0, 0, tp, tp, 96, 512,
                             16, 16, False, False, None, None,
                             ep_size=1, pp_size=1,
                             npu_memory_utilization=0.9)
        capacity = memory.npu_pool.num_blocks * 16
        feasible_max = capacity // (2048 + 600)
        batch = 36 if tp == 1 else 128
        step_ms = latency(tp, batch)
        records["tp%d" % tp] = {
            "weight_gib_per_gpu": memory.weight / 2**30,
            "kv_capacity_tokens_per_gpu_upper_bound": capacity,
            "max_2048_plus_600_sequences_by_kv": feasible_max,
            "profiled_feasible_batch": batch,
            "decode_step_ms": step_ms,
            "decode_tokens_per_s_per_instance": batch * 1000 / step_ms,
            "decode_tokens_per_s_per_gpu": batch * 1000 / step_ms / tp,
            "kv_bytes_per_source_rank": kv_total // tp,
            "one_200g_source_rail_serialization_ms":
                kv_total // tp * 8 / 200e9 * 1000,
        }
    optimistic_tp1 = 40 * 1000 / latency(1, 40)
    result = {
        "classification": {"model_profile_and_memory": "A",
                           "2048_input_600_output_two_200g_rails": "C"},
        "inputs_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (MODEL_PATH, *(BASE / ("tp%d" % tp) / name
                                       for tp in (1, 2)
                                       for name in ("dense.csv", "attention.csv",
                                                    "per_sequence.csv")))},
        "kv_total_bytes_per_request": kv_total,
        "per_layout": records,
        "optimistic_tp1_batch40_tokens_per_s_per_gpu": optimistic_tp1,
        "tp2_to_two_tp1_decode_throughput_ratio_upper_bound":
            2 * optimistic_tp1 /
            records["tp2"]["decode_tokens_per_s_per_instance"],
        "baseline": "best same-TP2 2P:2D role allocation and topology-aware pairing",
        "oracle": "choose TP1 or TP2 independently per phase without repartition cost",
        "gain_upper_for_decode_throughput": 0.0,
        "status": "NO_GO in the measured 2048/600 memory-feasible envelope",
        "limits": [
            "TP1 batch40 is itself above the KV-feasible 39-sequence bound, so its throughput is an intentionally optimistic TP1 upper screen.",
            "All profile values omit TP collective service; a new mixed-TP claim needs calibrated local communication and weight-memory validation.",
            "This excludes only this long-output Qwen3-32B deployment shape, not every heterogeneous P/D cluster.",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"tp1": records["tp1"], "tp2": records["tp2"],
                      "optimistic_two_tp1_vs_tp2_ratio": result[
                          "tp2_to_two_tp1_decode_throughput_ratio_upper_bound"]},
                     indent=2))


if __name__ == "__main__":
    main()
