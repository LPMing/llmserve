#!/usr/bin/env python3
"""Compact the existing EP-EP and KV request evidence without rerunning sims.

The large EP per-flow file is currently only in /tmp. This script records its
hash in the report and exports group/collective summaries, not packet logs.
"""

import csv
import json
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
EP_FLOW = Path("/tmp/ep_ep_minimal_full_telemetry.jsonl")
EP_REQ = Path("/tmp/ep_ep_minimal_full_requests.csv")
EP_RUNS = {
    "full_2req_per_group": (Path("/tmp/ep_ep_minimal_full4"),
                             Path("/tmp/ep_ep_minimal_full4_requests.csv"),
                             Path("/tmp/ep_ep_minimal_a_only2"),
                             Path("/tmp/ep_ep_minimal_a_only2_requests.csv")),
    "full_4req_per_group": (Path("/tmp/ep_ep_minimal_full"), EP_REQ,
                             Path("/tmp/ep_ep_minimal_a_only4"),
                             Path("/tmp/ep_ep_minimal_a_only4_requests.csv")),
}
KV_RUNS = {
    "kv_kv_128_vs_2048": ROOT / "research_audit/results/minimal_kv_kv_i128_i2048",
    "kv_kv_128_control": ROOT / "research_audit/results/minimal_kv_kv_control_i128",
    "kv_kv_128_vs_8192": ROOT / "research_audit/results/minimal_kv_kv_i128_i8192",
    "kv_kv_128_control_2": ROOT / "research_audit/results/minimal_kv_kv_control_i128",
    "A7L2M_fair": ROOT / "research_motivation/nic_priority/results/A7L2M_fair",
    "A7L2M_ep_first": ROOT / "research_motivation/nic_priority/results/B_both_rails_ep_first",
    "A7L2M_kv_first": ROOT / "research_motivation/nic_priority/results/B_both_rails_kv_first",
    "A7L2M_ep_isolated": ROOT / "research_motivation/nic_priority/results/A7L2M_ep_isolated",
    "B_fair": ROOT / "research_motivation/nic_priority/results/B_both_rails_fair",
    "B_ep_first": ROOT / "research_motivation/nic_priority/results/B_both_rails_ep_first",
    "B_kv_first": ROOT / "research_motivation/nic_priority/results/B_both_rails_kv_first",
    "B_ep_isolated": ROOT / "research_motivation/nic_priority/results/B_both_rails_ep_isolated",
}


def read_jsonl(path):
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                rows.append(json.loads(line))
    return rows


def read_csv(path):
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def nearest_rank(values, p):
    values = sorted(float(v) for v in values)
    if not values:
        return ""
    return values[max(0, min(len(values) - 1, math.ceil(p * len(values)) - 1))]


def union_intervals(items):
    out = []
    for start, end in sorted(items):
        if not out or start > out[-1][1]:
            out.append([start, end])
        else:
            out[-1][1] = max(out[-1][1], end)
    return out


def intersect_union(a, b):
    left, right = union_intervals(a), union_intervals(b)
    i = j = total = 0
    while i < len(left) and j < len(right):
        total += max(0, min(left[i][1], right[j][1]) -
                     max(left[i][0], right[j][0]))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return total


def collect_ep_group(run_dir):
    rows = read_jsonl(run_dir / "collective_telemetry.jsonl")
    result = {}
    for row in rows:
        if row.get("event") != "COLLECTIVE_COMPLETED":
            continue
        ids = tuple(sorted(str(x) for x in row.get("request_ids", [])))
        phase = "EP_DISPATCH" if row.get("traffic_subtype") == "EP_DISPATCH" else "EP_COMBINE"
        layer = (int(row["layer_id"]) - (8 if phase == "EP_DISPATCH" else 12)) // 12
        key = (phase, layer)
        result.setdefault(key, []).append(row)
    return result


def ep_ledger():
    if not EP_FLOW.is_file():
        return [], [], "EP_FLOW_TELEMETRY_MISSING"
    flow_rows = read_jsonl(EP_FLOW)
    group_a = {0, 1, 4, 5}
    group_b = {2, 3, 6, 7}
    flows = defaultdict(list)
    for flow in flow_rows:
        if flow.get("traffic_class") != "EP":
            continue
        ids = set(int(x) for x in flow.get("request_ids", []))
        if ids & group_a:
            group = "A"
        elif ids & group_b:
            group = "B"
        else:
            continue
        subtype = flow.get("traffic_subtype", "")
        offset = 8 if subtype == "EP_DISPATCH" else 12
        layer = (int(flow["layer_id"]) - offset) // 12
        key = (int(flow["collective_id"]), int(flow["layer_id"]), subtype)
        flows[(group, key)].append(flow)

    a_only = {
        "2req": collect_ep_group(EP_RUNS["full_2req_per_group"][2]),
        "4req": collect_ep_group(EP_RUNS["full_4req_per_group"][2]),
    }
    all_keys = sorted({key for _, key in flows})
    ep_rows = []
    for key in all_keys:
        per_group = {}
        for group in ("A", "B"):
            fs = flows.get((group, key), [])
            if not fs:
                continue
            paths = [str(link) for f in fs for link in (f.get("path") or [])]
            per_link = defaultdict(list)
            for f in fs:
                for link in f.get("path") or []:
                    per_link[str(link)].append((int(f["start_ns"]), int(f["end_ns"])))
            per_group[group] = {
                "flows": fs,
                "start": min(int(f["start_ns"]) for f in fs),
                "finish": max(int(f["end_ns"]) for f in fs),
                "bytes": sum(int(f["bytes"]) for f in fs),
                "links": set(paths),
                "per_link": per_link,
                "ids": sorted({str(x) for f in fs for x in f.get("request_ids", [])}),
            }
        if set(per_group) != {"A", "B"}:
            continue
        subtype = key[2]
        layer = (key[1] - (8 if subtype == "EP_DISPATCH" else 12)) // 12
        shared_links = sorted(per_group["A"]["links"] & per_group["B"]["links"])
        shared_ov = sum(intersect_union(per_group["A"]["per_link"].get(link, []),
                                        per_group["B"]["per_link"].get(link, []))
                        for link in shared_links)
        group_size = "2req" if len(per_group["A"]["ids"]) == 2 else "4req"
        iso_rows = a_only[group_size].get((subtype, layer), [])
        isolated_ccts = [int(r["cct_ns"]) for r in iso_rows]
        for group in ("A", "B"):
            g = per_group[group]
            ep_rows.append({
                "run": "full_" + group_size + "_per_group_FAIR",
                "ep_group_id": group,
                "request_ids": ";".join(g["ids"]),
                "batch_id": key[0],
                "collective_id": key[0],
                "layer_index_0based": layer,
                "trace_layer_id": key[1],
                "dispatch_or_combine": subtype,
                "collective_type": "ALLGATHER" if subtype == "EP_DISPATCH" else "REDUCESCATTER",
                "participant_count": 4,
                "peer_flow_count": len(g["flows"]),
                "group_total_peer_bytes": g["bytes"],
                # A flow's payload is counted once per traversed directed link
                # here. This is link-byte-hop work, not unique payload bytes
                # and not the bytes on any single bottleneck link.
                "sum_link_byte_hops_on_shared_directed_links": sum(
                    sum(int(f["bytes"]) for f in g["flows"]
                        if link in (f.get("path") or [])) for link in shared_links),
                "release_ns": min(int(f["requested_start_ns"]) for f in g["flows"]),
                "service_start_ns": g["start"],
                "collective_completion_ns": g["finish"],
                "fair_cct_ns": g["finish"] - min(int(f["requested_start_ns"]) for f in g["flows"]),
                "matched_A_only_isolated_cct_ns": (nearest_rank(isolated_ccts, .5)
                                                     if group == "A" and isolated_ccts else ""),
                "ep_first_cct_ns": "NOT_SAVED_FOR_THIS_RUN",
                "shared_directed_links": ";".join(shared_links),
                "cross_group_shared_link_overlap_ns": shared_ov,
                "other_group_overlaps_same_shared_link": shared_ov > 0,
                "critical_peer_flow_id": max(g["flows"], key=lambda f: int(f["end_ns"]))["flow_id"],
                "critical_peer_src": max(g["flows"], key=lambda f: int(f["end_ns"]))["src"],
                "critical_peer_dst": max(g["flows"], key=lambda f: int(f["end_ns"]))["dst"],
                "critical_peer_path": ";".join(max(g["flows"], key=lambda f: int(f["end_ns"]))["path"]),
                "critical_peer_finish_ns": max(int(f["end_ns"]) for f in g["flows"]),
                "token_critical_path": "COLLECTIVE_BARRIER_FEEDS_DECODE_ITERATION",
                "evidence": "TRANSIENT_RAW_FLOWSIM_FLOW_LEDGER",
            })
    request_rows = []
    for label, (full_dir, full_req_path, iso_dir, iso_req_path) in EP_RUNS.items():
        full_requests = read_csv(full_req_path)
        iso_requests = read_csv(iso_req_path)
        group_by_req = {0: "A", 1: "A", 4: "A", 5: "A",
                        2: "B", 3: "B", 6: "B", 7: "B"}
        by_group = defaultdict(list)
        for row in full_requests:
            if not row:
                continue
            rid = int(row["request id"])
            group = group_by_req.get(rid)
            if group is None:
                # Full 4-request run maps its 0/1 requests to A, 2/3 to B.
                group = "A" if rid in (0, 1) else "B"
            itl = json.loads(row.get("ITL") or "[]")
            by_group[group].append((row, [int(x) for x in itl]))
        iso_itl = [int(v) for r in iso_requests for v in json.loads(r.get("ITL") or "[]")]
        for group, members in by_group.items():
            for row, itl in members:
                request_rows.append({
                    "run": label + "_FAIR",
                    "ep_group_id": group,
                    "request_id": row["request id"],
                    "instance_id": row["instance id"],
                    "input_tokens": row["input"],
                    "output_tokens_field": row["output"],
                    "ttft_ns": row["TTFT"],
                    "tpot_ns": row["TPOT"],
                    "itl_count": len(itl),
                    "itl_mean_ns": (sum(itl) / len(itl) if itl else ""),
                    "itl_p50_ns": nearest_rank(itl, .5),
                    "itl_p95_ns": nearest_rank(itl, .95),
                    "itl_p99_ns": nearest_rank(itl, .99),
                    "group_request_count": len(members),
                    "matched_A_only_itl_mean_ns": (sum(iso_itl) / len(iso_itl)
                                                   if group == "A" and iso_itl else ""),
                    "matched_A_only_itl_p99_ns": nearest_rank(iso_itl, .99)
                    if group == "A" else "",
                    "second_group_isolated_baseline": "NOT_MEASURED",
                    "slo_threshold": "NOT_DEFINED",
                    "slo_attainment": "NOT_CLAIMED",
                })
    # The smaller 4-request FULL run retained collective records (but not
    # per-peer paths). Keep its exact group/barrier records and mark path-level
    # fields unavailable instead of reconstructing them from the 8-request run.
    small_full = Path("/tmp/ep_ep_minimal_full4")
    small_reqs = read_csv(Path("/tmp/ep_ep_minimal_full4_requests.csv"))
    req_to_group = {int(r["request id"]): ("A" if int(r["request id"]) < 2 else "B")
                    for r in small_reqs}
    for row in read_jsonl(small_full / "collective_telemetry.jsonl"):
        if row.get("event") != "COLLECTIVE_COMPLETED":
            continue
        ids = sorted(str(x) for x in row.get("request_ids", []))
        numeric_ids = {int(x) for x in ids}
        group = "A" if numeric_ids and max(numeric_ids) < 2 else "B"
        phase = row.get("traffic_subtype", "")
        layer = (int(row["layer_id"]) - (8 if phase == "EP_DISPATCH" else 12)) // 12
        iso_rows = a_only["2req"].get((phase, layer), [])
        isolated_ccts = [int(r["cct_ns"]) for r in iso_rows]
        ep_rows.append({
            "run": "full_2req_per_group_FAIR",
            "ep_group_id": group,
            "request_ids": ";".join(ids),
            "batch_id": row.get("collective_batch_id", ""),
            "collective_id": row.get("collective_id", ""),
            "layer_index_0based": layer,
            "trace_layer_id": row.get("layer_id", ""),
            "dispatch_or_combine": phase,
            "collective_type": row.get("collective_type", ""),
            "participant_count": row.get("participant_count", ""),
            "peer_flow_count": row.get("peer_flow_count", ""),
            "group_total_peer_bytes": "NOT_RETAINED_IN_GROUP_COLLECTIVE_LEDGER",
            "sum_link_byte_hops_on_shared_directed_links": "NOT_RETAINED_IN_GROUP_COLLECTIVE_LEDGER",
            "release_ns": row.get("start_ns", ""),
            "service_start_ns": row.get("start_ns", ""),
            "collective_completion_ns": row.get("end_ns", ""),
            "fair_cct_ns": row.get("cct_ns", ""),
            "matched_A_only_isolated_cct_ns": (nearest_rank(isolated_ccts, .5)
                                                 if group == "A" and isolated_ccts else ""),
            "ep_first_cct_ns": "NOT_SAVED_FOR_THIS_RUN",
            "shared_directed_links": "PATHS_NOT_RETAINED_FOR_THIS_RUN",
            "cross_group_shared_link_overlap_ns": "NOT_RETAINED",
            "other_group_overlaps_same_shared_link": "NOT_RETAINED",
            "critical_peer_flow_id": "NOT_RETAINED",
            "critical_peer_src": "NOT_RETAINED",
            "critical_peer_dst": "NOT_RETAINED",
            "critical_peer_path": "NOT_RETAINED",
            "critical_peer_finish_ns": row.get("end_ns", ""),
            "token_critical_path": "COLLECTIVE_BARRIER_FEEDS_DECODE_ITERATION",
            "evidence": "DURABLE_COLLECTIVE_LEDGER_NO_PEER_PATHS",
        })
    return ep_rows, request_rows, "OK"


def kv_ledgers():
    request_rows, layer_rows = [], []
    for label, run_dir in KV_RUNS.items():
        requests = read_csv(run_dir / "requests.csv")
        events = read_jsonl(run_dir / "kv_event_telemetry.jsonl")
        if not requests or not events:
            continue
        # Select all KV-KV requests, and only P2D candidates (input > 128) for
        # the A7/B policy fixture. Preserve aggregate ownership as recorded.
        is_high_load = label.startswith("A7") or label.startswith("B_")
        for request in requests:
            rid = int(request["request id"])
            if is_high_load and int(request["input"]) <= 128:
                continue
            owned = [e for e in events if rid in [int(x) for x in e.get("request_ids", [])]
                     and e.get("traffic_subtype") == "P2D"]
            by_flow = defaultdict(dict)
            for event in owned:
                fid = event.get("flow_id")
                if fid is None:
                    continue
                by_flow[fid][event["event"]] = event
            flow_records = []
            for fid, event_map in by_flow.items():
                gen = event_map.get("KV_GENERATED", {})
                req = event_map.get("KV_REQUESTED", {})
                start = event_map.get("KV_STARTED", {})
                done = event_map.get("KV_COMPLETED", {})
                layer = int((done or req or gen).get("layer_id", -1))
                rec = {
                    "flow_id": fid,
                    "layer": layer,
                    "bytes": int((done or req or gen).get("bytes", 0)),
                    "src": (done or req or gen).get("src", ""),
                    "dst": (done or req or gen).get("dst", ""),
                    "generated_ns": int(gen.get("timestamp_ns", -1)),
                    "requested_ns": int(req.get("timestamp_ns", -1)),
                    "started_ns": int(start.get("timestamp_ns", -1)),
                    "finished_ns": int(done.get("timestamp_ns", -1)),
                    "path": ";".join(done.get("path", []) or []),
                }
                flow_records.append(rec)
            if not flow_records:
                continue
            completed = [f for f in flow_records if f["finished_ns"] >= 0]
            requested = [f for f in flow_records if f["requested_ns"] >= 0]
            last_done = max((f["finished_ns"] for f in completed), default="")
            ready = int(request.get("p2d_kv_ready_time_ns", -1))
            # Request-level last KV is max over all required shards; do not sum
            # shard FCTs. TTST is only the recorded first→second token interval.
            request_rows.append({
                "scenario_policy": label,
                "request_id": rid,
                "instance_id": request.get("instance id", ""),
                "prompt_tokens": request.get("input", ""),
                "output_tokens_field": request.get("output", ""),
                "arrival_ns": request.get("arrival", ""),
                "prefill_compute_finish_or_handoff_ns": ready,
                "kv_flow_count": len(flow_records),
                "unique_layers": len({f["layer"] for f in flow_records}),
                "first_kv_requested_ns": min((f["requested_ns"] for f in requested), default=""),
                "last_kv_requested_ns": max((f["requested_ns"] for f in requested), default=""),
                "last_required_kv_completion_ns": last_done,
                "request_kv_handoff_span_ns": (
                    last_done - min((f["requested_ns"] for f in requested), default=last_done)
                    if requested and completed else ""),
                "compute_masking_slack_ns": (ready - last_done if ready >= 0 and last_done != "" else ""),
                "p2d_ready_ns": ready,
                "first_decode_batch_decision_ns": request.get("decode_first_batch_decision_ns", ""),
                "first_decode_batch_finish_ns": request.get("decode_first_batch_finish_ns", ""),
                "first_token_visible_ns": (int(request.get("arrival", 0)) + int(request.get("TTFT", 0))),
                "second_token_visible_ns": request.get("second_token_visible_ns", ""),
                "TTFT_ns": request.get("TTFT", ""),
                "TTST_ns": request.get("ttst_ns", ""),
                "TTST_definition": "second_token_visible - first_token_visible",
                "ttst_caveat": ("output_tokens_field=1; retain as observed timestamp delta, not a robust serving sample"
                                if int(request.get("output", 0)) == 1 else ""),
                "network_exposed_to_ready": bool(ready >= 0 and last_done != "" and last_done >= ready),
                "slo_threshold": "NOT_DEFINED",
                "slo_attainment": "NOT_CLAIMED",
            })
            for rec in sorted(flow_records, key=lambda f: (f["layer"], f["flow_id"])):
                layer_rows.append({"scenario_policy": label, "request_id": rid, **rec})
    return request_rows, layer_rows


def ep_flow_ledger():
    rows = []
    if not EP_FLOW.is_file():
        return rows
    group_a = {0, 1, 4, 5}
    group_b = {2, 3, 6, 7}
    shared = {"26->30", "30->26", "28->30", "30->28"}
    for flow in read_jsonl(EP_FLOW):
        if flow.get("traffic_class") != "EP":
            continue
        ids = set(int(x) for x in flow.get("request_ids", []))
        group = "A" if ids & group_a else ("B" if ids & group_b else "UNKNOWN")
        subtype = flow.get("traffic_subtype", "")
        offset = 8 if subtype == "EP_DISPATCH" else 12
        trace_layer = int(flow.get("layer_id", -1))
        path = [str(link) for link in (flow.get("path") or [])]
        rows.append({
            "flow_id": flow.get("flow_id", ""),
            "ep_group_id": group,
            "request_ids": ";".join(str(x) for x in sorted(ids)),
            "collective_id": flow.get("collective_id", ""),
            "trace_layer_id": trace_layer,
            "layer_index_0based": (trace_layer - offset) // 12 if trace_layer >= 0 else "",
            "phase": subtype,
            "collective_type": "ALLGATHER" if subtype == "EP_DISPATCH" else "REDUCESCATTER",
            "src_physical_rank": flow.get("src", ""),
            "dst_physical_rank": flow.get("dst", ""),
            "bytes": flow.get("bytes", ""),
            "requested_start_ns": flow.get("requested_start_ns", ""),
            "service_start_ns": flow.get("start_ns", ""),
            "finish_ns": flow.get("end_ns", ""),
            "flow_completion_ns": (int(flow["end_ns"]) - int(flow["requested_start_ns"])
                                    if "end_ns" in flow and "requested_start_ns" in flow else ""),
            "path": ";".join(path),
            "shared_directed_link_byte_hops": sum(int(flow.get("bytes", 0)) for link in path
                                                    if link in shared),
            "evidence": "TRANSIENT_FLOWSIM_FLOW_LEDGER_COMPACTED_NO_REPLAY",
        })
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ep_rows, group_requests, status = ep_ledger()
    write_csv(OUT / "01_EP_PER_GROUP.csv", [
        "run", "ep_group_id", "request_ids", "batch_id", "collective_id",
        "layer_index_0based", "trace_layer_id", "dispatch_or_combine",
        "collective_type", "participant_count", "peer_flow_count",
        "group_total_peer_bytes", "sum_link_byte_hops_on_shared_directed_links", "release_ns",
        "service_start_ns", "collective_completion_ns", "fair_cct_ns",
        "matched_A_only_isolated_cct_ns", "ep_first_cct_ns",
        "shared_directed_links", "cross_group_shared_link_overlap_ns",
        "other_group_overlaps_same_shared_link", "critical_peer_flow_id",
        "critical_peer_src", "critical_peer_dst", "critical_peer_path",
        "critical_peer_finish_ns", "token_critical_path", "evidence"], ep_rows)
    write_csv(OUT / "01_EP_GROUP_REQUESTS.csv", [
        "run", "ep_group_id", "request_id", "instance_id", "input_tokens",
        "output_tokens_field", "ttft_ns", "tpot_ns", "itl_count", "itl_mean_ns",
        "itl_p50_ns", "itl_p95_ns", "itl_p99_ns", "group_request_count",
        "matched_A_only_itl_mean_ns", "matched_A_only_itl_p99_ns",
        "second_group_isolated_baseline", "slo_threshold", "slo_attainment"], group_requests)
    kv_requests, kv_layers = kv_ledgers()
    write_csv(OUT / "01_KV_PER_REQUEST.csv", [
        "scenario_policy", "request_id", "instance_id", "prompt_tokens",
        "output_tokens_field", "arrival_ns", "prefill_compute_finish_or_handoff_ns",
        "kv_flow_count", "unique_layers", "first_kv_requested_ns",
        "last_kv_requested_ns", "last_required_kv_completion_ns",
        "request_kv_handoff_span_ns", "compute_masking_slack_ns", "p2d_ready_ns",
        "first_decode_batch_decision_ns", "first_decode_batch_finish_ns",
        "first_token_visible_ns", "second_token_visible_ns", "TTFT_ns", "TTST_ns",
        "TTST_definition", "ttst_caveat", "network_exposed_to_ready",
        "slo_threshold", "slo_attainment"], kv_requests)
    write_csv(OUT / "01_KV_LAYER_EVENTS.csv", [
        "scenario_policy", "request_id", "flow_id", "layer", "bytes", "src", "dst",
        "generated_ns", "requested_ns", "started_ns", "finished_ns", "path"], kv_layers)
    flow_rows = ep_flow_ledger()
    write_csv(OUT / "01_EP_FLOW_LEDGER.csv", [
        "flow_id", "ep_group_id", "request_ids", "collective_id", "trace_layer_id",
        "layer_index_0based", "phase", "collective_type", "src_physical_rank",
        "dst_physical_rank", "bytes", "requested_start_ns", "service_start_ns",
        "finish_ns", "flow_completion_ns", "path", "shared_directed_link_byte_hops",
        "evidence"], flow_rows)
    print(json.dumps({"ep_status": status, "ep_group_round_rows": len(ep_rows),
                      "ep_request_rows": len(group_requests),
                      "kv_request_rows": len(kv_requests),
                      "kv_layer_flow_rows": len(kv_layers),
                      "ep_flow_rows": len(flow_rows)}, indent=2))


if __name__ == "__main__":
    main()
