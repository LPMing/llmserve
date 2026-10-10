#!/usr/bin/env python3
"""Matched-flow KV size and request-barrier criticality analysis for ns-3 runs."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


POLICIES = ("fair", "ep_first", "kv_first")
IDENTITY_FIELDS = (
    "request_id", "collective_id", "event_type", "layer_id", "src", "dst",
    "bytes", "issue_time_ns", "tag", "serving_role",
)


def read_events(path):
    starts, ends = {}, {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            event_id = row.get("event_id", "")
            if event_id in ("", "-1"):
                continue
            target = starts if row["phase"] == "START" else ends
            if event_id in target:
                raise ValueError("duplicate %s for event_id=%s in %s" %
                                 (row["phase"], event_id, path))
            target[event_id] = row
    if starts.keys() != ends.keys():
        raise ValueError("unmatched START/END event IDs in %s: starts=%d ends=%d" %
                         (path, len(starts), len(ends)))
    result = {}
    for event_id, start in starts.items():
        end = ends[event_id]
        if any(start[key] != end[key] for key in IDENTITY_FIELDS):
            raise ValueError("START/END identity mismatch for event_id=%s" % event_id)
        row = dict(start)
        row["network_end_ns"] = end["network_end_ns"]
        row["actual_directed_link_ids"] = end["directed_link_ids"]
        row["completion_path"] = end["path"]
        result[event_id] = row
    return result


def percentile(values, q):
    values = sorted(float(v) for v in values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def stats(values):
    values = [float(v) for v in values]
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "p99": None}
    return {
        "n": len(values), "mean": sum(values) / len(values),
        "p50": percentile(values, .50), "p95": percentile(values, .95),
        "p99": percentile(values, .99),
    }


def quantile_bins(values):
    cuts = [percentile(values, q) for q in (.25, .50, .75)]
    labels = ("Q1_smallest", "Q2", "Q3", "Q4_largest")
    def assign(value):
        if value <= cuts[0]:
            return labels[0]
        if value <= cuts[1]:
            return labels[1]
        if value <= cuts[2]:
            return labels[2]
        return labels[3]
    return cuts, assign


def csv_write(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fnum(value):
    return "NA" if value is None else "%.6g" % value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True,
                        help="Directory containing ns3_ack_reserved_{fair,ep_first,kv_first}")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--endpoint-nic-gbps", type=float, default=200.0)
    args = parser.parse_args()

    runs = {p: read_events(args.run_root / ("ns3_ack_reserved_" + p) /
                            "comm_events.csv") for p in POLICIES}
    base_ids = set(runs["fair"])
    if any(set(runs[p]) != base_ids for p in POLICIES[1:]):
        raise ValueError("policy event ledgers do not have 100% event-ID match")
    for event_id in base_ids:
        base = runs["fair"][event_id]
        for policy in POLICIES[1:]:
            candidate = runs[policy][event_id]
            for key in IDENTITY_FIELDS:
                if base[key] != candidate[key]:
                    raise ValueError("policy flow mismatch event=%s field=%s" %
                                     (event_id, key))

    kv_ids = [event_id for event_id, row in runs["fair"].items()
              if row["event_type"] == "1"]
    kv_by_request = defaultdict(list)
    for event_id in kv_ids:
        kv_by_request[int(runs["fair"][event_id]["request_id"])].append(event_id)
    request_finish = {
        request_id: max(int(runs["fair"][eid]["network_end_ns"]) for eid in ids)
        for request_id, ids in kv_by_request.items()
    }

    kv_bytes = [int(runs["fair"][eid]["bytes"]) for eid in kv_ids]
    size_cuts, size_bin = quantile_bins(kv_bytes)
    layer_labels = sorted({int(runs["fair"][eid]["layer_id"]) for eid in kv_ids})
    layer_position = {
        value: index / max(1, len(layer_labels) - 1)
        for index, value in enumerate(layer_labels)
    }
    all_fcts_fair = []
    for event_id in kv_ids:
        all_fcts_fair.append(int(runs["fair"][event_id]["network_end_ns"]) -
                             int(runs["fair"][event_id]["network_start_ns"]))
    barrier_slacks = [request_finish[int(runs["fair"][eid]["request_id"])] -
                      int(runs["fair"][eid]["network_end_ns"]) for eid in kv_ids]
    slack_cuts = [percentile(barrier_slacks, .10), percentile(barrier_slacks, .25)]

    matched = []
    for event_id in kv_ids:
        fair, ep, kv = (runs[p][event_id] for p in POLICIES)
        row = fair
        size = int(row["bytes"])
        request_id = int(row["request_id"])
        release = int(row["issue_time_ns"])
        finishes = {"fair": int(fair["network_end_ns"]),
                    "ep_first": int(ep["network_end_ns"]),
                    "kv_first": int(kv["network_end_ns"])}
        fcts = {p: finishes[p] - int(runs[p][event_id]["network_start_ns"])
                for p in POLICIES}
        # Payload-only floor assuming this one flow monopolizes its 200-Gb/s source NIC.
        serialization_ns = size * 8.0 / (args.endpoint_nic_gbps * 1e9) * 1e9
        slack = request_finish[request_id] - finishes["fair"]
        flow = {
            "event_id": int(event_id), "request_id": request_id,
            "layer_id": int(row["layer_id"]),
            # Exported layer_id is an opaque graph provenance label (2, 12, ...),
            # not the zero-based transformer layer ordinal. Normalize by its
            # observed ordering rather than misreading the encoded integer.
            "normalized_layer_position": layer_position[int(row["layer_id"])],
            "layer_ordinal_from_observed_order": layer_labels.index(int(row["layer_id"])),
            "src": int(row["src"]), "dst": int(row["dst"]), "bytes": size,
            "release_time_ns": release,
            "fair_finish_ns": finishes["fair"],
            "ep_first_finish_ns": finishes["ep_first"],
            "kv_first_finish_ns": finishes["kv_first"],
            "fair_fct_us": fcts["fair"] / 1000.0,
            "ep_first_fct_us": fcts["ep_first"] / 1000.0,
            "kv_first_fct_us": fcts["kv_first"] / 1000.0,
            "serialization_lower_bound_us": serialization_ns / 1000.0,
            "fair_fct_over_serialization": fcts["fair"] / serialization_ns,
            "ep_first_fct_over_serialization": fcts["ep_first"] / serialization_ns,
            "kv_first_fct_over_serialization": fcts["kv_first"] / serialization_ns,
            "fair_excess_delay_us": (fcts["fair"] - serialization_ns) / 1000.0,
            "ep_first_excess_delay_us": (fcts["ep_first"] - serialization_ns) / 1000.0,
            "kv_first_excess_delay_us": (fcts["kv_first"] - serialization_ns) / 1000.0,
            "ep_first_delta_fct_us": (fcts["ep_first"] - fcts["fair"]) / 1000.0,
            "ep_first_relative_fct": fcts["ep_first"] / fcts["fair"],
            "kv_first_delta_fct_us": (fcts["kv_first"] - fcts["fair"]) / 1000.0,
            "kv_first_relative_fct": fcts["kv_first"] / fcts["fair"],
            "barrier_slack_fair_us": slack / 1000.0,
            "critical_exact_last": int(slack == 0),
            "near_critical_p10": int(slack <= slack_cuts[0]),
            "near_critical_p25": int(slack <= slack_cuts[1]),
            "exposed_penalty_ep_first_us": max(0, finishes["ep_first"] -
                                                request_finish[request_id]) / 1000.0,
            "size_bin": size_bin(size),
            "fair_actual_link_ids": fair["actual_directed_link_ids"],
            "ep_first_actual_link_ids": ep["actual_directed_link_ids"],
            "kv_first_actual_link_ids": kv["actual_directed_link_ids"],
        }
        matched.append(flow)

    matched_fields = list(matched[0]) if matched else []
    csv_write(args.outdir / "matched_kv_flows.csv", matched, matched_fields)

    groups = []
    for bin_name in ("Q1_smallest", "Q2", "Q3", "Q4_largest"):
        selected = [r for r in matched if r["size_bin"] == bin_name]
        for policy in POLICIES:
            fct_key = policy + "_fct_us"
            excess_key = policy + "_excess_delay_us"
            for critical_name, predicate in (
                ("all", lambda r: True),
                ("exact_last", lambda r: bool(r["critical_exact_last"])),
                ("near_p10", lambda r: bool(r["near_critical_p10"])),
                ("near_p25", lambda r: bool(r["near_critical_p25"])),
                ("noncritical", lambda r: not bool(r["critical_exact_last"])),
            ):
                cohort = [r for r in selected if predicate(r)]
                fct_stat, excess_stat = stats([r[fct_key] for r in cohort]), stats(
                    [r[excess_key] for r in cohort])
                groups.append({
                    "size_bin": bin_name, "criticality": critical_name,
                    "policy": policy.upper(), "flows": len(cohort),
                    "total_bytes": sum(r["bytes"] for r in cohort),
                    "fct_mean_us": fct_stat["mean"], "fct_p50_us": fct_stat["p50"],
                    "fct_p95_us": fct_stat["p95"], "fct_p99_us": fct_stat["p99"],
                    "excess_mean_us": excess_stat["mean"],
                    "relative_slowdown_vs_fair_mean": (
                        sum(r["ep_first_relative_fct"] for r in cohort) / len(cohort)
                        if cohort and policy == "ep_first" else
                        sum(r["kv_first_relative_fct"] for r in cohort) / len(cohort)
                        if cohort and policy == "kv_first" else 1.0 if cohort else None),
                    "exposed_penalty_mean_us": (
                        sum(r["exposed_penalty_ep_first_us"] for r in cohort) / len(cohort)
                        if cohort else None),
                })
    csv_write(args.outdir / "size_criticality_summary.csv", groups,
              list(groups[0]) if groups else [])

    request_rows = []
    for request_id, event_ids in sorted(kv_by_request.items()):
        fair_end = request_finish[request_id]
        req = {"request_id": request_id, "shards": len(event_ids),
               "total_kv_bytes": sum(int(runs["fair"][eid]["bytes"]) for eid in event_ids),
               "fair_barrier_finish_ns": fair_end}
        for policy in POLICIES:
            req[policy + "_last_finish_ns"] = max(
                int(runs[policy][eid]["network_end_ns"]) for eid in event_ids)
            req[policy + "_handoff_span_ms"] = (
                req[policy + "_last_finish_ns"] - min(
                    int(runs[policy][eid]["network_start_ns"]) for eid in event_ids)) / 1e6
        req["ep_first_barrier_delta_us"] = (
            req["ep_first_last_finish_ns"] - fair_end) / 1000.0
        request_rows.append(req)
    csv_write(args.outdir / "request_barrier_summary.csv", request_rows,
              list(request_rows[0]) if request_rows else [])

    # Compare actual physical-link sets, not the BFS placeholder path written at START.
    actual_link_match = {
        p: sum(runs[p][eid]["actual_directed_link_ids"] ==
               runs["fair"][eid]["actual_directed_link_ids"] for eid in kv_ids)
        for p in POLICIES
    }
    slack_bytes = {}
    for label, pred in (("exact_last", lambda r: bool(r["critical_exact_last"])),
                        ("near_p10", lambda r: bool(r["near_critical_p10"])),
                        ("near_p25", lambda r: bool(r["near_critical_p25"])),
                        ("noncritical_exact", lambda r: not bool(r["critical_exact_last"]))):
        rows = [r for r in matched if pred(r)]
        slack_bytes[label] = {
            "flow_count": len(rows), "bytes": sum(r["bytes"] for r in rows),
            "fraction_of_flows": len(rows) / len(matched) if matched else None,
            "fraction_of_bytes": (sum(r["bytes"] for r in rows) /
                                  sum(r["bytes"] for r in matched)) if matched else None,
        }
    summary = {
        "matched_policy_flow_ids": len(base_ids), "matched_kv_shards": len(matched),
        "request_count": len(kv_by_request), "event_match_rate": 1.0,
        "actual_physical_link_set_matches_fair": actual_link_match,
        "kv_size_bytes": stats(kv_bytes), "kv_size_q25_q50_q75_bytes": size_cuts,
        "observed_layer_labels": layer_labels,
        "fair_barrier_slack_us": stats([r["barrier_slack_fair_us"] for r in matched]),
        "barrier_slack_p10_p25_us": slack_cuts,
        "barrier_slack_flow_and_byte_fractions": slack_bytes,
        "policy_fct_us": {p: stats([r[p + "_fct_us"] for r in matched])
                          for p in POLICIES},
        "ep_first_relative_fct_by_size": {
            b: stats([r["ep_first_relative_fct"] for r in matched
                      if r["size_bin"] == b])
            for b in ("Q1_smallest", "Q2", "Q3", "Q4_largest")},
        "ep_first_delta_fct_us_by_size": {
            b: stats([r["ep_first_delta_fct_us"] for r in matched
                      if r["size_bin"] == b])
            for b in ("Q1_smallest", "Q2", "Q3", "Q4_largest")},
        "kv_first_relative_fct_by_size": {
            b: stats([r["kv_first_relative_fct"] for r in matched
                      if r["size_bin"] == b])
            for b in ("Q1_smallest", "Q2", "Q3", "Q4_largest")},
        "serialization_reference": {
            "endpoint_nic_gbps": args.endpoint_nic_gbps,
            "definition": "payload bytes / full physical sender NIC rate; single-flow exclusive-NIC floor, not shared-NIC observed service",
            "fair_fct_over_floor": stats([r["fair_fct_over_serialization"] for r in matched]),
            "ep_first_fct_over_floor": stats([r["ep_first_fct_over_serialization"] for r in matched]),
            "kv_first_fct_over_floor": stats([r["kv_first_fct_over_serialization"] for r in matched]),
        },
    }
    (args.outdir / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    q1 = summary["ep_first_relative_fct_by_size"]["Q1_smallest"]
    q4 = summary["ep_first_relative_fct_by_size"]["Q4_largest"]
    kv_q1 = summary["kv_first_relative_fct_by_size"]["Q1_smallest"]
    kv_q4 = summary["kv_first_relative_fct_by_size"]["Q4_largest"]
    total_bytes = sum(r["bytes"] for r in matched)
    report = [
        "# KV size × request-barrier criticality (native ns-3)", "",
        "This is matched offline analysis of the corrected FAIR / EP_FIRST / KV_FIRST packet replays; no new simulation was run.", "",
        "## Match and definitions", "",
        "- Policy ledgers were matched 100% by event_id and verified against request, layer, endpoints, bytes, release timestamp, tag and serving role.",
        "- A KV shard is event_type=1. Flow FCT is END.network_end_ns minus START.network_start_ns. Request barrier is the maximum FAIR KV-shard finish per request.",
        "- The exported layer_id values are opaque provenance labels (the 48 P2D values are ordered labels such as 2, 12, ..., 472), not zero-based layer ordinals. The normalized position below is derived from their observed sorted order; ordinal 47 corresponds to the last exported P2D layer label.",
        "- Barrier slack is request FAIR barrier finish minus a shard's FAIR finish; zero means the shard finishes at the observed request barrier. It is a retrospective counterfactual label, not online-known state.",
        "- Serialization reference is payload bytes / 200-Gbps endpoint NIC, assuming a shard alone owns the sender NIC. Four GPU ranks share that physical NIC, so this is not an observed per-flow rate and excludes protocol overhead.",
        "- Actual directed-link telemetry is the union of links used by packets for each flow, not the BFS placeholder path. Policy route-set equality: %s" % json.dumps(actual_link_match, sort_keys=True),
        "", "## KV shard size distribution", "",
        "| metric | bytes |", "|---|---:|",
    ]
    for label, value in (("min", min(kv_bytes)), ("P10", percentile(kv_bytes, .10)),
                         ("Q1 / P25", size_cuts[0]), ("median / P50", size_cuts[1]),
                         ("Q3 / P75", size_cuts[2]), ("P90", percentile(kv_bytes, .90)),
                         ("P99", percentile(kv_bytes, .99)), ("max", max(kv_bytes))):
        report.append("| %s | %s |" % (label, fnum(value)))
    report += ["", "## Size sensitivity: EP_FIRST versus FAIR", "",
               "Relative penalty is computed per matched shard as FCT_EP_FIRST / FCT_FAIR. The Q bins are based only on this workload's empirical byte quartiles.", "",
               "| KV size bin | shard count | byte range (empirical) | relative FCT mean | relative FCT P95 | relative FCT P99 | ΔFCT mean (µs) | Δ excess delay mean (µs) |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for b, low, high in zip(("Q1_smallest", "Q2", "Q3", "Q4_largest"),
                            (min(kv_bytes), size_cuts[0], size_cuts[1], size_cuts[2]),
                            (size_cuts[0], size_cuts[1], size_cuts[2], max(kv_bytes))):
        cohort = [r for r in matched if r["size_bin"] == b]
        rel = stats([r["ep_first_relative_fct"] for r in cohort])
        delta = stats([r["ep_first_delta_fct_us"] for r in cohort])
        excess_delta = stats([r["ep_first_excess_delay_us"] - r["fair_excess_delay_us"] for r in cohort])
        report.append("| %s | %d | %s–%s | %s | %s | %s | %s | %s |" %
                      (b, len(cohort), fnum(low), fnum(high), fnum(rel["mean"]),
                       fnum(rel["p95"]), fnum(rel["p99"]), fnum(delta["mean"]),
                       fnum(excess_delta["mean"])))
    report += ["", "## Barrier criticality and size", "",
               "Empirical FAIR slack cutoffs: P10=%s µs; P25=%s µs. Exact-last means slack=0 (ties retained). These cutoffs describe this 16-request window and must not be generalized as universal serving thresholds." %
               (fnum(slack_cuts[0] / 1000), fnum(slack_cuts[1] / 1000)), "",
               "| cohort | flows | bytes | flow fraction | byte fraction |", "|---|---:|---:|---:|---:|"]
    for label, data in slack_bytes.items():
        report.append("| %s | %d | %s | %s | %s |" %
                      (label, data["flow_count"], data["bytes"],
                       fnum(data["fraction_of_flows"]), fnum(data["fraction_of_bytes"])))
    exact_last = [r for r in matched if r["critical_exact_last"]]
    noncritical = [r for r in matched if not r["critical_exact_last"]]
    report += ["", "### Barrier-flow layer position", "",
               "| cohort | count | mean observed layer ordinal (0–47) | layer-47 fraction |", "|---|---:|---:|---:|"]
    for label, rows in (("exact request last-shard ties", exact_last),
                        ("all other shards", noncritical)):
        ordinals = [r["layer_ordinal_from_observed_order"] for r in rows]
        report.append("| %s | %d | %s | %s |" %
                      (label, len(rows), fnum(sum(ordinals) / len(ordinals) if ordinals else None),
                       fnum(sum(o == 47 for o in ordinals) / len(ordinals) if ordinals else None)))
    report += ["", "## Request barrier response", "",
               "| metric | FAIR | EP_FIRST | KV_FIRST |", "|---|---:|---:|---:|"]
    for metric, func in (("request handoff mean (ms)", lambda row, p: row[p + "_handoff_span_ms"]),
                         ("request handoff P99 (ms)", None),
                         ("last-shard finish delta mean vs FAIR (µs)", lambda row, p: row[p + "_ep_first_barrier_delta_us"])):
        if func is None:
            vals = {p: [r[p + "_handoff_span_ms"] for r in request_rows] for p in POLICIES}
            report.append("| %s | %s | %s | %s |" % tuple([metric] + [fnum(percentile(vals[p], .99)) for p in POLICIES]))
        elif metric.startswith("last-shard"):
            vals = {p: [0.0 if p == "fair" else
                        (r[p + "_last_finish_ns"] - r["fair_barrier_finish_ns"]) / 1000.0
                        for r in request_rows] for p in POLICIES}
            report.append("| %s | %s | %s | %s |" % tuple([metric] + [fnum(sum(vals[p])/len(vals[p])) for p in POLICIES]))
        else:
            report.append("| %s | %s | %s | %s |" % tuple([metric] + [fnum(sum(func(r,p) for r in request_rows)/len(request_rows)) for p in POLICIES]))
    report += ["", "## Interpretation", "",
               "- `EP_FIRST` per-shard size sensitivity must be read alongside request-barrier slack: a larger relative FCT penalty on tiny shards is not TTFT-relevant if those shards finish well before the request's last required shard.",
               "- `ExposedPenalty` is a matched single-flow approximation: max(0, EP_FIRST shard finish − FAIR request barrier). It is not a full request resimulation.",
               "- `KV_FIRST` and `EP_FIRST` are class-wide static policies in this replay. This analysis can identify how much promoted KV was noncritical, but cannot prove an online critical-KV policy would improve serving.",
               "- This run contains only 16 requests from one Azure window; any apparent size/criticality trend is exploratory. No isolated KV_ONLY/EP_ONLY control is included here.",
               "", "## Key values", "",
               "- EP_FIRST/FAIR relative FCT mean: smallest quartile %s (n=%d), largest quartile %s (n=%d)." %
               (fnum(q1["mean"]), q1["n"], fnum(q4["mean"]), q4["n"]),
               "- KV_FIRST/FAIR relative FCT mean: smallest quartile %s, largest quartile %s." %
               (fnum(kv_q1["mean"]), fnum(kv_q4["mean"])),
               "- Total model-derived P2D shard bytes: %s across %d shards and %d requests." %
               (total_bytes, len(matched), len(kv_by_request)), ""]
    (args.outdir / "KV_SIZE_X_CRITICALITY.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
