#!/usr/bin/env python3
"""Decompose native P4 remote-KV completion into endpoint/provider capacity scopes."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path


RATE_BPS = 200_000_000_000


def integer(row, key, default=0):
    value = row.get(key, "")
    return default if value in ("", "-1", None) else int(value)


def load_metadata(path):
    metadata = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            rank = int(row["astra_rank"])
            metadata[rank] = row
    return metadata


def load_events(path):
    events = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("phase") != "END":
                continue
            if row.get("event_type") != "1" or row.get("serving_role") != "remote_kv":
                continue
            request_id = integer(row, "request_id", -1)
            if request_id < 0:
                continue
            events.append({
                "request_id": request_id,
                "src": integer(row, "src"),
                "dst": integer(row, "dst"),
                "bytes": integer(row, "bytes"),
                "start_ns": integer(row, "network_start_ns"),
                "end_ns": integer(row, "network_end_ns"),
                "duration_ns": integer(row, "duration_ns"),
                "event_id": integer(row, "event_id", -1),
                "links": row.get("directed_link_ids", ""),
            })
    return events


def scope_rows(label, events, metadata):
    scopes = {
        "all_remote": lambda event: "all",
        "provider_rank": lambda event: f"rank:{event['src']}",
        "provider_instance": lambda event: f"instance:{metadata[event['src']]['instance_id']}",
        "provider_leaf": lambda event: f"leaf:{metadata[event['src']]['leaf_id']}",
        "destination_rank": lambda event: f"rank:{event['dst']}",
        "destination_instance": lambda event: f"instance:{metadata[event['dst']]['instance_id']}",
        "destination_leaf": lambda event: f"leaf:{metadata[event['dst']]['leaf_id']}",
        "provider_destination_pair": lambda event: f"{event['src']}->{event['dst']}",
    }
    output = []
    for scope_name, key_fn in scopes.items():
        grouped = defaultdict(list)
        for event in events:
            grouped[key_fn(event)].append(event)
        for key, values in sorted(grouped.items()):
            total_bytes = sum(value["bytes"] for value in values)
            first_ns = min(value["start_ns"] for value in values)
            last_ns = max(value["end_ns"] for value in values)
            span_ns = max(last_ns - first_ns, 1)
            serial_ns = total_bytes * 8 * 1e9 / RATE_BPS
            output.append({
                "run": label,
                "scope": scope_name,
                "scope_key": key,
                "flow_count": len(values),
                "request_count": len({value["request_id"] for value in values}),
                "bytes": total_bytes,
                "bytes_mib": total_bytes / (1024 * 1024),
                "first_start_ns": first_ns,
                "last_end_ns": last_ns,
                "span_ns": span_ns,
                "nominal_200g_serial_lower_bound_ns": serial_ns,
                "nominal_200g_serial_lower_bound_ms": serial_ns / 1e6,
                "serial_time_over_observed_span": serial_ns / span_ns,
                "max_flow_duration_ms": max(value["duration_ns"] for value in values) / 1e6,
            })
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True,
                        help="label=/path/to/native-run directory")
    parser.add_argument("--rank-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = load_metadata(args.rank_metadata)
    rows = []
    for item in args.run:
        if "=" not in item:
            raise SystemExit("--run must use label=directory")
        label, raw_path = item.split("=", 1)
        rows.extend(scope_rows(label, load_events(Path(raw_path) / "comm_events.csv"), metadata))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        fields = list(rows[0]) if rows else [
            "run", "scope", "scope_key", "flow_count", "request_count", "bytes",
            "bytes_mib", "first_start_ns", "last_end_ns", "span_ns",
            "nominal_200g_serial_lower_bound_ns",
            "nominal_200g_serial_lower_bound_ms",
            "serial_time_over_observed_span", "max_flow_duration_ms"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
