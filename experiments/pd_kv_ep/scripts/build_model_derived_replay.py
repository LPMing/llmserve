#!/usr/bin/env python3
"""Build a bounded native ns-3 KV/EP data-plane replay.

The replay is deliberately separate from the serving control loop.  Request
arrival, input/output lengths, P/D pairing, KV bytes, expert routing, and EP
bytes are model/trace-derived.  The event clock is a documented serving
anchor: profiler-backed prefill/decode compute estimates plus an uncongested
line-rate P2D estimate.  It is therefore suitable for network attribution,
not for claiming end-to-end TTFT/TPOT.

EP traffic is coalesced over ``--ep-bin-us`` and over all transformer layers in
that bin.  This keeps a real trace window runnable at S64/S256 while retaining
the model-derived source/destination route matrix and total dispatch/combine
bytes.  The manifest records this approximation explicitly.
"""

import argparse
import csv
import json
import math
import sys
from collections import OrderedDict, defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serving.core.gate_function import GateRouter


DEFAULT_MODEL = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
MANIFESTS = {
    "S64": ROOT / "experiments/pd_kv_ep/configs/large_scale/s64_64_servers_manifest.json",
    "S256": ROOT / "experiments/pd_kv_ep/configs/large_scale/s256_256_servers_manifest.json",
    "S16_EP64": ROOT / "experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_manifest.json",
}
EVENT_HEADER = [
    "start_ns", "src", "dst", "bytes", "event_type", "request_id",
    "collective_id", "layer_id", "tag", "active_request_ids", "serving_role",
]
EVENT_CODES = {"P2D_KV": 1, "EP_DISPATCH": 2, "EP_COMBINE": 3}


def _balanced_pair_matrix(source_tokens, ep_size, top_k):
    """Match GateRouter's balanced owner-interleaved route without token loops.

    ``GateRouter._balanced_pair_matrix`` cycles the expert-owner sequence and
    assigns ``top_k`` consecutive entries to each token.  For an owner-
    interleaved cycle, the owner of entry ``position`` is ``position % ep``.
    The token pattern therefore repeats every ``ep / gcd(ep, top_k)`` tokens.
    Counting the period arithmetically is exactly equivalent to the native
    implementation, but avoids a Python loop over every generated token in a
    large trace builder.
    """
    ep_size = int(ep_size)
    top_k = int(top_k)
    if ep_size <= 0 or top_k <= 0:
        raise ValueError("ep_size and top_k must be positive")
    period = ep_size // math.gcd(ep_size, top_k)
    pattern = []
    for token_phase in range(period):
        counts = [0] * ep_size
        for offset in range(top_k):
            counts[(token_phase * top_k + offset) % ep_size] += 1
        pattern.append(counts)
    matrix = [[0] * ep_size for _ in source_tokens]
    token_start = 0
    for source_rank, count_value in enumerate(source_tokens):
        count = int(count_value)
        full, remainder = divmod(count, period)
        base_phase = token_start % period
        for destination in range(ep_size):
            total = full * sum(row[destination] for row in pattern)
            total += sum(
                pattern[(base_phase + phase) % period][destination]
                for phase in range(remainder))
            matrix[source_rank][destination] = total
        token_start += count
    return matrix


def _uniform_same_bytes_pair_matrix(source_tokens, routed_matrix, ep_size):
    """Spread each source's GateRouter remote bytes uniformly over peers.

    This is a P5 route-geometry counterfactual.  The per-source remote token
    count is copied from the model-derived GateRouter matrix, so aggregate
    EP bytes and source/destination population are unchanged; only peer
    geometry changes.  It is not a replacement for the native routing path.
    """
    matrix = [[0] * ep_size for _ in source_tokens]
    for source, row in enumerate(routed_matrix):
        remote = sum(int(row[destination]) for destination in range(ep_size)
                     if destination != source)
        peer_ids = [destination for destination in range(ep_size)
                    if destination != source]
        peers, remainder = divmod(remote, max(len(peer_ids), 1))
        for index, destination in enumerate(peer_ids):
            matrix[source][destination] = peers + (1 if index < remainder else 0)
    return matrix


def _load_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _read_requests(path, offset, limit, interval_scale=1.0):
    if offset < 0 or limit <= 0 or limit > 25_000:
        raise ValueError("require 0 <= offset and 1 <= limit <= 25,000")
    if interval_scale <= 0:
        raise ValueError("interval_scale must be positive")
    rows = []
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index < offset:
                continue
            row = json.loads(line)
            rows.append(row)
            if len(rows) >= limit:
                break
    if not rows:
        raise ValueError(f"no requests selected from {path}")
    first = int(rows[0]["arrival_time_ns"])
    previous = None
    normalized = []
    for index, row in enumerate(rows):
        source_arrival = int(row["arrival_time_ns"])
        arrival = int(round((source_arrival - first) * interval_scale))
        if previous is not None and arrival < previous:
            raise ValueError(f"request arrival order decreases at selected row {index}")
        previous = arrival
        block_hashes = row.get("input_block_hashes")
        if block_hashes is None:
            block_hashes = row.get("prefix_block_hashes", [])
        if block_hashes is None:
            block_hashes = []
        if not isinstance(block_hashes, list):
            raise ValueError(f"input_block_hashes must be a list at selected row {index}")
        normalized.append({
            "replay_request_id": index,
            "source_request_id": row.get("request_id", str(index)),
            "session_id": row.get("session_id", ""),
            "source_arrival_time_ns": source_arrival,
            "arrival_time_ns": arrival,
            "input_toks": max(0, int(row.get("input_toks", 0))),
            "output_toks": max(0, int(row.get("output_toks", 0))),
            "input_block_hashes": list(block_hashes),
            "hash_block_size": max(1, int(row.get("hash_block_size", 512))),
            "hash_semantics": row.get("hash_semantics", ""),
            "emit_p2d": bool(row.get("emit_p2d", True)),
            "emit_ep": bool(row.get("emit_ep", True)),
        })
    return normalized, first


def _read_ledger(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _group_ranks(ledger):
    by_instance = defaultdict(list)
    prefill_instances = []
    decode_instances = []
    pools = defaultdict(list)
    for row in ledger:
        rank = int(row["astra_rank"])
        instance = int(row["instance_id"])
        by_instance[instance].append(rank)
        if row["role"] == "prefill" and instance not in prefill_instances:
            prefill_instances.append(instance)
        if row["role"] == "decode" and instance not in decode_instances:
            decode_instances.append(instance)
        if row["role"] == "decode":
            pools[row["dp_group"]].append(rank)
    for values in by_instance.values():
        values.sort()
    for values in pools.values():
        values.sort(key=lambda rank: int(next(r["ep_rank"] for r in ledger
                                              if int(r["astra_rank"]) == rank)))
    return (dict(by_instance), sorted(prefill_instances), sorted(decode_instances),
            {key: value for key, value in sorted(pools.items())})


def _load_placement_map(path, prefill_instances, decode_instances):
    """Load a bijective P/D instance pairing for matched placement studies.

    The replay keeps the request arrival sequence and source prefill instance
    unchanged.  A placement map only changes which decode instance receives
    that prefill instance's handoff.  This is intentionally an offline
    characterization hook, not a serving scheduler or a routing algorithm.
    """
    if path is None:
        return None
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if isinstance(payload, dict) and "placement_map" in payload:
        payload = payload["placement_map"]
    if not isinstance(payload, dict):
        raise ValueError("placement map must be a JSON object")
    normalized = {}
    for key, value in payload.items():
        try:
            normalized[int(key)] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("placement map keys and values must be instance IDs") from exc
    expected_sources = set(prefill_instances)
    expected_destinations = set(decode_instances)
    if set(normalized) != expected_sources:
        raise ValueError(
            "placement map must contain exactly all prefill instances; "
            "missing=%s extra=%s" % (
                sorted(expected_sources - set(normalized)),
                sorted(set(normalized) - expected_sources)))
    if set(normalized.values()) != expected_destinations:
        raise ValueError(
            "placement map values must be a one-to-one permutation of all "
            "decode instances; missing=%s extra=%s" % (
                sorted(expected_destinations - set(normalized.values())),
                sorted(set(normalized.values()) - expected_destinations)))
    return {source: normalized[source] for source in sorted(normalized)}


def _topology_graph(path):
    graph = defaultdict(list)
    with path.open(encoding="utf-8") as stream:
        first = stream.readline().split()
        if len(first) != 3:
            raise ValueError(f"invalid topology header: {path}")
        node_count, switch_count, link_count = map(int, first)
        switch_line = stream.readline().split()
        for _ in range(link_count):
            fields = stream.readline().split()
            if len(fields) < 4:
                raise ValueError(f"invalid topology edge in {path}")
            src, dst = int(fields[0]), int(fields[1])
            graph[src].append(dst)
            graph[dst].append(src)
    return graph


def _path_hops(graph, src, dst):
    if src == dst:
        return 0
    queue = deque([(src, 0)])
    seen = {src}
    while queue:
        current, distance = queue.popleft()
        for neighbor in graph[current]:
            if neighbor in seen:
                continue
            if neighbor == dst:
                return distance + 1
            seen.add(neighbor)
            queue.append((neighbor, distance + 1))
    raise ValueError(f"no physical path between endpoint {src} and {dst}")


def _read_profile_rows(path, fields):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _interp(rows, x_key, x):
    points = sorted((float(row[x_key]), float(row["time_us"])) for row in rows)
    if not points:
        return 0.0
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        x0, y0 = points[-2]
        x1, y1 = points[-1]
        return y1 + (x - x1) * (y1 - y0) / max(x1 - x0, 1.0)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 + (x - x0) * (y1 - y0) / max(x1 - x0, 1.0)
    return points[-1][1]


def _interp_points(points, x):
    """Linear interpolation over an already-sorted ``(x, y)`` table."""
    if not points:
        return 0.0
    x = float(x)
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        x0, y0 = points[-2]
        x1, y1 = points[-1]
        return y1 + (x - x1) * (y1 - y0) / max(x1 - x0, 1.0)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 + (x - x0) * (y1 - y0) / max(x1 - x0, 1.0)
    return points[-1][1]


def _nearest_attention(rows, prefill_chunk, kv_prefill, n_decode, kv_decode):
    if not rows:
        return 0.0
    def distance(row):
        values = [
            (float(row["prefill_chunk"]), prefill_chunk),
            (float(row["kv_prefill"]), kv_prefill),
            (float(row["n_decode"]), n_decode),
            (float(row["kv_decode"]), kv_decode),
        ]
        return sum((math.log1p(a) - math.log1p(b)) ** 2 for a, b in values)
    return float(min(rows, key=distance)["time_us"])


class ProfileClock:
    """Small profile-backed serving clock for the network replay anchor."""

    DENSE_LAYERS = ("layernorm", "qkv_proj", "qk_norm", "rotary_emb", "o_proj")

    def __init__(self, hardware, model_name, model, override_period_ns=None):
        model_rel = model_name.split("/", 1)
        profile_root = ROOT / "profiler/perf" / hardware / model_name
        variant = profile_root / "bf16"
        dense = _read_profile_rows(variant / "tp2/dense.csv", ("layer", "tokens", "time_us"))
        attention = _read_profile_rows(variant / "tp2/attention.csv",
                                       ("prefill_chunk", "kv_prefill", "n_decode", "kv_decode", "time_us"))
        moe = _read_profile_rows(variant / "tp1/moe.csv", ("tokens", "activated_experts", "time_us"))
        self.dense = defaultdict(list)
        for row in dense:
            self.dense[row["layer"]].append(
                (float(row["tokens"]), float(row["time_us"])))
        for layer in self.dense:
            self.dense[layer].sort()
        self.attention = attention
        self.prefill_attention = [
            row for row in attention
            if float(row["n_decode"]) == 0 and float(row["kv_decode"]) == 0
        ]
        self.decode_attention = [
            row for row in attention
            if float(row["prefill_chunk"]) == 0
            and float(row["kv_prefill"]) == 0
            and float(row["n_decode"]) == 1
        ]
        if not self.prefill_attention:
            self.prefill_attention = attention
        if not self.decode_attention:
            self.decode_attention = attention
        self.moe_by_k = defaultdict(list)
        for row in moe:
            self.moe_by_k[int(row["activated_experts"])].append(
                (float(row["tokens"]), float(row["time_us"])))
        for rows in self.moe_by_k.values():
            rows.sort()
        self.layers = int(model["num_hidden_layers"])
        self.top_k = int(model.get("num_experts_per_tok", 1))
        self.prefill_override = override_period_ns
        self._prefill_cache = {}
        self._decode_cache = {}

    def _dense_sum(self, tokens):
        return sum(_interp_points(self.dense[layer], max(1, tokens))
                   for layer in self.DENSE_LAYERS) * self.layers

    def prefill_ns(self, tokens):
        tokens = max(1, int(tokens))
        if tokens in self._prefill_cache:
            return self._prefill_cache[tokens]
        attention = _nearest_attention(self.prefill_attention, tokens, tokens, 0, 0)
        moe = _interp_points(self.moe_by_k.get(self.top_k, []), tokens)
        per_layer_us = self._dense_sum(tokens) / max(self.layers, 1) + attention + moe
        value = max(1, int((per_layer_us * self.layers) * 1000))
        self._prefill_cache[tokens] = value
        return value

    def prefill_layer_ns(self, tokens):
        """Return the profile-backed prefill anchor for one transformer layer."""
        tokens = max(1, int(tokens))
        attention = _nearest_attention(self.prefill_attention, tokens, tokens, 0, 0)
        moe = _interp_points(self.moe_by_k.get(self.top_k, []), tokens)
        per_layer_us = self._dense_sum(tokens) / max(self.layers, 1) + attention + moe
        return max(1, int(per_layer_us * 1000))

    def decode_period_ns(self, context_tokens=1024, active_tokens=1):
        if self.prefill_override is not None:
            return int(self.prefill_override)
        key = (int(context_tokens), int(active_tokens))
        if key in self._decode_cache:
            return self._decode_cache[key]
        attention = _nearest_attention(
            self.decode_attention, 0, 0, max(1, active_tokens), context_tokens)
        moe = _interp_points(self.moe_by_k.get(self.top_k, []), max(1, active_tokens))
        per_layer_us = self._dense_sum(max(1, active_tokens)) / max(self.layers, 1)
        value = max(1, int((per_layer_us + attention + moe) * self.layers * 1000))
        self._decode_cache[key] = value
        return value


def _split_bytes(total, limit):
    while total > limit:
        yield limit
        total -= limit
    if total:
        yield total


def build(args):
    manifest = _load_json(MANIFESTS[args.scale])
    ledger_path = ROOT / manifest["rank_metadata"]
    topology_path = ROOT / manifest["ns3_topology"]
    cache_endpoint_by_leaf = {}
    if args.remote_cache_placement == "dedicated_cache_nodes":
        if args.kv_subtype != "REMOTE_KV_FETCH":
            raise ValueError("dedicated_cache_nodes requires REMOTE_KV_FETCH")
        if args.remote_cache_topology is None:
            raise ValueError(
                "dedicated_cache_nodes requires --remote-cache-topology")
        topology_path = args.remote_cache_topology.resolve()
        topology_metadata = topology_path.with_suffix(".json")
        if not topology_metadata.is_file():
            raise ValueError(f"missing remote-cache topology metadata: {topology_metadata}")
        metadata = _load_json(topology_metadata)
        for leaf, endpoints in metadata.get("cache_endpoints_by_leaf", {}).items():
            if len(endpoints) != 1:
                raise ValueError("the replay currently requires one cache endpoint per leaf")
            cache_endpoint_by_leaf[int(leaf)] = int(endpoints[0])
        if not cache_endpoint_by_leaf:
            raise ValueError("remote-cache topology has no cache endpoints")
    ledger = _read_ledger(ledger_path)
    rank_rows = {int(row["astra_rank"]): row for row in ledger}
    by_instance, prefill_instances, decode_instances, pools = _group_ranks(ledger)
    if not prefill_instances or not decode_instances or not pools:
        raise ValueError("large-scale ledger has no complete P/D or EP mapping")
    placement_map = _load_placement_map(
        args.placement_map, prefill_instances, decode_instances)
    if placement_map is None:
        placement_name = "DEFAULT_RR"
    else:
        placement_name = args.placement_name or args.placement_map.stem
    requests, source_first_ns = _read_requests(
        args.trace.resolve(), args.request_offset, args.num_reqs,
        1.0 / args.load_scale)
    model = _load_json(args.model.resolve())
    clock = ProfileClock(args.hardware, args.model_name, model, args.decode_period_ns)
    graph = _topology_graph(topology_path)

    layers = int(model["num_hidden_layers"])
    kv_heads = int(model.get("num_key_value_heads", model["num_attention_heads"]))
    head_dim = int(model.get("head_dim", model["hidden_size"] // model["num_attention_heads"]))
    hidden = int(model["hidden_size"])
    fp_bytes = 2 if str(model.get("torch_dtype", "bfloat16")) in {"bfloat16", "float16"} else 4
    ep_degree = int(manifest["decode_ep_degree"])
    top_k = int(model.get("num_experts_per_tok", 1))
    kv_per_token_per_tp_rank = layers * 2 * kv_heads * head_dim * fp_bytes // 2
    kv_per_token_per_layer_per_tp_rank = 2 * kv_heads * head_dim * fp_bytes // 2
    bytes_per_pair_all_layers = layers * hidden * fp_bytes
    ep_bin_ns = int(args.ep_bin_us * 1000)
    if ep_bin_ns <= 0:
        raise ValueError("--ep-bin-us must be positive")
    link_rate_bps = 200_000_000_000
    link_delay_ns = 5_000
    router = GateRouter(0, 0, int(model.get("num_experts", model.get("num_local_experts", 128))),
                        num_experts_per_tok=top_k, routing_policy="BALANCED", block_copy=False)

    events = []
    request_map = []
    tag = 1000
    collective_id = 1
    cache_blocks = {}
    cache_blocks_by_instance = (
        {instance: OrderedDict() for instance in prefill_instances}
        if args.remote_cache_capacity_blocks is not None else None
    )
    # Keep aggregate token counts per decode time bin rather than one tuple per
    # generated token. This bounds Python memory for long production traces.
    pool_request_steps = defaultdict(dict)
    for request in requests:
        request_id = request["replay_request_id"]
        pidx = request_id % len(prefill_instances)
        didx = pidx % len(decode_instances)
        prefill_instance = prefill_instances[pidx]
        decode_instance = (
            placement_map[prefill_instance]
            if placement_map is not None else decode_instances[didx])
        source_ranks = by_instance[prefill_instance]
        destination_ranks = by_instance[decode_instance]
        if len(source_ranks) != 2 or len(destination_ranks) != 2:
            raise ValueError("this replay currently requires TP=2 P/D instances")
        matched_blocks = []
        if args.kv_subtype == "REMOTE_KV_FETCH":
            if not request["input_block_hashes"]:
                raise ValueError(
                    "REMOTE_KV_FETCH requires input_block_hashes; use a Mooncake trace")
            seen_hashes = set()
            for block_hash in request["input_block_hashes"]:
                if block_hash in seen_hashes:
                    continue
                seen_hashes.add(block_hash)
                if cache_blocks_by_instance is None:
                    cached = cache_blocks.get(block_hash)
                else:
                    cached = None
                    for owner_instance in prefill_instances:
                        candidate = cache_blocks_by_instance[owner_instance].get(block_hash)
                        if candidate is not None:
                            cached = dict(candidate)
                            cached["source_instance"] = owner_instance
                            cache_blocks_by_instance[owner_instance].move_to_end(block_hash)
                            break
                if cached is not None:
                    matched_blocks.append((block_hash, cached))
        block_size = request["hash_block_size"]
        matched_tokens = min(
            request["input_toks"], len(matched_blocks) * block_size)
        local_miss_tokens = (
            request["input_toks"] - matched_tokens
            if args.kv_subtype == "REMOTE_KV_FETCH"
            else request["input_toks"]
        )
        prefill_done = request["arrival_time_ns"] + clock.prefill_ns(local_miss_tokens)
        p2d_bytes = local_miss_tokens * kv_per_token_per_tp_rank
        p2d_end_anchor = prefill_done
        for src, dst in zip(source_ranks, destination_ranks):
            hops = _path_hops(graph, src, dst)
            if (args.traffic_class != "EP_ONLY" and
                    request.get("emit_p2d", True) and p2d_bytes):
                if args.pd_kv_transfer_mode == "POST_PREFILL":
                    layer_events = [(0, prefill_done, p2d_bytes)]
                else:
                    layer_ns = clock.prefill_layer_ns(local_miss_tokens)
                    layer_events = []
                    for layer_id in range(layers):
                        layer_ready = min(
                            prefill_done,
                            request["arrival_time_ns"] + (layer_id + 1) * layer_ns)
                        layer_events.append((
                            layer_id,
                            layer_ready,
                            local_miss_tokens * kv_per_token_per_layer_per_tp_rank,
                        ))
                for layer_id, start_ns, event_bytes in layer_events:
                    p2d_end_anchor = max(
                        p2d_end_anchor,
                        start_ns + hops * link_delay_ns + int(
                            event_bytes * 8 * 1e9 / link_rate_bps),
                    )
                    for chunk in _split_bytes(event_bytes, args.max_flow_bytes):
                        events.append((start_ns, src, dst, chunk, EVENT_CODES["P2D_KV"],
                                       request_id, 0, layer_id, tag,
                                       str(request_id), "prefill"))
                        tag += 1
        remote_kv_bytes = 0
        remote_end_anchor = request["arrival_time_ns"]
        if matched_blocks:
            by_source = defaultdict(lambda: {"bytes": 0, "ready_ns": 0})
            for block_index, (_, cached) in enumerate(matched_blocks):
                block_tokens = min(
                    block_size,
                    max(0, request["input_toks"] - block_index * block_size))
                block_bytes = block_tokens * kv_per_token_per_tp_rank
                if args.remote_provider_policy == "BALANCED_REPLICA_ORACLE":
                    # Offline characterization only: assume the matched block
                    # already has a legal replica on every prefill worker and
                    # select a deterministic provider per requester/block.
                    # This changes only source placement; it does not add the
                    # replication traffic and must not be treated as a
                    # deployable placement algorithm.
                    source_instance = prefill_instances[
                        (request_id + block_index) % len(prefill_instances)]
                else:
                    source_instance = cached["source_instance"]
                entry = by_source[source_instance]
                entry["bytes"] += block_bytes
                entry["ready_ns"] = max(entry["ready_ns"], cached["ready_ns"])
                entry["source_leaf"] = int(
                    rank_rows[by_instance[source_instance][0]]["leaf_id"].replace("Leaf", ""))
                # Keep the request/decode anchor matched across provider
                # policies.  The oracle changes only the already-existing
                # replica source; its serving timeline is anchored to the
                # first-producer path so EP issue times and coalesced bytes
                # remain identical in the counterfactual.
                anchor_ranks = by_instance[cached["source_instance"]]
                anchor_hops = max(
                    _path_hops(graph, anchor, destination)
                    for anchor, destination in zip(anchor_ranks, destination_ranks))
                entry["anchor_hops"] = max(
                    int(entry.get("anchor_hops", 0)), int(anchor_hops))
                provider_ranks = by_instance[source_instance]
                remote_kv_bytes += block_bytes * len(provider_ranks)
            if args.remote_provider_policy == "BALANCED_REPLICA_ORACLE":
                # Freeze the serving anchor to the native first-producer
                # aggregation.  Otherwise redistributing blocks across
                # providers changes the anchor merely because the selected
                # provider groups have different aggregate byte counts.
                native_source = defaultdict(lambda: {"bytes": 0, "ready_ns": 0})
                for block_index, (_, cached) in enumerate(matched_blocks):
                    block_tokens = min(
                        block_size,
                        max(0, request["input_toks"] - block_index * block_size))
                    native_entry = native_source[cached["source_instance"]]
                    native_entry["bytes"] += block_tokens * kv_per_token_per_tp_rank
                    native_entry["ready_ns"] = max(
                        native_entry["ready_ns"], cached["ready_ns"])
                for native_instance, native_entry in native_source.items():
                    native_ranks = by_instance[native_instance]
                    native_hops = max(
                        _path_hops(graph, source, destination)
                        for source, destination in zip(native_ranks, destination_ranks))
                    remote_end_anchor = max(
                        remote_end_anchor,
                        max(request["arrival_time_ns"], native_entry["ready_ns"])
                        + native_hops * link_delay_ns
                        + int(native_entry["bytes"] * 8 * 1e9 / link_rate_bps))
            for source_instance, entry in sorted(by_source.items()):
                remote_start = max(request["arrival_time_ns"], entry["ready_ns"])
                if args.remote_cache_placement == "dedicated_cache_nodes":
                    source_ranks_for_events = [
                        cache_endpoint_by_leaf[entry["source_leaf"]]]
                    destination_pairs = [
                        (source_ranks_for_events[0], destination_rank)
                        for destination_rank in destination_ranks]
                else:
                    provider_ranks = by_instance[source_instance]
                    destination_pairs = [
                        (source_rank, destination_ranks[index % len(destination_ranks)])
                        for index, source_rank in enumerate(provider_ranks)]
                for source_rank, destination_rank in destination_pairs:
                    hops = _path_hops(graph, source_rank, destination_rank)
                    anchor_hops = int(entry.get("anchor_hops", hops))
                    remote_end_anchor = max(
                        remote_end_anchor,
                        remote_start + anchor_hops * link_delay_ns + int(
                            entry["bytes"] * 8 * 1e9 / link_rate_bps))
                    if args.traffic_class != "EP_ONLY" and entry["bytes"]:
                        for chunk in _split_bytes(entry["bytes"], args.max_flow_bytes):
                            events.append((remote_start, source_rank, destination_rank,
                                           chunk, EVENT_CODES["P2D_KV"], request_id, 0,
                                           0, tag, str(request_id), "remote_kv"))
                            tag += 1
        # Publish blocks only after the current request's local prefill is
        # ready.  This is a trace-local cache ledger; no session is inferred
        # from hash similarity, and no block is available before its producer
        # has completed local prefill.
        if args.kv_subtype == "REMOTE_KV_FETCH":
            block_metadata = {
                "source_instance": prefill_instance,
                "source_leaf": int(rank_rows[by_instance[prefill_instance][0]]["leaf_id"].replace("Leaf", "")),
                "ready_ns": prefill_done,
                "producer_request_id": request_id,
            }
            if cache_blocks_by_instance is None:
                for block_hash in request["input_block_hashes"]:
                    cache_blocks.setdefault(block_hash, block_metadata.copy())
            else:
                matched_hashes = {block_hash for block_hash, _ in matched_blocks}
                local_cache = cache_blocks_by_instance[prefill_instance]
                for block_hash in request["input_block_hashes"]:
                    if block_hash in matched_hashes:
                        continue
                    local_cache[block_hash] = block_metadata.copy()
                    local_cache.move_to_end(block_hash)
                    while len(local_cache) > args.remote_cache_capacity_blocks:
                        local_cache.popitem(last=False)
        decode_period = clock.decode_period_ns(max(request["input_toks"], 1), 1)
        decode_start = max(p2d_end_anchor, remote_end_anchor)
        request_map.append({
            **request,
            "prefill_instance": prefill_instance,
            "decode_instance": decode_instance,
            "decode_pool": next(key for key, ranks in pools.items()
                                 if set(destination_ranks).issubset(set(ranks))),
            "prefill_done_anchor_ns": prefill_done,
            "decode_start_anchor_ns": decode_start,
            "decode_period_ns": decode_period,
            "p2d_bytes_total": p2d_bytes * len(source_ranks),
            "local_miss_tokens": local_miss_tokens,
            "remote_kv_blocks": len(matched_blocks),
            "remote_kv_bytes": remote_kv_bytes,
            "kv_movement_bytes_total": (
                p2d_bytes * len(source_ranks) + remote_kv_bytes),
        })
        pool = request_map[-1]["decode_pool"]
        output_tokens = max(0, int(request["output_toks"]))
        if (output_tokens and args.traffic_class != "KV_ONLY" and
                request.get("emit_ep", True)):
            first_bin = decode_start // ep_bin_ns
            last_time = decode_start + (output_tokens - 1) * decode_period
            last_bin = last_time // ep_bin_ns
            for bin_id in range(first_bin, last_bin + 1):
                bin_start = bin_id * ep_bin_ns
                bin_end = bin_start + ep_bin_ns
                first_step = max(
                    0,
                    (bin_start - decode_start + decode_period - 1) // decode_period,
                )
                last_step = min(
                    output_tokens - 1,
                    (bin_end - 1 - decode_start) // decode_period,
                )
                if first_step > last_step:
                    continue
                entry = pool_request_steps[pool].setdefault(
                    bin_id, {"token_count": 0, "start_ns": None, "request_ids": set()})
                entry["token_count"] += last_step - first_step + 1
                candidate_start = decode_start + first_step * decode_period
                if entry["start_ns"] is None or candidate_start < entry["start_ns"]:
                    entry["start_ns"] = candidate_start
                if (args.max_active_request_ids > 0 and
                        len(entry["request_ids"]) < args.max_active_request_ids):
                    entry["request_ids"].add(str(request_id))

    if args.traffic_class != "KV_ONLY":
        for pool, bins in pool_request_steps.items():
            ranks = pools[pool]
            for bin_id, request_steps in sorted(bins.items()):
                request_ids = sorted(request_steps["request_ids"], key=int)
                token_count = int(request_steps["token_count"])
                source_tokens = [token_count // ep_degree + (1 if r < token_count % ep_degree else 0)
                                 for r in range(ep_degree)]
                pair_matrix = _balanced_pair_matrix(source_tokens, ep_degree, top_k)
                if args.ep_realization == "UNIFORM_A2A_SAME_BYTES":
                    pair_matrix = _uniform_same_bytes_pair_matrix(
                        source_tokens, pair_matrix, ep_degree)
                # Keep the native CSV telemetry one-row-per-flow.  The ns-3
                # replay reader is intentionally lightweight and does not
                # parse quoted CSV fields; semicolons preserve the complete
                # active-request list without shifting src/dst columns.
                active = ";".join(str(value) for value in sorted(set(request_ids)))
                # A coalesced bin is a fluid approximation of the decode
                # batch: issue it at the earliest constituent step, while
                # retaining only bytes generated by steps in this bin.  This
                # lets already-active Decode requests overlap a later P2D
                # transfer; using the latest step would serialize away that
                # cross-request data-plane condition.  The manifest records
                # the bounded bin-width approximation explicitly.
                start_ns = int(request_steps["start_ns"])
                for src_index, row in enumerate(pair_matrix):
                    for dst_index, pair_count in enumerate(row):
                        if src_index == dst_index or pair_count <= 0:
                            continue
                        bytes_total = pair_count * bytes_per_pair_all_layers
                        src_rank, dst_rank = ranks[src_index], ranks[dst_index]
                        for event_type, event_src, event_dst in (
                                ("EP_DISPATCH", src_rank, dst_rank),
                                ("EP_COMBINE", dst_rank, src_rank)):
                            for chunk in _split_bytes(bytes_total, args.max_flow_bytes):
                                events.append((start_ns, event_src, event_dst, chunk,
                                               EVENT_CODES[event_type], -1, collective_id,
                                               0, tag, active, "decode"))
                                tag += 1
                collective_id += 1

    events.sort(key=lambda value: (value[0], value[4], value[1], value[2], value[8]))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    event_path = args.output_dir / "events.csv"
    with event_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(EVENT_HEADER)
        writer.writerows(events)
    request_path = args.output_dir / "requests.csv"
    with request_path.open("w", newline="", encoding="utf-8") as stream:
        fields = list(request_map[0]) if request_map else []
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(request_map)
    summary = {
        "schema_version": 1,
        "trace": str(args.trace.resolve()),
        "source_first_timestamp_ns": source_first_ns,
        "scale": args.scale,
        "ns3_topology": str(topology_path),
        "model": args.model_name,
        "hardware": args.hardware,
        "request_count": len(requests),
        "load_scale": args.load_scale,
        "arrival_interval_scale": 1.0 / args.load_scale,
        "placement_name": placement_name,
        "placement_map": placement_map,
        "traffic_class": args.traffic_class,
        "kv_subtype": args.kv_subtype,
        "remote_cache_placement": (
            args.remote_cache_placement if args.kv_subtype == "REMOTE_KV_FETCH" else None
        ),
        "remote_provider_policy": (
            args.remote_provider_policy
            if args.kv_subtype == "REMOTE_KV_FETCH" else None
        ),
        "remote_cache_capacity_blocks": args.remote_cache_capacity_blocks,
        "remote_provider_anchor_policy": (
            "FIRST_PRODUCER_PATH_FOR_MATCHED_ORACLE"
            if (args.kv_subtype == "REMOTE_KV_FETCH" and
                args.remote_provider_policy == "BALANCED_REPLICA_ORACLE")
            else "NATIVE_PROVIDER_PATH"
        ),
        "remote_cache_topology": (
            str(topology_path) if args.remote_cache_placement == "dedicated_cache_nodes" else None
        ),
        "hash_block_size": (
            requests[0]["hash_block_size"] if requests else None
        ),
        "hash_semantics": (
            requests[0]["hash_semantics"] if requests else None
        ),
        "event_count": len(events),
        "p2d_event_count": sum(1 for event in events if event[4] == 1),
        "remote_kv_event_count": sum(
            1 for event in events if event[4] == 1 and event[10] == "remote_kv"),
        "ep_event_count": sum(1 for event in events if event[4] in (2, 3)),
        "p2d_bytes": sum(
            event[3] for event in events if event[4] == 1 and event[10] == "prefill"),
        "remote_kv_bytes": sum(
            event[3] for event in events if event[4] == 1 and event[10] == "remote_kv"),
        "ep_bytes": sum(event[3] for event in events if event[4] in (2, 3)),
        "remote_kv_blocks": sum(
            int(row.get("remote_kv_blocks", 0)) for row in request_map),
        "ep_bin_us": args.ep_bin_us,
        "pd_kv_transfer_mode": args.pd_kv_transfer_mode,
        "ep_realization": args.ep_realization,
        "ep_realization_semantics": (
            "GateRouter model-derived A2A_P2P route matrix"
            if args.ep_realization == "GATE_ROUTER_A2A_P2P" else
            "uniform peer route matrix with exact GateRouter remote bytes per source; offline P5 counterfactual"),
        "p2d_layer_count": layers if args.pd_kv_transfer_mode == "LAYERWISE" else 1,
        "p2d_event_granularity": (
            "one independent model-derived P2D KV event per transformer layer"
            if args.pd_kv_transfer_mode == "LAYERWISE"
            else "one model-derived P2D KV event after prefill"),
        "max_active_request_ids_per_ep_bin": args.max_active_request_ids,
        "ep_layer_coalescing": layers,
        "kv_bytes_per_input_token_all_tp_ranks": layers * 2 * kv_heads * head_dim * fp_bytes,
        "kv_bytes_per_input_token_per_tp_rank": kv_per_token_per_tp_rank,
        "bytes_per_routed_expert_token_all_layers": bytes_per_pair_all_layers,
        "ep_degree": ep_degree,
        "top_k": top_k,
        "synthetic_byte_override": False,
        "timing_model": {
            "kind": "profiler_backed_independent_request_anchor",
            "prefill_compute": "profile interpolation at request input length",
            "p2d_completion": "uncongested 200-Gbps path estimate used only to anchor decode",
            "decode_period": "profile interpolation at one active decode token",
            "prefill_queueing": "not modeled; each request keeps trace-relative open-loop arrival",
            "ep_time_coalescing": "all 48 MoE layers in each time bin are one network phase",
            "ep_bin_start_policy": "earliest constituent decode step; fluid bin approximation",
        },
        "files": {"events": str(event_path), "requests": str(request_path)},
    }
    (args.output_dir / "replay_manifest.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--scale", choices=tuple(MANIFESTS), required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--num-reqs", required=True, type=int)
    parser.add_argument("--request-offset", type=int, default=0)
    parser.add_argument(
        "--load-scale", type=float, default=1.0,
        help="multiply offered arrival rate; 0.5=half load, 2.0=double load")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--model-name", default="Qwen/Qwen3-30B-A3B-Instruct-2507")
    parser.add_argument("--hardware", default="RTXPRO6000")
    parser.add_argument("--ep-bin-us", type=float, default=5000.0)
    parser.add_argument(
        "--pd-kv-transfer-mode", choices=("LAYERWISE", "POST_PREFILL"),
        default="POST_PREFILL",
        help="P2D granularity: one post-prefill cache chunk or one KV event "
             "after each transformer layer")
    parser.add_argument(
        "--max-active-request-ids", type=int, default=64,
        help="cap active request ids retained in each coalesced EP event; 0 omits them")
    parser.add_argument("--decode-period-ns", type=int, default=None)
    parser.add_argument("--max-flow-bytes", type=int, default=1_000_000_000)
    parser.add_argument(
        "--ep-realization",
        choices=("GATE_ROUTER_A2A_P2P", "UNIFORM_A2A_SAME_BYTES"),
        default="GATE_ROUTER_A2A_P2P",
        help="EP route geometry; uniform mode is a same-byte P5 counterfactual")
    parser.add_argument(
        "--placement-map", type=Path, default=None,
        help="optional bijection mapping prefill instance IDs to decode IDs")
    parser.add_argument(
        "--placement-name", default=None,
        help="label recorded in replay_manifest.json for a placement map")
    parser.add_argument("--traffic-class", choices=("FULL", "KV_ONLY", "EP_ONLY"), default="FULL")
    parser.add_argument(
        "--kv-subtype", choices=("P2D", "REMOTE_KV_FETCH"), default="P2D",
        help="KV movement source; REMOTE_KV_FETCH requires Mooncake block hashes")
    parser.add_argument(
        "--remote-cache-placement",
        choices=("prefill_workers_trace_local_cache", "dedicated_cache_nodes"),
        default="prefill_workers_trace_local_cache",
        help="REMOTE_KV_FETCH placement; dedicated_cache_nodes requires a topology")
    parser.add_argument(
        "--remote-provider-policy",
        choices=("FIRST_PRODUCER", "BALANCED_REPLICA_ORACLE"),
        default="FIRST_PRODUCER",
        help="remote provider selection; BALANCED_REPLICA_ORACLE is an offline "
             "same-byte upper bound and omits replication traffic")
    parser.add_argument(
        "--remote-cache-capacity-blocks", type=int, default=None,
        help="optional finite per-prefill-instance LRU capacity in model-derived hash blocks; "
             "default preserves the unlimited trace-local ledger"
    )
    parser.add_argument(
        "--remote-cache-topology", type=Path, default=None,
        help="Clos topology with one dedicated cache endpoint per leaf")
    args = parser.parse_args()
    if args.num_reqs <= 0 or args.num_reqs > 25_000:
        parser.error("--num-reqs must be in [1, 25,000]")
    if args.max_flow_bytes <= 0:
        parser.error("--max-flow-bytes must be positive")
    if args.load_scale <= 0:
        parser.error("--load-scale must be positive")
    if args.max_active_request_ids < 0:
        parser.error("--max-active-request-ids must be non-negative")
    if args.remote_cache_capacity_blocks is not None and args.remote_cache_capacity_blocks <= 0:
        parser.error("--remote-cache-capacity-blocks must be positive")
    if (args.remote_cache_capacity_blocks is not None and
            args.remote_provider_policy == "BALANCED_REPLICA_ORACLE"):
        parser.error("finite cache mode is only defined for FIRST_PRODUCER; the replica oracle is already an explicit upper bound")
    build(args)


if __name__ == "__main__":
    main()
