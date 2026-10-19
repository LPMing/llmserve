#!/usr/bin/env python3
"""Recompute the token-consumption gate from frozen FlowSim and Chakra artifacts.

This emits an explanatory profile-derived/oracle timeline; it does not rerun or
claim an integrated B2 serving simulation.
"""

import csv
import json
import os
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
BASE = ROOT / "research_cache_network_joint"
FLOW_FILE = BASE / "results/a0_sampler_debug_flows.jsonl"
TIMELINE_FILE = BASE / "02_BASELINE_EVENT_TIMELINE.csv"
ET_DIR = BASE / "inputs/cachejoint-a0-4p1d/workload/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/instance4_batch1"
REQ_IDS = {1, 3, 5, 7}
SAMPLER_NS = 177_175_000
ARRIVAL_NS = 150_107_000
LINK_BPS = 200_000_000_000
BYTES_PER_RAIL = 807_075_840


def read_varint(data, offset):
    value = shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def read_et(path):
    # Chakra ET is a stream of varint-length-prefixed GlobalMetadata then Nodes.
    sys.path.insert(0, str(ROOT / "astra-sim/extern/graph_frontend/chakra/schema/protobuf"))
    os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
    from et_def_pb2 import GlobalMetadata, Node

    data = path.read_bytes()
    offset = 0
    messages = []
    while offset < len(data):
        length, offset = read_varint(data, offset)
        payload = data[offset : offset + length]
        if len(payload) != length:
            raise ValueError(f"truncated ET message in {path}")
        offset += length
        messages.append(payload)
    if not messages:
        raise ValueError(f"empty ET file: {path}")
    metadata = GlobalMetadata()
    metadata.ParseFromString(messages[0])
    nodes = []
    for payload in messages[1:]:
        node = Node()
        node.ParseFromString(payload)
        nodes.append(node)
    return nodes


def read_flows():
    by_layer = defaultdict(list)
    all_flows = []
    bytes_per_receiver_rank = defaultdict(int)
    with FLOW_FILE.open() as stream:
        for line in stream:
            if not line.startswith("{"):
                continue
            flow = json.loads(line)
            ids = set(flow.get("request_ids") or [])
            if flow.get("traffic_subtype") != "P2D" or not ids.intersection(REQ_IDS):
                continue
            layer_id = int(flow["layer_id"])
            layer = (layer_id - 2) // 10
            if not 0 <= layer < 48 or layer_id != 2 + 10 * layer:
                raise AssertionError(f"unexpected P2D layer_id={layer_id}")
            flow["layer"] = layer
            by_layer[layer].append(flow)
            all_flows.append(flow)
            bytes_per_receiver_rank[int(flow["logical_dst"])] += int(flow["bytes"])
    if len(all_flows) != 4 * 96:
        raise AssertionError(f"expected 384 target flows, got {len(all_flows)}")
    if sum(int(f["bytes"]) for f in all_flows) != 4 * 403_537_920:
        raise AssertionError("P2D byte conservation failed")
    if len(bytes_per_receiver_rank) != 2 or any(
        value != BYTES_PER_RAIL for value in bytes_per_receiver_rank.values()
    ):
        raise AssertionError(f"expected two 807075840-byte TP receiver rails, got {dict(bytes_per_receiver_rank)}")
    return by_layer


def read_decode_costs():
    rank_costs = {}
    collectives_by_layer = defaultdict(list)
    for rank, filename in ((16, "llm.16.et"), (17, "llm.17.et")):
        nodes = read_et(ET_DIR / filename)
        comp = [n for n in nodes if int(n.type) == 5]
        rank_costs[rank] = {
            "nodes": nodes,
            "comp": comp,
            "embedding_us": max(int(n.duration_micros) for n in comp if "embedding_0" in n.name),
            "tail_us": sum(
                max(int(n.duration_micros) for n in comp if marker in n.name)
                for marker in ("final_layernorm_481", "lm_head_482", "sampler_483")
            ),
        }
        for node in nodes:
            match = re.search(r"_(\d+)_ALLREDUCE$", node.name)
            if match and int(node.type) == 8:
                line_index = int(match.group(1))
                layer = (line_index - 6) // 10
                if 0 <= layer < 48 and line_index == 10 * layer + 6:
                    collectives_by_layer[layer].append({
                        "rank": rank,
                        "duration_us_et": int(node.duration_micros),
                        "node_name": node.name,
                    })
    per_rank = {}
    for rank, bundle in rank_costs.items():
        per_rank[rank] = []
        nodes = bundle["nodes"]
        for layer in range(48):
            lo, hi = 10 * layer + 1, 10 * layer + 10
            us = 0
            for node in nodes:
                match = re.search(r"_(\d+)(?:_|$)", node.name)
                if match and lo <= int(match.group(1)) < hi and int(node.type) == 5:
                    us += int(node.duration_micros)
            per_rank[rank].append(us)
    return rank_costs, per_rank, collectives_by_layer


def ns_ms(value):
    return round(value / 1_000_000, 6)


def write_outputs():
    by_layer = read_flows()
    rank_meta, rank_layer_us, collective_layers = read_decode_costs()
    layer_rows = []
    decode_cursor = SAMPLER_NS + max(meta["embedding_us"] for meta in rank_meta.values()) * 1000
    cumulative_compute_us = max(meta["embedding_us"] for meta in rank_meta.values())

    for layer in range(48):
        flows = by_layer[layer]
        if len(flows) != 8:
            raise AssertionError(f"layer {layer}: expected 8 child/rank shards, got {len(flows)}")
        request_rank_pairs = {(rid, int(flow["logical_dst"])) for flow in flows for rid in flow["request_ids"] if rid in REQ_IDS}
        if len(request_rank_pairs) != 8:
            raise AssertionError(f"layer {layer}: expected 4 requests x TP2, got {len(request_rank_pairs)}")
        kv_ready = max(int(flow["end_ns"]) for flow in flows)
        first_release = min(int(flow["requested_start_ns"]) for flow in flows)
        last_release = max(int(flow["requested_start_ns"]) for flow in flows)
        rank_us = {rank: rank_layer_us[rank][layer] for rank in rank_layer_us}
        group_compute_us = max(rank_us.values())
        collective_rows = collective_layers.get(layer, [])
        layer_start = max(decode_cursor, kv_ready)
        layer_finish = layer_start + group_compute_us * 1000
        wait_ns = layer_start - decode_cursor
        layer_rows.append({
            "layer": layer,
            "request_ids": "1;3;5;7",
            "tp_rank_shards": 8,
            "p2d_first_release_ns": first_release,
            "p2d_last_release_ns": last_release,
            "p2d_last_flow_finish_ns": kv_ready,
            "p2d_flow_count": len(flows),
            "p2d_bytes_all_requests_layer": sum(int(flow["bytes"]) for flow in flows),
            "decode_rank16_compute_us_profile": rank_us[16],
            "decode_rank17_compute_us_profile": rank_us[17],
            "decode_group_compute_us_profile": group_compute_us,
            "decode_tp_collective_nodes": len(collective_rows),
            "decode_tp_collective_duration_us_in_et": sum(
                row["duration_us_et"] for row in collective_rows),
            "decode_tp_collective_runtime_event": "NOT_RECORDED",
            "decode_layer_start_ns_oracle": layer_start,
            "decode_layer_finish_ns_oracle": layer_finish,
            "kv_wait_ns_oracle": wait_ns,
            "kv_event_evidence": "SIMULATED_FLOWSIM",
            "decode_cost_evidence": "PROFILE_DERIVED_FROM_CHAKRA_TRACE",
            "oracle_schedule_evidence": "INDEPENDENT_RESOURCE_CONSTRAINED_ORACLE_NOT_INTEGRATED",
        })
        decode_cursor = layer_finish
        cumulative_compute_us += group_compute_us

    if any(row["decode_tp_collective_nodes"] != 2 or
           row["decode_tp_collective_duration_us_in_et"] != 0
           for row in layer_rows):
        raise AssertionError("frozen ET no longer has two zero-duration TP collective nodes per layer")
    if any(row["kv_wait_ns_oracle"] != 0 for row in layer_rows):
        raise AssertionError("this frozen workload should have zero layerwise KV wait in the oracle")

    tail_us = max(meta["tail_us"] for meta in rank_meta.values())
    b2_token2_ns = decode_cursor + tail_us * 1000
    b2_decode_us = cumulative_compute_us + tail_us
    if b2_decode_us != 14_395:
        raise AssertionError(f"expected 14.395 ms decode compute floor, got {b2_decode_us} us")
    with (OUT / "03_LAYER_CONSUMPTION_TIMELINE.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(layer_rows[0]))
        writer.writeheader()
        writer.writerows(layer_rows)

    per_rail_ns = BYTES_PER_RAIL * 8 * 1_000_000_000 / LINK_BPS
    capacity_before_sampler = (SAMPLER_NS - 150_125_000) * LINK_BPS / 8 / 1_000_000_000
    allkv_lb_ns = 150_125_000 + per_rail_ns
    a0_last_kv = 182_646_480
    a0_token2 = 197_041_480
    a0_token3 = 211_436_480
    a2_token2 = 191_570_000
    a2_token3 = 205_965_000
    proxy_15pct_target_ns = int(round((a0_token2 - SAMPLER_NS) * 0.85))
    b1_token2_lb = allkv_lb_ns + 14_395_000
    rows = [
        {
            "case": "B0_A0_FULL_BARRIER_INTEGRATED_FLOWSIM",
            "evidence": "SIMULATED_INTEGRATED_FLOWSIM",
            "sampler_ready_ms": ns_ms(SAMPLER_NS),
            "kv_ready_ms": ns_ms(a0_last_kv),
            "token2_ms": ns_ms(a0_token2),
            "token3_ms": ns_ms(a0_token3),
            "first_itl_sampler_anchored_ms": ns_ms(a0_token2 - SAMPLER_NS),
            "mean_itl_sampler_anchored_ms": ns_ms((a0_token3 - SAMPLER_NS) / 2),
            "first_interval_from_simulator_event_ms": ns_ms(a0_token2 - a0_last_kv),
            "mean_interval_from_simulator_events_ms": ns_ms((a0_token3 - a0_last_kv) / 2),
            "client_first_itl_ms": "",
            "arrival_to_token2_ms": ns_ms(a0_token2 - ARRIVAL_NS),
            "child_arrival_to_token3_ms": ns_ms(a0_token3 - ARRIVAL_NS),
            "session_arrival0_to_token3_ms": ns_ms(a0_token3),
            "first_itl_15pct_proxy_target_ms": ns_ms(proxy_15pct_target_ns),
            "token2_gain_vs_a0_sampler_proxy_ms": 0.0,
            "token2_gain_vs_a2_ms": ns_ms(a2_token2 - a0_token2),
            "kv_bytes_per_request": 403_537_920,
            "notes": "Client emission is not separately observed; sampler-anchored ITL is a proxy.",
        },
        {
            "case": "B1_FULL_BARRIER_IDEAL_NETWORK_ONLY_PHYSICAL_LOWER_BOUND",
            "evidence": "ANALYTICAL_LOWER_BOUND_NOT_RUN",
            "sampler_ready_ms": ns_ms(SAMPLER_NS),
            "kv_ready_ms": ns_ms(allkv_lb_ns),
            "token2_ms": ns_ms(b1_token2_lb),
            "token3_ms": ns_ms(b1_token2_lb + 14_395_000),
            "first_itl_sampler_anchored_ms": ns_ms(b1_token2_lb - SAMPLER_NS),
            "mean_itl_sampler_anchored_ms": ns_ms(14_395_000),
            "first_interval_from_simulator_event_ms": "",
            "mean_interval_from_simulator_events_ms": "",
            "client_first_itl_ms": "",
            "arrival_to_token2_ms": ns_ms(b1_token2_lb - ARRIVAL_NS),
            "child_arrival_to_token3_ms": ns_ms(b1_token2_lb + 14_395_000 - ARRIVAL_NS),
            "session_arrival0_to_token3_ms": ns_ms(b1_token2_lb + 14_395_000),
            "first_itl_15pct_proxy_target_ms": ns_ms(proxy_15pct_target_ns),
            "token2_gain_vs_a0_sampler_proxy_ms": ns_ms((a0_token2 - SAMPLER_NS) - (b1_token2_lb - SAMPLER_NS)),
            "token2_gain_vs_a2_ms": ns_ms(a2_token2 - b1_token2_lb),
            "kv_bytes_per_request": 403_537_920,
            "notes": "Work-conserving one-cut serialization bound; max network-only token2 gain vs B0 is 0.2384464 ms.",
        },
        {
            "case": "B2_LAYERWISE_KV_CONSUMPTION_ORACLE",
            "evidence": "INDEPENDENT_PROFILE_DERIVED_ORACLE_NOT_INTEGRATED",
            "sampler_ready_ms": ns_ms(SAMPLER_NS),
            "kv_ready_ms": ns_ms(a0_last_kv),
            "token2_ms": ns_ms(b2_token2_ns),
            "token3_ms": ns_ms(b2_token2_ns + 14_395_000),
            "first_itl_sampler_anchored_ms": ns_ms(b2_token2_ns - SAMPLER_NS),
            "mean_itl_sampler_anchored_ms": ns_ms(14_395_000),
            "first_interval_from_simulator_event_ms": "",
            "mean_interval_from_simulator_events_ms": "",
            "client_first_itl_ms": "",
            "arrival_to_token2_ms": ns_ms(b2_token2_ns - ARRIVAL_NS),
            "child_arrival_to_token3_ms": ns_ms(b2_token2_ns + 14_395_000 - ARRIVAL_NS),
            "session_arrival0_to_token3_ms": ns_ms(b2_token2_ns + 14_395_000),
            "first_itl_15pct_proxy_target_ms": ns_ms(proxy_15pct_target_ns),
            "token2_gain_vs_a0_sampler_proxy_ms": ns_ms(a0_token2 - b2_token2_ns),
            "token2_gain_vs_a2_ms": ns_ms(a2_token2 - b2_token2_ns),
            "kv_bytes_per_request": 403_537_920,
            "notes": "Conditional oracle: assumes all 4 requests x TP2 per-layer commits and stable non-conflicting KV slots; staged allocator and client emission are unmodeled.",
        },
        {
            "case": "A2_DELTA_EXISTING_INTEGRATED_STRONG_BASELINE",
            "evidence": "SIMULATED_INTEGRATED_FLOWSIM",
            "sampler_ready_ms": ns_ms(SAMPLER_NS),
            "kv_ready_ms": ns_ms(177_175_000),
            "token2_ms": ns_ms(a2_token2),
            "token3_ms": ns_ms(a2_token3),
            "first_itl_sampler_anchored_ms": ns_ms(a2_token2 - SAMPLER_NS),
            "mean_itl_sampler_anchored_ms": ns_ms((a2_token3 - SAMPLER_NS) / 2),
            "first_interval_from_simulator_event_ms": ns_ms(a2_token2 - 177_175_000),
            "mean_interval_from_simulator_events_ms": ns_ms((a2_token3 - 177_175_000) / 2),
            "client_first_itl_ms": "",
            "arrival_to_token2_ms": ns_ms(a2_token2 - ARRIVAL_NS),
            "child_arrival_to_token3_ms": ns_ms(a2_token3 - ARRIVAL_NS),
            "session_arrival0_to_token3_ms": ns_ms(a2_token3),
            "first_itl_15pct_proxy_target_ms": ns_ms(proxy_15pct_target_ns),
            "token2_gain_vs_a0_sampler_proxy_ms": ns_ms(a0_token2 - a2_token2),
            "token2_gain_vs_a2_ms": 0.0,
            "kv_bytes_per_request": 884_736,
            "notes": "A2 changes KV bytes, so it is a strong serving baseline but not a same-byte comparison to B2.",
        },
    ]
    with (OUT / "04_DECODE_ORACLE_RESULTS.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(layer_rows)} layer rows; B2 token2={ns_ms(b2_token2_ns):.6f} ms; decode={b2_decode_us} us")
    print(f"rail_lb_ms={ns_ms(per_rail_ns):.7f} all_kv_lb_ms={ns_ms(allkv_lb_ns):.7f} capacity_before_sampler={capacity_before_sampler:.0f} B deficit={BYTES_PER_RAIL-capacity_before_sampler:.0f} B")


if __name__ == "__main__":
    write_outputs()
