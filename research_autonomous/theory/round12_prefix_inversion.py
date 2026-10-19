#!/usr/bin/env python3
"""Pre-register the prefix-hit shared-NIC phase-transition screen."""

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROMPT = 2048
HITS = (0, 1024, 1536, 1792, 1920, 1984)
SOURCES = (1, 2, 4, 8)
NIC_BPS = 100e9


def main():
    from serving.core.trace_generator import (
        _load_perf_db, _lookup_attention, _lookup_dense)

    os.chdir(ROOT / "astra-sim")
    perf = _load_perf_db("RTX4090", "meta-llama/Llama-3.1-8B",
                         "bf16", {1}, "llama")
    model = json.loads((ROOT / "configs/model/meta-llama/Llama-3.1-8B.json")
                       .read_text())
    head_dim = model.get("head_dim", model["hidden_size"] //
                         model["num_attention_heads"])
    bytes_per_token_layer = (2 * model["num_key_value_heads"] *
                             head_dim * 2)
    full_layer_bytes = PROMPT * bytes_per_token_layer
    service_us = full_layer_bytes * 8 / NIC_BPS * 1e6
    sequence = ("layernorm", "qkv_proj", "rotary_emb", "o_proj",
                "layernorm", "gate_up_proj", "act_fn", "down_proj")
    rows = []
    for hit in HITS:
        fresh = PROMPT - hit
        block_ns = sum(_lookup_dense(perf, name, 1, fresh)
                       for name in sequence)
        block_ns += _lookup_attention(perf, 1, fresh, hit, 0, 0)
        block_us = block_ns / 1000
        for m in SOURCES:
            serialized_us = m * service_us
            rows.append({
                "sources": m,
                "prefix_hit_tokens": hit,
                "prefix_hit_fraction": hit / PROMPT,
                "fresh_tokens": fresh,
                "profiled_block_compute_us": block_us,
                "full_kv_bytes_per_request": (
                    full_layer_bytes * model["num_hidden_layers"]),
                "full_kv_source_nic_service_us_per_layer": serialized_us,
                "source_cut_ratio": serialized_us / block_us,
                "approx_layerwise_residual_ms": (
                    model["num_hidden_layers"] *
                    max(0, serialized_us - block_us) / 1000),
                "destination_prefix_delta_bytes_per_request": (
                    fresh * bytes_per_token_layer *
                    model["num_hidden_layers"]),
                "delta_source_cut_ratio": (
                    serialized_us * fresh / PROMPT / block_us),
            })
    result = {
        "status": "PRE_REGISTERED_SCREEN_NOT_SIMULATOR_RESULT",
        "model_profile": "RTX4090/meta-llama/Llama-3.1-8B/bf16/tp1",
        "physical_placement": "one 100G source NIC shared by 1/2/4/8 Prefill GPUs; targets split across two 100G Decode nodes",
        "hardware_anchor": "https://hpc-unibe-ch.github.io/hardware/gpu/",
        "prediction_scope": (
            "Synchronous full-KV source-cut service versus profiled layer "
            "compute. The residual is a fluid workload-screen estimate, "
            "not an exact P2D-ready bound or achieved improvement."),
        "rows": rows,
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("wrote", target)
    for row in rows:
        if row["sources"] in (2, 8):
            print(row["sources"], row["prefix_hit_tokens"],
                  "compute_us", round(row["profiled_block_compute_us"], 3),
                  "ratio", round(row["source_cut_ratio"], 3))


if __name__ == "__main__":
    main()
