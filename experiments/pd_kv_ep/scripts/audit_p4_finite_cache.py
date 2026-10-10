#!/usr/bin/env python3
"""Audit trace-driven remote-KV ownership under finite per-instance LRU caches.

This is an offline ownership audit, not a network replay and not a cache
implementation.  It deliberately models the conservative semantics used by
the current P4 replay: a remote hit is fetched by the requester but is not
silently replicated to that requester's prefill cache.  Only blocks produced
by a local miss are inserted into the assigned prefill instance.  This lets us
separate trace-supported provider concentration from the old unlimited,
first-writer ledger.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path


KV_BYTES_PER_TOKEN_PER_TP_RANK = 48 * 2 * 4 * 128 * 2 // 2


def load_rows(path: Path, offset: int, limit: int):
    rows = []
    with path.open(encoding="utf-8") as stream:
        for source_index, line in enumerate(stream):
            if source_index < offset:
                continue
            if len(rows) >= limit:
                break
            row = json.loads(line)
            hashes = row.get("input_block_hashes")
            if hashes is None:
                hashes = row.get("prefix_block_hashes", [])
            if not isinstance(hashes, list):
                raise ValueError(f"block hashes are not a list at source row {source_index}")
            deduped = list(dict.fromkeys(str(value) for value in hashes))
            rows.append({
                "replay_request_id": len(rows),
                "source_index": source_index,
                "request_id": row.get("request_id", str(source_index)),
                "arrival_time_ns": int(row.get("arrival_time_ns", 0)),
                "input_toks": max(0, int(row.get("input_toks", 0))),
                "hash_block_size": max(1, int(row.get("hash_block_size", 512))),
                "blocks": deduped,
            })
    if not rows:
        raise ValueError("selected trace window is empty")
    return rows


def prefill_instances(rank_metadata: Path):
    values = set()
    with rank_metadata.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("role") == "prefill":
                values.add(int(row["instance_id"]))
    return sorted(values)


def gini(values):
    values = [float(value) for value in values if value >= 0]
    if not values or sum(values) == 0:
        return 0.0
    ordered = sorted(values)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2.0 * weighted) / (len(ordered) * sum(ordered)) - (len(ordered) + 1.0) / len(ordered)


def quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def audit(rows, provider_ids, capacity_blocks):
    caches = {instance: OrderedDict() for instance in provider_ids}
    provider_bytes = Counter()
    provider_blocks = Counter()
    request_records = []
    evictions = Counter()
    block_request_counts = Counter(block for row in rows for block in row["blocks"])
    block_sources = defaultdict(list)

    for row in rows:
        local_instance = provider_ids[row["replay_request_id"] % len(provider_ids)]
        remote = []
        local_miss = []
        seen_remote = set()
        for block_index, block in enumerate(row["blocks"]):
            owner = None
            for instance in provider_ids:
                if block in caches[instance]:
                    owner = instance
                    break
            if owner is None:
                local_miss.append(block)
            elif owner != local_instance and block not in seen_remote:
                block_tokens = min(
                    row["hash_block_size"],
                    max(0, row["input_toks"] - block_index * row["hash_block_size"]),
                )
                remote.append({
                    "block": block,
                    "owner": owner,
                    "tokens": block_tokens,
                    "bytes_per_rank": block_tokens * KV_BYTES_PER_TOKEN_PER_TP_RANK,
                })
                seen_remote.add(block)
                caches[owner].move_to_end(block)
                block_sources[block].append(owner)
            elif owner == local_instance:
                caches[owner].move_to_end(block)

        # A local miss becomes available only after local prefill.  Remote
        # fetches are intentionally not inserted into the local provider cache.
        for block in local_miss:
            caches[local_instance][block] = row["replay_request_id"]
            caches[local_instance].move_to_end(block)
            while len(caches[local_instance]) > capacity_blocks:
                evicted, _ = caches[local_instance].popitem(last=False)
                evictions[local_instance] += 1

        request_bytes = Counter()
        for item in remote:
            request_bytes[item["owner"]] += item["bytes_per_rank"] * 2
            provider_blocks[item["owner"]] += 1
        for instance, bytes_value in request_bytes.items():
            provider_bytes[instance] += bytes_value
        request_records.append({
            "replay_request_id": row["replay_request_id"],
            "source_index": row["source_index"],
            "request_id": row["request_id"],
            "local_prefill_instance": local_instance,
            "input_tokens": row["input_toks"],
            "input_blocks": len(row["blocks"]),
            "remote_blocks": len(remote),
            "remote_bytes": sum(item["bytes_per_rank"] * 2 for item in remote),
            "local_miss_blocks": len(local_miss),
            "provider_instances": ";".join(str(value) for value in sorted(request_bytes)),
            "provider_bytes": ";".join(
                f"{instance}:{value}" for instance, value in sorted(request_bytes.items())
            ),
        })

    remote_request_bytes = [record["remote_bytes"] for record in request_records]
    nonzero = [value for value in remote_request_bytes if value > 0]
    total_bytes = sum(remote_request_bytes)
    provider_values = [provider_bytes[instance] for instance in provider_ids]
    active_providers = sum(value > 0 for value in provider_values)
    hottest_block = block_request_counts.most_common(10)
    return {
        "capacity_blocks_per_prefill_instance": capacity_blocks,
        "capacity_bytes_per_tp_rank": capacity_blocks * KV_BYTES_PER_TOKEN_PER_TP_RANK * 512,
        "capacity_bytes_per_tp2_instance": capacity_blocks * KV_BYTES_PER_TOKEN_PER_TP_RANK * 512 * 2,
        "request_count": len(rows),
        "prefill_instance_count": len(provider_ids),
        "remote_request_count": sum(value > 0 for value in remote_request_bytes),
        "remote_block_count": sum(record["remote_blocks"] for record in request_records),
        "remote_bytes": total_bytes,
        "remote_bytes_mib": total_bytes / (1024 * 1024),
        "remote_request_bytes_mean": sum(remote_request_bytes) / len(remote_request_bytes),
        "remote_request_bytes_p50": quantile(remote_request_bytes, 0.50),
        "remote_request_bytes_p95": quantile(remote_request_bytes, 0.95),
        "remote_request_bytes_p99": quantile(remote_request_bytes, 0.99),
        "remote_nonzero_bytes_mean": (sum(nonzero) / len(nonzero)) if nonzero else 0.0,
        "active_provider_count": active_providers,
        "provider_max_share": max(provider_values, default=0) / total_bytes if total_bytes else 0.0,
        "provider_gini": gini(provider_values),
        "provider_bytes": {str(instance): provider_bytes[instance] for instance in provider_ids},
        "provider_blocks": {str(instance): provider_blocks[instance] for instance in provider_ids},
        "evictions": {str(instance): evictions[instance] for instance in provider_ids},
        "total_evictions": sum(evictions.values()),
        "hottest_blocks": [
            {"block": block, "request_count": count, "source_sequence": block_sources.get(block, [])}
            for block, count in hottest_block
        ],
        "requests": request_records,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--rank-metadata", type=Path, required=True)
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--capacity-blocks", type=int, nargs="+", default=[128, 512, 1024, 2048, 2366, 4096])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.offset < 0 or args.limit <= 0:
        parser.error("offset must be nonnegative and limit must be positive")
    rows = load_rows(args.trace, args.offset, args.limit)
    providers = prefill_instances(args.rank_metadata)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "trace": str(args.trace),
        "rank_metadata": str(args.rank_metadata),
        "offset": args.offset,
        "limit": args.limit,
        "selected_first_request": rows[0]["request_id"],
        "selected_last_request": rows[-1]["request_id"],
        "model_derived_kv_bytes_per_token_per_tp_rank": KV_BYTES_PER_TOKEN_PER_TP_RANK,
        "ownership_semantics": "local-miss-only insertion, remote fetch is not silently replicated",
        "capacity_audit": [audit(rows, providers, capacity) for capacity in args.capacity_blocks],
    }
    with (args.output_dir / "finite_cache_audit.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
    with (args.output_dir / "finite_cache_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = [
            "capacity_blocks_per_prefill_instance", "capacity_bytes_per_tp2_instance",
            "remote_request_count", "remote_block_count", "remote_bytes_mib",
            "remote_request_bytes_mean", "remote_request_bytes_p50",
            "remote_request_bytes_p95", "remote_request_bytes_p99",
            "active_provider_count", "provider_max_share", "provider_gini", "total_evictions",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in summary["capacity_audit"]:
            writer.writerow({field: item[field] for field in fields})
    with (args.output_dir / "finite_cache_request_samples.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["capacity"] + list(summary["capacity_audit"][0]["requests"][0])
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in summary["capacity_audit"]:
            for row in item["requests"]:
                writer.writerow({"capacity": item["capacity_blocks_per_prefill_instance"], **row})
    print(json.dumps({
        "output_dir": str(args.output_dir),
        "prefill_instance_count": len(providers),
        "request_count": len(rows),
        "capacity_audit": [
            {key: item[key] for key in (
                "capacity_blocks_per_prefill_instance", "remote_request_count",
                "remote_block_count", "remote_bytes_mib", "provider_max_share",
                "provider_gini", "total_evictions")
            }
            for item in summary["capacity_audit"]
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
