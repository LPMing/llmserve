#!/usr/bin/env python3
"""Replay model-derived P2D shards at their actual integrated release times.

The replay is an offline network-only counterfactual. It keeps each flow's
model-derived bytes, physical endpoints, and Prefill-generated release anchor;
it does not infer TTFT/TBT from network completion. REQUEST_GROUPED is a
small offline FIFO/coflow baseline implemented by overriding only the fluid
allocator for this analysis, not a serving scheduler.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from serving.core.flowsim_backend import FlowSpec, PersistentFluidFlowNetwork


def read_flows(path):
    result = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        if row.get("traffic_subtype") != "P2D":
            continue
        ids = tuple(int(value) for value in row.get("request_ids", ()))
        if len(ids) != 1:
            raise ValueError(
                "This controlled workload must have one request per P2D "
                "flow; refusing to split an aggregate flow: %s" % row)
        result.append({
            "flow_id": str(row["flow_id"]),
            "request_id": ids[0],
            "src": int(row["src"]),
            "dst": int(row["dst"]),
            "bytes": int(row["bytes"]),
            "release_ns": int(row["requested_start_ns"]),
            "observed_path": tuple(row["path"]),
        })
    if not result:
        raise ValueError("no P2D flows found in %s" % path)
    return result


class RequestGroupedReplay(PersistentFluidFlowNetwork):
    """Strict request FIFO on shared minimum-capacity links; offline only."""

    def __init__(self, *args, priority_request_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.priority_request_ids = {int(value)
                                     for value in priority_request_ids}

    def _rates(self, active, paths):
        if self.policy != "REQUEST_GROUPED":
            return super()._rates(active, paths)
        high = []
        low = []
        for flow_id, data in active.items():
            request_ids = set(int(value) for value in
                              data["spec"].request_ids)
            if request_ids & self.priority_request_ids:
                high.append(flow_id)
            else:
                low.append(flow_id)
        capacities = {}
        for flow_id in active:
            for link in paths[flow_id]:
                capacities[link] = self._edge(link)["capacity_Bps"]
        rates = self._waterfill(high, paths, capacities) if high else {}
        residual = dict(capacities)
        high_link_rates = defaultdict(float)
        for flow_id in high:
            for link in paths[flow_id]:
                high_link_rates[link] += rates[flow_id]
        for link, capacity in residual.items():
            residual[link] = max(
                0.0, capacity - high_link_rates.get(link, 0.0))
        if low:
            rates.update(self._waterfill(low, paths, residual))
        return rates


def make_specs(rows):
    return [FlowSpec(
        flow_id=row["flow_id"], src=row["src"], dst=row["dst"],
        bytes=row["bytes"], start_ns=row["release_ns"],
        traffic_class="KV_MOVEMENT", traffic_subtype="P2D",
        request_ids=(row["request_id"],), event_type=1)
        for row in rows]


def run_replay(rows, topology, policy, priority_ids=()):
    if policy == "REQUEST_GROUPED":
        net = RequestGroupedReplay(
            topology, policy=policy, priority_request_ids=priority_ids)
    else:
        net = PersistentFluidFlowNetwork(topology, policy=policy)
    specs = make_specs(rows)
    net.submit(specs)
    while net.next_event_time() is not None:
        net.advance()
    records = {}
    for spec in specs:
        record = net.flow_record(spec.flow_id)
        if record is None:
            raise RuntimeError("missing replay completion for %s" % spec.flow_id)
        path = tuple(record["path"])
        source = next(row for row in rows if row["flow_id"] == spec.flow_id)
        if path != source["observed_path"]:
            raise RuntimeError(
                "replay path differs from integrated path for %s: %s != %s" %
                (spec.flow_id, path, source["observed_path"]))
        records[spec.flow_id] = record
    return records, net


def percentile(values, q):
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def request_metrics(rows, records):
    by_request = defaultdict(list)
    for row in rows:
        by_request[row["request_id"]].append(row)
    output = {}
    for request_id, request_rows in by_request.items():
        finished = [(row, records[row["flow_id"]]) for row in request_rows]
        critical = max(finished, key=lambda pair: pair[1]["end_ns"])
        first_release = min(row["release_ns"] for row in request_rows)
        last_release = max(row["release_ns"] for row in request_rows)
        ready = max(record["end_ns"] for _, record in finished)
        output[request_id] = {
            "flow_count": len(request_rows),
            "total_bytes": sum(row["bytes"] for row in request_rows),
            "first_release_ns": first_release,
            "last_release_ns": last_release,
            "kv_ready_ns": ready,
            "handoff_span_ns": ready - first_release,
            "last_release_to_ready_ns": ready - last_release,
            "last_shard_flow_id": critical[0]["flow_id"],
        }
    return output


def priority_requests_per_rail(rows, network):
    specs = make_specs(rows)
    requests_per_link = defaultdict(set)
    flow_min_links = {}
    for spec in specs:
        path = network._resolve_flow_path(spec)
        capacities = [network._edge(link)["capacity_Bps"] for link in path]
        minimum = min(capacities)
        shared_min_links = [link for link in path
                            if math.isclose(
                                network._edge(link)["capacity_Bps"], minimum,
                                rel_tol=1e-12)]
        flow_min_links[spec.flow_id] = shared_min_links
        for link in shared_min_links:
            requests_per_link[link].add(int(spec.request_ids[0]))
    priority_ids = set()
    for link, request_ids in requests_per_link.items():
        if len(request_ids) > 1:
            priority_ids.add(min(request_ids))
    return priority_ids, flow_min_links, requests_per_link


def write_csv(path, fieldnames, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--single-flow-file", required=True)
    parser.add_argument("--multi-flow-file", required=True)
    parser.add_argument("--topology", required=True)
    parser.add_argument("--expected-out", required=True)
    parser.add_argument("--results-out", required=True)
    args = parser.parse_args()

    single_rows = read_flows(args.single_flow_file)
    multi_rows = read_flows(args.multi_flow_file)
    scenarios = {
        1: ("integrated-1req", single_rows),
        2: ("integrated-4req-subset-2", [
            row for row in multi_rows if row["request_id"] in (0, 1)]),
        4: ("integrated-4req", multi_rows),
    }
    expected_rows = []
    network_rows = []
    fieldnames = [
        "scenario", "request_count", "policy", "scope", "request_id",
        "total_kv_bytes", "shard_count", "first_release_ns",
        "last_release_ns", "kv_ready_ns", "handoff_span_ns",
        "last_release_to_ready_ns", "last_shard_flow_id",
        "mean_handoff_span_ns", "p50_handoff_span_ns",
        "p99_handoff_span_ns", "mean_ready_ns", "p50_ready_ns",
        "p99_ready_ns", "priority_request_ids", "release_source"]

    for count, (source_name, selected) in scenarios.items():
        request_ids = sorted({row["request_id"] for row in selected})
        if len(request_ids) != count:
            raise ValueError("scenario %d has request IDs %s" %
                             (count, request_ids))
        fair_records, fair_net = run_replay(
            selected, args.topology, "FAIR")
        priority_ids, flow_min_links, requests_per_link = \
            priority_requests_per_rail(selected, fair_net)
        grouped_records, _ = run_replay(
            selected, args.topology, "REQUEST_GROUPED", priority_ids)
        if count == 1:
            priority_ids = set()
            grouped_records = fair_records

        # Simultaneous-release upper-bound model: each request has a complete
        # TP shard set on one 200-Gbps rail pair.  Report it separately from
        # the real release-anchor replay below.
        request_sizes = defaultdict(int)
        for row in selected:
            request_sizes[row["request_id"]] += row["bytes"]
        rails = defaultdict(set)
        for link, ids in requests_per_link.items():
            if len(ids) > 1:
                rails[network_link_name(fair_net, link)].update(ids)
        rail_groups = sorted(
            {tuple(sorted(group)) for group in rails.values()}) or [
                (rid,) for rid in request_ids]
        total_bytes = sum(request_sizes.values())
        shard_sizes = [row["bytes"] for row in selected]
        shard_bytes = max(shard_sizes)
        rate_Bps = min(
            fair_net._edge(link)["capacity_Bps"]
            for path in flow_min_links.values() for link in path)
        propagation_ns = max(
            sum(fair_net._edge(link)["latency_ns"]
                for link in fair_net._resolve_flow_path(spec))
            for spec in make_specs(selected))
        ideal_fair = {}
        ideal_grouped = {}
        for group in rail_groups:
            group_size = len(group)
            # Under simultaneous release, all TP shards of the group's
            # requests are active on the same bottleneck cut.
            fair_service = int(math.ceil(
                shard_bytes * 2 * group_size * 1e9 / rate_Bps))
            grouped_service = int(math.ceil(
                shard_bytes * 2 * 1e9 / rate_Bps))
            for position, rid in enumerate(sorted(group), start=1):
                ideal_fair[rid] = fair_service + propagation_ns
                ideal_grouped[rid] = (
                    position * grouped_service + propagation_ns)
        ideal_fair_mean = sum(ideal_fair.values()) / len(ideal_fair)
        ideal_grouped_mean = sum(ideal_grouped.values()) / len(ideal_grouped)
        expected_rows.append({
            "request_count": count,
            "topology_resource_groups": len(rail_groups),
            "requests_per_resource_group": ";".join(
                ",".join(str(item) for item in group)
                for group in rail_groups),
            "per_request_kv_bytes": int(round(total_bytes / count)),
            "tp_shard_bytes": shard_bytes,
            "bottleneck_capacity_Bps": rate_Bps,
            "path_propagation_ns": propagation_ns,
            "ideal_simultaneous_release_fair_mean_handoff_ns":
                ideal_fair_mean,
            "ideal_simultaneous_release_grouped_mean_handoff_ns":
                ideal_grouped_mean,
            "ideal_simultaneous_release_mean_gain_pct":
                100 * (ideal_fair_mean - ideal_grouped_mean) /
                ideal_fair_mean if ideal_fair_mean else 0.0,
            "interpretation": "simultaneous-release network-only upper bound; not serving prediction",
        })

        for policy_name, records in (
                ("FAIR", fair_records),
                ("REQUEST_GROUPED_FIFO", grouped_records),
                ("REQUEST_GROUPED_SRPT", grouped_records),
                ("COFLOW_FIFO", grouped_records)):
            metrics = request_metrics(selected, records)
            handoffs = [item["handoff_span_ns"]
                        for item in metrics.values()]
            ready_times = [item["kv_ready_ns"]
                           for item in metrics.values()]
            for request_id, item in metrics.items():
                network_rows.append({
                    "scenario": "N%d" % count,
                    "request_count": count,
                    "policy": policy_name,
                    "scope": "REQUEST",
                    "request_id": request_id,
                    "total_kv_bytes": item["total_bytes"],
                    "shard_count": item["flow_count"],
                    "first_release_ns": item["first_release_ns"],
                    "last_release_ns": item["last_release_ns"],
                    "kv_ready_ns": item["kv_ready_ns"],
                    "handoff_span_ns": item["handoff_span_ns"],
                    "last_release_to_ready_ns":
                        item["last_release_to_ready_ns"],
                    "last_shard_flow_id": item["last_shard_flow_id"],
                    "priority_request_ids": ";".join(
                        str(value) for value in sorted(priority_ids)),
                    "release_source": source_name,
                })
            network_rows.append({
                "scenario": "N%d" % count,
                "request_count": count,
                "policy": policy_name,
                "scope": "SUMMARY",
                "request_id": "ALL",
                "total_kv_bytes": sum(item["total_bytes"]
                                       for item in metrics.values()),
                "shard_count": sum(item["flow_count"]
                                    for item in metrics.values()),
                "mean_handoff_span_ns": sum(handoffs) / len(handoffs),
                "p50_handoff_span_ns": percentile(handoffs, 0.50),
                "p99_handoff_span_ns": percentile(handoffs, 0.99),
                "mean_ready_ns": sum(ready_times) / len(ready_times),
                "p50_ready_ns": percentile(ready_times, 0.50),
                "p99_ready_ns": percentile(ready_times, 0.99),
                "priority_request_ids": ";".join(
                    str(value) for value in sorted(priority_ids)),
                "release_source": source_name,
            })

    write_csv(args.expected_out, list(expected_rows[0].keys()), expected_rows)
    write_csv(args.results_out, fieldnames, network_rows)


def network_link_name(network, link):
    return network._link_name(link)


if __name__ == "__main__":
    main()
