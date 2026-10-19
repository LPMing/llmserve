#!/usr/bin/env python3
"""Profile-bound PP2 Qwen P2D receiver-cut theory screen.

The output is a lower-level fluid-service prediction, not a TTFT result.
"""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PERF = (ROOT / "profiler/perf/RTXPRO6000/Qwen/"
        "Qwen3-30B-A3B-Instruct-2507/bf16")
MODEL = json.loads((ROOT / "configs/model/Qwen/"
                    "Qwen3-30B-A3B-Instruct-2507.json").read_text())
PROMPT_TOKENS = 2048
TP = 2
PP = 2
SOURCES = (1, 2, 4, 8, 16)
NIC_GBPS = 200


def exact_row(path, **fields):
    with path.open(newline="") as stream:
        matches = [row for row in csv.DictReader(stream)
                   if all(row[key] == str(value) for key, value in fields.items())]
    if len(matches) != 1:
        raise ValueError("expected one measured row for %s: %s; found %d" %
                         (path, fields, len(matches)))
    return float(matches[0]["time_us"])


def main():
    layers = int(MODEL["num_hidden_layers"])
    assert layers == 48 and layers % PP == 0
    head_dim = MODEL.get("head_dim", MODEL["hidden_size"] //
                         MODEL["num_attention_heads"])
    kv_heads = int(MODEL["num_key_value_heads"])
    kv_bytes_per_token = 2 * layers * kv_heads * head_dim * 2
    per_layer_rank_bytes = kv_bytes_per_token * PROMPT_TOKENS // layers // TP
    assert per_layer_rank_bytes == 2_097_152
    dense_file = PERF / "tp2/dense.csv"
    dense_names = ("layernorm", "qkv_proj", "qk_norm", "rotary_emb",
                   "o_proj")
    dense_us = {name: exact_row(dense_file, layer=name, tokens=PROMPT_TOKENS)
                for name in dense_names}
    attention_us = exact_row(
        PERF / "tp2/attention.csv", prefill_chunk=PROMPT_TOKENS,
        kv_prefill=0, n_decode=0, kv_decode=0)
    moe_us = exact_row(PERF / "tp1/moe.csv", tokens=PROMPT_TOKENS,
                       activated_experts=128)
    block_us = (2 * dense_us["layernorm"] +
                sum(value for key, value in dense_us.items()
                    if key != "layernorm") + attention_us + moe_us)
    rail_bytes_per_second = NIC_GBPS * 1e9 / 8
    rows = []
    for sources in SOURCES:
        wave_bytes = sources * per_layer_rank_bytes
        wave_ms = wave_bytes / rail_bytes_per_second * 1000
        rows.append({
            "sources": sources,
            "prompt_tokens": PROMPT_TOKENS,
            "tp": TP,
            "pp": PP,
            "kv_total_bytes_per_request": kv_bytes_per_token * PROMPT_TOKENS,
            "kv_stage_bytes_per_request": kv_bytes_per_token * PROMPT_TOKENS // PP,
            "kv_layer_bytes_per_rank": per_layer_rank_bytes,
            "receiver_rail_wave_bytes": wave_bytes,
            "receiver_rail_service_ms": round(wave_ms, 6),
            "profile_block_compute_ms": round(block_us / 1000, 6),
            "wave_service_over_compute": round(wave_ms / (block_us / 1000), 6),
            "receiver_rail_total_bytes": sources *
                kv_bytes_per_token * PROMPT_TOKENS // TP,
            "receiver_rail_total_serialization_ms": round(
                sources * kv_bytes_per_token * PROMPT_TOKENS /
                TP / rail_bytes_per_second * 1000, 6),
        })
    with (HERE / "predictions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print("block_compute_ms=%.6f" % (block_us / 1000))
    for row in rows:
        print("m=%d rail_wave_ms=%.6f service/compute=%.3f" %
              (row["sources"], row["receiver_rail_service_ms"],
               row["wave_service_over_compute"]))


if __name__ == "__main__":
    main()
