#!/usr/bin/env python3
"""Attribute native ns-3 ECN/DCQCN feedback to serving traffic classes.

The analyzer requires an exact QP_START <-> integrated communication START
join. It deliberately does not infer request-level serving metrics from the
packet replay; ns-3 replays issue times and independently recomputes network
completion, without feeding that completion back to the serving scheduler.
"""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


CLASS_BY_EVENT_TYPE = {1: "KV_MOVEMENT", 2: "EP", 3: "EP"}
CLASS_ORDER = ("KV_MOVEMENT", "EP", "OTHER")


def csv_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def line_count(path):
    with path.open("rb") as stream:
        return sum(1 for _ in stream)


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def summarize_values(values):
    if not values:
        return {"count": 0, "mean_ns": None, "p50_ns": None,
                "p95_ns": None, "p99_ns": None}
    return {
        "count": len(values),
        "mean_ns": sum(values) / len(values),
        "p50_ns": percentile(values, 0.50),
        "p95_ns": percentile(values, 0.95),
        "p99_ns": percentile(values, 0.99),
    }


def integrated_serving_summary(requests_path):
    cohorts = defaultdict(lambda: {"ttft": [], "tpot": [], "tbt": [],
                                   "p2d_ready_delay": []})
    request_rows = []
    request_count = 0
    with requests_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            request_count += 1
            input_tokens = int(row["input"])
            cohort = "D_decode_background" if input_tokens == 128 else "K_new_p2d"
            bucket = cohorts[cohort]
            ttft = int(row["TTFT"])
            tpot = int(row["TPOT"])
            bucket["ttft"].append(ttft)
            bucket["tpot"].append(tpot)
            tbt = json.loads(row["TBT"] or "[]")
            tbt_values = [int(value) for value in tbt]
            bucket["tbt"].extend(tbt_values)
            arrival = int(row["arrival"])
            ready_text = row.get("p2d_kv_ready_time_ns", "")
            ready = int(ready_text) if ready_text not in (None, "", "-1") else None
            request_rows.append({
                "request_id": row["request id"],
                "cohort": cohort,
                "input_tokens": input_tokens,
                "output_tokens": int(row["output"]),
                "arrival_ns": arrival,
                "prefill_completion_ns": row.get("prefill_completion_time_ns", ""),
                "p2d_kv_ready_ns": "" if ready is None else ready,
                "decode_admit_ns": row.get("decode_admit_time_ns", ""),
                "first_token_ns": row.get("decode_first_token_time_ns", ""),
                "ttft_ns": ttft,
                "tpot_ns": tpot,
                "tbt_sample_count": len(tbt_values),
                "tbt_mean_ns": (sum(tbt_values) / len(tbt_values)
                                if tbt_values else ""),
                "tbt_p99_ns": percentile(tbt_values, 0.99) if tbt_values else "",
            })
            if row.get("p2d_kv_ready_time_ns") not in (None, "", "-1"):
                ready = int(row["p2d_kv_ready_time_ns"])
                bucket["p2d_ready_delay"].append(ready - arrival)
    result = {"request_count": request_count, "SLO": "not evaluated; no threshold supplied"}
    for cohort, metrics in cohorts.items():
        result[cohort] = {
            "ttft": summarize_values(metrics["ttft"]),
            "tpot": summarize_values(metrics["tpot"]),
            "token_tbt": summarize_values(metrics["tbt"]),
            "arrival_to_p2d_ready": summarize_values(metrics["p2d_ready_delay"]),
        }
    return result, request_rows


def parse_qlen(path):
    maxima = {}
    total_samples = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            fields = line.split()
            if len(fields) < 3 or fields[0] != "time":
                continue
            try:
                timestamp = int(fields[1])
                node_id = int(fields[2])
            except ValueError:
                continue
            index = 3
            while index + 2 < len(fields):
                if fields[index] != "j":
                    index += 1
                    continue
                try:
                    port = int(fields[index + 1])
                    queue_bytes = int(fields[index + 2])
                except ValueError:
                    index += 1
                    continue
                key = (node_id, port)
                old = maxima.get(key)
                if old is None or queue_bytes > old[1]:
                    maxima[key] = (timestamp, queue_bytes)
                total_samples += 1
                index += 3
    return maxima, total_samples


def sweep_overlap(points):
    """Return KV/EP overlap duration and peak concurrent active intervals."""
    active = {"KV_MOVEMENT": 0, "EP": 0}
    overlap_ns = 0
    peak = {"KV_MOVEMENT": 0, "EP": 0}
    ordered = sorted(points)
    index = 0
    previous_time = None
    while index < len(ordered):
        timestamp = ordered[index][0]
        if previous_time is not None and active["KV_MOVEMENT"] > 0 and active["EP"] > 0:
            overlap_ns += timestamp - previous_time
        kv_delta = 0
        ep_delta = 0
        while index < len(ordered) and ordered[index][0] == timestamp:
            kv_delta += ordered[index][1]
            ep_delta += ordered[index][2]
            index += 1
        active["KV_MOVEMENT"] += kv_delta
        active["EP"] += ep_delta
        if active["KV_MOVEMENT"] < 0 or active["EP"] < 0:
            raise ValueError("negative active-flow count during overlap sweep")
        peak["KV_MOVEMENT"] = max(peak["KV_MOVEMENT"], active["KV_MOVEMENT"])
        peak["EP"] = max(peak["EP"], active["EP"])
        previous_time = timestamp
    return overlap_ns, peak


def analyze(attempt_dir, packet_dir_name="packet_fresh_cc1_rankfix1"):
    attempt_dir = attempt_dir.resolve()
    packet_dir = attempt_dir / packet_dir_name
    packet_manifest_path = packet_dir / "network_run_manifest.json"
    replay_manifest_path = attempt_dir / "packet_input" / "replay_manifest.json"
    serving_manifest_path = attempt_dir / "SERVING_CANDIDATE_MANIFEST.json"
    for required in (packet_manifest_path, replay_manifest_path,
                     serving_manifest_path):
        if not required.is_file():
            raise FileNotFoundError(required)

    packet_manifest = json.loads(packet_manifest_path.read_text(encoding="utf-8"))
    replay_manifest = json.loads(replay_manifest_path.read_text(encoding="utf-8"))
    serving_manifest = json.loads(serving_manifest_path.read_text(encoding="utf-8"))
    if packet_manifest.get("status") != "PASS":
        raise ValueError("native packet replay is not PASS")
    if serving_manifest.get("synthetic_byte_override") is not False:
        raise ValueError("serving candidate does not certify native/model bytes")

    comm_path = packet_dir / "comm_events.csv"
    cc_path = packet_dir / "cc_events.csv"
    link_summary_path = packet_dir / "link_summary.csv"
    link_ts_path = packet_dir / "link_timeseries.csv"
    qlen_path = packet_dir / "qlen.txt"
    pfc_path = packet_dir / "pfc.txt"

    # Link summary stores final per-link ECN counters. The timeseries field is
    # cumulative at each sample and must never be summed across rows.
    link_rows = list(csv_rows(link_summary_path))
    marked_links = {
        int(row["link_id"]): row for row in link_rows
        if int(row["ecn_marks"]) > 0
    }
    total_ecn = sum(int(row["ecn_marks"]) for row in link_rows)
    max_link_queue = max(
        ((int(row["queue_max_bytes"]), int(row["link_id"])) for row in link_rows),
        default=(0, -1),
    )

    # The key is the exact packet QP_START signature supplied by the replay:
    # src/dst rank, source port, bytes, and issue timestamp.
    exact_start_to_class = {}
    triple_to_class = defaultdict(set)
    marked_link_class_flows = defaultdict(Counter)
    marked_link_class_bytes = defaultdict(Counter)
    starts_for_overlap = {}
    overlap_points = defaultdict(list)
    comm_start_count = 0
    comm_rows = 0
    comm_start_bytes = Counter()

    with comm_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            comm_rows += 1
            phase = row["phase"]
            event_id = int(row["event_id"])
            if phase == "START":
                comm_start_count += 1
                event_type = int(row["event_type"])
                traffic_class = CLASS_BY_EVENT_TYPE.get(event_type, "OTHER")
                src_rank = int(row["src_rank"])
                dst_rank = int(row["dst_rank"])
                port = int(row["port"])
                byte_count = int(row["bytes"])
                start_ns = int(row["issue_time_ns"])
                exact_key = (src_rank, dst_rank, port, byte_count, start_ns)
                if exact_key in exact_start_to_class:
                    raise ValueError("duplicate exact communication START key")
                exact_start_to_class[exact_key] = traffic_class
                triple_to_class[(src_rank, dst_rank, port)].add(traffic_class)
                comm_start_bytes[traffic_class] += byte_count

                links = [int(value) for value in row["directed_link_ids"].split(";")
                         if value]
                relevant = [link for link in links if link in marked_links]
                for link in relevant:
                    marked_link_class_flows[link][traffic_class] += 1
                    marked_link_class_bytes[link][traffic_class] += byte_count
                if relevant:
                    starts_for_overlap[event_id] = (traffic_class, relevant,
                                                    start_ns)
            elif phase == "END":
                started = starts_for_overlap.pop(event_id, None)
                if started is None:
                    continue
                traffic_class, links, start_ns = started
                finish_ns = int(row["network_end_ns"])
                if finish_ns < start_ns:
                    raise ValueError("communication END precedes its START")
                kv_delta = 1 if traffic_class == "KV_MOVEMENT" else 0
                ep_delta = 1 if traffic_class == "EP" else 0
                for link in links:
                    overlap_points[link].append((start_ns, kv_delta, ep_delta))
                    overlap_points[link].append((finish_ns, -kv_delta, -ep_delta))
            else:
                raise ValueError("unknown comm phase %r" % phase)

    if starts_for_overlap:
        raise ValueError("unmatched START rows on ECN-marked links: %d" %
                         len(starts_for_overlap))

    # Establish QP identity -> serving traffic class from exact QP_START matches.
    qp_class = {}
    qp_start_counts = Counter()
    qp_start_bytes = Counter()
    qps_by_class = defaultdict(set)
    cnp_counts = Counter()
    cnp_qps = defaultdict(set)
    rate_counts = Counter()
    rate_decreases = Counter()
    rate_qps = defaultdict(set)
    unmatched_qp_starts = 0
    unmatched_cc_feedback = Counter()
    cc_rows = 0
    cc_event_counts = Counter()

    with cc_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            cc_rows += 1
            event = row["event"]
            cc_event_counts[event] += 1
            qp_identity = (int(row["node_id"]), int(row["qp_id"]))
            src_rank = int(row["src_rank"])
            dst_rank = int(row["dst_rank"])
            sport = int(row["sport"])
            if event == "QP_START":
                exact_key = (src_rank, dst_rank, sport, int(row["bytes"]),
                             int(row["timestamp"]))
                traffic_class = exact_start_to_class.get(exact_key)
                if traffic_class is None:
                    unmatched_qp_starts += 1
                    continue
                if qp_identity in qp_class:
                    raise ValueError("duplicate QP identity at QP_START: %r" %
                                     (qp_identity,))
                qp_class[qp_identity] = traffic_class
                qp_start_counts[traffic_class] += 1
                qp_start_bytes[traffic_class] += int(row["bytes"])
                qps_by_class[traffic_class].add(qp_identity)
                continue
            if event not in ("CNP", "RATE"):
                continue
            traffic_class = qp_class.get(qp_identity)
            if traffic_class is None:
                # This can occur only if a backend emits feedback before its
                # QP_START record; retain it as unclassified, never guess.
                unmatched_cc_feedback[event] += 1
                continue
            if event == "CNP":
                cnp_counts[traffic_class] += 1
                cnp_qps[traffic_class].add(qp_identity)
            else:
                rate_counts[traffic_class] += 1
                if int(row["new_rate_bps"]) < int(row["old_rate_bps"]):
                    rate_decreases[traffic_class] += 1
                    rate_qps[traffic_class].add(qp_identity)

    if unmatched_qp_starts:
        raise ValueError("%d/%d QP_START rows failed exact serving-ledger join" %
                         (unmatched_qp_starts, cc_event_counts["QP_START"]))
    if sum(qp_start_counts.values()) != comm_start_count:
        raise ValueError("joined QP starts (%d) != comm START events (%d)" %
                         (sum(qp_start_counts.values()), comm_start_count))

    overlap_by_link = {}
    for link_id, points in overlap_points.items():
        overlap_ns, peak = sweep_overlap(points)
        overlap_by_link[link_id] = {
            "kv_ep_overlap_ns": overlap_ns,
            "peak_active_kv_flows": peak["KV_MOVEMENT"],
            "peak_active_ep_flows": peak["EP"],
        }

    queue_maxima, qlen_samples = parse_qlen(qlen_path)
    switch_egress = queue_maxima.get((68, 6), (None, 0))
    kmin_bytes = 600_000  # replay.conf KMIN_MAP at 200 Gbps: 600 * 1000 bytes
    class_rows = []
    for traffic_class in CLASS_ORDER:
        class_rows.append({
            "traffic_class": traffic_class,
            "qp_start_count": qp_start_counts[traffic_class],
            "qp_start_bytes": qp_start_bytes[traffic_class],
            "unique_qps": len(qps_by_class[traffic_class]),
            "cnp_count": cnp_counts[traffic_class],
            "qps_with_cnp": len(cnp_qps[traffic_class]),
            "rate_event_count": rate_counts[traffic_class],
            "rate_decrease_count": rate_decreases[traffic_class],
            "qps_with_rate_decrease": len(rate_qps[traffic_class]),
        })

    integrated_metrics, request_serving_rows = integrated_serving_summary(
        attempt_dir / "integrated_full" / "requests.csv")
    serving_rows_path = attempt_dir / "SERVING_METRICS_FROM_FLOWSIM.csv"
    serving_fields = list(request_serving_rows[0]) if request_serving_rows else []
    with serving_rows_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=serving_fields,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(request_serving_rows)

    result = {
        "decision": ("NATURAL_CONGESTION_DOES_NOT_REDUCE_EP_QP"
                     if cnp_counts["EP"] == 0 and
                     rate_decreases["EP"] == 0 and total_ecn > 0 and
                     cnp_counts["KV_MOVEMENT"] > 0 and
                     rate_decreases["KV_MOVEMENT"] > 0
                     else "REVIEW_GATE_RESULT"),
        "source_type": "new integrated model-derived serving event ledger",
        "topology": serving_manifest["topology"],
        "model": serving_manifest["model"],
        "serving_candidate": {
            "experiment_id": serving_manifest["experiment_id"],
            "EP_degree": serving_manifest["EP_degree"],
            "D_active": serving_manifest["D_active"],
            "K_active": serving_manifest["K_active"],
            "P2D_mode": serving_manifest["P2D_mode"],
            "packet_payload_size": packet_manifest["packet_payload_size"],
            "synthetic_byte_override": serving_manifest["synthetic_byte_override"],
        },
        "replay": {
            "status": packet_manifest["status"],
            "CC_MODE": 1,
            "event_count": packet_manifest["event_count"],
            "issued_qps": cc_event_counts["QP_START"],
            "unmatched_qp_starts": unmatched_qp_starts,
            "comm_start_events": comm_start_count,
            "comm_csv_rows": comm_rows,
            "cc_csv_rows": cc_rows,
            "cc_event_counts": dict(cc_event_counts),
            "unmatched_cc_feedback": dict(unmatched_cc_feedback),
            "class_metrics": class_rows,
        },
        "switch_and_link": {
            "ecn_marks_from_final_link_summary": total_ecn,
            "ecn_marked_directed_link_count": len(marked_links),
            "max_link_netdevice_queue_bytes": max_link_queue[0],
            "max_link_id": max_link_queue[1],
            "Kmin_bytes_at_200Gbps": kmin_bytes,
            "qlen_max_switch68_port6": switch_egress[1],
            "qlen_switch68_port6_at_ns": switch_egress[0],
            "qlen_switch68_port6_exceeds_Kmin": switch_egress[1] > kmin_bytes,
            "qlen_samples_parsed": qlen_samples,
            "pfc_file_bytes": pfc_path.stat().st_size,
            "pfc_line_count": line_count(pfc_path),
            "drop_count": sum(int(row["drop_count"]) for row in link_rows),
            "ecn_marked_links": [
                {
                    "link_id": link_id,
                    "src_node": int(row["src_node"]),
                    "dst_node": int(row["dst_node"]),
                    "ecn_marks": int(row["ecn_marks"]),
                    "queue_max_bytes": int(row["queue_max_bytes"]),
                    "kv_start_flows": marked_link_class_flows[link_id]["KV_MOVEMENT"],
                    "kv_start_bytes": marked_link_class_bytes[link_id]["KV_MOVEMENT"],
                    "ep_start_flows": marked_link_class_flows[link_id]["EP"],
                    "ep_start_bytes": marked_link_class_bytes[link_id]["EP"],
                    **overlap_by_link.get(link_id, {
                        "kv_ep_overlap_ns": 0,
                        "peak_active_kv_flows": 0,
                        "peak_active_ep_flows": 0,
                    }),
                }
                for link_id, row in sorted(marked_links.items())
            ],
        },
        "serving_metrics_boundary": (
            "TTFT/TPOT/TBT remain integrated FlowSim serving outputs only; "
            "this ns-3 replay does not feed packet completion into scheduler."
        ),
        "integrated_serving": integrated_metrics,
        "integrated_serving_request_table": serving_rows_path.relative_to(
            Path(__file__).resolve().parents[3]).as_posix(),
    }

    output_csv = packet_dir / "NATURAL_ECN_CNP_BY_CLASS.csv"
    with output_csv.open("w", encoding="utf-8", newline="") as stream:
        fields = list(class_rows[0])
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(class_rows)
    root_class_csv = attempt_dir.parents[1] / "NATURAL_ECN_CNP_BY_CLASS.csv"
    with root_class_csv.open("w", encoding="utf-8", newline="") as stream:
        fields = list(class_rows[0])
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(class_rows)
    output_json = packet_dir / "NATURAL_ECN_PACKET_ANALYSIS.json"
    output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    # Preserve one compact experiment-level manifest with immutable provenance
    # and output hashes. Hashing is streamed so the large JSONL/CSV ledgers do
    # not need to be loaded into memory.
    repo_root = Path(__file__).resolve().parents[3]
    inventory_paths = [
        attempt_dir / "SERVING_CANDIDATE_MANIFEST.json",
        replay_manifest_path,
        packet_manifest_path,
        attempt_dir / "integrated_full" / "requests.csv",
        serving_rows_path,
        attempt_dir / "integrated_full" / "inputs" / "flowsim" / "flow_telemetry.jsonl",
        attempt_dir / "packet_input" / "events.csv",
        attempt_dir / "packet_input" / "rank_to_nic_map.csv",
        packet_dir / "replay.conf",
        packet_dir / "replay.log",
        packet_dir / "comm_events.csv",
        packet_dir / "cc_events.csv",
        packet_dir / "link_summary.csv",
        packet_dir / "link_timeseries.csv",
        packet_dir / "qlen.txt",
        packet_dir / "pfc.txt",
        packet_dir / "fct.txt",
        output_csv,
        output_json,
        root_class_csv,
    ]
    inventory = []
    for path in inventory_paths:
        if not path.is_file():
            continue
        relative = path.relative_to(repo_root).as_posix()
        row_count = None
        if path.suffix == ".csv" or path.suffix in (".jsonl", ".txt"):
            row_count = max(0, line_count(path) - 1) if path.suffix == ".csv" else line_count(path)
        inventory.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "row_or_line_count_excluding_header_for_csv": row_count,
            "sha256": sha256_file(path),
        })
    baseline_manifest_path = attempt_dir.parents[1] / "BASELINE_MANIFEST.json"
    result["baseline_manifest"] = baseline_manifest_path.relative_to(repo_root).as_posix()
    output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    # Refresh the output hash after adding its stable manifest pointer.
    output_inventory = next(
        (item for item in inventory if item["path"] == output_json.relative_to(repo_root).as_posix()),
        None,
    )
    if output_inventory is not None:
        output_inventory["bytes"] = output_json.stat().st_size
        output_inventory["sha256"] = sha256_file(output_json)

    baseline_manifest = {
        "schema_version": 1,
        "decision": result["decision"],
        "experiment_id": serving_manifest["experiment_id"],
        "historical_s8_exact_reproduction": False,
        "new_candidate_from_integrated_serving": True,
        "serving_manifest": serving_manifest,
        "packet_manifest": packet_manifest,
        "replay_input_manifest": replay_manifest,
        "analysis": result,
        "artifact_inventory": inventory,
    }
    baseline_manifest_path.write_text(
        json.dumps(baseline_manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "decision": result["decision"],
        "class_metrics": class_rows,
        "ecn_marks": total_ecn,
        "marked_links": len(marked_links),
        "qlen_switch68_port6_bytes": switch_egress[1],
        "Kmin_bytes": kmin_bytes,
        "artifact_manifest": baseline_manifest_path.as_posix(),
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attempt_dir", type=Path)
    parser.add_argument("--packet-dir", default="packet_fresh_cc1_rankfix1")
    args = parser.parse_args()
    analyze(args.attempt_dir, args.packet_dir)


if __name__ == "__main__":
    main()
