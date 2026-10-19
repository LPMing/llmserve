#!/usr/bin/env python3
"""Profile-bound theory screens for three Qwen3-32B network/Serving ideas."""

import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from serving.core.memory_model import MemoryModel


PERF = ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-32B/bf16/tp2"
MODEL = json.loads((ROOT / "configs/model/Qwen/Qwen3-32B.json").read_text())
PROMPT = 2048
OUTPUT = 600
NIC_GBPS = 200
PREFILL_LAYERS = ("layernorm", "qkv_proj", "qk_norm", "rotary_emb",
                  "o_proj", "layernorm", "gate_up_proj", "act_fn",
                  "down_proj")


def exact(file_name, **query):
    with (PERF / file_name).open(newline="") as source:
        values = [float(row["time_us"]) for row in csv.DictReader(source)
                  if all(row[key] == str(value)
                         for key, value in query.items())]
    if len(values) != 1:
        raise ValueError("expected one measured profile row for %s %s" %
                         (file_name, query))
    return values[0]


def main():
    layers = MODEL["num_hidden_layers"]
    kv_bytes_per_token = (layers * 2 * MODEL["num_key_value_heads"] *
                          MODEL["head_dim"] * 2)
    kv_bytes = PROMPT * kv_bytes_per_token
    block_us = sum(exact("dense.csv", layer=name, tokens=PROMPT)
                   for name in PREFILL_LAYERS)
    block_us += exact("attention.csv", prefill_chunk=PROMPT,
                      kv_prefill=0, n_decode=0, kv_decode=0)
    prologue_us = (exact("dense.csv", layer="embedding", tokens=PROMPT) +
                   exact("dense.csv", layer="final_layernorm", tokens=PROMPT) +
                   exact("per_sequence.csv", layer="lm_head", sequences=1) +
                   exact("per_sequence.csv", layer="sampler", sequences=1))
    prefill_compute_ms = (layers * block_us + prologue_us) / 1000
    per_layer_rail_bytes = kv_bytes // layers // 2
    per_layer_rail_service_us = (per_layer_rail_bytes * 8 /
                                 (NIC_GBPS * 1e9) * 1e6)
    decoded = 128
    decode_layers = sum(exact("dense.csv", layer=name, tokens=decoded)
                        for name in PREFILL_LAYERS)
    decode_layers += exact("attention.csv", prefill_chunk=0, kv_prefill=0,
                           n_decode=decoded, kv_decode=PROMPT)
    decode_us = layers * decode_layers
    decode_us += exact("dense.csv", layer="embedding", tokens=decoded)
    decode_us += exact("dense.csv", layer="final_layernorm", tokens=decoded)
    decode_us += exact("per_sequence.csv", layer="lm_head", sequences=decoded)
    decode_us += exact("per_sequence.csv", layer="sampler", sequences=decoded)
    memory = MemoryModel("Qwen/Qwen3-32B", 0, 0, 2, 2, 96, 512, 16,
                         16, False, False, None, None, ep_size=1,
                         pp_size=1, npu_memory_utilization=0.9)
    capacity_tokens = memory.npu_pool.num_blocks * 16
    tp_collective_bytes_per_rank = 2 * layers * decoded * MODEL["hidden_size"] * 2
    tp_collective_floor_ms = (tp_collective_bytes_per_rank * 8 /
                              (NIC_GBPS * 1e9) * 1000)
    result = {
        "classification": {
            "model_and_profile": "MEASURED local profile and config",
            "prompt_output_and_nic": "ASSUMED small scenario",
            "derived_thresholds": "ANALYTICAL",
        },
        "scenario": {
            "model": "Qwen/Qwen3-32B BF16",
            "hardware": "RTX PRO 6000 Blackwell Server Edition",
            "tp": 2, "pp": 1, "prompt_tokens": PROMPT,
            "assumed_output_tokens": OUTPUT, "nic_gbps_per_tp_rail": NIC_GBPS,
            "kv_bytes_per_prompt_token_aggregate": kv_bytes_per_token,
            "kv_bytes_per_request_aggregate": kv_bytes,
        },
        "layerwise_receiver_cut": {
            "measured_prefill_block_compute_us_excluding_tp_collectives": block_us,
            "measured_prefill_compute_ms_excluding_tp_collectives": prefill_compute_ms,
            "kv_bytes_per_layer_per_tp_rail": per_layer_rail_bytes,
            "one_source_layer_service_us_at_200gbps": per_layer_rail_service_us,
            "minimum_synchronous_sources_on_one_receiver_to_exceed_one_block_compute_floor":
                math.floor(block_us / per_layer_rail_service_us) + 1,
            "four_source_layer_service_us": 4 * per_layer_rail_service_us,
            "four_source_per_layer_residual_lower_bound_us":
                max(0.0, 4 * per_layer_rail_service_us - block_us),
            "single_source_full_shard_serialization_ms":
                kv_bytes / 2 * 8 / (NIC_GBPS * 1e9) * 1000,
        },
        "decode_memory_and_rate": {
            "rank_model_weight_gib": memory.weight / 2**30,
            "rank_kv_capacity_tokens_upper_bound": capacity_tokens,
            "full_128_seq_capacity_output_threshold_tokens":
                capacity_tokens / decoded - PROMPT,
            "capacity_after_128_running_2048_plus_600_token_sequences":
                capacity_tokens - decoded * (PROMPT + OUTPUT),
            "additional_2048_token_handoff_slots_before_pool_full":
                (capacity_tokens - decoded * (PROMPT + OUTPUT)) // PROMPT,
            "decode_step_ms_excluding_tp_collectives": decode_us / 1000,
            "optimistic_decode_tokens_per_s": decoded * 1e6 / decode_us,
            "optimistic_decode_requests_per_s_at_600_output_tokens":
                decoded * 1e6 / decode_us / OUTPUT,
            "optimistic_one_prefill_instance_requests_per_s":
                1000 / prefill_compute_ms,
        },
        "cross_node_tp_cut": {
            "one_rank_tp_allreduce_payload_bytes_per_decode_step":
                tp_collective_bytes_per_rank,
            "one_rank_serialization_floor_ms_at_200gbps":
                tp_collective_floor_ms,
            "ideal_removal_latency_fraction_of_compute_plus_cut_floor":
                tp_collective_floor_ms / (tp_collective_floor_ms + decode_us / 1000),
            "caveat": "TP2 inside one GPU server uses local interconnect; this cross-node case needs deployment evidence",
        },
        "limits": [
            "Prefill and Decode profile times omit TP collective and graph scheduling cost.",
            "KV transfer serialization is a cut floor; completion and exposed stall require a causal DAG.",
            "The KV pool capacity omits activation peak and CUDA context and is an upper bound.",
            "No paper benefit or arrival rate is inferred from these optimistic figures.",
        ],
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
