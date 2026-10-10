#!/usr/bin/env python3
"""Build a model-derived 1P2D FlowSim motivation event ledger.

The ledger is deliberately separate from the interactive serving worker.  It
preserves the request arrival order and uses the Qwen profile/model to derive
prefill anchors, KV bytes, expert routing, and EP bytes.  FlowSim then sees
all requests in one global event queue, which is required for cross-request
P2D/Decode-EP overlap.
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serving.core.gate_function import GateRouter
from experiments.pd_kv_ep.scripts.build_model_derived_replay import ProfileClock


MODEL_DEFAULT = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
TOPOLOGY_DEFAULT = ROOT / (
    "experiments/pd_kv_ep/configs/ns3/two_prefill_6_rank_shared_spine.txt")
EVENT_FIELDS = [
    "event_id", "start_ns", "src", "dst", "bytes", "event_type",
    "request_id", "collective_id", "layer_id", "active_request_ids",
    "serving_role",
]


def _load(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _path_hops(topology, src, dst):
    graph = defaultdict(list)
    with topology.open(encoding="utf-8") as stream:
        first = stream.readline().split()
        if len(first) != 3:
            raise ValueError("invalid topology header")
        _, switch_count, link_count = map(int, first)
        for _ in range(switch_count):
            stream.readline()
        for _ in range(link_count):
            fields = stream.readline().split()
            a, b = int(fields[0]), int(fields[1])
            graph[a].append(b)
            graph[b].append(a)
    if src == dst:
        return 0
    pending = [(src, 0)]
    seen = {src}
    while pending:
        node, hops = pending.pop(0)
        for nxt in graph[node]:
            if nxt in seen:
                continue
            if nxt == dst:
                return hops + 1
            seen.add(nxt)
            pending.append((nxt, hops + 1))
    raise ValueError("no path %d -> %d" % (src, dst))


def _read_requests(path, count, arrival_interval_ns, input_tokens, output_tokens):
    rows = []
    if path is not None:
        with path.open(encoding="utf-8") as stream:
            for index, line in enumerate(stream):
                if index >= count:
                    break
                source = json.loads(line)
                rows.append({
                    "request_id": str(source.get("request_id", index)),
                    "input_toks": int(source["input_toks"]),
                    "output_toks": int(source["output_toks"]),
                    "arrival_time_ns": int(source["arrival_time_ns"]),
                    "emit_p2d": bool(source.get("emit_p2d", True)),
                    "emit_ep": bool(source.get("emit_ep", True)),
                    "decode_pool": source.get("decode_pool"),
                })
    else:
        for index in range(count):
            rows.append({
                "request_id": str(index),
                "input_toks": int(input_tokens),
                "output_toks": int(output_tokens),
                "arrival_time_ns": index * int(arrival_interval_ns),
                "emit_p2d": True,
                "emit_ep": True,
                "decode_pool": None,
            })
    if not rows:
        raise ValueError("no requests selected")
    first = rows[0]["arrival_time_ns"]
    for row in rows:
        row["arrival_time_ns"] -= first
    return rows


def build(args):
    model = _load(args.model)
    topology = args.topology.resolve()
    clock = ProfileClock(args.hardware, args.model_name, model)
    layers = int(model["num_hidden_layers"])
    kv_heads = int(model.get("num_key_value_heads", model["num_attention_heads"]))
    head_dim = int(model.get("head_dim", model["hidden_size"] // model["num_attention_heads"]))
    hidden = int(model["hidden_size"])
    fp_bytes = 2 if model.get("torch_dtype", "bfloat16") in ("bfloat16", "float16") else 4
    ep_degree = 2
    top_k = int(model.get("num_experts_per_tok", 1))
    kv_bytes_total_per_token = layers * 2 * kv_heads * head_dim * fp_bytes
    kv_bytes_per_dest_rank = kv_bytes_total_per_token // 2
    kv_bytes_per_dest_rank_per_layer = (
        2 * kv_heads * head_dim * fp_bytes // 2)
    ep_bytes_per_routed_token = layers * hidden * fp_bytes
    ep_bin_ns = int(args.ep_bin_us * 1000)
    if ep_bin_ns <= 0:
        raise ValueError("--ep-bin-us must be positive")
    line_rate_bps = int(args.link_gbps * 1_000_000_000)
    link_delay_ns = 5_000
    router = GateRouter(
        0, 0, int(model.get("num_experts", model.get("num_local_experts", 128))),
        num_experts_per_tok=top_k, routing_policy="BALANCED", block_copy=False)
    requests = _read_requests(
        args.trace, args.count, args.arrival_interval_ns,
        args.input_tokens, args.output_tokens)

    # One TP=2 Prefill unit and two TP=2 Decode instances.  The six endpoint
    # topology maps P=(0,1), D0=(2,3), and D1=(4,5).  Keeping two P source
    # NICs prevents a single source egress from hiding all downstream
    # KV-versus-EP interaction.
    prefill_ranks = (0, 1)
    decode_pools = ((2, 3), (4, 5))
    events = []
    request_rows = []
    ep_bins = defaultdict(list)
    event_id = 0
    collective_id = 0
    for index, request in enumerate(requests):
        req_id = str(index)
        input_toks = max(1, request["input_toks"])
        output_toks = max(1, request["output_toks"])
        arrival = request["arrival_time_ns"]
        prefill_done = arrival + clock.prefill_ns(input_toks)
        requested_pool = request.get("decode_pool")
        if requested_pool is None:
            dest_pool = decode_pools[index % len(decode_pools)]
        else:
            pool_index = int(requested_pool)
            if pool_index < 0 or pool_index >= len(decode_pools):
                raise ValueError(
                    "decode_pool=%r is outside available pools [0, %d]" %
                    (requested_pool, len(decode_pools) - 1))
            dest_pool = decode_pools[pool_index]
        p2d_finish = prefill_done
        p2d_event_count = 0
        for src, dst in zip(prefill_ranks, dest_pool):
            if request.get("emit_p2d", True):
                if args.pd_kv_transfer_mode == "POST_PREFILL":
                    layer_events = [(0, prefill_done,
                                     kv_bytes_per_dest_rank * input_toks)]
                else:
                    # Spread the profile-backed prefill anchor over the
                    # transformer layers.  Each event carries only that
                    # layer's model-derived K/V shard.
                    layer_ns = clock.prefill_layer_ns(input_toks)
                    layer_events = []
                    for layer_id in range(layers):
                        layer_ready = min(
                            prefill_done,
                            arrival + (layer_id + 1) * layer_ns)
                        layer_events.append((
                            layer_id,
                            layer_ready,
                            kv_bytes_per_dest_rank_per_layer * input_toks,
                        ))
                for layer_id, start_ns, event_bytes in layer_events:
                    wire_ns = math.ceil(event_bytes * 8 * 1e9 / line_rate_bps)
                    p2d_finish = max(
                        p2d_finish,
                        start_ns + _path_hops(topology, src, dst) * link_delay_ns + wire_ns)
                    events.append({
                        "event_id": event_id,
                        "start_ns": start_ns,
                        "src": src,
                        "dst": dst,
                        "bytes": event_bytes,
                        "event_type": "P2D_KV",
                        "request_id": req_id,
                        "collective_id": "",
                        "layer_id": layer_id,
                        "active_request_ids": req_id,
                        "serving_role": "prefill",
                    })
                    event_id += 1
                    p2d_event_count += 1
        if not request.get("emit_p2d", True):
            p2d_finish = prefill_done
        decode_period = clock.decode_period_ns(input_toks, 1)
        decode_start = p2d_finish
        if request.get("emit_ep", True):
            for step in range(output_toks):
                start = decode_start + step * decode_period
                ep_bins[(dest_pool, start // ep_bin_ns)].append((req_id, start))
        request_rows.append({
            "request_id": req_id,
            "arrival_time_ns": arrival,
            "input_toks": input_toks,
            "output_toks": output_toks,
            "prefill_done_anchor_ns": prefill_done,
            "decode_start_anchor_ns": decode_start,
            "decode_period_ns": decode_period,
            "p2d_bytes_total": kv_bytes_total_per_token * input_toks,
            "p2d_transfer_mode": args.pd_kv_transfer_mode,
            "p2d_event_count": p2d_event_count,
            "decode_pool": "%d,%d" % dest_pool,
            "requested_decode_pool": ("default" if requested_pool is None
                                       else int(requested_pool)),
            "emit_p2d": request.get("emit_p2d", True),
            "emit_ep": request.get("emit_ep", True),
        })

    for (pool, _), active_steps in sorted(ep_bins.items(), key=lambda item: min(t for _, t in item[1])):
        request_ids = sorted({req_id for req_id, _ in active_steps}, key=int)
        token_count = len(active_steps)
        source_tokens = [token_count // ep_degree + (1 if r < token_count % ep_degree else 0)
                         for r in range(ep_degree)]
        routing = router.route_ep(0, "motivation:%d" % collective_id,
                                  token_count, ep_degree,
                                  source_tokens=source_tokens)
        active = ";".join(request_ids)
        start_ns = min(start for _, start in active_steps)
        for src_index, row in enumerate(routing.pair_matrix):
            for dst_index, pair_count in enumerate(row):
                if src_index == dst_index or pair_count <= 0:
                    continue
                bytes_total = pair_count * ep_bytes_per_routed_token
                src, dst = pool[src_index], pool[dst_index]
                for event_type, event_src, event_dst in (
                        ("EP_DISPATCH", src, dst), ("EP_COMBINE", dst, src)):
                    events.append({
                        "event_id": event_id,
                        "start_ns": start_ns,
                        "src": event_src,
                        "dst": event_dst,
                        "bytes": bytes_total,
                        "event_type": event_type,
                        "request_id": "-1",
                        "collective_id": collective_id,
                        "layer_id": 0,
                        "active_request_ids": active,
                        "serving_role": "decode",
                    })
                    event_id += 1
        collective_id += 1

    events.sort(key=lambda row: (int(row["start_ns"]), row["event_type"], int(row["event_id"])))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "events.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        writer.writerows(events)
    request_fields = list(request_rows[0])
    with (args.output_dir / "requests.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=request_fields)
        writer.writeheader()
        writer.writerows(request_rows)
    manifest = {
        "schema_version": 1,
        "kind": "flowsim_model_derived_motivation_1p2d",
        "model": args.model_name,
        "hardware": args.hardware,
        "topology": str(topology),
        "request_count": len(request_rows),
        "event_count": len(events),
        "ep_collective_count": collective_id,
        "ep_suppressed_request_ids": [
            row["request_id"] for row in request_rows if not row.get("emit_ep", True)
        ],
        "p2d_suppressed_request_ids": [
            row["request_id"] for row in request_rows if not row.get("emit_p2d", True)
        ],
        "kv_bytes_per_token_total": kv_bytes_total_per_token,
        "kv_bytes_per_destination_rank_per_token": kv_bytes_per_dest_rank,
        "ep_bytes_per_routed_token_all_layers": ep_bytes_per_routed_token,
        "ep_degree": ep_degree,
        "top_k": top_k,
        "prefill_tp": 2,
        "decode_tp": 2,
        "ep_bin_us": args.ep_bin_us,
        "pd_kv_transfer_mode": args.pd_kv_transfer_mode,
        "p2d_layer_count": layers if args.pd_kv_transfer_mode == "LAYERWISE" else 1,
        "p2d_event_granularity": (
            "one independent model-derived P2D KV event per transformer layer"
            if args.pd_kv_transfer_mode == "LAYERWISE"
            else "one model-derived P2D KV event after prefill"),
        "synthetic_byte_override": False,
        "timing_model": {
            "prefill": "profile-backed Qwen3 prefill estimate",
            "p2d": "model-derived KV bytes at the configured link-rate anchor",
            "decode": "profile-backed one-token decode period",
            "ep": "GateRouter-derived pair matrix, coalesced into --ep-bin-us bins",
            "serving_scope": "data-plane replay; not interactive scheduler E2E",
        },
        "files": {"events": "events.csv", "requests": "requests.csv"},
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=32)
    parser.add_argument("--arrival-interval-ns", type=int, default=1_000_000)
    parser.add_argument("--input-tokens", type=int, default=2048)
    parser.add_argument("--output-tokens", type=int, default=32)
    parser.add_argument("--ep-bin-us", type=float, default=1000.0)
    parser.add_argument(
        "--pd-kv-transfer-mode", choices=("LAYERWISE", "POST_PREFILL"),
        default="POST_PREFILL",
        help="P2D granularity: one post-prefill cache chunk or one KV event "
             "after each transformer layer")
    parser.add_argument("--trace", type=Path, default=None)
    parser.add_argument("--model", type=Path, default=MODEL_DEFAULT)
    parser.add_argument("--model-name", default="Qwen/Qwen3-30B-A3B-Instruct-2507")
    parser.add_argument("--hardware", default="RTXPRO6000")
    parser.add_argument("--topology", type=Path, default=TOPOLOGY_DEFAULT)
    parser.add_argument("--link-gbps", type=float, default=200.0)
    args = parser.parse_args()
    if args.count <= 0 or args.count > 256:
        parser.error("--count must be in [1, 256]")
    if args.arrival_interval_ns < 0:
        parser.error("--arrival-interval-ns must be non-negative")
    if args.link_gbps <= 0:
        parser.error("--link-gbps must be positive")
    build(args)


if __name__ == "__main__":
    main()
