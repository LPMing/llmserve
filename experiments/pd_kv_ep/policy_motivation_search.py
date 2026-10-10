#!/usr/bin/env python3
"""Run a matched native KV/EP static-priority experiment.

This is a characterization driver, not a scheduler.  It generates one native
request workload and replays it under FAIR, KV_FIRST, and EP_FIRST.  The main
result is accepted only when the whole-run logical communication signature
matches.  A separately labelled pre-handoff cohort audit also exposes a
causal data-plane slice when later closed-loop Decode admission differs as a
consequence of the policy itself.
"""

import argparse
import ast
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from matched_search import write_matched_workload
from semantic_events import is_decode_ep, is_p2d_kv


ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "pd_kv_ep"
RUNNER = EXP / "run_experiments.py"
POLICIES = ("FAIR", "KV_FIRST", "EP_FIRST")


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


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def read_timeline(path):
    rows = []
    for row in read_rows(path):
        try:
            row["start_num"] = int(row["start"])
            row["end_num"] = int(row["end"])
            row["bytes_num"] = int(row["bytes"])
        except (KeyError, TypeError, ValueError):
            continue
        if row["end_num"] >= row["start_num"]:
            rows.append(row)
    return rows


def _summary(values):
    values = [float(value) for value in values]
    return {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, .50),
        "p95": percentile(values, .95),
        "p99": percentile(values, .99),
    }


def request_ids(row):
    value = row.get("active_request_ids", "") or row.get("request_id", "")
    return {item for item in str(value).replace(";", ",").split(",") if item}


def decode_collective_groups(rows):
    """Group every Decode EP physical flow into a collective-level record."""
    groups = defaultdict(list)
    for row in rows:
        if not is_decode_ep(row):
            continue
        key = (row.get("collective_id", ""), row.get("event_type", ""))
        if not key[0]:
            continue
        groups[key].append(row)
    return dict(groups)


def group_is_target_decode(group, target_request_ids):
    """Whether every physical flow belongs only to the old Decode cohort."""
    if target_request_ids is None:
        return True
    target = {str(value) for value in target_request_ids}
    return bool(group) and all(
        bool(request_ids(row)) and request_ids(row).issubset(target)
        for row in group)


def collective_cct_from_groups(groups):
    """Return collective CCTs, defined as last completion minus first start."""
    dispatch = []
    combine = []
    bytes_by_group = []
    for group in groups:
        start = min(row["start_num"] for row in group)
        end = max(row["end_num"] for row in group)
        cct_ns = end - start
        if group[0]["event_type"] == "EP_DISPATCH":
            dispatch.append(cct_ns)
        elif group[0]["event_type"] == "EP_COMBINE":
            combine.append(cct_ns)
        bytes_by_group.append(sum(row["bytes_num"] for row in group))
    return {
        "dispatch": _summary(dispatch),
        "combine": _summary(combine),
        "all": _summary(dispatch + combine),
        "collective_count": len(bytes_by_group),
        "collective_bytes_mean": (
            sum(bytes_by_group) / len(bytes_by_group)
            if bytes_by_group else None),
    }


def collective_cct(rows, target_request_ids=None):
    """Return dispatch/combine CCTs from all physical flows of each collective."""
    groups = decode_collective_groups(rows)
    selected = [
        group for group in groups.values()
        if group_is_target_decode(group, target_request_ids)
    ]
    return collective_cct_from_groups(selected)


def collective_fingerprint(group):
    """Timing-independent logical metadata for one Decode EP collective.

    A collective contains physical flows emitted by several ranks.  A single
    row therefore has only the requests local to that rank; retain the full
    multiset of row-level request memberships rather than using the first row.
    """
    return (
        group[0].get("event_type", ""),
        group[0].get("serving_role", ""),
        tuple(sorted(Counter(
            tuple(sorted(request_ids(row))) for row in group).items())),
        tuple(sorted(Counter(row.get("layer_id", "") for row in group).items())),
        tuple(sorted(Counter(
            (row.get("src", ""), row.get("dst", ""), row.get("bytes", ""))
            for row in group).items())),
    )


def p2d_completion_by_request(rows, request_id_set):
    """Return the last physical P2D cache-shard completion for each request."""
    requested = {str(value) for value in request_id_set}
    completions = {}
    for row in rows:
        if not is_p2d_kv(row) or row.get("request_id", "") not in requested:
            continue
        request_id = row["request_id"]
        completions[request_id] = max(
            completions.get(request_id, row["end_num"]), row["end_num"])
    return completions


def _positive_exact_overlap_ep_ids(overlap_rows, timeline_by_id, kv_ids):
    """Select Decode EP event ids that overlap a requested P2D flow exactly."""
    requested = {str(value) for value in kv_ids}
    event_ids = set()
    for row in overlap_rows:
        try:
            positive = int(row.get("overlap_ns", "0")) > 0
        except (TypeError, ValueError):
            positive = False
        if not positive:
            continue
        kv_row = timeline_by_id.get(row.get("kv_event_id", ""))
        ep_row = timeline_by_id.get(row.get("ep_event_id", ""))
        if (kv_row is None or ep_row is None or not is_p2d_kv(kv_row) or
                not is_decode_ep(ep_row)):
            continue
        if kv_row.get("request_id", "") in requested:
            event_ids.add(ep_row["event_id"])
    return event_ids


def pre_handoff_shared_link_cohort(timelines, overlap_rows, decode_ids, kv_ids,
                                   reference_policy):
    """Audit a causal old-Decode cohort before any new P2D request can decode.

    The normal whole-run signature remains the main matched-control guard.  In
    a closed-loop serving simulation, however, a true data-plane delay can
    causally change batches after a new request enters Decode.  This secondary
    audit isolates the earlier cohort: old Decode collectives that (a) have a
    positive exact same-directed-link overlap with a requested P2D flow under
    the FAIR reference and (b) begin before the earliest possible new-request
    cache-ready time in *any* policy.  Every selected collective's immutable
    metadata is matched across policies; only its physical timing may differ.
    """
    result = {
        "valid": False,
        "reference_policy": reference_policy,
        "definition": (
            "Old Decode-only collectives with positive exact same-directed-link "
            "overlap with requested P2D KV under the FAIR reference, issued "
            "before the earliest P2D cache-ready time across all policies."
        ),
        "policies": {},
    }
    if reference_policy not in timelines:
        result["reason"] = "reference policy timeline is unavailable"
        return result

    completions = {
        policy: p2d_completion_by_request(rows, kv_ids)
        for policy, rows in timelines.items()
    }
    expected_ids = {str(value) for value in kv_ids}
    if any(set(values) != expected_ids for values in completions.values()):
        result["reason"] = "at least one requested P2D transfer is missing"
        result["p2d_completion_by_policy"] = completions
        return result
    cutoff = min(
        completion for values in completions.values()
        for completion in values.values())
    result["earliest_new_decode_admit_bound_ns"] = cutoff
    result["p2d_completion_by_policy"] = completions

    reference_rows = timelines[reference_policy]
    reference_by_event_id = {
        row.get("event_id", ""): row for row in reference_rows
    }
    reference_groups = decode_collective_groups(reference_rows)
    reference_overlap_ids = _positive_exact_overlap_ep_ids(
        overlap_rows.get(reference_policy, []), reference_by_event_id, kv_ids)
    candidate_keys = set()
    for event_id in reference_overlap_ids:
        row = reference_by_event_id[event_id]
        key = (row.get("collective_id", ""), row.get("event_type", ""))
        group = reference_groups.get(key, [])
        if (group and group_is_target_decode(group, decode_ids) and
                min(item["start_num"] for item in group) < cutoff):
            candidate_keys.add(key)
    if not candidate_keys:
        result["reason"] = "no old Decode collective met the pre-handoff overlap rule"
        return result

    reference_fingerprints = {
        key: collective_fingerprint(reference_groups[key])
        for key in candidate_keys
    }
    matched_keys_by_policy = {}
    result["candidate_collective_count"] = len(candidate_keys)
    result["candidate_collectives"] = [
        {"collective_id": key[0], "event_type": key[1]}
        for key in sorted(candidate_keys)
    ]
    all_valid = True
    for policy, rows in timelines.items():
        groups = decode_collective_groups(rows)
        selected = []
        missing = []
        mismatched = []
        for key in sorted(candidate_keys):
            group = groups.get(key)
            if group is None:
                missing.append({"collective_id": key[0], "event_type": key[1]})
                continue
            if (not group_is_target_decode(group, decode_ids) or
                    collective_fingerprint(group) != reference_fingerprints[key]):
                mismatched.append({"collective_id": key[0], "event_type": key[1]})
                continue
            selected.append(group)
        matched_keys_by_policy[policy] = {
            key for key in candidate_keys
            if key not in {
                (item["collective_id"], item["event_type"])
                for item in missing + mismatched
            }
        }
        by_event_id = {row.get("event_id", ""): row for row in rows}
        exact_ep_ids = _positive_exact_overlap_ep_ids(
            overlap_rows.get(policy, []), by_event_id, kv_ids)
        selected_event_ids = {
            row["event_id"] for group in selected for row in group
        }
        policy_valid = not missing and not mismatched
        all_valid = all_valid and policy_valid
        result["policies"][policy] = {
            "valid": policy_valid,
            "matched_collective_count": len(selected),
            "missing_collectives": missing,
            "static_metadata_mismatch": mismatched,
            "cct": collective_cct_from_groups(selected),
            "exact_shared_link_overlap_event_rows": len(
                exact_ep_ids.intersection(selected_event_ids)),
        }
    result["valid"] = all_valid

    # A network policy can causally alter a later scheduler batch even before
    # the new request begins Decode.  Keep the all-policy cohort above as the
    # primary, strongest check, but also expose a transparent pairwise
    # intersection for policies whose immutable communication records remain
    # identical.  This does not promote an unmatched policy into the result:
    # every reported pair lists its exact retained coverage.
    pairwise = {}
    for policy, rows in timelines.items():
        if policy == reference_policy:
            continue
        pair_keys = sorted(
            matched_keys_by_policy.get(reference_policy, set()).intersection(
                matched_keys_by_policy.get(policy, set())))
        reference_selected = [reference_groups[key] for key in pair_keys]
        policy_groups = decode_collective_groups(rows)
        policy_selected = [policy_groups[key] for key in pair_keys]
        reference_event_ids = {
            row["event_id"] for group in reference_selected for row in group
        }
        policy_event_ids = {
            row["event_id"] for group in policy_selected for row in group
        }
        reference_by_event_id = {
            row.get("event_id", ""): row for row in reference_rows
        }
        policy_by_event_id = {row.get("event_id", ""): row for row in rows}
        reference_overlap_ids = _positive_exact_overlap_ep_ids(
            overlap_rows.get(reference_policy, []), reference_by_event_id,
            kv_ids)
        policy_overlap_ids = _positive_exact_overlap_ep_ids(
            overlap_rows.get(policy, []), policy_by_event_id, kv_ids)
        pairwise[policy] = {
            "valid": bool(pair_keys),
            "matched_collective_count": len(pair_keys),
            "excluded_candidate_collective_count": len(candidate_keys) - len(pair_keys),
            "collectives": [
                {"collective_id": key[0], "event_type": key[1]}
                for key in pair_keys
            ],
            "reference_cct": collective_cct_from_groups(reference_selected),
            "policy_cct": collective_cct_from_groups(policy_selected),
            "reference_exact_shared_link_overlap_event_rows": len(
                reference_overlap_ids.intersection(reference_event_ids)),
            "policy_exact_shared_link_overlap_event_rows": len(
                policy_overlap_ids.intersection(policy_event_ids)),
        }
    result["pairwise_reference_matched_cohorts"] = pairwise
    return result


def p2d_transfer(rows, request_ids=None):
    requested = ({str(value) for value in request_ids}
                 if request_ids is not None else None)
    groups = {}
    for row in rows:
        if not is_p2d_kv(row):
            continue
        request_id = row.get("request_id", "")
        if requested is not None and request_id not in requested:
            continue
        if not request_id:
            continue
        value = groups.setdefault(request_id, {
            "start": row["start_num"], "end": row["end_num"],
            "bytes": 0, "flows": 0,
        })
        value["start"] = min(value["start"], row["start_num"])
        value["end"] = max(value["end"], row["end_num"])
        value["bytes"] += row["bytes_num"]
        value["flows"] += 1
    durations = [value["end"] - value["start"] for value in groups.values()]
    return {
        "by_request": groups,
        "transfer": _summary(durations),
        "bytes_per_request": _summary(
            [value["bytes"] for value in groups.values()]),
    }


def serving_metrics(path, decode_ids, kv_ids):
    decode_ids = {str(value) for value in decode_ids}
    kv_ids = {str(value) for value in kv_ids}
    decode_tpot = []
    decode_itl = []
    decode_itl_by_position = defaultdict(list)
    kv_ttft = []
    kv_decode_ttft = []
    kv_ready_delay = []
    for row in read_rows(path):
        request_id = row.get("request id", "")
        if request_id in decode_ids:
            try:
                if float(row.get("TPOT", 0)) > 0:
                    decode_tpot.append(float(row["TPOT"]))
            except (TypeError, ValueError):
                pass
            try:
                values = ast.literal_eval(row.get("ITL", "[]"))
                if not isinstance(values, list):
                    values = []
                for position, value in enumerate(values):
                    value = float(value)
                    decode_itl.append(value)
                    decode_itl_by_position[position].append(value)
            except (SyntaxError, ValueError, TypeError):
                pass
        if request_id in kv_ids:
            try:
                kv_ttft.append(float(row["TTFT"]))
            except (TypeError, ValueError):
                pass
            try:
                kv_decode_ttft.append(float(row["decode_TTFT"]))
            except (TypeError, ValueError):
                pass
            try:
                ready = int(row["p2d_kv_ready_time_ns"])
                arrival = int(row["arrival"])
                kv_ready_delay.append(ready - arrival)
            except (KeyError, TypeError, ValueError):
                pass
    return {
        "decode_tpot_ns": _summary(decode_tpot),
        "decode_itl_ns": _summary(decode_itl),
        "decode_itl_by_output_position_ns": {
            str(position): _summary(values)
            for position, values in sorted(decode_itl_by_position.items())
        },
        "kv_ttft_ns": _summary(kv_ttft),
        "kv_decode_ttft_ns": _summary(kv_decode_ttft),
        "kv_ready_delay_ns": _summary(kv_ready_delay),
    }


def semantic_signature(rows, target_decode_ids=None):
    """Counter independent of time and priority for the matched window.

    P2D entries retain all requests.  Decode EP is restricted to non-empty
    groups containing only the pre-existing Decode requests.  Empty DP dummy
    waves and collectives after a new P2D request enters Decode are explicitly
    outside the observation window: their batch ids can change as a causal
    consequence of the data-plane policy, but they are not the active Decode
    EP communication under comparison.
    """
    target = ({str(value) for value in target_decode_ids}
              if target_decode_ids is not None else None)
    signature = Counter()
    for row in rows:
        if is_p2d_kv(row):
            include = True
        elif is_decode_ep(row):
            ids = request_ids(row)
            include = (target is None or (bool(ids) and ids.issubset(target)))
        else:
            include = False
        if not include:
            continue
        signature[(
            row.get("event_type", ""), row.get("serving_role", ""),
            row.get("request_id", ""), row.get("active_request_ids", ""),
            # ``collective_id`` embeds a scheduler batch id.  A DP dummy wave
            # outside the matched window can advance it without changing the
            # logical target group, so compare the immutable group semantics
            # rather than that time-derived identifier.
            row.get("layer_id", ""),
            row.get("src", ""), row.get("dst", ""), row.get("bytes", ""),
        )] += 1
    return signature


def full_semantic_signature(rows):
    """Diagnostic-only signature including all Decode EP and batch ids."""
    signature = Counter()
    for row in rows:
        if not (is_p2d_kv(row) or is_decode_ep(row)):
            continue
        signature[(
            row.get("event_type", ""), row.get("serving_role", ""),
            row.get("request_id", ""), row.get("active_request_ids", ""),
            row.get("collective_id", ""), row.get("layer_id", ""),
            row.get("src", ""), row.get("dst", ""), row.get("bytes", ""),
        )] += 1
    return signature


def priority_audit(comm_events_path):
    rows = [row for row in read_rows(comm_events_path) if row.get("phase") == "END"]
    return Counter(
        (row.get("event_type", ""), row.get("serving_role", ""),
         row.get("priority_group", ""))
        for row in rows
        if ((row.get("event_type") == "1" and
             row.get("serving_role") == "PREFILL") or
            (row.get("event_type") in ("2", "3") and
             row.get("serving_role") == "DECODE"))
    )


def expected_priorities(policy):
    if policy == "FAIR":
        return {("1", "PREFILL"): "3", ("2", "DECODE"): "3",
                ("3", "DECODE"): "3"}
    if policy == "KV_FIRST":
        return {("1", "PREFILL"): "0", ("2", "DECODE"): "3",
                ("3", "DECODE"): "3"}
    return {("1", "PREFILL"): "3", ("2", "DECODE"): "0",
            ("3", "DECODE"): "0"}


def policy_priority_valid(audit, policy):
    expected = expected_priorities(policy)
    actual = {}
    for event_type, role, priority in audit:
        actual.setdefault((event_type, role), set()).add(priority)
    return (all(actual.get(key) == {value} for key, value in expected.items()),
            {"expected": {"%s/%s" % key: value for key, value in expected.items()},
             "actual": {"%s/%s" % key: sorted(value)
                        for key, value in actual.items()}})


def write_workload(path, args):
    if path.exists() and not args.overwrite_workload:
        return
    write_matched_workload(
        path, args.p2d_arrival_ns,
        a_input=args.decode_input, a_output=args.decode_output,
        b_input=args.kv_input, b_output=args.kv_output,
        a_count=args.active_decode, b_count=args.p2d_count,
        b_spacing_ns=args.p2d_spacing_ns,
    )


def run_policy(label, policy, args, workload, output):
    run_id = "policy-%s-%s" % (label, policy.lower())
    run_root = ROOT / "astra-sim" / "inputs" / "runs" / run_id
    existing = {
        "run_id": run_id,
        "output": output,
        "timeline": output.with_suffix(".timeline.csv"),
        "comm_events": run_root / "ns3" / "output" / "comm_events.csv",
        "overlap": output.with_suffix(".directed_link_overlap.csv"),
    }
    if args.reuse_existing and all(path.exists() for path in (
            existing["output"], existing["timeline"],
            existing["comm_events"], existing["overlap"])):
        existing["command"] = ["REUSED_COMPLETED_RUN"]
        return existing
    command = [
        sys.executable, str(RUNNER),
        "--scenario", "mixed",
        "--cluster-config", str(args.cluster_config),
        "--workload", str(workload),
        "--network-backend", "ns3",
        "--kv-ep-network-policy", policy,
        "--ep-collective-semantics", args.ep_collective_semantics,
        "--pd-kv-transfer-mode", args.pd_kv_transfer_mode,
        "--run-id", run_id,
        "--output", str(output),
    ]
    if args.dry_run:
        return {"run_id": run_id, "command": command}
    subprocess.run(command, cwd=str(ROOT), check=True)
    return {
        "run_id": run_id,
        "command": command,
        "output": output,
        "timeline": output.with_suffix(".timeline.csv"),
        "comm_events": run_root / "ns3" / "output" / "comm_events.csv",
        "overlap": output.with_suffix(".directed_link_overlap.csv"),
    }


def percent_improvement(worse, better):
    if worse in (None, 0) or better is None:
        return None
    return (float(worse) - float(better)) / float(worse)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--cluster-config", type=Path, required=True)
    parser.add_argument("--active-decode", type=int, required=True)
    parser.add_argument("--p2d-count", type=int, required=True)
    parser.add_argument("--decode-input", type=int, default=64)
    parser.add_argument("--decode-output", type=int, default=4)
    parser.add_argument("--kv-input", type=int, default=1024)
    parser.add_argument("--kv-output", type=int, default=1)
    parser.add_argument("--p2d-arrival-ns", type=int, default=10000000)
    parser.add_argument("--p2d-spacing-ns", type=int, default=0)
    parser.add_argument("--ep-collective-semantics",
                        choices=("NATIVE_AG_RS", "A2A", "A2A_P2P"),
                        default="NATIVE_AG_RS")
    parser.add_argument("--pd-kv-transfer-mode",
                        choices=("LAYERWISE", "POST_PREFILL"),
                        default="LAYERWISE",
                        help="upstream-compatible layerwise P2D or an explicit "
                        "model-derived post-prefill cache chunk")
    parser.add_argument("--policies", nargs="+", choices=POLICIES,
                        default=list(POLICIES))
    parser.add_argument("--overwrite-workload", action="store_true")
    parser.add_argument("--reuse-existing", action="store_true",
                        help="reuse only a completed output/timeline/telemetry bundle")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.active_decode < 1 or args.p2d_count < 1:
        raise SystemExit("active-decode and p2d-count must both be positive")

    label = args.label
    workload = EXP / "workloads" / "policy" / (label + ".jsonl")
    results_dir = EXP / "results" / "policy" / label
    results_dir.mkdir(parents=True, exist_ok=True)
    write_workload(workload, args)
    if args.dry_run:
        preview = {
            policy: run_policy(label, policy, args, workload,
                               results_dir / (policy.lower() + ".csv"))
            for policy in args.policies
        }
        print(json.dumps({"workload": str(workload), "runs": preview}, indent=2))
        return

    common = {
        "workload": str(workload), "workload_sha256": file_hash(workload),
        "cluster_config": str(args.cluster_config),
        "cluster_config_sha256": file_hash(args.cluster_config),
        "ep_collective_semantics": args.ep_collective_semantics,
        "pd_kv_transfer_mode": args.pd_kv_transfer_mode,
        "request_parameters": {
            "active_decode": args.active_decode,
            "p2d_count": args.p2d_count,
            "decode_input": args.decode_input,
            "decode_output": args.decode_output,
            "kv_input": args.kv_input,
            "kv_output": args.kv_output,
            "p2d_arrival_ns": args.p2d_arrival_ns,
            "p2d_spacing_ns": args.p2d_spacing_ns,
        },
        "synthetic_byte_override": False,
    }
    decode_ids = list(range(args.active_decode))
    kv_ids = list(range(args.active_decode, args.active_decode + args.p2d_count))
    results = {}
    signatures = {}
    full_signatures = {}
    timelines = {}
    overlaps = {}
    for policy in args.policies:
        output = results_dir / (policy.lower() + ".csv")
        run = run_policy(label, policy, args, workload, output)
        timeline = read_timeline(run["timeline"])
        overlap = read_rows(run["overlap"])
        audit = priority_audit(run["comm_events"])
        priority_valid, priority_details = policy_priority_valid(audit, policy)
        results[policy] = {
            "run_id": run["run_id"],
            "cct_active_decode": collective_cct(timeline, decode_ids),
            "cct_all_decode": collective_cct(timeline),
            "p2d": p2d_transfer(timeline, kv_ids),
            "serving": serving_metrics(output, decode_ids, kv_ids),
            "priority_valid": priority_valid,
            "priority_audit": priority_details,
            "exact_shared_link_overlap_rows": len(overlap),
        }
        signatures[policy] = semantic_signature(timeline, decode_ids)
        full_signatures[policy] = full_semantic_signature(timeline)
        timelines[policy] = timeline
        overlaps[policy] = overlap

    reference = signatures[args.policies[0]]
    semantic_match = {
        policy: signatures[policy] == reference for policy in args.policies
    }
    full_semantic_match = {
        policy: full_signatures[policy] == full_signatures[args.policies[0]]
        for policy in args.policies
    }
    for policy in args.policies:
        results[policy]["semantic_signature_matches_reference"] = semantic_match[policy]
    reference_policy = "FAIR" if "FAIR" in args.policies else args.policies[0]
    pre_handoff_cohort = pre_handoff_shared_link_cohort(
        timelines, overlaps, decode_ids, kv_ids, reference_policy)
    fair = results.get("FAIR", {})
    ep_first = results.get("EP_FIRST", {})
    kv_first = results.get("KV_FIRST", {})
    if pre_handoff_cohort.get("valid", False):
        cohort_fair = pre_handoff_cohort.get("policies", {}).get("FAIR", {})
        cohort_ep_first = pre_handoff_cohort.get("policies", {}).get("EP_FIRST", {})
        cohort_kv_first = pre_handoff_cohort.get("policies", {}).get("KV_FIRST", {})
    else:
        # Never turn a partially matched cohort into an apparent opportunity.
        cohort_fair = {}
        cohort_ep_first = {}
        cohort_kv_first = {}
    pairwise_cohorts = pre_handoff_cohort.get(
        "pairwise_reference_matched_cohorts", {})
    fair_ep_pair = pairwise_cohorts.get("EP_FIRST", {})
    fair_ep_pair_valid = (
        fair_ep_pair.get("valid", False) and
        results.get("FAIR", {}).get("priority_valid", False) and
        results.get("EP_FIRST", {}).get("priority_valid", False))
    opportunities = {
        "ep_protection_p99_tpot": percent_improvement(
            kv_first.get("serving", {}).get("decode_tpot_ns", {}).get("p99"),
            ep_first.get("serving", {}).get("decode_tpot_ns", {}).get("p99")),
        "ep_protection_fair_to_ep_first_p99_tpot": percent_improvement(
            fair.get("serving", {}).get("decode_tpot_ns", {}).get("p99"),
            ep_first.get("serving", {}).get("decode_tpot_ns", {}).get("p99")),
        "ep_protection_p95_itl": percent_improvement(
            kv_first.get("serving", {}).get("decode_itl_ns", {}).get("p95"),
            ep_first.get("serving", {}).get("decode_itl_ns", {}).get("p95")),
        "ep_protection_fair_to_ep_first_p95_itl": percent_improvement(
            fair.get("serving", {}).get("decode_itl_ns", {}).get("p95"),
            ep_first.get("serving", {}).get("decode_itl_ns", {}).get("p95")),
        "ep_protection_p99_itl": percent_improvement(
            kv_first.get("serving", {}).get("decode_itl_ns", {}).get("p99"),
            ep_first.get("serving", {}).get("decode_itl_ns", {}).get("p99")),
        "ep_protection_p99_cct": percent_improvement(
            kv_first.get("cct_active_decode", {}).get("all", {}).get("p99"),
            ep_first.get("cct_active_decode", {}).get("all", {}).get("p99")),
        "ep_protection_fair_to_ep_first_p99_cct": percent_improvement(
            fair.get("cct_active_decode", {}).get("all", {}).get("p99"),
            ep_first.get("cct_active_decode", {}).get("all", {}).get("p99")),
        "ep_protection_p99_cct_pre_handoff_shared_link_cohort": percent_improvement(
            cohort_kv_first.get("cct", {}).get("all", {}).get("p99"),
            cohort_ep_first.get("cct", {}).get("all", {}).get("p99")),
        "ep_protection_fair_to_ep_first_p99_cct_pre_handoff_shared_link_cohort": percent_improvement(
            cohort_fair.get("cct", {}).get("all", {}).get("p99"),
            cohort_ep_first.get("cct", {}).get("all", {}).get("p99")),
        "ep_protection_fair_to_ep_first_p99_cct_pairwise_pre_handoff_shared_link_cohort": (
            percent_improvement(
                fair_ep_pair.get("reference_cct", {}).get("all", {}).get("p99"),
                fair_ep_pair.get("policy_cct", {}).get("all", {}).get("p99"))
            if fair_ep_pair_valid else None),
        "kv_protection_p99_ttft": percent_improvement(
            ep_first.get("serving", {}).get("kv_ttft_ns", {}).get("p99"),
            kv_first.get("serving", {}).get("kv_ttft_ns", {}).get("p99")),
    }
    valid = all(value["priority_valid"] for value in results.values()) and all(
        semantic_match.values())
    causal_cohort_valid = (
        pre_handoff_cohort.get("valid", False) and
        all(value["priority_valid"] for value in results.values()))
    report = {
        "valid": valid,
        "causal_pre_handoff_cohort_valid": causal_cohort_valid,
        "common": common,
        "policies": results,
        "semantic_signature_match": semantic_match,
        "full_semantic_signature_match_diagnostic": full_semantic_match,
        "pre_handoff_shared_link_cohort": pre_handoff_cohort,
        "matched_observation_window": (
            "all Prefill P2D flows plus non-empty Decode EP groups containing "
            "only the pre-existing Decode requests; excludes DP dummy waves and "
            "post-handoff Decode work of the new P2D requests"
        ),
        "opportunities": opportunities,
        "interpretation": (
            "The whole-run policy result is valid only when the predeclared "
            "observation window's logical communication metadata matches "
            "exactly across policies. The separately labelled pre-handoff "
            "cohort is a narrower causal data-plane result: its old Decode "
            "collectives have matched immutable metadata, while later "
            "closed-loop control-plane divergence remains visible rather than "
            "being folded into that result."
        ),
    }
    report_path = results_dir / "policy_summary.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({"valid": valid,
                      "causal_pre_handoff_cohort_valid": causal_cohort_valid,
                      "report": str(report_path),
                      "opportunities": opportunities}, indent=2))
    if not valid:
        raise SystemExit("policy comparison rejected by the matched-control audit")


if __name__ == "__main__":
    main()
