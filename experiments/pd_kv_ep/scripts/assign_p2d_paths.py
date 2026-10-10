#!/usr/bin/env python3
"""Attach offline path assignments to a P2D event ledger for P2.

The source event ledger is copied without changing request IDs, timestamps,
bytes, or event counts.  Only P2D rows receive a concrete shortest path.  The
assignments are characterization controls for last-shard sensitivity:
CURRENT_BFS reproduces the backend default, ALT_SPINE uses the other Clos
spine when available, and ECMP_ROUND_ROBIN deterministically stripes P2D
flows across all shortest logical spine choices.  This is not an online
routing implementation and does not claim packet-level ECMP behavior.
"""

import argparse
import csv
import json
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serving.core.flowsim_backend import FluidFlowNetwork


def _all_shortest_paths(network, src, dst, limit=8):
    src, dst = int(src), int(dst)
    if src == dst:
        return [()]
    distance = {src: 0}
    queue = deque([src])
    while queue:
        node = queue.popleft()
        for nxt in network.adj.get(node, ()):
            if nxt not in distance:
                distance[nxt] = distance[node] + 1
                queue.append(nxt)
    if dst not in distance:
        raise ValueError("no path %d -> %d" % (src, dst))
    paths = []

    def visit(node, links):
        if len(paths) >= limit:
            return
        if node == dst:
            paths.append(tuple(links))
            return
        for nxt in sorted(network.adj.get(node, ())):
            if distance.get(nxt) != distance[node] + 1:
                continue
            visit(nxt, links + [(node, nxt)])

    visit(src, [])
    return paths


def _route(network, row, mode, ordinal):
    if row["event_type"] not in ("1", "P2D_KV", "REMOTE_KV_FETCH"):
        return ""
    src, dst = int(row["src"]), int(row["dst"])
    candidates = _all_shortest_paths(network, src, dst)
    if len(candidates) <= 1 or mode == "CURRENT_BFS":
        return ""
    if mode == "ALT_SPINE":
        base = tuple(network.path(src, dst))
        for candidate in candidates:
            if candidate != base:
                return ";".join("%d->%d" % link for link in candidate)
        return ""
    if mode == "ECMP_ROUND_ROBIN":
        selected = candidates[ordinal % len(candidates)]
        return ";".join("%d->%d" % link for link in selected)
    raise ValueError("unknown path mode %s" % mode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("CURRENT_BFS", "ALT_SPINE", "ECMP_ROUND_ROBIN"),
        required=True)
    args = parser.parse_args()
    network = FluidFlowNetwork(str(args.topology), policy="FAIR")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    p2d_count = 0
    assigned_count = 0
    with args.events.open(newline="", encoding="utf-8") as source, \
            args.output.open("w", newline="", encoding="utf-8") as target:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        if "path_override" not in fields:
            fields.append("path_override")
        writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for ordinal, row in enumerate(reader):
            row = dict(row)
            if row.get("event_type") in ("1", "P2D_KV", "REMOTE_KV_FETCH"):
                p2d_count += 1
                value = _route(network, row, args.mode, ordinal)
                row["path_override"] = value
                assigned_count += bool(value)
            else:
                row["path_override"] = ""
            writer.writerow(row)
    manifest = {
        "source_events": str(args.events.resolve()),
        "output_events": str(args.output.resolve()),
        "topology": str(args.topology.resolve()),
        "mode": args.mode,
        "p2d_event_count": p2d_count,
        "overridden_p2d_event_count": assigned_count,
        "bytes_unchanged": True,
        "semantics": "offline shortest-path characterization; not online ECMP or routing policy",
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
