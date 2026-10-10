#!/usr/bin/env python3
"""Summarize persistent-EP-QP packet replays and matched EP-only controls."""

import csv
import json
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "experiments/pd_kv_ep/results/persistent_ep_qp"
TARGET_SRC_RANK = "16"
TARGET_DST_RANK = "8"
SHARED_LINK_SRC = "30"
SHARED_LINK_DST = "26"

RUNS = [
    ("D8K1_EP_ONLY", "D8K1_MAPPED_V2_EP_ONLY_PERSISTENT_BASELINE_V2", "D8K1", ""),
    ("D8K1_FULL", "D8K1_MAPPED_V2_FULL_PERSISTENT_K1", "D8K1", "D8K1_EP_ONLY"),
    ("D8K2_EP_ONLY", "D8K2_EP_ONLY_PERSISTENT_BASELINE", "D8K2", ""),
    ("D8K2_FULL_UNALIGNED", "D8K2_MAPPED_FULL_PERSISTENT_K2", "D8K2", "D8K2_EP_ONLY"),
    ("D8K2_ALIGNED_PERSISTENT", "D8K2_ALIGNED_R0_FULL_PERSISTENT", "D8K2", "D8K2_EP_ONLY"),
    ("D8K2_ALIGNED_CC_OFF", "D8K2_ALIGNED_R0_CC_OFF", "D8K2", "D8K2_EP_ONLY"),
    ("D8K2_ALIGNED_FRESH_QP", "D8K2_ALIGNED_R0_FRESH_QP", "D8K2", "D8K2_EP_ONLY"),
    ("D8K2_SHIFTED_P2D", "D8K2_SHIFTED_P2D_PERSISTENT", "D8K2", "D8K2_EP_ONLY"),
    ("D8K4_EP_ONLY", "K4_EP_ONLY_PERSISTENT", "D8K4", ""),
    ("D8K4_FULL", "D8K4_MAPPED_FULL_PERSISTENT_K4", "D8K4", "D8K4_EP_ONLY"),
    ("D8K4_CC_OFF", "K4_FULL_CC_OFF_PERSISTENT", "D8K4", "D8K4_EP_ONLY"),
    ("D8K4_FRESH_QP", "K4_FULL_FRESH_QP_UNIQUE_PORT", "D8K4", "D8K4_EP_ONLY"),
    ("D8K4_SHIFTED_P2D", "K4_SHIFTED_P2D_PERSISTENT", "D8K4", "D8K4_EP_ONLY"),
]


def read_csv(path):
    with path.open("r", newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def nearest_rank(values, q):
    if not values:
        return ""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def stats(values):
    values = [float(value) for value in values]
    if not values:
        return {"mean": "", "p50": "", "p95": "", "p99": "", "max": ""}
    return {
        "mean": sum(values) / len(values),
        "p50": nearest_rank(values, 0.50),
        "p95": nearest_rank(values, 0.95),
        "p99": nearest_rank(values, 0.99),
        "max": max(values),
    }


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def collect_run(label, run_name, point, baseline_label):
    run_dir = BASE / "runs" / run_name
    run_meta = read_json(run_dir / "network_run_manifest.json")
    if run_meta["status"] != "PASS":
        raise RuntimeError(f"{label}: run status is {run_meta['status']}")
    input_dir = Path(run_meta["input_replay_dir"])
    replay = read_json(input_dir / "replay_manifest.json")
    comm = read_csv(run_dir / "comm_events.csv")
    starts = {row["event_id"]: row for row in comm if row["phase"] == "START"}
    ends = {row["event_id"]: row for row in comm if row["phase"] == "END"}
    if set(starts) != set(ends):
        raise RuntimeError(
            f"{label}: incomplete communication events; starts={len(starts)}, ends={len(ends)}")

    groups = defaultdict(list)
    p2d = []
    flow_rows = []
    for event_id, start in starts.items():
        end = ends[event_id]
        start_ns = int(start["issue_time_ns"])
        end_ns = int(end["network_end_ns"])
        event_type = int(start["event_type"])
        item = {"start": start, "end": end, "start_ns": start_ns,
                "end_ns": end_ns, "event_type": event_type}
        if start["serving_role"] == "P2D_KV" or event_type == 1:
            p2d.append(item)
        elif event_type in (2, 3):
            groups[(start["collective_id"], event_type)].append(item)
        flow_rows.append(item)

    ep_groups = {}
    for key, items in groups.items():
        ep_groups[key] = {
            "collective_id": key[0],
            "event_type": key[1],
            "start_ns": min(item["start_ns"] for item in items),
            "finish_ns": max(item["end_ns"] for item in items),
            "cct_ns": max(item["end_ns"] for item in items)
            - min(item["start_ns"] for item in items),
            "last_item": max(items, key=lambda item: item["end_ns"]),
            "items": items,
        }

    cc = read_csv(run_dir / "cc_events.csv")
    target_cc = [row for row in cc
                 if row["src_rank"] == TARGET_SRC_RANK
                 and row["dst_rank"] == TARGET_DST_RANK]
    target_starts = [row for row in target_cc if row["event"] == "QP_START"]
    cnp_count = sum(row["event"] == "CNP" for row in target_cc)
    cnp_count_all = sum(row["event"] == "CNP" for row in cc)
    rate_changes = [row for row in target_cc if row["event"] == "RATE"]
    rate_changes_all = [row for row in cc if row["event"] == "RATE"]
    rate_decreases = [row for row in rate_changes
                      if int(row["new_rate_bps"]) < int(row["old_rate_bps"])]

    summaries = read_csv(run_dir / "link_summary.csv")
    shared_summary = next((row for row in summaries
                           if row["src_node"] == SHARED_LINK_SRC
                           and row["dst_node"] == SHARED_LINK_DST), {})
    reverse_shared_summary = next((row for row in summaries
                                   if row["src_node"] == SHARED_LINK_DST
                                   and row["dst_node"] == SHARED_LINK_SRC), {})
    queue_series = [row for row in read_csv(run_dir / "link_timeseries.csv")
                    if row["src_node"] == SHARED_LINK_SRC
                    and row["dst_node"] == SHARED_LINK_DST]
    queue_series.sort(key=lambda row: int(row["timestamp"]))

    p2d_start_ns = min((item["start_ns"] for item in p2d), default=None)
    p2d_last_finish_ns = max((item["end_ns"] for item in p2d), default=None)
    p2d_bytes = sum(int(item["start"]["bytes"]) for item in p2d)
    p2d_link_overlaps = []
    ep_target_items = [item for item in flow_rows
                       if item["event_type"] in (2, 3)
                       and item["start"]["src_rank"] == TARGET_SRC_RANK
                       and item["start"]["dst_rank"] == TARGET_DST_RANK]
    for kv in p2d:
        kv_links = set(kv["end"]["directed_link_ids"].split(";"))
        for ep in ep_target_items:
            ep_links = set(ep["end"]["directed_link_ids"].split(";"))
            overlap_ns = max(0, min(kv["end_ns"], ep["end_ns"])
                             - max(kv["start_ns"], ep["start_ns"]))
            shared = bool(kv_links & ep_links)
            if shared and overlap_ns:
                p2d_link_overlaps.append(overlap_ns)

    config_lines = (run_dir / "replay.conf").read_text(encoding="utf-8").splitlines()
    cc_mode = next((line.split()[1] for line in config_lines
                    if line.split() and line.split()[0] == "CC_MODE"), "")
    matched_ccts = {}
    if baseline_label:
        # Filled after all runs are collected.
        matched_ccts = {"baseline_label": baseline_label}
    return {
        "label": label,
        "run_name": run_name,
        "point": point,
        "baseline_label": baseline_label,
        "run_dir": run_dir,
        "run_meta": run_meta,
        "replay": replay,
        "groups": ep_groups,
        "cc": cc,
        "target_cc": target_cc,
        "target_starts": target_starts,
        "cnp_count": cnp_count,
        "cnp_count_all": cnp_count_all,
        "rate_changes": rate_changes,
        "rate_changes_all": rate_changes_all,
        "rate_decreases": rate_decreases,
        "summaries": summaries,
        "shared_summary": shared_summary,
        "reverse_shared_summary": reverse_shared_summary,
        "queue_series": queue_series,
        "p2d": p2d,
        "p2d_start_ns": p2d_start_ns,
        "p2d_last_finish_ns": p2d_last_finish_ns,
        "p2d_bytes": p2d_bytes,
        "queue_clear_after_p2d_ns": "",
        "queue_clear_baseline_envelope_bytes": "",
        "queue_clear_is_absolute_zero": "",
        "max_target_overlap_ns": max(p2d_link_overlaps, default=0),
        "target_ep_issue_times_ns": sorted({item["start_ns"] for item in ep_target_items}),
        "cc_mode": cc_mode,
        "matched_ccts": matched_ccts,
    }


def main():
    out_dir = BASE
    data = [collect_run(*spec) for spec in RUNS]
    by_label = {run["label"]: run for run in data}

    experiment_rows = []
    baseline_rows = []
    recovery_rows = []
    for run in data:
        label = run["label"]
        baseline = by_label.get(run["baseline_label"])
        if baseline and run["p2d_start_ns"] is not None:
            baseline_shared_max = int(baseline["shared_summary"].get("queue_max_bytes", 0))
            run["queue_clear_baseline_envelope_bytes"] = baseline_shared_max
            clear_samples = [row for row in run["queue_series"]
                             if int(row["timestamp"]) >= run["p2d_last_finish_ns"]
                             and int(row["queue_bytes"]) <= baseline_shared_max]
            if clear_samples:
                run["queue_clear_after_p2d_ns"] = min(
                    int(row["timestamp"]) for row in clear_samples)
                clear_row = next(row for row in clear_samples
                                 if int(row["timestamp"]) == run["queue_clear_after_p2d_ns"])
                run["queue_clear_is_absolute_zero"] = int(
                    int(clear_row["queue_bytes"]) == 0)
        if baseline:
            run["reverse_link_tx_delta_bytes"] = (
                int(run["reverse_shared_summary"].get("tx_bytes", 0))
                - int(baseline["reverse_shared_summary"].get("tx_bytes", 0)))
        else:
            run["reverse_link_tx_delta_bytes"] = ""

        paired = []
        post_queue_slowdowns = []
        for key, group in sorted(run["groups"].items()):
            base_group = baseline["groups"].get(key) if baseline else None
            slowdown = (group["cct_ns"] / base_group["cct_ns"] - 1.0
                        if base_group and base_group["cct_ns"] else "")
            last = group["last_item"]
            last_start = last["start"]
            last_peer_cc = [row for row in run["cc"]
                            if row["event"] == "QP_START"
                            and row["sport"] == last_start["port"]
                            and int(row["timestamp"]) == last["start_ns"]]
            last_peer_qpid = last_peer_cc[0]["qp_id"] if last_peer_cc else ""
            last_peer_rate = (int(last_peer_cc[0]["new_rate_bps"]) / 1e9
                              if last_peer_cc else "")
            target_peer_is_last = (
                last_start["src_rank"] == TARGET_SRC_RANK
                and last_start["dst_rank"] == TARGET_DST_RANK)
            target_items = [item for item in group["items"]
                            if item["start"]["src_rank"] == TARGET_SRC_RANK
                            and item["start"]["dst_rank"] == TARGET_DST_RANK]
            target_item = target_items[0] if target_items else None
            qpid = ""
            target_rate = ""
            if target_item:
                port = target_item["start"]["port"]
                matching = [row for row in run["target_starts"]
                            if row["sport"] == port
                            and int(row["timestamp"]) == target_item["start_ns"]]
                if matching:
                    qpid = matching[0]["qp_id"]
                    target_rate = int(matching[0]["new_rate_bps"]) / 1e9
            baseline_rows.append({
                "run": label,
                "baseline": run["baseline_label"],
                "collective_id": group["collective_id"],
                "collective_kind": "EP_DISPATCH" if group["event_type"] == 2 else "EP_COMBINE",
                "collective_start_ns": group["start_ns"],
                "collective_finish_ns": group["finish_ns"],
                "cct_us": group["cct_ns"] / 1000.0,
                "matched_baseline_cct_us": base_group["cct_ns"] / 1000.0 if base_group else "",
                "matched_slowdown_pct": slowdown * 100.0 if slowdown != "" else "",
                "last_peer_src_rank": last_start["src_rank"],
                "last_peer_dst_rank": last_start["dst_rank"],
                "last_peer_path": last["end"]["path"],
                "last_peer_directed_link_ids": last["end"]["directed_link_ids"],
                "last_peer_qp_id": last_peer_qpid,
                "last_peer_rate_at_issue_gbps": last_peer_rate,
                "last_peer_rate_below_95pct_line": (
                    int(float(last_peer_rate) < 190.0) if last_peer_rate != "" else ""),
                "target_peer_is_last": int(target_peer_is_last),
                "target_peer_qp_id": qpid,
                "target_peer_rate_at_issue_gbps": target_rate,
                "after_p2d_excess_queue_clear": int(
                    run["queue_clear_after_p2d_ns"] != ""
                    and group["start_ns"] >= run["queue_clear_after_p2d_ns"]),
            })
            if slowdown != "":
                paired.append(slowdown)
                if (run["queue_clear_after_p2d_ns"] != ""
                        and group["start_ns"] >= run["queue_clear_after_p2d_ns"]):
                    post_queue_slowdowns.append(slowdown * 100.0)

        ccts_us = [group["cct_ns"] / 1000.0 for group in run["groups"].values()]
        cct_stats = stats(ccts_us)
        paired_pct = [value * 100.0 for value in paired]
        paired_stats = stats(paired_pct)
        target_rates = [int(row["new_rate_bps"]) / 1e9 for row in run["target_starts"]]
        target_periods_us = [
            (right - left) / 1000.0
            for left, right in zip(run["target_ep_issue_times_ns"],
                                   run["target_ep_issue_times_ns"][1:])]
        shared = run["shared_summary"]
        max_all_queue = max((int(row["queue_max_bytes"]) for row in run["summaries"]), default=0)
        all_ecn = sum(int(row["ecn_marks"]) for row in run["summaries"])
        p2d_dur_us = ((run["p2d_last_finish_ns"] - run["p2d_start_ns"]) / 1000.0
                      if run["p2d_start_ns"] is not None else "")
        row = {
            "experiment_id": label,
            "run_name": run["run_name"],
            "topology": "1P+2D, EP16, single ToR; 2x200G NIC/server",
            "link_rate_gbps": 200,
            "K_requests": run["replay"]["request_count"] - 8,
            "K_tokens": run["replay"].get("kv_tokens_per_request", 8192),
            "K_flows": len(run["p2d"]),
            "KV_bytes": run["p2d_bytes"],
            "EP_collective_groups": len(run["groups"]),
            "EP_flows": sum(len(group["items"]) for group in run["groups"].values()),
            "EP_round_period_us": stats(target_periods_us)["p50"],
            "persistent_ep_qp": int(run["run_meta"]["persistent_ep_qps"]),
            "CC_MODE": run["cc_mode"],
            "target_qp": f"rank{TARGET_SRC_RANK}->rank{TARGET_DST_RANK}",
            "target_qp_ids": ";".join(sorted({r["qp_id"] for r in run["target_starts"]})),
            "target_sport_count": len({r["sport"] for r in run["target_starts"]}),
            "queue_max_shared_30_26_bytes": shared.get("queue_max_bytes", ""),
            "queue_max_any_link_bytes": max_all_queue,
            "ECN_marks_all_links": all_ecn,
            "PFC_pauses_all_links": sum(int(r["pfc_pause"]) for r in run["summaries"]),
            "drops_all_links": sum(int(r["drop_count"]) for r in run["summaries"]),
            "P2D_first_issue_us": run["p2d_start_ns"] / 1000.0 if run["p2d_start_ns"] is not None else "",
            "P2D_last_completion_us": run["p2d_last_finish_ns"] / 1000.0 if run["p2d_last_finish_ns"] is not None else "",
            "P2D_completion_span_us": p2d_dur_us,
            "P2D_excess_queue_clear_timestamp_us": (
                run["queue_clear_after_p2d_ns"] / 1000.0
                if run["queue_clear_after_p2d_ns"] != "" else ""),
            "P2D_excess_queue_tail_after_last_completion_us": (
                (run["queue_clear_after_p2d_ns"] - run["p2d_last_finish_ns"]) / 1000.0
                if run["queue_clear_after_p2d_ns"] != "" else ""),
            "P2D_excess_queue_episode_span_us": (
                (run["queue_clear_after_p2d_ns"] - run["p2d_start_ns"]) / 1000.0
                if run["queue_clear_after_p2d_ns"] != "" else ""),
            "EP_ONLY_queue_envelope_bytes": run["queue_clear_baseline_envelope_bytes"],
            "clear_sample_was_absolute_zero": run["queue_clear_is_absolute_zero"],
            "reverse_D0_to_ToR_tx_bytes_delta_vs_EP_ONLY": run["reverse_link_tx_delta_bytes"],
            "target_EP_P2D_shared_link_overlap_max_us": run["max_target_overlap_ns"] / 1000.0,
            "target_CNP_count": run["cnp_count"],
            "CNP_count_all_QPs": run["cnp_count_all"],
            "target_RATE_event_count": len(run["rate_changes"]),
            "RATE_event_count_all_QPs": len(run["rate_changes_all"]),
            "target_rate_decrease_count": len(run["rate_decreases"]),
            "target_rate_start_min_gbps": min(target_rates) if target_rates else "",
            "target_rate_start_max_gbps": max(target_rates) if target_rates else "",
            "EP_CCT_mean_us": cct_stats["mean"],
            "EP_CCT_p50_us": cct_stats["p50"],
            "EP_CCT_p95_us": cct_stats["p95"],
            "EP_CCT_p99_us": cct_stats["p99"],
            "EP_CCT_max_us": cct_stats["max"],
            "matched_EP_CCT_mean_slowdown_pct": paired_stats["mean"],
            "matched_EP_CCT_p50_slowdown_pct": paired_stats["p50"],
            "matched_EP_CCT_p95_slowdown_pct": paired_stats["p95"],
            "matched_EP_CCT_p99_slowdown_pct": paired_stats["p99"],
            "matched_EP_CCT_max_slowdown_pct": paired_stats["max"],
            "post_queue_collectives": len(post_queue_slowdowns),
            "post_queue_rounds_ge10pct": sum(value >= 10.0 for value in post_queue_slowdowns),
            "post_queue_rounds_ge20pct": sum(value >= 20.0 for value in post_queue_slowdowns),
            "post_queue_max_CCT_slowdown_pct": max(post_queue_slowdowns, default=""),
            "classification": (
                "EP_ONLY_BASELINE" if not run["baseline_label"] else
                "NO_TARGET_CNP_NO_RATE_REDUCTION" if run["cnp_count"] == 0
                and not run["rate_decreases"] else "REVIEW"),
            "run_status": run["run_meta"]["status"],
        }
        experiment_rows.append(row)

        peer_events = sorted(run["target_cc"], key=lambda r: int(r["timestamp"]))
        target_group_by_port_time = {}
        for group in run["groups"].values():
            for item in group["items"]:
                start = item["start"]
                if start["src_rank"] == TARGET_SRC_RANK and start["dst_rank"] == TARGET_DST_RANK:
                    target_group_by_port_time[(start["port"], item["start_ns"])] = group
        for index, event in enumerate(peer_events):
            group = target_group_by_port_time.get((event["sport"], int(event["timestamp"])))
            recovery_rows.append({
                "run": label,
                "timestamp_ns": event["timestamp"],
                "event": event["event"],
                "qp_id": event["qp_id"],
                "src_rank": event["src_rank"],
                "dst_rank": event["dst_rank"],
                "sport": event["sport"],
                "old_rate_gbps": int(event["old_rate_bps"]) / 1e9,
                "new_rate_gbps": int(event["new_rate_bps"]) / 1e9,
                "target_rate_gbps": int(event["target_rate_bps"]) / 1e9,
                "reason": event["reason"],
                "ecnbits": event["ecn_bits"],
                "collective_id": group["collective_id"] if group else "",
                "collective_kind": ("EP_DISPATCH" if group and group["event_type"] == 2
                                    else "EP_COMBINE" if group else ""),
                "collective_cct_us": group["cct_ns"] / 1000.0 if group else "",
                "note": "QP_START rate sample; no rate recovery can be inferred without CNP/RATE events"
                if event["event"] == "QP_START" else "",
            })

    write_csv(out_dir / "PERSISTENT_EP_QP_EXPERIMENTS.csv", experiment_rows,
              list(experiment_rows[0]))
    write_csv(out_dir / "EP_PERSISTENT_QP_BASELINE.csv", baseline_rows,
              list(baseline_rows[0]))
    write_csv(out_dir / "EP_QP_RECOVERY_TRACE.csv", recovery_rows,
              list(recovery_rows[0]))
    print(json.dumps({
        "experiment_rows": len(experiment_rows),
        "collective_rows": len(baseline_rows),
        "target_qp_state_rows": len(recovery_rows),
        "outputs": [
            str(out_dir / "PERSISTENT_EP_QP_EXPERIMENTS.csv"),
            str(out_dir / "EP_PERSISTENT_QP_BASELINE.csv"),
            str(out_dir / "EP_QP_RECOVERY_TRACE.csv"),
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
