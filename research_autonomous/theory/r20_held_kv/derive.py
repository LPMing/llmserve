#!/usr/bin/env python3
"""Exact Qwen3-32B TP2 KV/memory/cut threshold for held-source research."""

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from serving.core.memory_model import MemoryModel


MODEL = ROOT / "configs/model/Qwen/Qwen3-32B.json"
PROFILE = ROOT / "research_autonomous/theory/round11_qwen32b.json"
TRACE_MANIFEST = ROOT / "research_autonomous/workloads/swissai_raw/manifest.json"
SUMMARY = ROOT / "research_autonomous/workloads/swissai_analysis/summary.json"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    model = json.loads(MODEL.read_text())
    profile_screen = json.loads(PROFILE.read_text())
    memory = MemoryModel(
        "Qwen/Qwen3-32B", 0, 0, 2, 2, 96, 512, 16, 16,
        False, False, None, None, ep_size=1, pp_size=1,
        npu_memory_utilization=0.9)
    bytes_per_token_all_ranks = (
        model["num_hidden_layers"] * 2 * model["num_key_value_heads"] *
        model["head_dim"] * 2)
    bytes_per_token_rank = bytes_per_token_all_ranks // 2
    assert bytes_per_token_rank == memory.get_kv(1)
    assert bytes_per_token_all_ranks == 262144
    capacity = memory.npu_pool.num_blocks
    scenarios = {}
    for prompt in (128, 512, 1024, 2048, 4096, 8192, 16384):
        blocks = math.ceil((prompt + 1) / 16)
        rank_bytes = prompt * bytes_per_token_rank
        scenarios[str(prompt)] = {
            "required_blocks_including_first_decode_slot": blocks,
            "aggregate_kv_bytes": prompt * bytes_per_token_all_ranks,
            "per_rank_kv_bytes": rank_bytes,
            "simultaneous_held_requests_to_exceed_one_p_pool":
                capacity // blocks + 1,
            "per_rank_cut_floor_ms_at_200_gbps": rank_bytes / 25e9 * 1e3,
            "per_rank_cut_floor_ms_at_100_gbps": rank_bytes / 12.5e9 * 1e3,
        }
    result = {
        "status": "THEORY_THRESHOLD_ONLY",
        "parameter_classes": {
            "A": "local Qwen3-32B model and RTXPRO6000 TP2 profile, normal simulator 0.9 KV pool; pinned SwissAI raw trace if mined",
            "B": "No measured production NIC or P/D role mapping is available",
            "C": "200-Gb/s per-rank rail and 4P1D placement of SwissAI arrivals; neither is a measured production topology",
        },
        "model_sha256": sha256(MODEL),
        "profile_screen_sha256": sha256(PROFILE),
        "swissai_raw_manifest_sha256": sha256(TRACE_MANIFEST),
        "weight_gib_per_tp_rank": memory.weight / 2**30,
        "kv_bytes_per_prompt_token_all_ranks": bytes_per_token_all_ranks,
        "kv_bytes_per_prompt_token_per_rank": bytes_per_token_rank,
        "kv_pool_blocks_per_tp_rank": capacity,
        "kv_pool_tokens_per_tp_rank": capacity * 16,
        "scenarios": scenarios,
        "measured_2048_prefill_compute_ms_excluding_tp_collectives":
            profile_screen["layerwise_receiver_cut"][
                "measured_prefill_compute_ms_excluding_tp_collectives"],
        "profiled_2048_layerwise_cut_service_ms":
            profile_screen["layerwise_receiver_cut"][
                "single_source_full_shard_serialization_ms"],
        "qualifiers": [
            "KV pool excludes activation peak and CUDA context and is an upper capacity bound.",
            "A physical P/D topology and actual cache residence are not in SwissAI.",
            "A memory threshold is necessary, not sufficient for an exposed critical path or policy gain.",
            "Two-stage simulator currently supports TP1 only; a TP2 experiment needs a byte/path-conserving extension.",
        ],
    }
    if SUMMARY.exists():
        summary = json.loads(SUMMARY.read_text())
        result["swissai_summary_sha256"] = sha256(SUMMARY)
        result["swissai_counts"] = summary.get("counts", {})
        result["swissai_peak_arrival_200ms"] = summary.get("arrival_200ms", {})
        result["swissai_peak_arrival_1s"] = summary.get("arrival_1s", {})
        result["swissai_prefix_signal"] = {
            "same_day_completed_input_prefix_tokens_p50_p95_p99":
                summary.get("same_day_completed_input_prefix_tokens_p50_p95_p99"),
            "same_day_completed_input_prefix_ratio_p50_p95_p99":
                summary.get("same_day_completed_input_prefix_ratio_p50_p95_p99"),
        }
    target = HERE / "derive.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
