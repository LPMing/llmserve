#!/usr/bin/env python3
"""Generate matched P/D instance pairings for P1 characterization.

These maps do not change a request, its bytes, its routing matrix, or its
arrival time.  They only change the decode instance paired with each prefill
instance.  The leaf-aligned and leaf-crossed maps are offline bounds for the
placement question, not an online placement algorithm.
"""

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_ledger(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _instances(ledger, role):
    by_instance = defaultdict(list)
    for row in ledger:
        if row["role"] == role:
            by_instance[int(row["instance_id"])].append(row)
    return by_instance


def _leaf_by_instance(rows):
    leaves = {}
    for instance, values in rows.items():
        observed = {value["leaf_id"] for value in values}
        if len(observed) != 1:
            raise ValueError("instance %s spans multiple leaves: %s" %
                             (instance, sorted(observed)))
        leaves[instance] = next(iter(observed))
    return leaves


def _maps(prefill, decode, seed):
    pids = sorted(prefill)
    dids = sorted(decode)
    if len(pids) != len(dids):
        raise ValueError("P1 maps require equal prefill/decode instance counts")
    p_leaf = _leaf_by_instance(prefill)
    d_leaf = _leaf_by_instance(decode)
    p_by_leaf = defaultdict(list)
    d_by_leaf = defaultdict(list)
    for instance in pids:
        p_by_leaf[p_leaf[instance]].append(instance)
    for instance in dids:
        d_by_leaf[d_leaf[instance]].append(instance)
    for values in p_by_leaf.values():
        values.sort()
    for values in d_by_leaf.values():
        values.sort()

    default = {source: destination for source, destination in zip(pids, dids)}
    shuffled = dids[:]
    random.Random(seed).shuffle(shuffled)
    random_map = {source: destination for source, destination in zip(pids, shuffled)}

    # The two maps preserve a bijection while changing only which Decode leaf
    # receives each source leaf's P2D shards.  If leaf labels are not exactly
    # two-by-two, fail loudly rather than silently producing a biased map.
    if len(p_by_leaf) != 2 or len(d_by_leaf) != 2:
        raise ValueError("current P1 leaf-aligned maps expect two P and two D leaves")
    p_leaves = sorted(p_by_leaf)
    d_leaves = sorted(d_by_leaf)
    if sorted(len(p_by_leaf[key]) for key in p_leaves) != sorted(
            len(d_by_leaf[key]) for key in d_leaves):
        raise ValueError("P/D leaf populations are not pairable")
    min_map = {}
    max_map = {}
    for source_leaf, destination_leaf in zip(p_leaves, d_leaves):
        for source, destination in zip(p_by_leaf[source_leaf], d_by_leaf[destination_leaf]):
            min_map[source] = destination
    for source_leaf, destination_leaf in zip(p_leaves, reversed(d_leaves)):
        for source, destination in zip(p_by_leaf[source_leaf], d_by_leaf[destination_leaf]):
            max_map[source] = destination
    if set(min_map.values()) != set(dids) or set(max_map.values()) != set(dids):
        raise AssertionError("generated placement is not bijective")

    return {
        "DEFAULT_RR": default,
        "LOAD_ONLY": default,
        "RANDOM_SEED_%d" % seed: random_map,
        "MIN_OVERLAP_ORACLE": min_map,
        "MAX_OVERLAP_ORACLE": max_map,
    }, p_leaf, d_leaf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rank-metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    ledger = _read_ledger(args.rank_metadata)
    prefill = _instances(ledger, "prefill")
    decode = _instances(ledger, "decode")
    maps, p_leaf, d_leaf = _maps(prefill, decode, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, mapping in maps.items():
        path = args.output_dir / (name.lower() + ".json")
        path.write_text(json.dumps({
            "placement_name": name,
            "placement_map": {str(key): value for key, value in mapping.items()},
            "source_leaf_by_prefill_instance": {
                str(key): value for key, value in sorted(p_leaf.items())},
            "destination_leaf_by_decode_instance": {
                str(key): value for key, value in sorted(d_leaf.items())},
            "semantics": "offline matched P/D pairing characterization; no bytes or routing changes",
        }, indent=2) + "\n", encoding="utf-8")
        files[name] = str(path)
    manifest = {
        "rank_metadata": str(args.rank_metadata.resolve()),
        "placement_files": files,
        "random_seed": args.seed,
        "oracle_semantics": {
            "MIN_OVERLAP_ORACLE": "leaf-aligned lower-bound candidate",
            "MAX_OVERLAP_ORACLE": "leaf-crossed upper-bound candidate",
        },
        "warning": "These are offline bounds for P1; they are not an online placement algorithm.",
    }
    manifest_path = args.output_dir / "placement_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
