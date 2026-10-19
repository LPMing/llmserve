#!/usr/bin/env python3
"""Audit the branch-placement headroom claimed by the supplied P0 memo.

This reproduces its stated Qwen3 N=4 formula exactly. It is a theory gate,
not an integrated simulation or an online scheduler result.
"""

import csv
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODEL_CONFIG = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
MODEL = json.loads(MODEL_CONFIG.read_text())
PROMPT_TOKENS = 4105
KV_BYTES = (2 * MODEL["num_hidden_layers"] * MODEL["num_key_value_heads"]
            * MODEL.get("head_dim", MODEL["hidden_size"] // MODEL["num_attention_heads"])
            * 2 * PROMPT_TOKENS)
assert KV_BYTES == 403_537_920, "Qwen model parameters or prompt length changed"
EGRESS_BYTES_PER_SECOND = 50_000_000_000
DECODE_STEP_MS = {1: 4.698, 2: 9.256, 4: 14.395}
PREFILL_MS = {"prefix_hit_proxy": 27.068, "full_prefill_proxy": 162.780}
OUTPUT_STEPS = tuple(range(1, 65))


def group_completion_ms(prefill_ms, replicas, output_steps):
    network_ms = 1000.0 * replicas * KV_BYTES / EGRESS_BYTES_PER_SECOND
    return prefill_ms + network_ms + output_steps * DECODE_STEP_MS[4 // replicas]


def main():
    rows = []
    for case, prefill_ms in PREFILL_MS.items():
        for output_steps in OUTPUT_STEPS:
            costs = {
                k: group_completion_ms(prefill_ms, k, output_steps)
                for k in (1, 2, 4)
            }
            strong_static_envelope = min(costs[1], costs[4])
            best_k = min(costs, key=costs.get)
            rows.append({
                "case": case,
                "output_steps": output_steps,
                "one_decode_ms": f"{costs[1]:.6f}",
                "two_decode_ms": f"{costs[2]:.6f}",
                "four_decode_ms": f"{costs[4]:.6f}",
                "best_k": best_k,
                "strong_static_envelope_ms": f"{strong_static_envelope:.6f}",
                "optimal_ms": f"{costs[best_k]:.6f}",
                "gain_over_one_decode_pct": f"{100 * (1 - costs[best_k] / costs[1]):.6f}",
                "gain_over_static_envelope_pct":
                    f"{100 * (1 - costs[best_k] / strong_static_envelope):.6f}",
            })

    output = HERE / "theory_gate.csv"
    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    for case in PREFILL_MS:
        candidates = [row for row in rows if row["case"] == case]
        best_incremental = max(
            candidates,
            key=lambda row: float(row["gain_over_static_envelope_pct"]),
        )
        print(
            case,
            "max incremental gain over best of one-D/equal-four-D =",
            best_incremental["gain_over_static_envelope_pct"],
            "percent at O =",
            best_incremental["output_steps"],
        )


if __name__ == "__main__":
    main()
