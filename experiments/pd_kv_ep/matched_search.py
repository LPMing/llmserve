#!/usr/bin/env python3
"""Generate and compare matched two-request KV/EP experiments.

The two runs must use the same model, topology, seed, and request contents.
Only request B's arrival time is allowed to differ.  The comparison uses
request/collective metadata and exact directed-link intervals; it never uses
the P2D/EP envelope as evidence of contention.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from semantic_events import is_decode_ep, is_p2d_kv


def percentile(values, fraction):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def write_matched_workload(path, b_arrival_ns, a_input=64, a_output=128,
                           b_input=512, b_output=1, a_count=1, b_count=1,
                           b_spacing_ns=0):
    """Write A decode requests followed by native B P2D requests.

    A rows arrive at time zero to establish Decode EP activity. B rows differ
    only by their arrival offset/spacing across matched runs. Communication
    bytes remain entirely model-derived.
    """
    if a_count < 1 or b_count < 1:
        raise ValueError("a_count and b_count must both be positive")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(a_count):
        token_base = 1 + index * (a_input + a_output + 32)
        rows.append({
            "input_toks": a_input,
            "output_toks": a_output,
            "arrival_time_ns": 0,
            "input_tok_ids": list(range(token_base, token_base + a_input)),
            "output_tok_ids": list(range(token_base + a_input,
                                          token_base + a_input + a_output)),
        })
    for index in range(b_count):
        token_base = 1000000 + index * (b_input + b_output + 32)
        rows.append({
            "input_toks": b_input,
            "output_toks": b_output,
            "arrival_time_ns": int(b_arrival_ns + index * b_spacing_ns),
            "input_tok_ids": list(range(token_base, token_base + b_input)),
            "output_tok_ids": list(range(token_base + b_input,
                                          token_base + b_input + b_output)),
        })
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


def _read_timeline(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = []
        for row in csv.DictReader(stream):
            try:
                row["start_num"] = int(row["start"])
                row["end_num"] = int(row["end"])
                row["bytes_num"] = int(row["bytes"])
            except (KeyError, TypeError, ValueError):
                continue
            if row["end_num"] >= row["start_num"]:
                rows.append(row)
        return rows


def _ids(row):
    value = row.get("active_request_ids", "") or row.get("request_id", "")
    return tuple(sorted((item for item in value.replace(";", ",").split(",")
                         if item != ""), key=lambda item: int(item)))


def _collectives(rows, request_ids=("0",)):
    """Aggregate flow rows into collective-level records for Request A."""
    groups = {}
    for row in rows:
        if not is_decode_ep(row):
            continue
        if _ids(row) != tuple(sorted((str(value) for value in request_ids),
                                     key=lambda item: int(item))):
            continue
        collective = row.get("collective_id", "")
        if not collective:
            continue
        key = (row["event_type"], row.get("layer_id", ""), collective,
               _ids(row))
        value = groups.setdefault(key, {
            "event_type": row["event_type"],
            "layer_id": row.get("layer_id", ""),
            "collective_id": collective,
            "active_request_ids": ",".join(_ids(row)),
            "start": row["start_num"],
            "end": row["end_num"],
            "bytes": 0,
            "flow_count": 0,
            "participants": set(),
        })
        value["start"] = min(value["start"], row["start_num"])
        value["end"] = max(value["end"], row["end_num"])
        value["bytes"] += row["bytes_num"]
        value["flow_count"] += 1
        value["participants"].add((row.get("src", ""), row.get("dst", "")))

    ordered = sorted(groups.values(), key=lambda item: (
        item["event_type"], item["layer_id"], item["start"],
        item["collective_id"]))
    ordinals = defaultdict(int)
    for item in ordered:
        ordinal_key = (item["event_type"], item["layer_id"],
                       item["active_request_ids"])
        item["decode_step"] = ordinals[ordinal_key]
        ordinals[ordinal_key] += 1
        item["cct_ns"] = item["end"] - item["start"]
        item["participants_text"] = ";".join(
            "%s>%s" % pair for pair in sorted(item["participants"]))
    return ordered


def _match_collectives(no_overlap, overlap):
    no_by_key = {(row["event_type"], row["layer_id"], row["decode_step"],
                  row["active_request_ids"]): row for row in no_overlap}
    ov_by_key = {(row["event_type"], row["layer_id"], row["decode_step"],
                 row["active_request_ids"]): row for row in overlap}
    rows = []
    for key in sorted(set(no_by_key) | set(ov_by_key)):
        base = no_by_key.get(key)
        mixed = ov_by_key.get(key)
        same_payload = bool(base and mixed and
                            base["bytes"] == mixed["bytes"] and
                            base["flow_count"] == mixed["flow_count"] and
                            base["participants"] == mixed["participants"])
        row = {
            "event_type": key[0],
            "layer_id": key[1],
            "decode_step": key[2],
            "active_request_ids": key[3],
            "baseline_collective_id": base["collective_id"] if base else "",
            "overlap_collective_id": mixed["collective_id"] if mixed else "",
            "baseline_bytes": base["bytes"] if base else "",
            "overlap_bytes": mixed["bytes"] if mixed else "",
            "baseline_flow_count": base["flow_count"] if base else "",
            "overlap_flow_count": mixed["flow_count"] if mixed else "",
            "baseline_participants": base["participants_text"] if base else "",
            "overlap_participants": mixed["participants_text"] if mixed else "",
            "baseline_cct_ns": base["cct_ns"] if base else "",
            "overlap_cct_ns": mixed["cct_ns"] if mixed else "",
            "cct_slowdown": (mixed["cct_ns"] / base["cct_ns"]
                             if same_payload and base["cct_ns"] > 0 else ""),
            "same_payload": same_payload,
        }
        rows.append(row)
    return rows


def _read_overlap_collective_ids(path, timeline_rows=None, kv_request_ids=None):
    if path is None or not path.exists():
        return set()
    by_event = {}
    if timeline_rows is not None:
        by_event = {row.get("event_id", ""): row for row in timeline_rows}
    requested = ({str(value) for value in kv_request_ids}
                 if kv_request_ids is not None else None)
    with path.open(newline="", encoding="utf-8") as stream:
        ids = set()
        for row in csv.DictReader(stream):
            if not row.get("ep_collective_id"):
                continue
            if requested is not None:
                kv = by_event.get(row.get("kv_event_id", ""), {})
                if kv.get("request_id", "") not in requested:
                    continue
            ids.add(row["ep_collective_id"])
        return ids


def _count_overlap_rows(path, collective_ids, timeline_rows=None,
                        kv_request_ids=None):
    """Count exact-link rows for a run-local set of EP collective IDs."""
    if path is None or not path.exists() or not collective_ids:
        return 0
    by_event = {}
    if timeline_rows is not None:
        by_event = {row.get("event_id", ""): row for row in timeline_rows}
    requested = ({str(value) for value in kv_request_ids}
                 if kv_request_ids is not None else None)
    count = 0
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("ep_collective_id") not in collective_ids:
                continue
            if requested is not None:
                kv = by_event.get(row.get("kv_event_id", ""), {})
                if kv.get("request_id", "") not in requested:
                    continue
            count += 1
    return count


def _kv_summary(rows, request_ids=("1",)):
    requested = {str(value) for value in request_ids}
    events = [row for row in rows if is_p2d_kv(row) and
              row.get("request_id", "") in requested]
    if not events:
        return {"flow_count": 0, "bytes": 0, "start": None, "end": None,
                "duration_ns": None}
    start = min(row["start_num"] for row in events)
    end = max(row["end_num"] for row in events)
    return {"flow_count": len(events),
            "bytes": sum(row["bytes_num"] for row in events),
            "start": start, "end": end, "duration_ns": end - start}


def compare(no_overlap_timeline, overlap_timeline, output, no_overlap_name="NO_OVERLAP",
            overlap_name="OVERLAP", overlap_links=None, baseline_links=None,
            target_request_ids=("0",), kv_request_ids=("1",)):
    no_rows = _read_timeline(no_overlap_timeline)
    ov_rows = _read_timeline(overlap_timeline)
    no_collectives = _collectives(no_rows, target_request_ids)
    ov_collectives = _collectives(ov_rows, target_request_ids)
    focus_ids = _read_overlap_collective_ids(overlap_links, ov_rows,
                                              kv_request_ids)
    if focus_ids:
        focus_keys = {
            (row["event_type"], row["layer_id"], row["decode_step"],
             row["active_request_ids"])
            for row in ov_collectives if row["collective_id"] in focus_ids
        }
        no_collectives = [row for row in no_collectives if (
            row["event_type"], row["layer_id"], row["decode_step"],
            row["active_request_ids"]) in focus_keys]
        ov_collectives = [row for row in ov_collectives if (
            row["event_type"], row["layer_id"], row["decode_step"],
            row["active_request_ids"]) in focus_keys]
    matched = _match_collectives(no_collectives, ov_collectives)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(matched[0]) if matched else [
        "event_type", "layer_id", "decode_step", "active_request_ids",
        "baseline_collective_id", "overlap_collective_id", "baseline_bytes",
        "overlap_bytes", "baseline_flow_count", "overlap_flow_count",
        "baseline_participants", "overlap_participants", "baseline_cct_ns",
        "overlap_cct_ns", "cct_slowdown", "same_payload"]
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(matched)

    no_kv = _kv_summary(no_rows, kv_request_ids)
    ov_kv = _kv_summary(ov_rows, kv_request_ids)
    valid = [row for row in matched if row["same_payload"]]
    baseline_ccts = [float(row["baseline_cct_ns"]) for row in valid
                     if row["baseline_cct_ns"] != ""]
    overlap_ccts = [float(row["overlap_cct_ns"]) for row in valid
                    if row["overlap_cct_ns"] != ""]
    baseline_focus_ids = {row["baseline_collective_id"] for row in valid
                          if row["baseline_collective_id"]}
    overlap_focus_ids = {row["overlap_collective_id"] for row in valid
                         if row["overlap_collective_id"]}
    baseline_exact_count = _count_overlap_rows(
        baseline_links, baseline_focus_ids, no_rows, kv_request_ids)
    overlap_exact_count = _count_overlap_rows(
        overlap_links, overlap_focus_ids, ov_rows, kv_request_ids)
    summary = {
        "baseline": no_overlap_name,
        "overlap": overlap_name,
        "evidence_rule": "only same-payload Request-A collectives are compared",
        "target_request_ids": [str(value) for value in target_request_ids],
        "kv_request_ids": [str(value) for value in kv_request_ids],
        "collectives": {
            "baseline_request_a": len(no_collectives),
            "overlap_request_a": len(ov_collectives),
            "matched_same_payload": len(valid),
            "all_same_payload": bool(valid) and len(valid) == len(no_collectives) == len(ov_collectives),
            "max_cct_slowdown": max((float(row["cct_slowdown"])
                                      for row in valid if row["cct_slowdown"] != ""),
                                     default=None),
            "baseline_cct_p50_ns": percentile(baseline_ccts, .50),
            "baseline_cct_p95_ns": percentile(baseline_ccts, .95),
            "baseline_cct_p99_ns": percentile(baseline_ccts, .99),
            "overlap_cct_p50_ns": percentile(overlap_ccts, .50),
            "overlap_cct_p95_ns": percentile(overlap_ccts, .95),
            "overlap_cct_p99_ns": percentile(overlap_ccts, .99),
            "p50_cct_slowdown": (
                percentile(overlap_ccts, .50) / percentile(baseline_ccts, .50)
                if percentile(baseline_ccts, .50) else None),
            "p95_cct_slowdown": (
                percentile(overlap_ccts, .95) / percentile(baseline_ccts, .95)
                if percentile(baseline_ccts, .95) else None),
            "p99_cct_slowdown": (
                percentile(overlap_ccts, .99) / percentile(baseline_ccts, .99)
                if percentile(baseline_ccts, .99) else None),
            "focus_rule": (
                "EP collective ids appearing in exact OVERLAP directed-link rows"
                if focus_ids else "all Request-A-only collectives"
            ),
        },
        "kv_request_b": {
            "baseline": no_kv,
            "overlap": ov_kv,
            "duration_slowdown": (ov_kv["duration_ns"] / no_kv["duration_ns"]
                                   if no_kv["duration_ns"] and ov_kv["duration_ns"] is not None else None),
            "bytes_equal": no_kv["bytes"] == ov_kv["bytes"],
            "flow_count_equal": no_kv["flow_count"] == ov_kv["flow_count"],
        },
        "matched_collectives_csv": str(output),
        "exact_overlap_focus": {
            "baseline_matched_collective_count": len(baseline_focus_ids),
            "overlap_matched_collective_count": len(overlap_focus_ids),
            "baseline_exact_overlap_rows": baseline_exact_count,
            "overlap_exact_overlap_rows": overlap_exact_count,
            "baseline_focus_isolated": baseline_exact_count == 0,
            "overlap_directed_link_csv": str(overlap_links) if overlap_links else None,
            "baseline_directed_link_csv": str(baseline_links) if baseline_links else None,
        },
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-overlap", type=Path, required=False)
    parser.add_argument("--overlap", type=Path, required=False)
    parser.add_argument("--output", type=Path, required=False)
    parser.add_argument("--baseline-name", default="NO_OVERLAP")
    parser.add_argument("--overlap-name", default="OVERLAP")
    parser.add_argument("--overlap-links", type=Path,
                        help="exact OVERLAP directed-link rows used to select focus collectives")
    parser.add_argument("--baseline-links", type=Path,
                        help="baseline directed-link rows retained as an audit reference")
    parser.add_argument("--write-workload", type=Path)
    parser.add_argument("--b-arrival-ns", type=int, default=0)
    parser.add_argument("--a-input", type=int, default=64)
    parser.add_argument("--a-output", type=int, default=128)
    parser.add_argument("--b-input", type=int, default=512)
    parser.add_argument("--b-output", type=int, default=1)
    parser.add_argument("--a-count", type=int, default=1)
    parser.add_argument("--b-count", type=int, default=1)
    parser.add_argument("--b-spacing-ns", type=int, default=0)
    parser.add_argument("--target-request-ids", default="0",
                        help="comma-separated active Decode request IDs")
    parser.add_argument("--kv-request-ids", default="1",
                        help="comma-separated native P2D request IDs")
    args = parser.parse_args()
    if args.write_workload:
        write_matched_workload(args.write_workload, args.b_arrival_ns,
                               args.a_input, args.a_output, args.b_input,
                               args.b_output, args.a_count, args.b_count,
                               args.b_spacing_ns)
        print(str(args.write_workload))
    if args.no_overlap and args.overlap:
        if not args.output:
            parser.error("--output is required when comparing two runs")
        compare(args.no_overlap, args.overlap, args.output,
                no_overlap_name=args.baseline_name,
                overlap_name=args.overlap_name,
                overlap_links=args.overlap_links,
                baseline_links=args.baseline_links,
                target_request_ids=[item for item in args.target_request_ids.split(",")
                                    if item],
                kv_request_ids=[item for item in args.kv_request_ids.split(",")
                                if item])


if __name__ == "__main__":
    main()
