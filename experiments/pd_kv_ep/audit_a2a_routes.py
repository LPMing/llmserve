#!/usr/bin/env python3
"""Validate model-derived route matrices behind A2A experiment realizations.

A GateRouter produces a variable source-to-expert-owner matrix.  The native
ASTRA collective accepts one equal input buffer per rank, whereas A2A_P2P
emits the variable peer matrix directly.  This audit distinguishes those two
realizations and never modifies a simulation result.
"""

import argparse
import json
import math
from pathlib import Path


def percentile(values, fraction):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def sidecars(inputs):
    paths = []
    for value in inputs:
        path = Path(value)
        if path.is_dir():
            paths.extend(path.rglob("*.a2a_routes.json"))
        elif path.name.endswith(".a2a_routes.json"):
            paths.append(path)
        else:
            raise ValueError("expected a route sidecar or directory: %s" % path)
    return sorted(set(paths))


def validate_record(record, source, realization, ep_global_ranks):
    ep_size = int(record["ep_size"])
    top_k = int(record["top_k"])
    source_tokens = [int(value) for value in record["source_tokens"]]
    matrix = [[int(value) for value in row] for row in record["pair_matrix"]]
    if ep_size < 1 or len(source_tokens) != ep_size or len(matrix) != ep_size:
        raise ValueError("invalid EP shape in %s" % source)
    if any(len(row) != ep_size for row in matrix):
        raise ValueError("non-square pair matrix in %s" % source)
    if any(value < 0 for row in matrix for value in row):
        raise ValueError("negative pair count in %s" % source)

    pair_counts = [sum(row) for row in matrix]
    expected_rows = [tokens * top_k for tokens in source_tokens]
    if pair_counts != expected_rows:
        raise ValueError(
            "source-pair mismatch in %s: got %s, expected %s" %
            (source, pair_counts, expected_rows))
    total_pairs = sum(pair_counts)
    if total_pairs != int(record["total_expert_token_pairs"]):
        raise ValueError("total-pair mismatch in %s" % source)

    max_pairs = max(pair_counts, default=0)
    bytes_per_pair = int(record["bytes_per_expert_token"])
    padded_pairs = ep_size * max_pairs
    expected_comm_size = max_pairs * bytes_per_pair
    if expected_comm_size != int(record["astra_comm_size_per_rank"]):
        raise ValueError("ASTRA buffer mismatch in %s" % source)
    if padded_pairs != int(record["padded_input_pairs"]):
        raise ValueError("padded-pair mismatch in %s" % source)
    remote_pairs = sum(
        value for src_rank, row in enumerate(matrix)
        for dst_rank, value in enumerate(row) if src_rank != dst_rank)
    if remote_pairs != int(record["remote_expert_token_pairs"]):
        raise ValueError("remote-pair mismatch in %s" % source)
    exact_remote_bytes = remote_pairs * bytes_per_pair
    if exact_remote_bytes != int(record.get(
            "exact_routed_remote_bytes_per_phase", exact_remote_bytes)):
        raise ValueError("exact-routed byte mismatch in %s" % source)

    if realization == "ASTRA_UNIFORM_PADDED_ALLTOALL":
        source_padding_factor = float(padded_pairs) / total_pairs if total_pairs else 1.0
        padded_input_bytes = int(record["padded_collective_input_bytes"])
    elif realization == "EXACT_P2P_ROUTED_ALLTOALL":
        source_padding_factor = 1.0
        padded_input_bytes = None
    else:
        raise ValueError("unsupported A2A realization in %s: %s" %
                         (source, realization))

    repetitions = max(1, int(record.get("trace_repetitions", 1)))
    return {
        "ep_size": ep_size,
        "total_pairs": total_pairs,
        "remote_pairs": remote_pairs,
        "logical_pair_bytes": int(record["logical_pair_bytes"]),
        "padded_input_bytes": padded_input_bytes,
        "exact_routed_remote_bytes_per_phase": exact_remote_bytes,
        "source_padding_factor": source_padding_factor,
        "uniform_peer_matrix": bool(record["uniform_peer_matrix"]),
        "trace_repetitions": repetitions,
        # A full routing matrix is attached to every local DP-member trace.
        # It describes the same logical collective, not a second collective.
        # Retaining the group identity here lets the caller collapse those
        # observational copies without collapsing different EP groups.
        "ep_global_ranks": tuple(int(rank) for rank in ep_global_ranks),
        "record": record,
    }


def _logical_collective_key(record, realization):
    """Return a stable identity for one globally routed A2A collective.

    Each DP member converts only its local ranks into an ET graph, but the
    route sidecar intentionally carries the full GateRouter matrix on every
    member.  A non-empty physical EP-rank ledger is therefore mandatory for
    aggregate byte accounting: without it, an audit cannot distinguish a
    duplicate sidecar from an independent EP group safely.
    """
    ranks = record["ep_global_ranks"]
    if record["ep_size"] <= 1:
        return None
    if len(ranks) != record["ep_size"] or len(set(ranks)) != len(ranks):
        return None
    source = record["record"]
    # JSON serialization preserves every route field that affects bytes or
    # realization while avoiding assumptions about future routing metadata.
    canonical_record = json.dumps(source, sort_keys=True,
                                  separators=(",", ":"))
    return realization, ranks, canonical_record


def _weighted(records, field):
    return sum(record[field] * record["trace_repetitions"]
               for record in records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="+", type=Path,
                        help="route sidecar file(s) or run/trace directory")
    parser.add_argument("--output", type=Path,
                        help="optional JSON output path")
    parser.add_argument("--max-source-padding-factor", type=float,
                        help="fail if any network A2A record exceeds this factor")
    args = parser.parse_args()

    files = sidecars(args.input)
    if not files:
        raise SystemExit("no .a2a_routes.json sidecars found")
    records = []
    legacy_repetition_sidecars = 0
    missing_rank_identity_sidecars = 0
    realizations = set()
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        realization = payload.get("realization", "ASTRA_UNIFORM_PADDED_ALLTOALL")
        realizations.add(realization)
        if int(payload.get("schema_version", 1)) < 2:
            legacy_repetition_sidecars += 1
        ep_global_ranks = payload.get("ep_global_ranks") or []
        if payload.get("records") and not ep_global_ranks:
            missing_rank_identity_sidecars += 1
        for record in payload.get("records", []):
            records.append(validate_record(
                record, path, realization, ep_global_ranks))
    if not records:
        raise SystemExit("route sidecars contain no records")
    if len(realizations) != 1:
        raise SystemExit("input sidecars mix A2A realizations: %s" %
                         ", ".join(sorted(realizations)))
    realization = next(iter(realizations))

    network = [record for record in records if record["ep_size"] > 1]
    unique_network = {}
    unidentifiable_network = []
    for record in network:
        key = _logical_collective_key(record, realization)
        if key is None:
            unidentifiable_network.append(record)
            continue
        # Identical sidecars from DP members represent the same collective.
        # If two records share an identity but disagree on derived accounting,
        # fail rather than silently choosing one.
        previous = unique_network.get(key)
        if previous is not None:
            for field in (
                    "total_pairs", "remote_pairs", "logical_pair_bytes",
                    "padded_input_bytes", "exact_routed_remote_bytes_per_phase",
                    "source_padding_factor", "trace_repetitions"):
                if previous[field] != record[field]:
                    raise ValueError(
                        "duplicate logical A2A collective has inconsistent "
                        "%s accounting" % field)
        else:
            unique_network[key] = record
    unique_network_records = list(unique_network.values())
    accounting_complete = not unidentifiable_network
    unique_weighted = (
        (lambda field: _weighted(unique_network_records, field))
        if accounting_complete else None)
    raw_weighted = lambda field: _weighted(network, field)
    result = {
        "valid": True,
        "realization": realization,
        "sidecar_files": len(files),
        "raw_sidecar_records": len(records),
        "raw_network_route_patterns": len(network),
        "deduplicated_network_collective_records": len(unique_network_records),
        "unidentifiable_network_route_patterns": len(unidentifiable_network),
        "weighted_moe_blocks": (
            sum(record["trace_repetitions"] for record in unique_network_records)
            if accounting_complete else None),
        "weighted_logical_pair_bytes": (
            unique_weighted("logical_pair_bytes") if accounting_complete else None),
        "weighted_exact_routed_remote_bytes_per_phase": (
            unique_weighted("exact_routed_remote_bytes_per_phase")
            if accounting_complete else None),
        "weighted_padded_input_bytes": (
            unique_weighted("padded_input_bytes")
            if (accounting_complete and
                realization == "ASTRA_UNIFORM_PADDED_ALLTOALL") else None),
        "raw_weighted_network_logical_pair_bytes": raw_weighted(
            "logical_pair_bytes"),
        "raw_weighted_network_exact_routed_remote_bytes_per_phase": raw_weighted(
            "exact_routed_remote_bytes_per_phase"),
        "raw_weighted_network_padded_input_bytes": (
            raw_weighted("padded_input_bytes")
            if realization == "ASTRA_UNIFORM_PADDED_ALLTOALL" else None),
        "trace_repetition_accounting": (
            "complete" if (not legacy_repetition_sidecars and
                           accounting_complete) else
            "incomplete: legacy trace-repetition metadata or a complete "
            "EP-rank identity is unavailable"
        ),
        "legacy_repetition_sidecars": legacy_repetition_sidecars,
        "missing_rank_identity_sidecars": missing_rank_identity_sidecars,
        "aggregate_accounting_valid": accounting_complete,
        "network_collective_accounting": (
            "complete_deduplicated_by_ep_global_ranks"
            if accounting_complete else
            "unavailable: at least one network sidecar lacks a complete "
            "ep_global_ranks identity; raw totals are diagnostic only"),
        "source_padding_factor": {
            "mean": (sum(record["source_padding_factor"]
                         for record in unique_network_records) /
                     len(unique_network_records)
                     if accounting_complete and unique_network_records else None),
            "p50": (percentile(
                [record["source_padding_factor"]
                 for record in unique_network_records], .50)
                if accounting_complete else None),
            "p95": (percentile(
                [record["source_padding_factor"]
                 for record in unique_network_records], .95)
                if accounting_complete else None),
            "max": (max((record["source_padding_factor"]
                         for record in unique_network_records), default=1.0)
                    if accounting_complete else None),
        },
        "uniform_peer_matrix_patterns": sum(
            record["uniform_peer_matrix"] for record in unique_network_records),
        "note": (
            "The matrix conserves model-derived expert-token pairs. ASTRA's "
            "native ALLTOALL models a common equal buffer; source_padding_factor "
            "quantifies the resulting source-buffer inflation."
            if realization == "ASTRA_UNIFORM_PADDED_ALLTOALL" else
            "The matrix is emitted as exact nonzero source-to-owner P2P messages "
            "for each phase; no equal-buffer source padding is applied."
        ),
    }
    if (args.max_source_padding_factor is not None and accounting_complete and
            result["source_padding_factor"]["max"] > args.max_source_padding_factor):
        result["valid"] = False
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if not result["valid"]:
        raise SystemExit("source-padding factor exceeds requested bound")


if __name__ == "__main__":
    main()
