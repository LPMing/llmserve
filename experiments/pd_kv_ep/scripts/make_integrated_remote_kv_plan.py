#!/usr/bin/env python3
"""Build a small, model-derived integrated remote-KV characterization plan.

This is deliberately an offline experiment-plan generator, not a provider
selection algorithm.  It preserves the selected Mooncake request rows and
adds only the remote-hit token accounting consumed by LLMServingSim plus
same-fabric remote-fetch/replica-warm-up flows consumed by FlowSim.
"""
import argparse
import json
from collections import OrderedDict
from pathlib import Path


MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
LAYERS = 48
KV_HEADS = 4
HEAD_DIM = 128
KV_DTYPE_BYTES = 2
PREFILL_RANKS = (0, 1)
DECODE_RANKS = {0: (2, 3), 1: (4, 5)}


def cache_bytes(tokens):
    return int(tokens) * LAYERS * 2 * KV_HEADS * HEAD_DIM * KV_DTYPE_BYTES


def load_rows(path, limit, start_index=0):
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index < start_index:
                continue
            if len(rows) >= limit:
                break
            row = json.loads(line)
            rows.append(row)
    if not rows:
        raise ValueError("selected workload is empty")
    return rows


def build(rows, policy, architecture_mode="REMOTE_PREFIX_PD_BASELINE"):
    policy = policy.upper()
    architecture_mode = architecture_mode.upper()
    if policy not in ("FIRST_PRODUCER", "LEAST_LOADED_EXISTING_HOLDER",
                      "BALANCED_REPLICA", "BALANCED_REPLICA_ORACLE"):
        raise ValueError(policy)
    if policy == "BALANCED_REPLICA_ORACLE":
        policy = "BALANCED_REPLICA"
    if architecture_mode not in (
            "REMOTE_PREFIX_PD_BASELINE", "SPLIT_SOURCE_KV_ASSEMBLY",
            "DIRECT_DECODE_CHARACTERIZE"):
        raise ValueError(architecture_mode)
    first_producer = OrderedDict()
    holders = OrderedDict()
    holder_load = {}
    request_plans = {}
    enriched = []
    warmup = []
    warmup_seen = set()
    total_remote_bytes = 0
    total_remote_tokens = 0
    total_remote_network_bytes = 0
    total_remote_network_tokens = 0
    total_replication_bytes = 0
    for request_id, source in enumerate(rows):
        input_tokens = int(source["input_toks"])
        block_size = int(source.get("hash_block_size", 512))
        hashes = list(source.get("input_block_hashes", []))
        provider_owner = PREFILL_RANKS[request_id % len(PREFILL_RANKS)]
        if architecture_mode == "REMOTE_PREFIX_PD_BASELINE":
            # Exact prefix hits are materialized in the target Prefill KV
            # layout; native P2D later sends complete prefix+suffix KV.
            destination_ranks = (provider_owner,)
        elif architecture_mode == "SPLIT_SOURCE_KV_ASSEMBLY":
            # V1 keeps the existing R->P dependency for suffix compute and
            # adds a second R->D leg. The worker keeps the two roles separate.
            destination_ranks = (provider_owner,)
        else:
            destination_ranks = DECODE_RANKS[request_id % len(PREFILL_RANKS)]
        fetches = []
        remote_tokens = 0
        remote_bytes = 0
        remote_network_bytes = 0
        remote_network_tokens = 0
        for block_index, block_hash in enumerate(hashes):
            block_tokens = max(0, min(block_size,
                                      input_tokens - block_index * block_size))
            if block_tokens <= 0:
                continue
            block_key = str(block_hash)
            producer = first_producer.setdefault(block_key, provider_owner)
            holders.setdefault(block_key, [producer])
            balanced_owner = PREFILL_RANKS[
                (request_id + block_index) % len(PREFILL_RANKS)]
            warmup_key = (block_key, balanced_owner)
            if warmup_key in warmup_seen:
                continue
            warmup_seen.add(warmup_key)
            if policy == "BALANCED_REPLICA" and balanced_owner != producer:
                bytes_to_copy = cache_bytes(block_tokens)
                warmup.append({
                    "flow_id": "remote_kv_warmup:%s:%d" %
                               (block_key, balanced_owner),
                    "src": int(producer),
                    "dst": int(balanced_owner),
                    "bytes": bytes_to_copy,
                    "block_index": block_index,
                    "block_hash": block_key,
                })
                total_replication_bytes += bytes_to_copy
                if balanced_owner not in holders[block_key]:
                    holders[block_key].append(balanced_owner)
        # Use an explicit occurrence ledger instead of inferring from the
        # warm-up list: first producer request itself is never a remote hit.
        occurrence = getattr(build, "_occurrence", None)
        if occurrence is None:
            occurrence = {}
            build._occurrence = occurrence
        fetches = []
        remote_tokens = 0
        remote_bytes = 0
        for block_index, block_hash in enumerate(hashes):
            block_tokens = max(0, min(block_size,
                                      input_tokens - block_index * block_size))
            if block_tokens <= 0:
                continue
            block_key = str(block_hash)
            is_remote = block_key in occurrence
            occurrence[block_key] = occurrence.get(block_key, 0) + 1
            if not is_remote:
                continue
            if policy == "FIRST_PRODUCER":
                source_rank = first_producer[block_key]
            elif policy == "LEAST_LOADED_EXISTING_HOLDER":
                # This is an offline existing-holder policy, not a replica
                # creator. With only the first producer present it must
                # exactly equal FIRST_PRODUCER; when a legal pre-existing
                # holder set is supplied, use deterministic byte load.
                source_rank = min(
                    holders[block_key],
                    key=lambda rank: (holder_load.get(rank, 0), rank))
            else:
                source_rank = PREFILL_RANKS[
                    (request_id + block_index) % len(PREFILL_RANKS)]
                if source_rank not in holders[block_key]:
                    raise ValueError(
                        "BALANCED_REPLICA selected a holder without warm-up")
            full_bytes = cache_bytes(block_tokens)
            holder_load[source_rank] = holder_load.get(source_rank, 0) + full_bytes
            if architecture_mode == "REMOTE_PREFIX_PD_BASELINE":
                legs = (("REMOTE_KV_TO_PREFILL", (provider_owner,)),)
            elif architecture_mode == "SPLIT_SOURCE_KV_ASSEMBLY":
                legs = (
                    ("REMOTE_KV_TO_PREFILL", (provider_owner,)),
                    ("REMOTE_KV_TO_DECODE",
                     DECODE_RANKS[request_id % len(PREFILL_RANKS)]),
                )
            else:
                legs = (("REMOTE_KV_TO_DECODE", destination_ranks),)
            for role, destinations in legs:
                shard_bytes = full_bytes // len(destinations)
                shard_tokens = block_tokens // len(destinations)
                for dst in destinations:
                    if source_rank == dst:
                        # The target already has a legal local holder. This
                        # is a logical prefix hit but not a network fetch.
                        continue
                    fetches.append({
                        "src": int(source_rank),
                        "dst": int(dst),
                        "bytes": int(shard_bytes),
                        "block_index": int(block_index),
                        "block_hash": block_key,
                        "role": role,
                    })
                    remote_network_bytes += int(shard_bytes)
                    remote_network_tokens += shard_tokens
            remote_tokens += block_tokens
            remote_bytes += full_bytes
        plan = {
            "fetches": fetches,
            "remote_kv_tokens": remote_tokens,
            "remote_kv_bytes": remote_bytes,
            "remote_network_bytes": remote_network_bytes,
            "remote_network_tokens": remote_network_tokens,
            "remote_blocks": len({item["block_hash"] for item in fetches}),
            "remote_source_policy": policy,
            "destination_ranks": list(destination_ranks),
        }
        request_plans[str(request_id)] = plan
        out = dict(source)
        out["request_id"] = str(request_id)
        out["source_request_id"] = source.get("request_id", str(request_id))
        out["remote_kv_tokens"] = remote_tokens
        out["remote_kv_bytes"] = remote_bytes
        out["remote_kv_mode"] = architecture_mode
        out["remote_kv_subtype"] = "REMOTE_KV_FETCH"
        enriched.append(out)
        total_remote_bytes += remote_bytes
        total_remote_tokens += remote_tokens
        total_remote_network_bytes += remote_network_bytes
        total_remote_network_tokens += remote_network_tokens
    build._occurrence = None
    return enriched, {
        "schema_version": 2,
        "mode": policy,
        "architecture_mode": architecture_mode,
        "model": MODEL,
        "semantics": (
            "R_TO_P_SUFFIX_COMPUTE_THEN_FULL_P2D"
            if architecture_mode == "REMOTE_PREFIX_PD_BASELINE"
            else ("R_TO_P_AND_R_TO_D_PREFIX_THEN_SUFFIX_P2D"
                  if architecture_mode == "SPLIT_SOURCE_KV_ASSEMBLY"
                  else "DIRECT_REMOTE_TO_DECODE_CHARACTERIZATION")),
        "topology_rank_mapping": {
            "prefill_ranks": list(PREFILL_RANKS),
            "decode_ranks_by_prefill": {str(k): list(v)
                                         for k, v in DECODE_RANKS.items()},
        },
        "warmup": warmup if policy == "BALANCED_REPLICA" else [],
        "request_plans": request_plans,
        "stats": {
            "request_count": len(rows),
            "remote_kv_bytes": total_remote_bytes,
            "remote_kv_tokens": total_remote_tokens,
            "remote_kv_network_bytes": total_remote_network_bytes,
            "remote_kv_network_tokens": total_remote_network_tokens,
            "replication_bytes": (total_replication_bytes
                                   if policy == "BALANCED_REPLICA" else 0),
            "replication_flow_count": len(warmup) if policy == "BALANCED_REPLICA" else 0,
            "existing_holder_policy": policy == "LEAST_LOADED_EXISTING_HOLDER",
            "unique_blocks": len(first_producer),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--num-requests", type=int, default=8)
    parser.add_argument("--start-index", type=int, default=0,
                        help="zero-based row offset within the source trace")
    parser.add_argument("--output-tokens", type=int, default=0,
                        help="optional serving-only output cap; input/KV remains unchanged")
    parser.add_argument(
        "--architecture-mode",
        choices=["REMOTE_PREFIX_PD_BASELINE", "SPLIT_SOURCE_KV_ASSEMBLY",
                 "DIRECT_DECODE_CHARACTERIZE"],
        default="REMOTE_PREFIX_PD_BASELINE",
        help="remote-KV DAG to encode in the workload/plan")
    args = parser.parse_args()
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.input, args.num_requests, args.start_index)
    if args.output_tokens > 0:
        rows = [dict(row, output_toks=min(int(row["output_toks"]),
                                          args.output_tokens))
                for row in rows]
    for policy in ("FIRST_PRODUCER", "LEAST_LOADED_EXISTING_HOLDER",
                   "BALANCED_REPLICA_ORACLE"):
        enriched, plan = build(rows, policy, args.architecture_mode)
        workload = outdir / ("workload_%s.jsonl" % policy.lower())
        with workload.open("w", encoding="utf-8") as stream:
            for row in enriched:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        plan_path = outdir / ("plan_%s.json" % policy.lower())
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        print(json.dumps({"policy": policy, "workload": str(workload),
                          "plan": str(plan_path), "stats": plan["stats"]},
                         sort_keys=True))


if __name__ == "__main__":
    main()
