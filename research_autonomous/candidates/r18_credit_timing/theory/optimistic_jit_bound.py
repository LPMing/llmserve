#!/usr/bin/env python3
"""Compute an optimistic two-stage handoff bound from frozen measured events.

This is a scheduling lower bound, not a simulated JIT protocol result.
"""

import csv
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CASE = HERE.parent / "experiments/prompt_14000"
TIMELINE = CASE / "timeline.csv"
ANALYSIS = CASE / "analysis.json"
SOURCE_CUT_BPS = 100_000_000_000


def main():
    rows = {int(row["request_id"]): {key: int(value)
            for key, value in row.items() if key != "request_id"}
            for row in csv.DictReader(TIMELINE.open())}
    analysis = json.loads(ANALYSIS.read_text())
    if analysis["status"] != "VALID" or set(rows) != set(range(4)):
        raise AssertionError("Frozen four-request case is invalid")
    if not all(rows[i]["prefill_start_ns"] == 0 for i in range(3)):
        raise AssertionError("First three Prefills must start together")
    fourth = rows[3]
    credit_free_ns = max(rows[i]["completion_ns"] for i in range(3))
    if credit_free_ns != fourth["credit_ns"]:
        raise AssertionError("Fourth request must wait for D credit")
    # This underestimates the actual post-Prefill transfer latency: no
    # propagation, setup, graph callbacks or competing flows are charged.
    nic_floor_ns = analysis["bytes_per_request"] * 8 * 1_000_000_000 // SOURCE_CUT_BPS
    measured_prefill_to_ready_ns = (
        fourth["p2d_ready_ns"] - fourth["prefill_start_ns"])
    measured_d_service_ns = (
        fourth["completion_ns"] - fourth["decode_admit_ns"])
    optimistic_ready_ns = max(credit_free_ns, measured_prefill_to_ready_ns) + nic_floor_ns
    optimistic_finish_ns = optimistic_ready_ns + measured_d_service_ns
    if optimistic_finish_ns >= fourth["completion_ns"]:
        raise AssertionError("No optimistic early-credit gap")
    result = {
        "status": "ANALYTICAL_ONLY",
        "claim": "conditional Oracle gap versus early credit, not policy gain",
        "assumptions": [
            "Fourth Prefill starts at arrival and retains all source KV.",
            "No KV byte is sent before receiver credit.",
            "First three D jobs and their credit release remain unchanged.",
            "The fourth transfer pays only the 100-Gb/s cut serialization floor.",
            "Fourth Decode service equals its measured isolated service.",
            "An ordinary two-stage FIFO may attain the same idealized bound."
        ],
        "timeline_sha256": hashlib.sha256(TIMELINE.read_bytes()).hexdigest(),
        "analysis_sha256": hashlib.sha256(ANALYSIS.read_bytes()).hexdigest(),
        "source_cut_bps": SOURCE_CUT_BPS,
        "credit_release_ns": credit_free_ns,
        "measured_prefill_to_ready_ns": measured_prefill_to_ready_ns,
        "nic_serialization_floor_ns": nic_floor_ns,
        "measured_decode_service_ns": measured_d_service_ns,
        "measured_early_credit_finish_ns": fourth["completion_ns"],
        "optimistic_two_stage_fifo_finish_ns": optimistic_finish_ns,
        "optimistic_gap_fraction_vs_early_credit": (
            fourth["completion_ns"] - optimistic_finish_ns)
            / fourth["completion_ns"],
        "incremental_gap_vs_two_stage_fifo": "unknown; no implementation",
    }
    (HERE / "optimistic_jit_bound.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
