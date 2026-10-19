#!/usr/bin/env python3
"""Derive the smallest normal-capacity P-hit/D-eviction test."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MODEL = ROOT / "configs/model/meta-llama/Llama-3.1-8B.json"
PROFILE = ROOT / "profiler/perf/RTX4090/meta-llama/Llama-3.1-8B/bf16/meta.yaml"
POOL_BLOCKS = 3400
BLOCK_TOKENS = 16
PREFIX_TOKENS = 1984
PROMPT_TOKENS = 2048
SOURCES = 2
LINK_GBPS = 100


def main():
    config = json.loads(MODEL.read_text())
    head_dim = config.get("head_dim", config["hidden_size"] //
                          config["num_attention_heads"])
    kv_per_token = (2 * config["num_hidden_layers"] *
                    config["num_key_value_heads"] * head_dim * 2)
    prefix_blocks = PREFIX_TOKENS // BLOCK_TOKENS
    filler_blocks = PROMPT_TOKENS // BLOCK_TOKENS
    first_overflow_fillers = ((POOL_BLOCKS - SOURCES * prefix_blocks) //
                              filler_blocks + 1)
    result = {
        "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
        "kv_bytes_per_token": kv_per_token,
        "full_kv_bytes_per_request": PROMPT_TOKENS * kv_per_token,
        "delta_kv_bytes_per_request": (PROMPT_TOKENS - PREFIX_TOKENS) *
                                      kv_per_token,
        "pool_blocks": POOL_BLOCKS,
        "prefix_blocks_per_key": prefix_blocks,
        "filler_blocks_per_request": filler_blocks,
        "first_overflow_filler_count": first_overflow_fillers,
        "negative_fillers": 24,
        "positive_fillers": 28,
        "negative_total_blocks": SOURCES * prefix_blocks + 24 * filler_blocks,
        "positive_total_blocks": SOURCES * prefix_blocks + 28 * filler_blocks,
        "maximum_blocks_per_prefill_gpu": prefix_blocks + 14 * filler_blocks,
        "full_two_request_cut_floor_ns": round(
            SOURCES * PROMPT_TOKENS * kv_per_token * 8 / LINK_GBPS),
        "delta_two_request_cut_floor_ns": round(
            SOURCES * (PROMPT_TOKENS - PREFIX_TOKENS) * kv_per_token * 8 /
            LINK_GBPS),
        "prior_profile_cold_prefill_ns": 193_161_000,
        "prior_profile_hot_prefill_ns": 20_969_000,
        "predicted_ready_ns_if_miss": 42_949_673,
        "predicted_ready_ns_if_hit": 20_969_000,
        "assumption": "Two distinct cached prefixes, one D and two P GPUs; all filler jobs finish before targets. The D pool is the normal 24-GB/0.9 configuration, not an artificial cap.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
