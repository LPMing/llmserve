#!/usr/bin/env python3
"""Compute a profile-matched 2048-token P2D layer-wave screening ratio."""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "configs/model/Qwen/Qwen3-32B.json"
PROFILE = (ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-32B/"
           "bf16/tp2")
OUTPUT = Path(__file__).resolve().parent / "chutes_qwen32b_network_gate.json"
TOKENS = 2048
LINK_BYTES_PER_SECOND = 200e9 / 8
BLOCK_LAYERS = ("layernorm", "qkv_proj", "qk_norm", "rotary_emb",
                "attention", "o_proj", "layernorm", "gate_up_proj",
                "act_fn", "down_proj")


def main():
    model = json.loads(MODEL.read_text())
    dense = {}
    with (PROFILE / "dense.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["tokens"]) == TOKENS:
                dense[row["layer"]] = float(row["time_us"])
    with (PROFILE / "attention.csv").open(newline="") as handle:
        attention = [float(row["time_us"]) for row in csv.DictReader(handle)
                     if (int(row["prefill_chunk"]) == TOKENS and
                         int(row["kv_prefill"]) == 0 and
                         int(row["n_decode"]) == 0)]
    if len(attention) != 1:
        raise ValueError("expected exactly one profiled first-chunk attention row")
    layers_us = [attention[0] if name == "attention" else dense[name]
                 for name in BLOCK_LAYERS]
    block_compute_ms = sum(layers_us) / 1000
    per_layer_bytes = (TOKENS * 2 * model["num_key_value_heads"] *
                       model["head_dim"] * 2)
    per_layer_wire_ms = per_layer_bytes / LINK_BYTES_PER_SECOND * 1000
    result = {
        "model": "Qwen/Qwen3-32B",
        "hardware_profile": "RTXPRO6000/bf16/tp2",
        "profile_condition": "2048-token first prefill chunk, no prior KV",
        "block_compute_ms_excluding_collectives": block_compute_ms,
        "per_layer_kv_bytes_aggregate_ranks": per_layer_bytes,
        "per_layer_wire_ms_single_200gbps_cut": per_layer_wire_ms,
        "compute_to_wire_ratio": block_compute_ms / per_layer_wire_ms,
        "conditional_prefill_cache_fraction_for_full_kv_wire_to_match_compute": (
            1 - per_layer_wire_ms / block_compute_ms),
        "minimum_identical_sources_to_exceed_block_compute_on_one_cut": (
            int(block_compute_ms // per_layer_wire_ms) + 1),
        "notes": ("This is a necessary pressure screen for a layerwise "
                  "P2D baseline with one shared 200-Gbps cut. Compute omits "
                  "collectives and control overhead, so real inter-wave "
                  "slack can be larger. It is not a simulated TTFT or "
                  "proof that concurrent sources share one physical cut. "
                  "The cache-fraction threshold assumes a Prefill cache hit, "
                  "a cold Decode prefix, full KV retransmission, and compute "
                  "linear in fresh tokens; attention on long cached contexts "
                  "and a cache-aware Decode choice can defeat it."),
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
