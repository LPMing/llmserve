#!/usr/bin/env python3
"""Extract compact, provenance-preserving ledgers for the final research audit."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "research_final_audit"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def request_headroom():
    source = ROOT / "research_motivation/decode_opportunity/06_SERVING_INTEGRATED_RESULTS.csv"
    rows = read_csv(source)
    selected = {
        "S0_FAIR", "S4_DECODE_OPPORTUNITY_REQ3",
        "B11_FAIR", "B11_OPPORTUNITY", "B13_FAIR", "B13_OPPORTUNITY",
    }
    rows = [row for row in rows if row["scenario"] in selected]
    baseline_scenario = {
        "S4_DECODE_OPPORTUNITY_REQ3": "S0_FAIR",
        "B11_OPPORTUNITY": "B11_FAIR",
        "B13_OPPORTUNITY": "B13_FAIR",
    }
    baselines = {
        (row["seed_d0_output_tokens"], row["request_id"]): row
        for row in rows if row["scenario"] in {"S0_FAIR", "B11_FAIR", "B13_FAIR"}
    }
    paired = {}
    for row in rows:
        base_name = baseline_scenario.get(row["scenario"])
        if base_name:
            paired[(row["scenario"], row["seed_d0_output_tokens"],
                    row["request_id"])] = baselines.get(
                        (row["seed_d0_output_tokens"], row["request_id"]))

    output = []
    for row in rows:
        seed_key = row["seed_d0_output_tokens"]
        base = (row if row["scenario"] in {"S0_FAIR", "B11_FAIR", "B13_FAIR"}
                else paired.get((row["scenario"], seed_key, row["request_id"])))
        lane_free = ""
        if base and row["request_role"] == "new_p2d_target":
            lane_candidates = [candidate for candidate in rows
                               if candidate["scenario"] == base["scenario"]
                               and candidate["request_role"] == "active_decode_seed"
                               and candidate["instance_id"] == base["instance_id"]]
            if lane_candidates:
                lane_free = lane_candidates[0]["request_completion_ns"]

        ready_delta = ""
        second_gain = ""
        exposed_gap = (max(0, int(base["p2d_kv_ready_time_ns"])
                           - int(lane_free))
                       if base and lane_free and
                       row["request_role"] == "new_p2d_target" else "")
        g_upper = ""
        if base and row["scenario"] in baseline_scenario:
            ready_delta = (int(base["p2d_kv_ready_time_ns"])
                           - int(row["p2d_kv_ready_time_ns"]))
            second_gain = (int(base["arrival_to_second_ns"])
                           - int(row["arrival_to_second_ns"]))
            if lane_free:
                g_upper = min(max(0, ready_delta), exposed_gap)

        output.append({
            "source_csv": "research_motivation/decode_opportunity/06_SERVING_INTEGRATED_RESULTS.csv",
            "scenario": row["scenario"],
            "policy": row["policy"],
            "seed_d0_output_tokens": seed_key,
            "request_id": row["request_id"],
            "request_role": row["request_role"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "request_kv_bytes": row["request_kv_bytes"],
            "last_required_kv_finish_ns": row["last_required_kv_finish_ns"],
            "p2d_ready_ns": row["p2d_kv_ready_time_ns"],
            "fixed_baseline_lane_free_ns": lane_free,
            "fixed_lane_exposed_gap_ns": exposed_gap,
            "kv_ready_advance_vs_fair_ns": ready_delta,
            "frozen_lane_G_upper_ns": g_upper,
            "decode_batch_start_ns": row["decode_first_batch_start_ns"],
            "decode_capacity_wait_ns": row["decode_capacity_queue_wait_ns"],
            "arrival_to_second_ns": row["arrival_to_second_ns"],
            "arrival_to_second_gain_vs_fair_ns": second_gain,
            "reported_ttft_ns": row["ttft_reported_ns"],
            "reported_ttst_ns_not_client_validated": row["reported_ttst_ns"],
            "sampler_to_second_diagnostic_ns_not_user_ttst": row["sampler_to_second_diagnostic_ns"],
            "tbt_sample_count": row["tbt_sample_count"],
            "tbt_mean_ns": row["tbt_mean_ns"],
            "tbt_max_ns": row["tbt_max_ns"],
            "request_completion_ns": row["request_completion_ns"],
        })
    fields = list(output[0]) if output else []
    write_csv(AUDIT / "02_PER_REQUEST_HEADROOM.csv", fields, output)


def collective_headroom():
    base = AUDIT / "sparse_a2a_minimal"
    names = ("exact_ep_only", "exact_full", "uniform_ep_only", "uniform_full")
    by_scenario = {name: {row["collective_id"]: row
                          for row in read_csv(base / name / "collectives.csv")}
                   for name in names}
    ids = sorted(set.intersection(*(set(rows) for rows in by_scenario.values())),
                 key=lambda value: int(value))
    result = []
    for collective_id in ids:
        e0 = by_scenario["exact_ep_only"][collective_id]
        ef = by_scenario["exact_full"][collective_id]
        u0 = by_scenario["uniform_ep_only"][collective_id]
        uf = by_scenario["uniform_full"][collective_id]
        cct = lambda row: int(row["cct_ns"])
        result.append({
            "collective_id": collective_id,
            "active_request_ids": e0["active_request_ids"],
            "flow_count_exact": e0["flow_count"],
            "flow_count_uniform": u0["flow_count"],
            "ep_bytes_exact": e0["bytes"],
            "ep_bytes_uniform": u0["bytes"],
            "cct_exact_ep_only_us": cct(e0) / 1000,
            "cct_exact_full_us": cct(ef) / 1000,
            "cct_uniform_ep_only_us": cct(u0) / 1000,
            "cct_uniform_full_us": cct(uf) / 1000,
            "p2d_delta_exact_full_minus_ep_only_us": (cct(ef) - cct(e0)) / 1000,
            "p2d_delta_uniform_full_minus_ep_only_us": (cct(uf) - cct(u0)) / 1000,
            "uniform_minus_exact_ep_only_us": (cct(u0) - cct(e0)) / 1000,
            "uniform_minus_exact_full_us": (cct(uf) - cct(ef)) / 1000,
            "event_unit_warning": "1us time-bin aggregate; all 48 MoE layers coalesced; not a native per-layer collective",
            "interpretation": "same-source-byte offline route counterfactual; uniform remainder mapping changes receiver fan-in and expert assignments",
        })
    write_csv(AUDIT / "02_PER_COLLECTIVE_HEADROOM.csv",
              list(result[0]) if result else [], result)


if __name__ == "__main__":
    request_headroom()
    collective_headroom()
