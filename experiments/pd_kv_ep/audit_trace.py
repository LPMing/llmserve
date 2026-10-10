#!/usr/bin/env python3
"""Extract semantic and timed communication rows without fake timing."""

import argparse
import bisect
import csv
import json
from pathlib import Path

from analyze_results import write_directed_link_overlap


def parse_trace(path):
    rows = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        fields = raw.split()
        if fields and fields[0] == "EXPERT" and len(fields) >= 4:
            event_type = "EP_COMBINE" if fields[1] == "END" else "EP_DISPATCH"
            try:
                comm_size = int(fields[3])
            except ValueError:
                continue
            if comm_size <= 0 or fields[2] == "NONE":
                continue
            rows.append({
                "trace_order": len(rows),
                "line_number": line_number,
                "request_id": "",
                "event_type": event_type,
                "src": "",
                "dst": "",
                "bytes": comm_size,
                "compute_ns": "",
                "start": "",
                "end": "",
                "path": "",
                "timing_status": "not_available_from_trace_text",
                "comm_type": fields[2],
                "misc": "",
            })
            continue
        if len(fields) < 11 or fields[0] in {"Layername", "COLOCATED", "PREFILL", "DECODE"}:
            continue
        try:
            (layer, comp_ns, input_loc, input_size, weight_loc, weight_size,
             output_loc, output_size, comm_type, comm_size, misc) = fields[:11]
            comp_ns = int(comp_ns)
            comm_size = int(comm_size)
        except (ValueError, IndexError):
            continue
        upper = comm_type.upper()
        if layer.startswith("qkv_proj") and comm_size > 0:
            event_type = "P2D_KV"
        elif upper.startswith(("ALLGATHER", "ALLTOALL")) and comm_size > 0:
            event_type = "EP_DISPATCH"
        elif upper.startswith(("REDUCESCATTER", "ALLTOALL")) and comm_size > 0:
            event_type = "EP_COMBINE"
        else:
            continue
        rows.append({
            "trace_order": len(rows),
            "line_number": line_number,
            "request_id": "",
            "event_type": event_type,
            "src": "",
            "dst": "",
            "bytes": comm_size,
            "compute_ns": comp_ns,
            "start": "",
            "end": "",
            "path": "",
            "timing_status": "not_available_from_trace_text",
            "comm_type": comm_type,
            "misc": misc,
        })
    return rows


def _read_backend_events(path):
    """Join ns-3 START and END rows into completed communication intervals."""
    starts = {}
    ends = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            try:
                key = row.get("event_id", "")
                if not key or key == "-1":
                    key = (row["src"], row["dst"], row["port"])
                if row["phase"] == "START":
                    starts[key] = row
                elif row["phase"] == "END":
                    ends[key] = row
            except KeyError:
                continue
    events = []
    for key, row in starts.items():
        end = ends.get(key)
        if end is None:
            continue
        try:
            start_raw = row.get("network_start_ns") or row.get("start_ns")
            end_raw = end.get("network_end_ns") or end.get("end_ns")
            events.append({
                "src": row["src"],
                "dst": row["dst"],
                "port": row["port"],
                "tag": row["tag"],
                "bytes": int(row["bytes"]),
                "event_id": row.get("event_id", ""),
                "request_id": row.get("request_id", ""),
                "collective_id": row.get("collective_id", ""),
                "event_type_code": row.get("event_type", "0"),
                "layer_id": row.get("layer_id", ""),
                "active_request_ids": row.get("active_request_ids", ""),
                "serving_role": row.get("serving_role", ""),
                "start": int(start_raw),
                "end": int(end_raw),
                "path": row.get("path", ""),
                "directed_link_ids": row.get("directed_link_ids", ""),
            })
        except (TypeError, ValueError):
            continue
    return events


def _read_issue_events(path):
    """Read optional ASTRA issue/callback rows emitted by the debug hook."""
    if path is None or not path.exists():
        return []
    events = []
    with path.open(encoding="utf-8") as stream:
        for raw in stream:
            fields = raw.rstrip("\n").split(",")
            if len(fields) < 6:
                continue
            phase, sys_id, tick, node_id, node_type, name = fields[:6]
            try:
                event = {
                    "phase": phase,
                    "sys": sys_id,
                    "tick": int(tick),
                    "node": node_id,
                    "type": node_type,
                    "name": name,
                    "request_ids": "",
                    "collective_id": "",
                }
                if len(fields) >= 15:
                    event.update({
                        "comm_src": fields[6],
                        "comm_dst": fields[7],
                        "comm_tag": fields[8],
                        "comm_size": fields[9],
                        "request_id": fields[10],
                        "collective_id": fields[11],
                        "layer_id": fields[12],
                        "event_type": fields[13],
                        "request_ids": fields[14],
                    })
                events.append(event)
            except ValueError:
                continue
    return events


def _build_issue_index(issue_events):
    index = {}
    for row in issue_events:
        if row["phase"] != "ISSUE":
            continue
        if "COMM_COLL_NODE" not in row["name"] and "COMM_SEND_NODE" not in row["name"]:
            continue
        index.setdefault(row["sys"], []).append(row)
    return {
        sys_id: (tuple(row["tick"] for row in rows), rows)
        for sys_id, rows in index.items()
        for rows in [sorted(rows, key=lambda item: item["tick"])]
    }


def _nearest_issue(issue_index, event):
    indexed = issue_index.get(event["src"])
    if indexed is None:
        return None
    ticks, rows = indexed
    position = bisect.bisect_right(ticks, event["start"]) - 1
    if position < 0:
        return None
    row = rows[position]
    if event["start"] - row["tick"] > 100000:
        return None
    return row


def _event_kind(issue_index, event):
    code = str(event.get("event_type_code", "0"))
    role = event.get("serving_role", "")
    if code == "1" and role == "PREFILL":
        return "P2D_KV", event.get("collective_id", "")
    if code == "2" and role == "DECODE":
        return "EP_DISPATCH", event.get("collective_id", "")
    if code == "3" and role == "DECODE":
        return "EP_COMBINE", event.get("collective_id", "")
    # Do not fall back to a name/timestamp heuristic.  Prefill MoE and Decode
    # EP use the same event types, so a role-less legacy artifact cannot be a
    # valid source for this study's Decode-side EP metrics.
    return "", ""


def build_timeline(comm_events, issue_events):
    """Build timed rows from backend intervals and explicit issue metadata."""
    p2d_sources = set()
    issue_index = _build_issue_index(issue_events)
    issue_metadata = {
        # Collective ids are now rank-independent metadata.  The ASTRA
        # callback's graph-local node id is not the same key as the backend
        # event's collective_id, so join on the emitted collective attribute.
        (row["sys"], row.get("collective_id", "") or row.get("node", "")): row
        for row in issue_events
        if row["phase"] == "ISSUE" and row.get("request_ids")
    }
    rows = []
    for event in comm_events:
        event_type, collective_id = _event_kind(issue_index, event)
        if not event_type:
            continue
        if event_type == "P2D_KV":
            p2d_sources.add(event["src"])
        metadata = issue_metadata.get((event["src"], event.get("collective_id", "")), {})
        active_request_ids = (event.get("active_request_ids", "") or
                              metadata.get("request_ids", ""))
        rows.append({
            "timestamp": event["start"],
            "event_id": event.get("event_id", ""),
            "request_id": event.get("request_id", ""),
            "active_request_ids": active_request_ids,
            "serving_role": event.get("serving_role", ""),
            "event_type": event_type,
            "layer_id": event.get("layer_id", ""),
            "src": event["src"],
            "dst": event["dst"],
            "bytes": event["bytes"],
            "start": event["start"],
            "end": event["end"],
            "path": event.get("path", ""),
            "directed_link_ids": event.get("directed_link_ids", ""),
            "collective_id": collective_id or event.get("collective_id", ""),
            "timing_status": "backend_start_end",
        })

    pending_compute = {}
    for event in issue_events:
        key = (event["sys"], event["node"], event["name"])
        if event["phase"] == "ISSUE" and "COMP_NODE" in event["name"]:
            pending_compute.setdefault(key, []).append(event["tick"])
        elif event["phase"] == "CALL" and "COMP_NODE" in event["name"]:
            starts = pending_compute.get(key, [])
            if not starts:
                continue
            start = starts.pop(0)
            event_type = ("PREFILL_COMPUTE" if event["sys"] in p2d_sources
                          else "DECODE_COMPUTE")
            serving_role = ("PREFILL" if event_type == "PREFILL_COMPUTE"
                            else "DECODE")
            rows.append({
                "timestamp": start,
                "event_id": "",
                "request_id": "",
                "active_request_ids": event.get("request_ids", ""),
                "serving_role": serving_role,
                "event_type": event_type,
                "layer_id": event.get("layer_id", ""),
                "src": event["sys"],
                "dst": "",
                "bytes": 0,
                "start": start,
                "end": event["tick"],
                "path": "",
                "directed_link_ids": "",
                "collective_id": "",
                "timing_status": "workload_issue_callback",
            })
    return sorted(rows, key=lambda row: (int(row["start"]), row["event_type"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--comm-events", type=Path, default=None)
    parser.add_argument("--astra-events", type=Path, default=None)
    parser.add_argument("--timeline", type=Path, default=None)
    parser.add_argument("--link-summary", type=Path, default=None)
    parser.add_argument("--directed-link-overlap", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.trace.with_name("trace_events.csv")
    rows = parse_trace(args.trace)
    fields = ["trace_order", "line_number", "request_id", "event_type", "src", "dst",
              "bytes", "compute_ns", "start", "end", "path", "timing_status",
              "comm_type", "misc"]
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    timed_rows = []
    if args.comm_events is not None:
        timed_rows = build_timeline(
            _read_backend_events(args.comm_events),
            _read_issue_events(args.astra_events),
        )
        timeline = args.timeline or args.comm_events.with_name("timeline.csv")
        timeline_fields = ["timestamp", "event_id", "request_id", "active_request_ids",
                           "serving_role", "event_type", "layer_id", "src", "dst", "bytes",
                           "start", "end", "path", "directed_link_ids",
                           "collective_id", "timing_status"]
        with timeline.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=timeline_fields)
            writer.writeheader()
            writer.writerows(timed_rows)
        overlap_path = args.directed_link_overlap or timeline.with_name(
            "directed_link_overlap.csv")
        write_directed_link_overlap(timeline, overlap_path, args.link_summary)
    summary = {
        "trace": str(args.trace),
        "output": str(output),
        "event_count": len(rows),
        "event_types": {name: sum(row["event_type"] == name for row in rows)
                         for name in ("P2D_KV", "EP_DISPATCH", "EP_COMBINE")},
        "timed_event_count": len(timed_rows),
        "timed_event_types": {
            name: sum(row["event_type"] == name for row in timed_rows)
            for name in ("P2D_KV", "EP_DISPATCH", "EP_COMBINE",
                         "PREFILL_COMPUTE", "DECODE_COMPUTE")
        },
        "overlap_verified": bool(timed_rows),
        "request_id_status": "direct for single-request P2D; batch list for collectives when metadata is present",
        "reason": "trace text alone has no timing; native backend rows carry start/end and directed paths",
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
