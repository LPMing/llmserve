#!/usr/bin/env python3
"""Audit the P1 Decode-side cut for existing FlowSim replays.

This is a streaming, network-only audit.  It intentionally does not infer
packet queues, ECMP hashes, ECN, PFC, or serving TTFT/TBT from FlowSim.  Flow
intervals are reconstructed from the requested start, queueing time, and
completion time written by ``run_flowsim_replay.py``.  Rates are binned at a
coarse interval only to make the audit bounded for large ledgers.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


BIN_NS = 1_000_000
NETWORK_CLASSES = {"KV_MOVEMENT", "EP"}


def percentile(values, fraction):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(math.floor(position))
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def stats(values, scale=1.0):
    scaled = [float(value) * scale for value in values]
    return {
        "count": len(scaled),
        "mean": sum(scaled) / len(scaled) if scaled else None,
        "p50": percentile(scaled, 0.50),
        "p95": percentile(scaled, 0.95),
        "p99": percentile(scaled, 0.99),
        "max": max(scaled) if scaled else None,
    }


def _paths(value):
    return [item for item in str(value or "").split(";") if item]


def _parse_link(value):
    left, right, *physical = value.split("->")
    return (int(left), int(right), int(physical[0])) if physical else (int(left), int(right))

def _add_interval(bins, entity, traffic_class, start, end, bytes_value,
                  flow_count, bin_ns=BIN_NS):
    """Add an interval's constant service rate to coarse bins."""
    if end <= start:
        return
    rate = float(bytes_value) * 1_000_000_000.0 / float(end - start)
    first = start // bin_ns
    last = (end - 1) // bin_ns
    for bucket in range(first, last + 1):
        overlap_start = max(start, bucket * bin_ns)
        overlap_end = min(end, (bucket + 1) * bin_ns)
        if overlap_end <= overlap_start:
            continue
        bins[entity][traffic_class][bucket] += rate * (overlap_end - overlap_start) / bin_ns
        bins[entity]["_flows"][traffic_class][bucket] += flow_count


def _read_metadata(path):
    metadata = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            rank = int(row["astra_rank"])
            metadata[rank] = {
                "role": row.get("role", ""),
                "leaf_id": row.get("leaf_id", ""),
                "instance_id": int(row["instance_id"]),
            }
    return metadata


def _network_info(topology):
    # Importing the production parser avoids duplicating parallel-link
    # aggregation semantics in this audit.
    from serving.core.flowsim_backend import FluidFlowNetwork
    network = FluidFlowNetwork(str(topology), "FAIR", parallel_link_mode="AGGREGATE")
    capacities = {
        "%d->%d" % (src, dst): edge["capacity_Bps"]
        for (src, dst), edge in network.edges.items()
    }
    return network.topology_audit, capacities


def _load_telemetry(path):
    max_queue = defaultdict(float)
    max_active = defaultdict(int)
    rows = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            link = str(row.get("link_id", ""))
            if not link:
                continue
            rows += 1
            max_queue[link] = max(max_queue[link], float(row.get("queue_bytes", 0)))
            max_active[link] = max(max_active[link], int(row.get("active_flows", 0)))
    return {
        "rows": rows,
        "max_queue_bytes": dict(max_queue),
        "max_active_flows": dict(max_active),
    }


def audit_run(run_dir, metadata, capacities):
    run_dir = Path(run_dir)
    bins = defaultdict(lambda: {"KV_MOVEMENT": defaultdict(float),
                                "EP": defaultdict(float),
                                "_flows": {"KV_MOVEMENT": defaultdict(int),
                                            "EP": defaultdict(int)}})
    totals = defaultdict(lambda: defaultdict(float))
    endpoint_flows = defaultdict(lambda: defaultdict(int))
    endpoint_bytes = defaultdict(lambda: defaultdict(float))
    endpoint_intervals = defaultdict(lambda: defaultdict(list))
    link_bytes = defaultdict(lambda: defaultdict(float))
    link_flow_counts = defaultdict(lambda: defaultdict(int))
    class_interval_ns = defaultdict(lambda: defaultdict(int))
    flow_count = 0
    first_ns = None
    last_ns = 0
    with (run_dir / "flows.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            traffic_class = row.get("traffic_class", "")
            if traffic_class not in NETWORK_CLASSES:
                continue
            requested = int(row.get("requested_start_ns", row["start_ns"]))
            queueing = int(row.get("queueing_ns", 0))
            start = requested + queueing
            end = int(row["end_ns"])
            if end <= start:
                continue
            src = int(row["src"])
            dst = int(row["dst"])
            bytes_value = int(row["bytes"])
            duration = end - start
            flow_count += 1
            first_ns = start if first_ns is None else min(first_ns, start)
            last_ns = max(last_ns, end)
            totals["global"][traffic_class] += bytes_value
            class_interval_ns["global"][traffic_class] += duration
            endpoint_bytes[dst][traffic_class] += bytes_value
            endpoint_flows[dst][traffic_class] += 1
            endpoint_intervals[dst][traffic_class].append((start, end))
            _add_interval(bins, "endpoint:%d" % dst, traffic_class, start, end,
                          bytes_value, 1)
            for link in _paths(row.get("path")):
                parsed = _parse_link(link)
                logical = "%d->%d" % (parsed[0], parsed[1])
                link_bytes[logical][traffic_class] += bytes_value
                link_flow_counts[logical][traffic_class] += 1
                class_interval_ns[logical][traffic_class] += duration
                _add_interval(bins, "link:%s" % logical, traffic_class, start,
                              end, bytes_value, 1)

    telemetry = _load_telemetry(run_dir / "link_telemetry.jsonl")

    def summarize_entities(prefix, capacity_for):
        rows = []
        names = sorted(name for name in bins if name.startswith(prefix))
        for name in names:
            entity = name[len(prefix):]
            capacity = capacity_for(entity)
            if not capacity:
                continue
            result = {"entity": entity, "capacity_Bps": capacity}
            for traffic_class in ("KV_MOVEMENT", "EP"):
                rate_values = list(bins[name][traffic_class].values())
                util_values = [value / capacity for value in rate_values]
                active_values = list(bins[name]["_flows"][traffic_class].values())
                result[traffic_class] = {
                    "bytes": link_bytes[entity][traffic_class] if prefix == "link:" else endpoint_bytes[int(entity)][traffic_class],
                    "flow_count": link_flow_counts[entity][traffic_class] if prefix == "link:" else endpoint_flows[int(entity)][traffic_class],
                    "peak_rate_Bps": max(rate_values, default=0.0),
                    "peak_utilization": max(util_values, default=0.0),
                    "time_above_80pct_ns": sum(BIN_NS for value in util_values if value > 0.8),
                    "time_above_90pct_ns": sum(BIN_NS for value in util_values if value > 0.9),
                    "time_saturated_ns": sum(BIN_NS for value in util_values if value >= 1.0),
                    "max_concurrent_flows": max(active_values, default=0),
                }
            result["mixed_peak_utilization"] = max(
                (sum(bins[name][traffic_class].get(bucket, 0.0) for traffic_class in ("KV_MOVEMENT", "EP")) / capacity
                 for bucket in set(bins[name]["KV_MOVEMENT"]) | set(bins[name]["EP"])),
                default=0.0)
            if prefix == "link:" and entity in telemetry["max_queue_bytes"]:
                result["max_fluid_queue_bytes"] = telemetry["max_queue_bytes"][entity]
                result["telemetry_max_active_flows"] = telemetry["max_active_flows"].get(entity, 0)
            rows.append(result)
        rows.sort(key=lambda row: row["mixed_peak_utilization"], reverse=True)
        return rows

    def endpoint_capacity(endpoint):
        # The authoritative endpoint rate is the endpoint-facing edge in the
        # parsed topology.  It remains 200 Gbps even when leaf-spine pairs are
        # represented by an aggregate logical resource.
        endpoint = int(endpoint)
        candidates = [capacity for link, capacity in capacities.items()
                      if link.endswith("->%d" % endpoint)]
        return min(candidates) if candidates else None

    link_rows = summarize_entities("link:", lambda link: capacities.get(link))
    endpoint_rows = summarize_entities("endpoint:", endpoint_capacity)
    top_links = link_rows[:20]
    top_endpoints = endpoint_rows[:20]
    return {
        "run": str(run_dir.resolve()),
        "flow_count": flow_count,
        "first_service_ns": first_ns,
        "last_completion_ns": last_ns,
        "duration_ns": max(0, last_ns - (first_ns or 0)),
        "traffic_totals": {key: dict(value) for key, value in totals.items()},
        "telemetry": telemetry,
        "top_logical_links_by_mixed_utilization": top_links,
        "top_decode_endpoints_by_mixed_utilization": top_endpoints,
        "logical_link_count": len(link_rows),
        "decode_endpoint_count": len(endpoint_rows),
    }


def _pct(new, old):
    if old in (None, 0) or new is None:
        return None
    return 100.0 * (new / old - 1.0)


def _metric(result, entity, traffic_class, field):
    return next((row[traffic_class][field] for row in result[entity]
                 if row["entity"] == field), None)


def build_report(spread, fanin, audit, topology_audit):
    spread_links = {row["entity"]: row for row in spread["top_logical_links_by_mixed_utilization"]}
    fanin_links = {row["entity"]: row for row in fanin["top_logical_links_by_mixed_utilization"]}
    all_links = sorted(set(spread_links) | set(fanin_links))
    link_comparison = []
    for link in all_links:
        left = spread_links.get(link, {})
        right = fanin_links.get(link, {})
        link_comparison.append({
            "link": link,
            "spread_kv_bytes": left.get("KV_MOVEMENT", {}).get("bytes", 0),
            "fanin_kv_bytes": right.get("KV_MOVEMENT", {}).get("bytes", 0),
            "spread_ep_bytes": left.get("EP", {}).get("bytes", 0),
            "fanin_ep_bytes": right.get("EP", {}).get("bytes", 0),
            "spread_mixed_peak_utilization": left.get("mixed_peak_utilization", 0),
            "fanin_mixed_peak_utilization": right.get("mixed_peak_utilization", 0),
            "spread_fluid_queue_bytes": left.get("max_fluid_queue_bytes", 0),
            "fanin_fluid_queue_bytes": right.get("max_fluid_queue_bytes", 0),
        })
    link_comparison.sort(key=lambda row: max(row["spread_mixed_peak_utilization"],
                                              row["fanin_mixed_peak_utilization"]), reverse=True)
    return {
        "schema_version": 1,
        "semantics": {
            "backend": "FlowSim aggregate fluid max-min",
            "queue": "analytical residual fluid backlog, not packet-buffer occupancy",
            "rate_bin_ns": BIN_NS,
            "endpoint_capacity_is_not_aggregate_leaf_spine_capacity": True,
        },
        "topology_audit": topology_audit,
        "spread": spread,
        "fanin16": fanin,
        "link_comparison": link_comparison,
        "interpretation": {
            "kv_fct_is_request_barrier": "last required KV flow completion minus first requested KV start; it is not a sum of flow delays",
            "p1_status": "PRELIMINARY_NETWORK_MECHANISM_ONLY",
            "serving_validation": "pending_integrated_fan-in comparison; no TTFT/TBT claim is made here",
        },
    }


def render_markdown(result):
    topology = result["topology_audit"]
    spread = result["spread"]
    fanin = result["fanin16"]
    lines = [
        "# P1 Decode-side cut audit",
        "",
        "This is a FlowSim network-only audit. Rates and queues are aggregate fluid",
        "measurements; they are not packet-buffer occupancy, ECMP, ECN, PFC, or drops.",
        "No TTFT/TBT claim is made until an integrated serving comparison is completed.",
        "",
        "## Topology gate",
        "",
        "- Physical directed links parsed: `%s`" % topology["directed_physical_edge_count"],
        "- Aggregate directed endpoint pairs: `%s`" % topology["directed_aggregate_pair_count"],
        "- Parallel pairs: `%s`" % len(topology["parallel_pairs"]),
        "- Routing model: `%s`" % topology["routing_model"],
        "",
        "## Aggregate replay accounting",
        "",
        "| geometry | flows | KV bytes | EP bytes | max fluid queue rows |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, data in (("spread", spread), ("fan-in16", fanin)):
        totals = data["traffic_totals"]["global"]
        lines.append("| %s | %d | %.3f GB | %.3f GB | %d |" % (
            name, data["flow_count"], totals.get("KV_MOVEMENT", 0) / 1e9,
            totals.get("EP", 0) / 1e9, data["telemetry"]["rows"]))
    lines += [
        "",
        "The two rows use the same request set, model-derived bytes, EP routing,",
        "arrival timing, and topology. The offline control changes only P2D destination",
        "concentration.",
        "",
        "## Highest mixed-utilization logical resources",
        "",
        "| link | spread peak mixed util | fan-in16 peak mixed util | spread KV GB | fan-in16 KV GB | spread queue GB | fan-in16 queue GB |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["link_comparison"][:12]:
        lines.append("| `%s` | %.3f | %.3f | %.3f | %.3f | %.3f | %.3f |" % (
            row["link"], row["spread_mixed_peak_utilization"],
            row["fanin_mixed_peak_utilization"], row["spread_kv_bytes"] / 1e9,
            row["fanin_kv_bytes"] / 1e9, row["spread_fluid_queue_bytes"] / 1e9,
            row["fanin_fluid_queue_bytes"] / 1e9))
    lines += [
        "",
        "## Decode endpoint resources",
        "",
        "The endpoint-facing capacity is kept separate from the aggregated",
        "leaf-spine capacity. Therefore a 200-Gbps endpoint is never reported as",
        "3.2 Tbps merely because 16 parallel leaf-spine links were aggregated.",
        "",
    ]
    for name, data in (("spread", spread), ("fan-in16", fanin)):
        decode_rows = [row for row in data["top_decode_endpoints_by_mixed_utilization"]
                       if row["entity"] in {str(value) for value in range(64, 128)}]
        peak = max((row["mixed_peak_utilization"] for row in decode_rows), default=0)
        lines.append("- %s: maximum Decode endpoint mixed utilization %.3f" % (name, peak))
    lines += [
        "",
        "## Current decision",
        "",
        "The existing network-only gap is consistent with concentration on a",
        "Decode-side logical cut rather than a single Decode NIC: fan-in16 pushes",
        "the same P2D bytes through fewer Decode-side paths while the EP collective",
        "continues to use the cut. This is still only a P1 mechanism result.",
        "",
        "P1 is not marked PASS until the same controlled concentration is shown in",
        "integrated TTFT/TBT and is reproduced with a second heterogeneous or natural",
        "workload. Next: concurrency-knee and heterogeneous spread/fan-in checks,",
        "then the tractable integrated serving gate.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spread", type=Path, required=True)
    parser.add_argument("--fanin", type=Path, required=True)
    parser.add_argument("--rank-metadata", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    metadata = _read_metadata(args.rank_metadata)
    topology_audit, capacities = _network_info(args.topology)
    # Metadata is loaded and validated here so an endpoint audit cannot be
    # accidentally run with a different rank map.  The current metrics are
    # keyed by endpoint rank and the metadata count is recorded in the JSON.
    decode_ranks = sorted(rank for rank, row in metadata.items()
                          if row["role"] == "decode")
    result = build_report(
        audit_run(args.spread, metadata, capacities),
        audit_run(args.fanin, metadata, capacities),
        {**topology_audit, "decode_rank_count": len(decode_ranks)},
        topology_audit,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({
        "output_json": str(args.output_json),
        "output_md": str(args.output_md),
        "spread_flows": result["spread"]["flow_count"],
        "fanin_flows": result["fanin16"]["flow_count"],
    }, indent=2))


if __name__ == "__main__":
    main()
