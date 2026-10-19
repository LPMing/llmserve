#!/usr/bin/env python3
"""Compare the network, Decode-memory and compute thresholds jointly."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
A = ROOT / "research_autonomous/candidates/r18_prefix_retention/theory/derive.json"
B = ROOT / "research_autonomous/candidates/r18_credit_timing/theory/derive.json"


def main():
    a, b = json.loads(A.read_text()), json.loads(B.read_text())
    cases = {}
    for label, data in b["cases"].items():
        prefill_ns = data["prefill_profile_sum_ns"]
        nic_ns = data["four_request_nic_floor_ns"]
        decode_ns = 64 * data["decode_step_n4_profile_ns"]
        cases[label] = {
            "network_to_prefill_ratio": nic_ns / prefill_ns,
            "credit_to_pool_ratio": data["four_credits_blocks"] /
                                    b["pool_blocks"],
            "decode_64_token_profile_ns": decode_ns,
            "decode_to_prefill_ratio": decode_ns / prefill_ns,
            "first_binding_resource": (
                "Decode credit" if data["four_credits_blocks"] >
                b["pool_blocks"] else "no initial D capacity block"),
        }
    result = {
        "cases": cases,
        "two_hot_source_2048_network_to_prefill_ratio":
            a["full_two_request_cut_floor_ns"] /
            a["prior_profile_hot_prefill_ns"],
        "necessary_conditions": {
            "network_exposure": "source cut serialization minus profile-backed overlap slack must be positive at P2D-ready",
            "capacity_exposure": "sum of outstanding D credit blocks must exceed the physical pool while a useful P GPU or D GPU is idle",
            "decode_compute_exposure": "Decode arrival work exceeds sustainable batch token service or its queue delays the target event",
        },
        "oracle_constraint": "Any oracle must preserve four P GPUs, one D GPU, their normal KV pools, the same100-Gb/s cut, workload bytes and causal release times.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
