#!/usr/bin/env python3
"""Replay a small, explicit D prefix cache model against online baselines.

This is a decision screen, not a Serving simulation or a latency result.
Only completed, full 16-token prompt blocks are cacheable. Requests are
inserted sequentially after completion, matching the motivation fixture's
non-overlapping filler arrivals.
"""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
WORKLOAD = (HERE.parent / "experiments/filler_28/workload.jsonl")
POOL_BLOCKS = 3400
BLOCK_SIZE = 16
KV_BYTES_PER_TOKEN = 131072


def replay(accesses, policy, protected=()):
    resident = {}
    frequency = {}
    clock = 0
    used = 0
    hits = []
    for key, blocks, is_target in accesses:
        clock += 1
        frequency[key] = frequency.get(key, 0) + 1
        hit = key in resident
        if is_target:
            hits.append(hit)
            continue
        if hit:
            resident[key]["last"] = clock
            continue
        while used + blocks > POOL_BLOCKS:
            victims = [(name, entry) for name, entry in resident.items()
                       if name not in protected]
            if not victims:
                raise RuntimeError("Oracle protection exceeds the pool")
            if policy == "LRU":
                victim = min(victims, key=lambda pair: pair[1]["last"])[0]
            elif policy == "LFU":
                victim = min(victims, key=lambda pair: (
                    frequency[pair[0]], pair[1]["last"]))[0]
            elif policy == "COST_LFU":
                # Full-KV retransmission cost per retained cache block.
                victim = min(victims, key=lambda pair: (
                    frequency[pair[0]] * pair[1]["blocks"] * BLOCK_SIZE
                    * KV_BYTES_PER_TOKEN / pair[1]["blocks"],
                    pair[1]["last"]))[0]
            else:
                raise ValueError(policy)
            used -= resident.pop(victim)["blocks"]
        resident[key] = {"blocks": blocks, "last": clock}
        used += blocks
        if used > POOL_BLOCKS:
            raise AssertionError("KV pool overfilled")
    if len(hits) != 2:
        raise AssertionError("Expected two target requests")
    return {"target_hits": hits, "resident_blocks": used}


def main():
    rows = [json.loads(line) for line in WORKLOAD.read_text().splitlines()]
    if len(rows) != 32:
        raise AssertionError("The frozen 28-filler fixture changed")
    warm = [tuple(row["input_tok_ids"]) for row in rows[:2]]
    if len(warm[0]) != 1984 or len(warm[1]) != 1984:
        raise AssertionError("Unexpected warm prefix length")
    if warm[0] == warm[1]:
        raise AssertionError("Targets must use different prefixes")
    targets = [tuple(row["input_tok_ids"][:1984]) for row in rows[-2:]]
    if targets != warm:
        raise AssertionError("Target prefix identities changed")
    if any(len(row["input_tok_ids"]) != 2048 for row in rows[2:]):
        raise AssertionError("Unexpected filler or target length")
    filler_keys = [tuple(row["input_tok_ids"]) for row in rows[2:-2]]
    if len(set(filler_keys)) != 28 or any(key[:1984] in warm
                                             for key in filler_keys):
        raise AssertionError("Fillers must be distinct cold prompts")
    original = [("warm0", 124, False), ("warm1", 124, False)]
    original += [("filler%02d" % i, 128, False) for i in range(28)]
    original += [("warm0", 124, True), ("warm1", 124, True)]
    history = original[:2] + original[:2] + original[2:]
    scenarios = {"one_prior_access": original,
                 "two_prior_accesses_analytic_only": history}
    results = {}
    for scenario, accesses in scenarios.items():
        results[scenario] = {
            policy: replay(accesses, policy)
            for policy in ("LRU", "LFU", "COST_LFU")}
        results[scenario]["FUTURE_KNOWING_ORACLE"] = replay(
            accesses, "LRU", protected=("warm0", "warm1"))
    output = {
        "status": "ANALYTICAL_ONLY",
        "claim": "cache admission decision screen; no Serving latency or policy gain",
        "capacity_blocks": POOL_BLOCKS,
        "block_size_tokens": BLOCK_SIZE,
        "kv_bytes_per_token": KV_BYTES_PER_TOKEN,
        "workload_sha256": hashlib.sha256(WORKLOAD.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "results": results,
    }
    path = HERE / "online_baseline_screen.json"
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
