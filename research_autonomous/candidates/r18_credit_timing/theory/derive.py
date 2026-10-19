#!/usr/bin/env python3
"""Profile-backed P/D capacity-credit and compute thresholds."""

import hashlib
import json
import os
from pathlib import Path

from serving.core import trace_generator as trace


ROOT = Path(__file__).resolve().parents[4]
MODEL = ROOT / "configs/model/meta-llama/Llama-3.1-8B.json"
PROFILE = ROOT / "profiler/perf/RTX4090/meta-llama/Llama-3.1-8B/bf16/meta.yaml"
POOL_BLOCKS = 3400
BLOCK_TOKENS = 16
P_COUNT = 4
LINK_GBPS = 100


def prefill_profile_ns(db, prompt_tokens):
    total = 0
    for prior in range(0, prompt_tokens, 2048):
        chunk = min(2048, prompt_tokens - prior)
        dense = lambda name: trace._lookup_dense(db, name, 1, chunk)
        one_block = (2 * dense("layernorm") + dense("qkv_proj") +
                     dense("rotary_emb") +
                     trace._lookup_attention(db, 1, chunk, prior, 0, 0) +
                     dense("o_proj") + dense("gate_up_proj") +
                     dense("act_fn") + dense("down_proj"))
        total += (dense("embedding") + 32 * one_block +
                  dense("final_layernorm") +
                  trace._lookup_per_sequence(db, "lm_head", 1, 1) +
                  trace._lookup_per_sequence(db, "sampler", 1, 1))
    return total


def decode_step_ns(db, n, kv_tokens):
    dense = lambda name: trace._lookup_dense(db, name, 1, n)
    one_block = (2 * dense("layernorm") + dense("qkv_proj") +
                 dense("rotary_emb") +
                 trace._lookup_attention(db, 1, 0, 0, n, kv_tokens) +
                 dense("o_proj") + dense("gate_up_proj") +
                 dense("act_fn") + dense("down_proj"))
    return (dense("embedding") + 32 * one_block +
            dense("final_layernorm") +
            trace._lookup_per_sequence(db, "lm_head", 1, n) +
            trace._lookup_per_sequence(db, "sampler", 1, n))


def main():
    config = json.loads(MODEL.read_text())
    head_dim = config.get("head_dim", config["hidden_size"] //
                          config["num_attention_heads"])
    kv_per_token = (2 * config["num_hidden_layers"] *
                    config["num_key_value_heads"] * head_dim * 2)
    cwd = Path.cwd()
    try:
        os.chdir(ROOT / "astra-sim")
        db = trace._load_perf_db("RTX4090", "meta-llama/Llama-3.1-8B",
                                 "bf16", {1}, "llama")
        cases = {}
        for length in (12000, 14000):
            blocks = (length + 1 + BLOCK_TOKENS - 1) // BLOCK_TOKENS
            cases[str(length)] = {
                "blocks_per_handoff_credit": blocks,
                "four_credits_blocks": P_COUNT * blocks,
                "four_credits_fit": P_COUNT * blocks <= POOL_BLOCKS,
                "prefill_profile_sum_ns": prefill_profile_ns(db, length),
                "decode_step_n3_profile_ns": decode_step_ns(db, 3, length),
                "decode_step_n4_profile_ns": decode_step_ns(db, 4, length),
                "kv_bytes_per_request": length * kv_per_token,
                "four_request_nic_floor_ns": round(
                    P_COUNT * length * kv_per_token * 8 / LINK_GBPS),
            }
    finally:
        os.chdir(cwd)
    result = {
        "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
        "pool_blocks": POOL_BLOCKS,
        "block_tokens": BLOCK_TOKENS,
        "prefill_gpu_count": P_COUNT,
        "decode_gpu_count": 1,
        "first_prompt_length_that_blocks_four_credits": 13600,
        "cases": cases,
        "assumption": "Four single-GPU Prefills share one100-Gb/s source NIC; one 24-GB/0.9 RTX4090 Decode has3400 blocks. A credit is acquired before Prefill and held until D completion. Profile sum excludes graph/network overhead and is a compute estimate, not an observed completion time.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
