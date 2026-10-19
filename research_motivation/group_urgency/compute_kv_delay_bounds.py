#!/usr/bin/env python3
"""Compute arithmetic P2D-ready bounds from retained request event ledgers.

This does not replay network service. An added delay is applied only to the
observed last-required-KV completion; resulting ready-time movement is
max(0, delay - prefill-completion masking slack).
"""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "01_KV_PER_REQUEST.csv"
OUT = ROOT / "08_KV_REQUEST_RESULTS.csv"
DELAYS_MS = (0.5, 0.7, 1.0, 1.5)


def load_rows():
    with SOURCE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pick(rows, run, request_id, prompt):
    matches = [r for r in rows if r["scenario_policy"] == run
               and r["request_id"] == str(request_id)
               and r["prompt_tokens"] == str(prompt)]
    if not matches:
        raise RuntimeError(f"Missing retained request: {run=} {request_id=} {prompt=}")
    return matches[0]


def main():
    rows = load_rows()
    samples = [
        ("KV_KV_SMALL_VICTIM", pick(rows, "kv_kv_128_vs_2048", 0, 128)),
        ("KV_KV_MEDIUM_BACKGROUND", pick(rows, "kv_kv_128_vs_2048", 1, 2048)),
        ("KV_KV_LARGE_BACKGROUND", pick(rows, "kv_kv_128_vs_8192", 1, 8192)),
        ("A7_FAIR_SHORT_CONTEXT", pick(rows, "A7L2M_fair", 16, 1024)),
        ("A7_FAIR_MEDIUM_CONTEXT", pick(rows, "A7L2M_fair", 8, 2048)),
    ]
    out_rows = []
    for label, r in samples:
        slack_ns = int(r["compute_masking_slack_ns"])
        ready_ns = int(r["p2d_ready_ns"])
        decision_raw = r.get("first_decode_batch_decision_ns", "")
        decision_ns = int(decision_raw) if decision_raw not in ("", "-1") else None
        for extra_ms in DELAYS_MS:
            extra_ns = round(extra_ms * 1e6)
            ready_shift_ns = max(0, extra_ns - slack_ns)
            predicted_ready_ns = ready_ns + ready_shift_ns
            out_rows.append({
                "sample": label,
                "source_run": r["scenario_policy"],
                "request_id": r["request_id"],
                "prompt_tokens": r["prompt_tokens"],
                "observed_last_required_kv_ns": r["last_required_kv_completion_ns"],
                "observed_p2d_ready_ns": ready_ns,
                "observed_compute_masking_slack_us": slack_ns / 1000,
                "hypothetical_extra_delay_to_last_required_kv_ms": extra_ms,
                "arithmetic_p2d_ready_shift_us": ready_shift_ns / 1000,
                "arithmetic_p2d_ready_ns": predicted_ready_ns,
                "first_recorded_decode_batch_decision_ns": decision_ns if decision_ns is not None else "NOT_RETAINED",
                "baseline_ready_to_first_decode_decision_us": (
                    (decision_ns - ready_ns) / 1000 if decision_ns is not None else "NOT_RETAINED"),
                "crosses_recorded_decode_decision": (
                    predicted_ready_ns > decision_ns if decision_ns is not None else "NOT_TESTABLE"),
                "evidence": "ARITHMETIC_COUNTERFACTUAL_NOT_NETWORK_REPLAY",
                "caveat": "Does not model changed queueing, future release times, or scheduler wake-up after delay",
            })
    fields = list(out_rows[0])
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"wrote {len(out_rows)} arithmetic KV delay-bound rows to {OUT}")


if __name__ == "__main__":
    main()
