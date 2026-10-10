#!/usr/bin/env python3
"""Audit a FlowSim/ns-3 topology without running a serving workload.

FlowSim aggregates identical parallel links into one directed fluid resource.
This report keeps the physical-link multiplicity visible and distinguishes the
physical path alternatives in the Clos from the single BFS path currently used
by the fluid backend.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serving.core.flowsim_backend import FluidFlowNetwork


def _gbps(value):
    return float(value) * 8.0 / 1_000_000_000.0


def _switch_roles(network):
    switches = set(network.topology_audit["switch_nodes"])
    leaves = []
    spines = []
    for switch in sorted(switches):
        neighbors = set(network.adj.get(switch, ()))
        # Reverse edges are present in the parsed graph, so this captures
        # endpoint-facing leaves and switch-only spine nodes.
        if any(node not in switches for node in neighbors):
            leaves.append(switch)
        else:
            spines.append(switch)
    return switches, leaves, spines


def _edge(network, src, dst):
    return network.edges.get((int(src), int(dst)))


def _audit(path):
    network = FluidFlowNetwork(str(path), policy="FAIR")
    audit = dict(network.topology_audit)
    switches, leaves, spines = _switch_roles(network)
    endpoints = set(audit["endpoint_nodes"])

    endpoint_links = []
    leaf_spine_links = []
    for (src, dst), edge in sorted(network.edges.items()):
        if src in endpoints and dst in switches:
            endpoint_links.append({
                "endpoint": src,
                "leaf": dst,
                "direction": "endpoint_to_leaf",
                "physical_link_count": edge["physical_link_count"],
                "aggregate_capacity_Gbps": _gbps(edge["capacity_Bps"]),
            })
        elif src in switches and dst in endpoints:
            endpoint_links.append({
                "endpoint": dst,
                "leaf": src,
                "direction": "leaf_to_endpoint",
                "physical_link_count": edge["physical_link_count"],
                "aggregate_capacity_Gbps": _gbps(edge["capacity_Bps"]),
            })
        elif src in leaves and dst in spines:
            leaf_spine_links.append({
                "leaf": src,
                "spine": dst,
                "direction": "leaf_to_spine",
                "physical_link_count": edge["physical_link_count"],
                "aggregate_capacity_Gbps": _gbps(edge["capacity_Bps"]),
            })
        elif src in spines and dst in leaves:
            leaf_spine_links.append({
                "leaf": dst,
                "spine": src,
                "direction": "spine_to_leaf",
                "physical_link_count": edge["physical_link_count"],
                "aggregate_capacity_Gbps": _gbps(edge["capacity_Bps"]),
            })

    per_leaf = []
    for leaf in leaves:
        endpoint_up = [
            row for row in endpoint_links
            if row["leaf"] == leaf and row["direction"] == "endpoint_to_leaf"]
        endpoint_down = [
            row for row in endpoint_links
            if row["leaf"] == leaf and row["direction"] == "leaf_to_endpoint"]
        uplinks = [
            row for row in leaf_spine_links
            if row["leaf"] == leaf and row["direction"] == "leaf_to_spine"]
        downlinks = [
            row for row in leaf_spine_links
            if row["leaf"] == leaf and row["direction"] == "spine_to_leaf"]
        endpoint_capacity = sum(row["aggregate_capacity_Gbps"] for row in endpoint_up)
        uplink_capacity = sum(row["aggregate_capacity_Gbps"] for row in uplinks)
        per_leaf.append({
            "leaf": leaf,
            "endpoint_count": len(endpoint_up),
            "endpoint_uplink_capacity_Gbps": endpoint_capacity,
            "endpoint_downlink_capacity_Gbps": sum(
                row["aggregate_capacity_Gbps"] for row in endpoint_down),
            "leaf_to_spine_capacity_Gbps": uplink_capacity,
            "spine_to_leaf_capacity_Gbps": sum(
                row["aggregate_capacity_Gbps"] for row in downlinks),
            "endpoint_to_uplink_oversubscription": (
                endpoint_capacity / uplink_capacity
                if uplink_capacity else None),
            "leaf_spine_links": uplinks,
        })

    # In the current backend a source/destination pair uses one BFS path.  In
    # a Clos, endpoints on different leaves have one logical path per common
    # spine, while parallel physical links are represented by aggregate
    # capacity rather than independent FlowSim paths.
    leaf_spine_options = []
    for src_leaf in leaves:
        for dst_leaf in leaves:
            if src_leaf == dst_leaf:
                continue
            common_spines = [
                spine for spine in spines
                if _edge(network, src_leaf, spine) is not None and
                _edge(network, dst_leaf, spine) is not None]
            leaf_spine_options.append({
                "src_leaf": src_leaf,
                "dst_leaf": dst_leaf,
                "logical_spine_path_count": len(common_spines),
                "physical_parallel_links_per_spine": {
                    str(spine): {
                        "src_uplink_count": _edge(network, src_leaf, spine)[
                            "physical_link_count"],
                        "dst_downlink_count": _edge(network, spine, dst_leaf)[
                            "physical_link_count"],
                    }
                    for spine in common_spines
                },
                "flowsim_selected_path_count": 1 if common_spines else 0,
            })

    audit.update({
        "switch_roles": {
            "leaf_nodes": leaves,
            "spine_nodes": spines,
        },
        "endpoint_links": endpoint_links,
        "leaf_spine_links": leaf_spine_links,
        "per_leaf_capacity": per_leaf,
        "leaf_spine_path_options": leaf_spine_options,
        "queue_semantics": "analytical residual fluid backlog, not packet queue",
        "ecn_pfc_drop_semantics": "not modeled by FlowSim",
    })
    return audit


def _markdown(audit):
    lines = [
        "# FlowSim Topology Audit",
        "",
        f"- Topology: `{audit['topology_path']}`",
        f"- Declared physical edges: `{audit['declared_physical_edge_count']}`",
        f"- Parsed physical edges: `{audit['parsed_physical_edge_count']}`",
        f"- Directed physical edges after reverse materialization: `{audit['directed_physical_edge_count']}`",
        f"- Directed aggregate pairs: `{audit['directed_aggregate_pair_count']}`",
        f"- Routing: `{audit['routing_model']}`",
        f"- Parallel-link model: `{audit['parallel_link_model']}`",
        "- FlowSim queue: analytical residual fluid backlog; not packet-buffer occupancy, ECN, PFC, or drops.",
        "",
        "## Per-leaf capacity",
        "",
        "| Leaf | endpoints | endpoint-facing Gbps | leaf→spine Gbps | oversubscription |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in audit["per_leaf_capacity"]:
        lines.append(
            f"| {row['leaf']} | {row['endpoint_count']} | "
            f"{row['endpoint_uplink_capacity_Gbps']:.1f} | "
            f"{row['leaf_to_spine_capacity_Gbps']:.1f} | "
            f"{row['endpoint_to_uplink_oversubscription']:.3f} |")
    lines.extend(["", "## Parallel leaf-spine links", "",
                  "| Leaf | Spine | direction | physical links | aggregate Gbps |",
                  "|---:|---:|---|---:|---:|"])
    for row in audit["leaf_spine_links"]:
        lines.append(
            f"| {row['leaf']} | {row['spine']} | {row['direction']} | "
            f"{row['physical_link_count']} | "
            f"{row['aggregate_capacity_Gbps']:.1f} |")
    lines.extend(["", "## Path alternatives", "",
                  "The topology may have multiple spine choices, but the current "
                  "FlowSim backend selects one BFS path per endpoint pair. "
                  "Parallel physical links are represented as aggregate capacity.", "",
                  "| source leaf | destination leaf | logical spine paths | FlowSim paths used |",
                  "|---:|---:|---:|---:|"])
    for row in audit["leaf_spine_path_options"]:
        lines.append(
            f"| {row['src_leaf']} | {row['dst_leaf']} | "
            f"{row['logical_spine_path_count']} | "
            f"{row['flowsim_selected_path_count']} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("topology", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit = _audit(args.topology)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.topology.stem
    json_path = args.output_dir / f"{stem}.json"
    md_path = args.output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(audit), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
