#!/usr/bin/env python3
"""Independent tiny max-min fluid reference for theory sanity checks only.

This is not a Qwen workload, not FlowSim, and not a performance experiment.
It validates link-capacity, release-time, byte-conservation, and barrier-bound
accounting on small hand-checkable examples.
"""

import csv
import math
from pathlib import Path
from math import comb


ROOT = Path(__file__).resolve().parent


def max_min_rates(active, paths, capacities):
    rates = {flow: 0.0 for flow in active}
    unfrozen = set(active)
    while unfrozen:
        residual = dict(capacities)
        for flow in active:
            for link in paths[flow]:
                residual[link] -= rates[flow]
        candidates = [
            residual[link] / sum(link in paths[flow] for flow in unfrozen)
            for link in capacities
            if any(link in paths[flow] for flow in unfrozen)
        ]
        if not candidates:
            for flow in unfrozen:
                rates[flow] = math.inf
            break
        delta = min(candidates)
        if delta < -1e-10:
            raise AssertionError("allocated rates exceeded a link capacity")
        for flow in unfrozen:
            rates[flow] += max(delta, 0.0)
        saturated = set()
        for link, capacity in capacities.items():
            used = sum(rates[flow] for flow in active if link in paths[flow])
            if abs(used - capacity) <= max(1e-9, capacity * 1e-9):
                saturated.add(link)
        newly_frozen = {
            flow for flow in unfrozen
            if any(link in saturated for link in paths[flow])
        }
        if not newly_frozen:
            raise AssertionError("progressive filling made no progress")
        unfrozen.difference_update(newly_frozen)
    for link, capacity in capacities.items():
        used = sum(rates[flow] for flow in active if link in paths[flow])
        if used > capacity + max(1e-8, capacity * 1e-8):
            raise AssertionError("link capacity violated")
    return rates


def simulate(flows, capacities):
    """Return flow completion times for finite fluid transfers.

    Each flow is {id, bytes, release, path}; capacities use bytes per time
    unit. Flows share any common directed link under unweighted max-min fair
    allocation. Propagation, packetization, compute, and protocol startup are
    deliberately absent.
    """
    remaining = {flow["id"]: float(flow["bytes"]) for flow in flows}
    release = {flow["id"]: float(flow["release"]) for flow in flows}
    paths = {flow["id"]: tuple(flow["path"]) for flow in flows}
    finish = {}
    now = min(release.values(), default=0.0)
    while len(finish) < len(flows):
        active = [
            flow_id for flow_id in remaining
            if flow_id not in finish and release[flow_id] <= now + 1e-12
        ]
        if not active:
            future = [release[f] for f in remaining if f not in finish]
            now = min(future)
            continue
        rates = max_min_rates(active, paths, capacities)
        next_release = min(
            [release[f] for f in remaining if f not in finish and release[f] > now + 1e-12]
            or [math.inf])
        next_finish = min(
            [remaining[f] / rates[f] for f in active if rates[f] > 0]
            or [math.inf])
        delta = min(next_release - now, next_finish)
        if not math.isfinite(delta) or delta < 0:
            raise AssertionError("invalid fluid event interval")
        for flow_id in active:
            remaining[flow_id] = max(0.0, remaining[flow_id] - rates[flow_id] * delta)
        now += delta
        for flow_id in active:
            if remaining[flow_id] <= 1e-8:
                finish[flow_id] = now
    return finish


def main():
    rows = []
    # Positive control: two flows share one cut; barrier flow doubles versus isolation.
    shared = simulate([
        {"id": "kv", "bytes": 100, "release": 0, "path": ["cut"]},
        {"id": "ep", "bytes": 10, "release": 0, "path": ["cut"]},
    ], {"cut": 10})
    assert abs(shared["ep"] - 2.0) < 1e-9
    assert abs(shared["kv"] - 11.0) < 1e-9
    rows.append({"case": "ABSTRACT_SHARED_CUT", "status": "PASS",
                 "expected": "EP=2, KV=11 time units", "observed": str(shared),
                 "scope": "abstract sanity only; not Qwen evidence"})

    # Negative control: no shared directed resource, so EP completion is unchanged.
    disjoint = simulate([
        {"id": "kv", "bytes": 100, "release": 0, "path": ["cut_p"]},
        {"id": "ep", "bytes": 10, "release": 0, "path": ["cut_d"]},
    ], {"cut_p": 10, "cut_d": 10})
    assert abs(disjoint["ep"] - 1.0) < 1e-9
    assert abs(disjoint["kv"] - 10.0) < 1e-9
    rows.append({"case": "ABSTRACT_DISJOINT_CUTS", "status": "PASS",
                 "expected": "EP=1, KV=10 time units", "observed": str(disjoint),
                 "scope": "abstract sanity only; not Qwen evidence"})

    # Boundary: the flow-work lower bound equals the observed isolated service time.
    isolated = simulate([
        {"id": "ep", "bytes": 10, "release": 0, "path": ["cut"]},
    ], {"cut": 10})
    assert abs(isolated["ep"] - 1.0) < 1e-9
    rows.append({"case": "ABSTRACT_ISOLATED_BOUNDARY", "status": "PASS",
                 "expected": "EP=bytes/capacity=1 time unit", "observed": str(isolated),
                 "scope": "abstract sanity only; not Qwen evidence"})

    # Multi-bottleneck: two flows share the 4-unit cut; the other link is slack.
    multi = simulate([
        {"id": "f1", "bytes": 8, "release": 0, "path": ["wide", "narrow"]},
        {"id": "f2", "bytes": 8, "release": 0, "path": ["narrow"]},
    ], {"wide": 10, "narrow": 4})
    assert abs(multi["f1"] - 4.0) < 1e-9
    assert abs(multi["f2"] - 4.0) < 1e-9
    rows.append({"case": "ABSTRACT_MULTI_BOTTLENECK", "status": "PASS",
                 "expected": "f1=f2=4; narrow cut saturates", "observed": str(multi),
                 "scope": "abstract sanity only; not Qwen evidence"})

    output = ROOT / "reference_scheduler_checks.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    route_rows = []
    experts, top_k = 128, 8
    for ep in (4, 8, 16, 32, 64):
        experts_per_rank = experts // ep
        unique_owners = ep * (
            1.0 - comb(experts - experts_per_rank, top_k) /
            comb(experts, top_k))
        remote_owners = unique_owners * (1.0 - 1.0 / ep)
        sparse_to_dense_payload_ratio = (
            remote_owners * (4096 + 4096) /
            ((ep - 1) * (4352 + 4096)))
        assert 1.0 <= unique_owners <= min(ep, top_k)
        assert 0.0 <= remote_owners <= ep - 1
        route_rows.append({
            "ep_degree": ep,
            "experts_per_rank": experts_per_rank,
            "expected_unique_owners_uniform_topk": "%.10f" % unique_owners,
            "expected_remote_owners_uniform_topk": "%.10f" % remote_owners,
            "payload_ratio_sparse_over_ag_rs": "%.10f" % sparse_to_dense_payload_ratio,
            "status": "ANALYTIC_ASSUMPTION_ONLY",
        })
    route_output = ROOT / "uniform_route_expectation.csv"
    with route_output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(route_rows[0]))
        writer.writeheader()
        writer.writerows(route_rows)
    print(output)
    for row in rows:
        print(row["case"], row["status"], row["observed"])
    print(route_output)
    for row in route_rows:
        print(row["ep_degree"], row["expected_unique_owners_uniform_topk"],
              row["expected_remote_owners_uniform_topk"],
              row["payload_ratio_sparse_over_ag_rs"])


if __name__ == "__main__":
    main()
