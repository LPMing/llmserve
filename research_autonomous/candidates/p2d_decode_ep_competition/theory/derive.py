#!/usr/bin/env python3
"""Cut and latency screen for P2D traffic against active Decode EP."""

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MODEL_PATH = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
PROFILE_PATH = ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/meta.yaml"
PRIOR_PATH = ROOT / "research_joint/11_SERVING_INTEGRATED_COMPARISON.csv"
OUT = Path(__file__).with_suffix(".json")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    model = json.loads(MODEL_PATH.read_text())
    with PRIOR_PATH.open(newline="") as source:
        rows = {row["condition"] + ":" + row["group"]: row
                for row in csv.DictReader(source)}
    sync = rows["B2_SYNC_FAIR:A"]
    alone = rows["B0_GROUP_A_ONLY:A"]
    phased = rows["B3_PHASE20US:ALL"]
    kv_per_token = (model["num_hidden_layers"] * 2 *
                    model["num_key_value_heads"] *
                    model.get("head_dim", model["hidden_size"] //
                              model["num_attention_heads"]) * 2)
    prompt = 2048
    n = 4
    full_kv = kv_per_token * prompt
    rail = full_kv // 2
    cut_ms = n * rail * 8 / (200e9) * 1000
    sync_itl = float(sync["ITL_mean_ms"])
    alone_itl = float(alone["ITL_mean_ms"])
    phased_itl = float(phased["ITL_mean_ms"])
    result = {
        "inputs": {"model_sha256": sha(MODEL_PATH),
                   "profile_meta_sha256": sha(PROFILE_PATH),
                   "prior_integrated_csv_sha256": sha(PRIOR_PATH)},
        "classification": {"model_and_prior_measured_cohort": "A",
                           "same-cut_2048_new_wave": "C: candidate arrival pattern",
                           "link_rate": "A/C: existing 200 Gb/s configured physical cut"},
        "model": "Qwen3-30B-A3B BF16 TP2 EP4 PP1",
        "kv_bytes_per_2048_request": full_kv,
        "kv_bytes_per_tp_rank": rail,
        "four_request_one_rail_bytes": n * rail,
        "four_request_one_rail_serialization_ms": cut_ms,
        "per_layer_four_request_rail_serialization_us": cut_ms * 1000 /
        model["num_hidden_layers"],
        "prior_sync_itl_ms": sync_itl,
        "prior_isolated_itl_ms": alone_itl,
        "prior_phase_itl_ms": phased_itl,
        "prior_ep_only_cross_group_interference_ceiling_fraction":
            (sync_itl - alone_itl) / sync_itl,
        "prior_phase_gain_fraction": (sync_itl - phased_itl) / sync_itl,
        "prior_sync_ep_dispatch_bytes_per_group": int(sync["EP_dispatch_bytes"]),
        "prior_sync_ep_combine_bytes_per_group": int(sync["EP_combine_bytes"]),
        "prior_sync_kv_bytes_per_group": int(sync["KV_bytes"]),
        "baseline": "FAIR, EP_FIRST, topology-aware P/D pairing, and existing phase staggering",
        "oracle": "zero *additional* EP waiting from a new P2D wave, preserving EP and KV bytes",
        "gain_upper_new_wave": None,
        "status": "THEORY_READY_NEEDS_OVERLAP_EVENT; prior EP-only interference upper <1% does not bound a new KV-overlap wave",
        "falsifiable_prediction": "a 2048-token P wave released while D is active must share at least one directed cut interval with D EP and delay D token2/ITL under FAIR; EP_FIRST should recover most of it",
        "limits": [
            "The old synchronized run had initial P2D before Decode EP; its <1% ceiling applies only to EP-versus-EP interference.",
            "The 2048-token four-request cut time is a serialization bound, not exposed Decode delay.",
            "The integrated MoE collective is AG/RS with synthetic BALANCED routing, not measured sparse A2A.",
            "A staggered new wave requires provenance-backed arrival evidence before population SLO claims.",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in (
        "kv_bytes_per_2048_request", "four_request_one_rail_serialization_ms",
        "prior_ep_only_cross_group_interference_ceiling_fraction",
        "gain_upper_new_wave", "status")}, indent=2))


if __name__ == "__main__":
    main()
