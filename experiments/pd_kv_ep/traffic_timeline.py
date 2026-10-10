#!/usr/bin/env python3
"""Aggregate timed native events into a request-serving traffic timeline."""

import argparse
import csv
from pathlib import Path

from semantic_events import is_decode_ep, is_p2d_kv


def read_events(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = []
        for row in csv.DictReader(stream):
            if not (is_p2d_kv(row) or is_decode_ep(row)):
                continue
            try:
                row["start_num"] = int(row["start"])
                row["end_num"] = int(row["end"])
                row["bytes_num"] = int(row["bytes"])
            except (KeyError, TypeError, ValueError):
                continue
            if row["end_num"] > row["start_num"]:
                rows.append(row)
        return rows


def read_requests(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = []
        for row in csv.DictReader(stream):
            try:
                arrival = int(row["arrival"])
                ttft = int(row["TTFT"])
                end = int(row["end_time"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append((arrival, arrival + ttft, end))
        return rows


def aggregate(events, requests, bucket_ns):
    end_time = max(
        [row["end_num"] for row in events] +
        [end for _, _, end in requests] + [0]
    )
    bucket_count = (end_time + bucket_ns - 1) // bucket_ns
    output = []
    for index in range(bucket_count):
        start = index * bucket_ns
        end = start + bucket_ns
        bits = {"P2D_KV": 0.0, "EP": 0.0}
        for event in events:
            overlap = min(end, event["end_num"]) - max(start, event["start_num"])
            if overlap <= 0:
                continue
            duration = event["end_num"] - event["start_num"]
            key = "P2D_KV" if is_p2d_kv(event) else "EP"
            bits[key] += event["bytes_num"] * 8.0 * overlap / duration
        prefill = sum(arrival <= start < ready for arrival, ready, _ in requests)
        decode = sum(ready <= start < finish for _, ready, finish in requests)
        output.append({
            "timestamp_ns": start,
            "P2D_KV_Gbps": bits["P2D_KV"] / (bucket_ns / 1e9) / 1e9,
            "Decode_EP_Gbps": bits["EP"] / (bucket_ns / 1e9) / 1e9,
            "active_prefill_requests": prefill,
            "active_decode_requests": decode,
        })
    return output


def write_figure(rows, path):
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("matplotlib is required for traffic timeline figures") from exc
    x = [row["timestamp_ns"] / 1e6 for row in rows]
    figure, axis = plt.subplots(figsize=(10, 4.5))
    axis.plot(x, [row["P2D_KV_Gbps"] for row in rows], label="P2D KV Gbps")
    axis.plot(x, [row["Decode_EP_Gbps"] for row in rows], label="Decode EP Gbps")
    axis.set_xlabel("simulated time (ms)")
    axis.set_ylabel("communication demand (Gbps)")
    right = axis.twinx()
    right.step(x, [row["active_prefill_requests"] for row in rows],
               where="post", linestyle="--", label="active prefill")
    right.step(x, [row["active_decode_requests"] for row in rows],
               where="post", linestyle=":", label="active decode")
    right.set_ylabel("active requests")
    handles, labels = axis.get_legend_handles_labels()
    other_handles, other_labels = right.get_legend_handles_labels()
    axis.legend(handles + other_handles, labels + other_labels, loc="upper right")
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timeline", type=Path)
    parser.add_argument("requests", type=Path)
    parser.add_argument("--bucket-us", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    args = parser.parse_args()
    rows = aggregate(read_events(args.timeline), read_requests(args.requests),
                     args.bucket_us * 1000)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.figure.parent.mkdir(parents=True, exist_ok=True)
    fields = ["timestamp_ns", "P2D_KV_Gbps", "Decode_EP_Gbps",
              "active_prefill_requests", "active_decode_requests"]
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write_figure(rows, args.figure)
    print("wrote", args.output)
    print("wrote", args.figure)


if __name__ == "__main__":
    main()
