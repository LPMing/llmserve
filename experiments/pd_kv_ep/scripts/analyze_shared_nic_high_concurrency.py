#!/usr/bin/env python3
"""Summarize matched FlowSim/ns-3 4P4D shared-NIC high-concurrency runs."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _percentile(values, q):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    position = (len(values) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def _stats(values):
    values = [float(value) for value in values if value is not None]
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None,
                "p99": None, "max": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values),
    }


def _node_names(root):
    names = {}
    config_root = root / "experiments/pd_kv_ep/configs/large_scale"
    rank_path = config_root / "s8_4p4d_ep32_rank_metadata.csv"
    for row in _read_csv(rank_path):
        names[int(row["astra_rank"])] = row["gpu_id"]
    nic_path = config_root / "s8_4p4d_ep32_gpu_to_nic.csv"
    for row in _read_csv(nic_path):
        names[int(row["nic_id"])] = "NIC[%s:%s]" % (
            row["server_id"], row["gpu_ids"].replace(";", "+"))
    for leaf in range(4):
        names[80 + leaf] = "Leaf%d" % leaf
    for spine in range(2):
        names[84 + spine] = "Spine%d" % spine
    return names


def _read_ns3_run(label, scenario_dir, overlap_dir, node_names):
    scenario_dir = scenario_dir.resolve()
    run_manifest = json.loads(
        (scenario_dir / "network_run_manifest.json").read_text(encoding="utf-8"))
    replay_manifest = json.loads(
        (scenario_dir / "replay_manifest.json").read_text(encoding="utf-8"))
    starts, ends = {}, {}
    with (scenario_dir / "comm_events.csv").open(
            newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["event_id"] in ("", "-1"):
                continue
            (starts if row["phase"] == "START" else ends)[row["event_id"]] = row

    flows = []
    priority_groups = {"P2D_KV": {}, "EP": {}}
    for event_id, start in starts.items():
        end = ends.get(event_id)
        if end is None or int(end["network_end_ns"]) < 0:
            continue
        item = {
            "event_id": int(event_id),
            "request_id": int(start["request_id"]),
            "collective_id": int(start["collective_id"] or 0),
            "event_type": int(start["event_type"]),
            "priority_group": int(start["priority_group"]),
            "layer_id": int(start["layer_id"] or 0),
            "src": int(start["src"]),
            "dst": int(start["dst"]),
            "bytes": int(start["bytes"]),
            "start": int(start["network_start_ns"]),
            "end": int(end["network_end_ns"]),
            "path": start["path"],
            "directed_links": start["directed_link_ids"],
        }
        flows.append(item)
        traffic = "P2D_KV" if item["event_type"] == 1 else "EP"
        group = str(item["priority_group"])
        priority_groups[traffic][group] = priority_groups[traffic].get(group, 0) + 1

    kv_flows = [flow for flow in flows if flow["event_type"] == 1]
    ep_flows = [flow for flow in flows if flow["event_type"] in (2, 3)]
    kv_flow_ns = [flow["end"] - flow["start"] for flow in kv_flows]
    kv_by_request = {}
    for flow in kv_flows:
        if flow["request_id"] < 0:
            continue
        group = kv_by_request.setdefault(flow["request_id"], {
            "first_start": flow["start"], "last_finish": flow["end"],
            "last_request": flow["start"],
            "flow_count": 0, "bytes": 0, "last_layer": flow["layer_id"],
        })
        group["first_start"] = min(group["first_start"], flow["start"])
        group["last_request"] = max(group["last_request"], flow["start"])
        group["last_finish"] = max(group["last_finish"], flow["end"])
        group["flow_count"] += 1
        group["bytes"] += flow["bytes"]
        if flow["end"] >= group["last_finish"]:
            group["last_layer"] = flow["layer_id"]
    kv_handoff_ns = [value["last_finish"] - value["first_start"]
                     for value in kv_by_request.values()]
    kv_release_span_ns = [value["last_request"] - value["first_start"]
                          for value in kv_by_request.values()]
    kv_post_release_drain_ns = [value["last_finish"] - value["last_request"]
                                for value in kv_by_request.values()]

    collective_groups = {}
    for flow in ep_flows:
        group = collective_groups.setdefault(flow["collective_id"], {
            "first_start": flow["start"], "last_finish": flow["end"],
            "flow_count": 0, "bytes": 0, "dispatch_bytes": 0,
            "combine_bytes": 0,
        })
        group["first_start"] = min(group["first_start"], flow["start"])
        group["last_finish"] = max(group["last_finish"], flow["end"])
        group["flow_count"] += 1
        group["bytes"] += flow["bytes"]
        group["dispatch_bytes" if flow["event_type"] == 2 else "combine_bytes"] += flow["bytes"]
    ep_cct_ns = [value["last_finish"] - value["first_start"]
                 for value in collective_groups.values()]

    bytes_by_link = defaultdict(lambda: {"P2D_KV_payload_bytes": 0,
                                         "EP_payload_bytes": 0})
    for flow in flows:
        traffic = ("P2D_KV_payload_bytes" if flow["event_type"] == 1
                   else "EP_payload_bytes")
        for link_id in set(item for item in flow["directed_links"].split(";") if item):
            bytes_by_link[int(link_id)][traffic] += flow["bytes"]

    links = _read_csv(scenario_dir / "link_summary.csv")
    physical = [row for row in links if int(row["capacity_bps"]) == 200_000_000_000]
    ecn_total = sum(int(row["ecn_marks"]) for row in physical)
    pfc_total = sum(int(row["pfc_pause"]) for row in physical)
    drops_total = sum(int(row["drop_count"]) for row in physical)
    max_queue = max((int(row["queue_max_bytes"]) for row in physical), default=0)
    max_peak_util = max((float(row["peak_utilization"]) for row in physical), default=0)
    queue_top = sorted(physical, key=lambda row: int(row["queue_max_bytes"]), reverse=True)[:5]
    ecn_top = sorted(physical, key=lambda row: int(row["ecn_marks"]), reverse=True)[:5]
    top_class_bytes = sorted(
        physical,
        key=lambda row: sum(bytes_by_link[int(row["link_id"])].values()),
        reverse=True)[:8]

    overlap_summary = _read_csv(
        overlap_dir / scenario_dir.name / "directed_link_overlap_summary.csv")
    overlap_file_links = []
    link_by_id = {int(row["link_id"]): row for row in physical}
    for row in overlap_summary[:8]:
        link_id = int(row["link_id"])
        edge = link_by_id.get(link_id)
        if edge:
            overlap_file_links.append({
                "link_id": link_id,
                "link": "%s -> %s" % (
                    node_names.get(int(edge["src_node"]), edge["src_node"]),
                    node_names.get(int(edge["dst_node"]), edge["dst_node"])),
                "overlapping_flow_pairs": int(row["pairs"]),
                "queue_max_bytes": int(edge["queue_max_bytes"]),
                "ecn_marks": int(edge["ecn_marks"]),
            })

    by_link_name = lambda row: "%s -> %s" % (
        node_names.get(int(row["src_node"]), row["src_node"]),
        node_names.get(int(row["dst_node"]), row["dst_node"]))
    return {
        "policy": label,
        "status": run_manifest["status"],
        "wall_seconds": run_manifest["wall_seconds"],
        "packet_payload_size": run_manifest["packet_payload_size"],
        "events_expected": replay_manifest["event_count"],
        "events_completed": len(flows),
        "completion_coverage": len(flows) / replay_manifest["event_count"],
        "p2d_bytes": replay_manifest["p2d_bytes"],
        "ep_bytes": replay_manifest["ep_bytes"],
        "p2d_shard_flow_fct_ns": _stats(kv_flow_ns),
        "kv_request_handoff_span_ns": _stats(kv_handoff_ns),
        "kv_request_layer_release_span_ns": _stats(kv_release_span_ns),
        "kv_request_post_last_release_drain_ns": _stats(kv_post_release_drain_ns),
        "kv_request_count": len(kv_by_request),
        "data_priority_group_flow_counts": priority_groups,
        "ep_collective_cct_ns": _stats(ep_cct_ns),
        "ep_collective_count": len(collective_groups),
        "shared_link_overlap_flow_pairs": sum(
            int(row["pairs"]) for row in overlap_summary),
        "shared_directed_links_with_overlap": len(overlap_summary),
        "physical_200g_link_count": len(physical),
        "physical_200g_peak_utilization_max": max_peak_util,
        "physical_200g_queue_max_bytes": max_queue,
        "physical_200g_queue_max_link": by_link_name(max(
            physical, key=lambda row: int(row["queue_max_bytes"]),
            default={"src_node": 0, "dst_node": 0})),
        "physical_200g_ecn_marks_total": ecn_total,
        "physical_200g_pfc_pause_total": pfc_total,
        "physical_200g_drop_total": drops_total,
        "top_queue_links": [{
            "link_id": int(row["link_id"]), "link": by_link_name(row),
            "queue_max_bytes": int(row["queue_max_bytes"]),
            "ecn_marks": int(row["ecn_marks"]),
            "peak_utilization": float(row["peak_utilization"]),
        } for row in queue_top],
        "top_ecn_links": [{
            "link_id": int(row["link_id"]), "link": by_link_name(row),
            "queue_max_bytes": int(row["queue_max_bytes"]),
            "ecn_marks": int(row["ecn_marks"]),
        } for row in ecn_top],
        "top_links_by_model_payload_bytes": [{
            "link_id": int(row["link_id"]), "link": by_link_name(row),
            **bytes_by_link[int(row["link_id"])],
        } for row in top_class_bytes],
        "overlap_links": overlap_file_links,
        "kv_requests": kv_by_request,
        "ep_collectives": collective_groups,
    }


def _serving_summary(path):
    rows = _read_csv(path)
    ttft, tpot, tbt = [], [], []
    ready_gap, requests = [], []
    source_by_index = {}
    for index, line in enumerate(open(
            ROOT / "experiments/pd_kv_ep/workloads/shared_nic_4p4d_ep32_azure_window_16812_16req.jsonl",
            encoding="utf-8")):
        source_by_index[index] = json.loads(line)
    for row in rows:
        ttft.append(float(row["TTFT"]))
        tpot.append(float(row["TPOT"]))
        tbt.extend(float(value) for value in json.loads(row["TBT"]))
        ready_gap.append(int(row["p2d_kv_ready_time_ns"]) -
                         int(row["prefill_completion_time_ns"]))
        source = source_by_index[int(row["request id"])]
        requests.append({
            "request_id": int(row["request id"]),
            "source_request_id": source.get("source_request_id", ""),
            "input_toks": int(row["input"]),
            "output_toks": int(row["output"]),
            "ttft_ns": float(row["TTFT"]),
            "tpot_ns": float(row["TPOT"]),
            "tbt_samples": len(json.loads(row["TBT"])),
            "prefill_completion_ns": int(row["prefill_completion_time_ns"]),
            "p2d_ready_ns": int(row["p2d_kv_ready_time_ns"]),
        })
    return {
        "source": str(path.resolve()),
        "request_count": len(rows),
        "input_tokens": sum(int(row["input"]) for row in rows),
        "declared_output_tokens": sum(int(row["output"]) for row in rows),
        "recorded_tbt_intervals": len(tbt),
        "TTFT_ns": _stats(ttft),
        "TPOT_ns": _stats(tpot),
        "token_TBT_ns": _stats(tbt),
        "p2d_ready_minus_prefill_completion_ns": _stats(ready_gap),
        "per_request": requests,
        "slo": "not computed: no matched low-load baseline for this trace/model/topology",
    }


def _write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze(root, runs, serving_csv, overlap_dir, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    names = _node_names(root)
    summaries = [
        _read_ns3_run(label, scenario, overlap_dir, names)
        for label, scenario in runs
    ]
    serving = _serving_summary(serving_csv)

    policy_rows = []
    for row in summaries:
        kv, ep = row["kv_request_handoff_span_ns"], row["ep_collective_cct_ns"]
        policy_rows.append({
            "policy": row["policy"],
            "completed_events": row["events_completed"],
            "coverage": row["completion_coverage"],
            "kv_requests": row["kv_request_count"],
            "kv_handoff_mean_ms": kv["mean"] / 1e6,
            "kv_handoff_p99_ms": kv["p99"] / 1e6,
            "kv_post_last_release_drain_mean_us": (
                row["kv_request_post_last_release_drain_ns"]["mean"] / 1e3),
            "kv_post_last_release_drain_p99_us": (
                row["kv_request_post_last_release_drain_ns"]["p99"] / 1e3),
            "kv_shard_fct_mean_us": row["p2d_shard_flow_fct_ns"]["mean"] / 1e3,
            "kv_shard_fct_p99_us": row["p2d_shard_flow_fct_ns"]["p99"] / 1e3,
            "ep_collectives": row["ep_collective_count"],
            "ep_cct_mean_us": ep["mean"] / 1e3,
            "ep_cct_p99_us": ep["p99"] / 1e3,
            "shared_link_overlap_pairs": row["shared_link_overlap_flow_pairs"],
            "links_with_overlap": row["shared_directed_links_with_overlap"],
            "max_200g_queue_mib": row["physical_200g_queue_max_bytes"] / (1024 ** 2),
            "ecn_marks_200g_total": row["physical_200g_ecn_marks_total"],
            "pfc_pause_200g_total": row["physical_200g_pfc_pause_total"],
            "drops_200g_total": row["physical_200g_drop_total"],
            "wall_seconds": row["wall_seconds"],
            "kv_priority_group_1_flows": row["data_priority_group_flow_counts"]["P2D_KV"].get("1", 0),
            "kv_priority_group_3_flows": row["data_priority_group_flow_counts"]["P2D_KV"].get("3", 0),
            "ep_priority_group_1_flows": row["data_priority_group_flow_counts"]["EP"].get("1", 0),
            "ep_priority_group_3_flows": row["data_priority_group_flow_counts"]["EP"].get("3", 0),
        })
    _write_csv(output_dir / "policy_summary.csv", list(policy_rows[0]), policy_rows)

    req_rows = []
    source_by_id = {
            i: json.loads(line)
            for i, line in enumerate(open(
                root / "experiments/pd_kv_ep/workloads/shared_nic_4p4d_ep32_azure_window_16812_16req.jsonl",
                encoding="utf-8"))}
    for index, source in source_by_id.items():
        row = {
            "request_id": index,
            "source_request_id": source.get("source_request_id", ""),
            "input_toks": int(source["input_toks"]),
            "output_toks": int(source["output_toks"]),
        }
        for summary in summaries:
            values = summary["kv_requests"].get(index)
            label = summary["policy"].lower()
            row[label + "_kv_handoff_ms"] = (
                (values["last_finish"] - values["first_start"]) / 1e6
                if values else None)
            row[label + "_kv_layer_release_span_ms"] = (
                (values["last_request"] - values["first_start"]) / 1e6
                if values else None)
            row[label + "_kv_post_last_release_drain_us"] = (
                (values["last_finish"] - values["last_request"]) / 1e3
                if values else None)
            row[label + "_kv_shards"] = values["flow_count"] if values else 0
            row[label + "_kv_bytes"] = values["bytes"] if values else 0
        req_rows.append(row)
    _write_csv(output_dir / "per_request_kv_handoff.csv",
               list(req_rows[0]), req_rows)

    _write_csv(output_dir / "serving_per_request.csv", list(serving["per_request"][0]),
               serving["per_request"])
    (output_dir / "summary.json").write_text(json.dumps({
        "experiment": "S8 4P4D EP32; 4 GPU ranks/shared 200G NIC; all scale-out physical links 200G; 1:1 leaf Clos",
        "workload": "first 16 requests from Azure 2024 code trace window 16812; original relative arrivals and token lengths preserved",
        "ns3": summaries,
        "flowsim_integrated_serving": serving,
        "interpretation_constraints": [
            "ns-3 replays the integrated FlowSim FAIR issue timestamps; ns-3 network completion is not fed back into serving metrics",
            "P2D request handoff is last required shard completion minus first required shard issue, not the sum of flow FCTs",
            "EP CCT is last peer-flow completion minus collective start",
            "FlowSim residual fluid queues are not packet queues; packet queue/ECN/PFC/drop values come from ns-3 only",
            "No EP_ONLY/KV_ONLY control was run; policy comparisons are matched FULL-trace counterfactuals, not class-isolation attribution",
        ],
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir.resolve()),
                      "policy_summary": policy_rows,
                      "serving": serving}, indent=2))


ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True,
                        help="POLICY=ns3 scenario directory; repeat once per policy")
    parser.add_argument("--serving-csv", required=True, type=Path)
    parser.add_argument("--overlap-dir", required=True, type=Path,
                        help="output directory used by analyze_model_derived_replay.py")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    runs = []
    for item in args.run:
        label, separator, path = item.partition("=")
        if not separator or label not in {"FAIR", "EP_FIRST", "KV_FIRST"}:
            parser.error("--run must be FAIR|EP_FIRST|KV_FIRST=SCENARIO_DIR")
        runs.append((label, Path(path)))
    if {label for label, _ in runs} != {"FAIR", "EP_FIRST", "KV_FIRST"}:
        parser.error("provide exactly FAIR, EP_FIRST, and KV_FIRST runs")
    analyze(ROOT, runs, args.serving_csv.resolve(), args.overlap_dir.resolve(),
            args.output_dir.resolve())


if __name__ == "__main__":
    main()
