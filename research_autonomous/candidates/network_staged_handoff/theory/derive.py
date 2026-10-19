#!/usr/bin/env python3
"""Measured-profile bounds for a network-staged P/D handoff candidate."""

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
PROFILE = ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-32B/bf16/tp2"
MODEL_PATH = ROOT / "configs/model/Qwen/Qwen3-32B.json"
PRIOR_PATH = ROOT / "research_autonomous/theory/round11_qwen32b.json"
OUT = Path(__file__).with_suffix(".json")
PROMPT = 2048
OUTPUT = 600
NIC_GBPS_PER_RAIL = 200


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    model = json.loads(MODEL_PATH.read_text())
    prior = json.loads(PRIOR_PATH.read_text())
    dense_rows = list(csv.DictReader((PROFILE / "dense.csv").open()))
    attention_rows = list(csv.DictReader((PROFILE / "attention.csv").open()))
    layer_names = ("layernorm", "qkv_proj", "qk_norm", "rotary_emb",
                   "o_proj", "layernorm", "gate_up_proj", "act_fn",
                   "down_proj")
    dense_2048 = {row["layer"]: float(row["time_us"])
                  for row in dense_rows if int(row["tokens"]) == PROMPT}
    block_us = sum(dense_2048[name] for name in layer_names)
    attn = [float(row["time_us"]) for row in attention_rows
            if (int(row["prefill_chunk"]) == PROMPT and
                int(row["kv_prefill"]) == 0 and
                int(row["n_decode"]) == 0 and
                int(row["kv_decode"]) == 0)]
    assert len(attn) == 1
    block_us += attn[0]
    kv_bytes = (PROMPT * model["num_hidden_layers"] * 2 *
                model["num_key_value_heads"] * model["head_dim"] * 2)
    per_rank = kv_bytes // 2
    transfer_ms = per_rank * 8 / (NIC_GBPS_PER_RAIL * 1e9) * 1000
    memory = prior["decode_memory_and_rate"]
    p_rps = memory["optimistic_one_prefill_instance_requests_per_s"]
    d_rps = memory["optimistic_decode_requests_per_s_at_600_output_tokens"]
    ready_ms = 184.907
    result = {
        "inputs": {"model_sha256": sha(MODEL_PATH),
                   "profile_dense_sha256": sha(PROFILE / "dense.csv"),
                   "profile_attention_sha256": sha(PROFILE / "attention.csv"),
                   "prior_theory_sha256": sha(PRIOR_PATH)},
        "classification": {"model_profile": "A: measured vLLM TP2 profile",
                           "kv_size": "A: exact model config",
                           "network_and_output": "C: 200 Gb/s per rail, 600 output tokens",
                           "ready_barrier": "A: prior integrated FlowSim run"},
        "model": "Qwen/Qwen3-32B BF16 TP2 PP1",
        "prompt_tokens": PROMPT,
        "output_tokens": OUTPUT,
        "kv_total_bytes_per_request": kv_bytes,
        "kv_bytes_per_rank": per_rank,
        "physical_cut": "two independent 200 Gb/s receiver rails, one shard each",
        "full_kv_serialization_ms_per_rail": transfer_ms,
        "measured_prefill_block_us": block_us,
        "one_to_four_source_layer_service_us": [
            n * (per_rank / model["num_hidden_layers"]) * 8 /
            (NIC_GBPS_PER_RAIL * 1e9) * 1e6 for n in (1, 2, 3, 4)],
        "four_source_ready_ms_existing_run": ready_ms,
        "four_source_last_flow_to_ready_slack_ms_existing_run": 2.453,
        "cold_isolated_zero_transfer_fraction_ceiling":
            transfer_ms / (ready_ms + transfer_ms),
        "optimistic_p_rps": p_rps,
        "optimistic_d_rps_at_batch128": d_rps,
        "steady_bottleneck_one_p_one_d": "Decode" if d_rps < p_rps else "Prefill",
        "capacity_after_128_running_tokens":
            memory["capacity_after_128_running_2048_plus_600_token_sequences"],
        "additional_full_prompt_handoffs_before_d_pool_full":
            memory["additional_2048_token_handoff_slots_before_pool_full"],
        "conditional_fill_time_s_after_128_running_at_one_p_one_d_rate_gap":
            memory["additional_2048_token_handoff_slots_before_pool_full"] /
            (p_rps - d_rps),
        "baseline": "layerwise FAIR + capacity-aware FIFO admission and 1P2D resource-ratio control",
        "oracle": "zero handoff network service, with unchanged GPU and KV capacity",
        "gain_upper_cold_isolated": 0.0,
        "gain_upper_saturated": None,
        "status": "NO_GO for cold isolated network staging; saturated case needs causal backpressure and a matched burst",
        "falsifier": "if 1-4-source ready rises with transfer despite the measured 2.453-ms last-flow slack, re-audit DAG and topology",
        "limits": [
            "The isolated zero-transfer fraction is a loose serial ceiling; layerwise overlap makes the observed ready headroom zero.",
            "The fill time is conditional on already having 128 active sequences; it is not an observed trace interval.",
            "At pool exhaustion the current simulator frees source KV before Decode allocation and raises; no saturated Serving gain is credible.",
            "The 128-sequence Decode service estimate omits TP collective time and is optimistic.",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in (
        "kv_total_bytes_per_request", "full_kv_serialization_ms_per_rail",
        "measured_prefill_block_us", "gain_upper_cold_isolated",
        "additional_full_prompt_handoffs_before_d_pool_full", "status")}, indent=2))


if __name__ == "__main__":
    main()
