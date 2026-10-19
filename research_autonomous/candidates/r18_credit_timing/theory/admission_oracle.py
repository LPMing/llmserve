#!/usr/bin/env python3
"""Bound admission-timing choices under a fixed FAIR NIC and FIFO Decode.

The bound is scoped to the handoff-admission decision. It is not an
Oracle over network priorities, Decode batching, GPU role changes or
future arrivals.
"""

import csv
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CASES = HERE.parent / "experiments"
PAIRS = {
    "uniform": ("prompt_14000_early_post_r19b",
                "prompt_14000_two_stage_fifo_r19b"),
    "heterogeneous": ("prompt_14000_early_post_hetero_r19h",
                      "prompt_14000_two_stage_fifo_hetero_r19h"),
}
SOURCE_CUT_BPS = 100_000_000_000


def load(name):
    path = CASES / name
    summary = json.loads((path / "matched_analysis.json").read_text())
    if summary["status"] != "VALID":
        raise AssertionError("case did not pass its causal audit")
    timeline = [{key: int(value) for key, value in row.items()}
                for row in csv.DictReader((path / "matched_timeline.csv").open())]
    workload = (path / "workload.jsonl").read_bytes()
    topology = (path / "topology.txt").read_bytes()
    rank_map = (path / "rank_map.json").read_bytes()
    return summary, timeline, workload, topology, rank_map


def main():
    results = {}
    for label, (early_name, two_name) in PAIRS.items():
        early = load(early_name)
        two = load(two_name)
        if early[2:] != two[2:]:
            raise AssertionError("matched arms changed work or physical topology")
        if early[0]["p2d_bytes"] != two[0]["p2d_bytes"]:
            raise AssertionError("matched arms changed aggregate P2D bytes")
        early_last = early[0]["last_completion_ns"]
        two_last = two[0]["last_completion_ns"]
        if label == "uniform":
            # All jobs are identical and occupy one P each. Under fixed FAIR
            # service, any choice of three credits is symmetric. The fourth
            # credit cannot arrive before a first-wave D completion. After
            # credit it owes one full KV cut serialization and its measured
            # isolated Decode service. This is an admission-only lower bound.
            first_wave_finish = max(row["completion_ns"] for row in two[1][:3])
            last = two[1][3]
            cut_ns = last["p2d_bytes"] * 8 * 1_000_000_000 // SOURCE_CUT_BPS
            d_service_ns = last["completion_ns"] - last["decode_admit_ns"]
            oracle_lower_ns = first_wave_finish + cut_ns + d_service_ns
            if last["credit_ns"] != first_wave_finish:
                raise AssertionError("FIFO did not take earliest available credit")
            proof = "identical first-three credits are symmetric under fixed FAIR and FIFO Decode"
        else:
            # Every P job starts at its own arrival; every D credit arrives
            # exactly when that Prefill finishes. Transfers are disjoint on
            # the declared source cut and each Decode admission occurs at
            # P2D-ready. With fixed network/D execution there is no admission
            # wait or earlier admissible handoff decision left to make.
            rows = two[1]
            if not all(row["prefill_start_ns"] == row["arrival_ns"] and
                       row["credit_ns"] == row["prefill_compute_end_ns"] and
                       row["decode_admit_ns"] == row["p2d_ready_ns"]
                       for row in rows):
                raise AssertionError("heterogeneous FIFO has admission slack")
            intervals = sorted((row["first_flow_ns"], row["last_flow_ns"])
                               for row in rows)
            if any(intervals[i][1] > intervals[i+1][0] for i in range(3)):
                raise AssertionError("heterogeneous P2D transfers compete")
            oracle_lower_ns = two_last
            proof = "all four Prefills start at arrival; credits and D admissions occur at readiness with non-overlapping P2D flows"
        if oracle_lower_ns > two_last:
            raise AssertionError("lower bound exceeds measured FIFO")
        results[label] = {
            "early_case": early_name,
            "two_stage_case": two_name,
            "workload_sha256": hashlib.sha256(early[2]).hexdigest(),
            "early_last_completion_ns": early_last,
            "two_stage_last_completion_ns": two_last,
            "early_to_two_stage_gain_fraction": (early_last-two_last)/early_last,
            "admission_only_oracle_lower_ns": oracle_lower_ns,
            "two_stage_gap_to_admission_lower_fraction": (
                two_last-oracle_lower_ns)/two_last,
            "scope_proof": proof,
        }
    artifact = {
        "status": "CONDITIONAL_ORACLE",
        "scope": "admission timing only; same FAIR network and FIFO Decode; no GPU/NIC/KV changes",
        "not_in_scope": ["network flow priority", "Decode rebatching",
                         "role reallocation", "future-informed routing"],
        "results": results,
    }
    (HERE / "admission_oracle.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps(artifact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
