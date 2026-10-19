#!/usr/bin/env python3
"""Screen a documented 8x4090/one-100G node with measured Llama-8B kernels."""

import json
import math
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROMPT = 2048
NIC_GBPS = 100
FRESH_TOKENS = (64, 2048)


def main():
    from serving.core.trace_generator import (
        _load_perf_db, _lookup_attention, _lookup_dense,
        _lookup_per_sequence)

    os.chdir(ROOT / "astra-sim")
    perf = _load_perf_db("RTX4090", "meta-llama/Llama-3.1-8B",
                         "bf16", {1}, "llama")
    model = json.loads((ROOT / "configs/model/meta-llama/Llama-3.1-8B.json").read_text())
    kv_bytes = (PROMPT * model["num_hidden_layers"] * 2 *
                model["num_key_value_heads"] *
                model["hidden_size"] // model["num_attention_heads"] * 2)
    layer_bytes = kv_bytes // model["num_hidden_layers"]
    layer_service_us = layer_bytes * 8 / (NIC_GBPS * 1e9) * 1e6
    layers = ("layernorm", "qkv_proj", "rotary_emb", "o_proj",
              "layernorm", "gate_up_proj", "act_fn", "down_proj")
    cases = {}
    for fresh in FRESH_TOKENS:
        hit = PROMPT - fresh
        block_ns = sum(_lookup_dense(perf, name, 1, fresh)
                       for name in layers)
        block_ns += _lookup_attention(perf, 1, fresh, hit, 0, 0)
        prologue_ns = (
            _lookup_dense(perf, "embedding", 1, fresh) +
            _lookup_dense(perf, "final_layernorm", 1, fresh) +
            _lookup_per_sequence(perf, "lm_head", 1, 1) +
            _lookup_per_sequence(perf, "sampler", 1, 1))
        block_us = block_ns / 1000
        cases[str(fresh)] = {
            "source_prefix_hit_tokens": hit,
            "profiled_block_compute_us": block_us,
            "profiled_prefill_compute_ms_excluding_transport":
                (model["num_hidden_layers"] * block_ns + prologue_ns) / 1e6,
            "minimum_synchronous_sources_per_shared_nic_for_layer_service_to_exceed_block":
                math.floor(block_us / layer_service_us) + 1,
            "two_source_layer_serialization_us": 2 * layer_service_us,
            "two_source_per_layer_residual_serialization_us":
                max(0.0, 2 * layer_service_us - block_us),
        }
    decode_batch = 16
    decode_step_ns = sum(_lookup_dense(perf, name, 1, decode_batch)
                         for name in layers)
    decode_step_ns += _lookup_attention(
        perf, 1, 0, 0, decode_batch, PROMPT)
    decode_step_ns = model["num_hidden_layers"] * decode_step_ns
    decode_step_ns += _lookup_dense(perf, "embedding", 1, decode_batch)
    decode_step_ns += _lookup_dense(perf, "final_layernorm", 1, decode_batch)
    decode_step_ns += _lookup_per_sequence(perf, "lm_head", 1, decode_batch)
    decode_step_ns += _lookup_per_sequence(perf, "sampler", 1, decode_batch)
    decode_tokens_per_s = decode_batch * 1e9 / decode_step_ns
    result = {
        "hardware_evidence": "UBELIX documents 8x RTX4090 and one 100-Gbps InfiniBand interface per node",
        "hardware_url": "https://hpc-unibe-ch.github.io/hardware/gpu/",
        "model_profile": "RTX4090/meta-llama/Llama-3.1-8B/bf16/tp1",
        "prompt_tokens": PROMPT,
        "kv_bytes_per_request": kv_bytes,
        "kv_bytes_per_layer": layer_bytes,
        "one_layer_service_us_at_100gbps": layer_service_us,
        "cases_by_fresh_tokens": cases,
        "decode_capacity_control": {
            "batch": decode_batch,
            "step_ms": decode_step_ns / 1e6,
            "optimistic_tokens_per_s": decode_tokens_per_s,
            "optimistic_requests_per_s_for_64_output_tokens":
                decode_tokens_per_s / 64,
        },
        "condition": "After a strong destination-prefix suppression baseline, full KV remains only if Decode has no reusable prefix; the current default simulator sends full KV even when Decode is hot, and a Prefill hit does not prove a Decode miss",
        "strong_baselines": [
            "cache-aware Decode selection or local pairing",
            "pinned destination-prefix DELTA",
            "existing network priority and flow-size scheduling",
        ],
        "status": "THEORY_READY_NEED_CACHE_AND_PLACEMENT_EVIDENCE",
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
