#!/usr/bin/env python3
"""Summarize the corrected packet replay of one model-derived MoE layer."""

import csv
import math
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "research_audit/results/ns3_corrected_full_moe_layer_108"
CASES = ("full", "ep_only", "kv_only")
EP_COLLECTIVES = (1082, 1103)
SHARED_LINK = (38, 34)


def percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return ""
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def read_case(case):
    case_root = RUN_ROOT / case
    with (case_root / "comm_events.csv").open(
            encoding="utf-8", newline="") as stream:
        events = list(csv.DictReader(stream))
    ends = [row for row in events if row["phase"] == "END"]
    kv = [row for row in ends
          if row["event_type"] == "1" and row["request_id"] == "1"]
    ep = {collective_id: [row for row in ends
                          if int(row["collective_id"]) == collective_id]
          for collective_id in EP_COLLECTIVES}

    expected_kv = 0 if case == "ep_only" else 96
    expected_ep_per_collective = 0 if case == "kv_only" else 128
    if len(kv) != expected_kv:
        raise ValueError("%s: expected %d packetized KV messages, got %d" %
                         (case, expected_kv, len(kv)))
    for collective_id, rows in ep.items():
        if len(rows) != expected_ep_per_collective:
            raise ValueError(
                "%s collective %d: expected %d remote messages, got %d" %
                (case, collective_id, expected_ep_per_collective, len(rows)))

    link_rows = list(csv.DictReader((case_root / "link_summary.csv").open(
        encoding="utf-8", newline="")))
    shared = [row for row in link_rows
              if (int(row["src_node"]), int(row["dst_node"])) == SHARED_LINK]
    if len(shared) != 1 or int(shared[0]["capacity_bps"]) != 200_000_000_000:
        raise ValueError("%s: expected one 200-Gbps directed shared link %r" %
                         (case, SHARED_LINK))

    result = {
        "case": case,
        "packetized_kv_messages": len(kv),
        "packetized_ep_messages_dispatch": len(ep[EP_COLLECTIVES[0]]),
        "packetized_ep_messages_combine": len(ep[EP_COLLECTIVES[1]]),
        "kv_mean_fct_us": "",
        "kv_p50_fct_us": "",
        "kv_p95_fct_us": "",
        "kv_p99_fct_us": "",
        "kv_max_fct_us": "",
        "dispatch_cct_us": "",
        "combine_cct_us": "",
        "shared_link_src": SHARED_LINK[0],
        "shared_link_dst": SHARED_LINK[1],
        "shared_link_capacity_gbps": 200,
        "shared_link_tx_bytes": int(shared[0]["tx_bytes"]),
        "shared_link_queue_max_bytes": int(shared[0]["queue_max_bytes"]),
        "shared_link_ecn_marks": int(shared[0]["ecn_marks"]),
        "shared_link_pfc_pauses": int(shared[0]["pfc_pause"]),
        "shared_link_drops": int(shared[0]["drop_count"]),
    }
    if kv:
        fcts = [(int(row["network_end_ns"]) -
                 int(row["issue_time_ns"])) / 1000.0 for row in kv]
        result.update({
            "kv_mean_fct_us": statistics.mean(fcts),
            "kv_p50_fct_us": percentile(fcts, .50),
            "kv_p95_fct_us": percentile(fcts, .95),
            "kv_p99_fct_us": percentile(fcts, .99),
            "kv_max_fct_us": max(fcts),
        })
    for collective_id, column in zip(
            EP_COLLECTIVES, ("dispatch_cct_us", "combine_cct_us")):
        rows = ep[collective_id]
        if rows:
            start = min(int(row["issue_time_ns"]) for row in rows)
            finish = max(int(row["network_end_ns"]) for row in rows)
            result[column] = (finish - start) / 1000.0
    return result


def main():
    results = [read_case(case) for case in CASES]
    ep_only = next(row for row in results if row["case"] == "ep_only")
    kv_only = next(row for row in results if row["case"] == "kv_only")
    for row in results:
        row["dispatch_cct_slowdown_vs_ep_only_pct"] = (
            (row["dispatch_cct_us"] / ep_only["dispatch_cct_us"] - 1) * 100
            if row["dispatch_cct_us"] != "" else "")
        row["combine_cct_slowdown_vs_ep_only_pct"] = (
            (row["combine_cct_us"] / ep_only["combine_cct_us"] - 1) * 100
            if row["combine_cct_us"] != "" else "")
        row["kv_mean_fct_slowdown_vs_kv_only_pct"] = (
            (row["kv_mean_fct_us"] / kv_only["kv_mean_fct_us"] - 1) * 100
            if row["kv_mean_fct_us"] != "" else "")
        row["kv_p99_fct_slowdown_vs_kv_only_pct"] = (
            (row["kv_p99_fct_us"] / kv_only["kv_p99_fct_us"] - 1) * 100
            if row["kv_p99_fct_us"] != "" else "")

    output = RUN_ROOT / "matched_network_summary.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    print(output)
    for row in results:
        print(row)


if __name__ == "__main__":
    main()
