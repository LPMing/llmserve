#!/usr/bin/env python3
"""Compute profile-backed EP/AG-RS serialization upper bounds.

No simulator backend is launched. Batch tensors, compute layers, and collective
message sizes are emitted by the current trace generator from the Qwen3 config
and RTX PRO 6000 profile. Output values are bounds, never measured TBT.
"""

import csv
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from serving.core.request import Batch  # noqa: E402
from serving.core.trace_generator import generate_trace  # noqa: E402


MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
CONTEXTS = (256, 2048, 8192)
GROUP_REQUESTS = (2, 4, 8, 16, 32, 64)
LINK_GBPS = 200.0
LAYERS = 48
RANKS_PER_SERVER = 2
MODEL_PROFILE = "RTXPRO6000"
# Measured one-group 200G FlowSim CCT minus its effective-cut serialization
# time is ~10.2 us for both AG and RS in the retained EP4 runs. Reuse that
# startup/propagation component only as a profile-alignment proxy; it is not a
# packet-level or group-64 measured CCT.
MEASURED_BASE_CCT_NS = 10_200.0
PLACEMENT = {
    "default": {"weights": "LOCAL", "kv_loc": "LOCAL", "kv_evict_loc": "LOCAL"},
    "layer": {},
}


def decode_trace(local_active, context, instance_id, node_id):
    batch = Batch(
        0, MODEL, local_active, local_active * context,
        [], [], 0, local_active, [], [], [context] * local_active, 0, 0,
    )
    batch.requests = [SimpleNamespace(id=i) for i in range(local_active)]
    return generate_trace(
        batch, MODEL_PROFILE, tp_size=2, pp_size=1, local_ep=2, ep_total=4,
        pd_type="decode", node_id=node_id, instance_id=instance_id,
        max_num_batched_tokens=2048, max_num_seqs=256,
        placement=PLACEMENT, block_mode_on=False,
        expert_routing_policy="BALANCED", enable_prefix_caching=False,
        enable_attn_offloading=False, power_model=None, pim_model=None,
        enable_sub_batch_interleaving=False, fp=16, dtype="bfloat16",
        kv_cache_dtype="auto", ep_dim=[False, True, False],
        dp_sum_total_len=local_active, enable_block_copy=True,
    )


def extract(trace):
    compute = []
    expert_compute = []
    dispatch = []
    combine = []
    for row in trace.rows:
        if len(row) >= 10:
            try:
                value = int(row[1])
            except (TypeError, ValueError):
                continue
            compute.append(value)
            if row[0] == "expert":
                expert_compute.append(value)
        elif len(row) == 1:
            fields = row[0].split()
            if fields[:2] == ["EXPERT", "END"] and len(fields) >= 3:
                if "REDUCESCATTER" in fields[2]:
                    combine.append(int(fields[-1]))
            elif fields and fields[0] == "EXPERT" and len(fields) >= 4:
                if "ALLGATHER" in fields[2]:
                    dispatch.append(int(fields[-1]))
    if len(expert_compute) != LAYERS * 2:
        raise RuntimeError(f"Expected {LAYERS * 2} local EP expert ops, got {len(expert_compute)}")
    expert_max = sum(max(expert_compute[i:i + 2]) for i in range(0, len(expert_compute), 2))
    compute_lb_ns = sum(compute) - sum(expert_compute) + expert_max
    if len(dispatch) != LAYERS or len(combine) != LAYERS:
        raise RuntimeError(f"Expected 48 AG/RS messages, got {len(dispatch)}/{len(combine)}")
    return compute_lb_ns, dispatch, combine


def effective_cut_bytes(kind, participant_bytes):
    # Verified against retained EP4 per-flow paths: AG has four cross-server
    # peers per direction; RS's generated per-rank payload aggregates to this
    # many bytes on one directed cut. This is a per-directed-cut workload, not
    # total collective payload or sum over both directions.
    return participant_bytes * (RANKS_PER_SERVER ** 2 if kind == "DISPATCH" else 1)


def wire_service_ns(kind, participant_bytes):
    return effective_cut_bytes(kind, participant_bytes) * 8 / (LINK_GBPS * 1e9) * 1e9


def isolated_cct_ns(kind, participant_bytes):
    return MEASURED_BASE_CCT_NS + wire_service_ns(kind, participant_bytes)


def phase_release_timeline(trace):
    """Compute profile releases with an isolated measured-base + wire CCT.

    This approximates each group's no-contention release timeline. It does not
    model cross-group network feedback, which is why the later overlap oracle
    is explicitly an optimistic screening bound, not an experiment.
    """
    cursor = 0
    expert_rank_times = []
    releases = []
    for row in trace.rows:
        if len(row) == 1:
            fields = row[0].split()
            if fields[:2] == ["EXPERT", "END"] and len(fields) >= 3:
                if "REDUCESCATTER" in fields[2]:
                    size = int(fields[-1])
                    releases.append(("COMBINE", cursor, size))
                    cursor += isolated_cct_ns("COMBINE", size)
            elif fields and fields[0] == "EXPERT" and len(fields) >= 4:
                if "ALLGATHER" in fields[2]:
                    size = int(fields[-1])
                    releases.append(("DISPATCH", cursor, size))
                    cursor += isolated_cct_ns("DISPATCH", size)
        elif len(row) >= 10:
            try:
                duration = int(row[1])
            except (TypeError, ValueError):
                continue
            if row[0] == "expert":
                expert_rank_times.append(duration)
                if len(expert_rank_times) % 2 == 0:
                    # Two local EP ranks execute concurrently; the next combine
                    # becomes ready after the slower local expert operation.
                    cursor += max(expert_rank_times[-2:])
            else:
                cursor += duration
    if len(releases) != 2 * LAYERS:
        raise RuntimeError(f"Expected 96 EP phase releases, got {len(releases)}")
    return releases


def group_profile(group_requests, context, group_index):
    local_active = group_requests // 2
    first_instance = 4 + 2 * group_index
    # A DP group contains two TP2 instances, one per physical Decode server.
    member_traces = [
        extract(decode_trace(local_active, context, first_instance, 1 + 2 * group_index)),
        extract(decode_trace(local_active, context, first_instance + 1, 2 + 2 * group_index)),
    ]
    compute_ns = max(item[0] for item in member_traces)
    dispatch = [max(item[1][i] for item in member_traces) for i in range(LAYERS)]
    combine = [max(item[2][i] for item in member_traces) for i in range(LAYERS)]
    return compute_ns, dispatch, combine


def group_phase_profile(group_requests, context, group_index):
    local_active = group_requests // 2
    first_instance = 4 + 2 * group_index
    members = [
        phase_release_timeline(decode_trace(local_active, context, first_instance,
                                            1 + 2 * group_index)),
        phase_release_timeline(decode_trace(local_active, context, first_instance + 1,
                                            2 + 2 * group_index)),
    ]
    return [(kind, max(members[0][i][1], members[1][i][1]),
             max(members[0][i][2], members[1][i][2]))
            for i, kind in enumerate(x[0] for x in members[0])]


def interval_union(intervals):
    out = []
    for start, end in sorted(intervals):
        if not out or start > out[-1][1]:
            out.append([start, end])
        else:
            out[-1][1] = max(out[-1][1], end)
    return out


def union_intersection_ns(left, right):
    a, b = interval_union(left), interval_union(right)
    i = j = total = 0
    while i < len(a) and j < len(b):
        total += max(0, min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return total


def main():
    old_cwd = Path.cwd()
    os.chdir(ROOT / "astra-sim")  # trace generator resolves perf relative to this directory
    rows = []
    try:
        for group_requests in GROUP_REQUESTS:
            for context in CONTEXTS:
                # Context can differ across A/B in a later candidate. Using
                # group A's larger/local-profile result bounds its own token.
                comp_a, disp_a, comb_a = group_profile(group_requests, context, 0)
                comp_b, disp_b, comb_b = group_profile(group_requests, context, 1)
                # Bytes are expected to match for equal active-token batches.
                if disp_a != disp_b or comb_a != comb_b:
                    raise RuntimeError("Group identity changed model-derived AG/RS bytes")
                d_bytes = disp_a[0] * (RANKS_PER_SERVER ** 2)
                c_bytes = comb_a[0]
                if any(x != d_bytes // (RANKS_PER_SERVER ** 2) for x in disp_a):
                    raise RuntimeError("Dispatch bytes vary by layer unexpectedly")
                if any(x != c_bytes for x in comb_a):
                    raise RuntimeError("Combine bytes vary by layer unexpectedly")
                # The group has four EP ranks, two on each server. The actual
                # P2P expansion in the retained full run confirms four cross-
                # server messages in each direction: 4*AG participant bytes;
                # RS's per-rank buffer becomes one effective directional cut.
                per_phase_cut_bytes = [d_bytes, c_bytes]
                theoretical_gain_ns = (
                    LAYERS * sum(per_phase_cut_bytes) * 8.0 /
                    (LINK_GBPS * 1e9) * 1e9
                )
                avg_phase_bytes = sum(per_phase_cut_bytes) / 2.0
                isolated_ep_ns = sum(
                    isolated_cct_ns("DISPATCH", disp_a[i]) +
                    isolated_cct_ns("COMBINE", comb_a[i])
                    for i in range(LAYERS)
                )
                row = {
                    "group_active_requests": group_requests,
                    "requests_per_tp2_dp_member": group_requests // 2,
                    "context_tokens": context,
                    "ep_degree": 4,
                    "tp_per_member": 2,
                    "local_ep_per_member": 2,
                    "profiled_decode_n_per_member": group_requests // 2,
                    "profile_max_num_seqs": 256,
                    "profile_max_num_batched_tokens": 2048,
                    "prefill_context_compute_not_included": "TRUE",
                    "group_A_compute_only_lower_bound_ns": comp_a,
                    "group_B_compute_only_lower_bound_ns": comp_b,
                    "dispatch_comm_size_per_participant_bytes": disp_a[0],
                    "combine_comm_size_per_participant_bytes": comb_a[0],
                    "dispatch_effective_bytes_per_directed_cut_bytes": d_bytes,
                    "combine_effective_bytes_per_directed_cut_bytes": c_bytes,
                    "mean_effective_bytes_per_candidate_collective_phase": avg_phase_bytes,
                    "ideal_96_phase_contention_removal_upper_bound_ns": theoretical_gain_ns,
                    "profile_derived_isolated_EP_CCT_sum_ns": isolated_ep_ns,
                    "profile_compute_plus_isolated_EP_token_interval_estimate_ns": comp_a + isolated_ep_ns,
                    "ideal_gain_percent_of_group_A_compute_lower_bound": 100 * theoretical_gain_ns / comp_a,
                    "ideal_gain_percent_of_group_A_profile_token_interval_estimate": 100 * theoretical_gain_ns / (comp_a + isolated_ep_ns),
                    "ideal_gain_percent_of_group_B_profile_token_interval_estimate": 100 * theoretical_gain_ns / (comp_b + isolated_ep_ns),
                    "ideal_gain_percent_of_6ms_reference": 100 * theoretical_gain_ns / 6e6,
                    "required_mean_cut_bytes_per_phase_for_1pct_of_A_compute_lb": 0.01 * comp_a * LINK_GBPS * 1e9 / (96 * 8 * 1e9),
                    "required_mean_cut_bytes_per_phase_for_3pct_of_A_compute_lb": 0.03 * comp_a * LINK_GBPS * 1e9 / (96 * 8 * 1e9),
                    "required_mean_cut_bytes_per_phase_for_5pct_of_A_compute_lb": 0.05 * comp_a * LINK_GBPS * 1e9 / (96 * 8 * 1e9),
                    "required_mean_cut_bytes_per_phase_for_1pct_of_profile_token_interval": 0.01 * (comp_a + isolated_ep_ns) * LINK_GBPS / (96 * 8),
                    "required_mean_cut_bytes_per_phase_for_3pct_of_profile_token_interval": 0.03 * (comp_a + isolated_ep_ns) * LINK_GBPS / (96 * 8),
                    "required_mean_cut_bytes_per_phase_for_5pct_of_profile_token_interval": 0.05 * (comp_a + isolated_ep_ns) * LINK_GBPS / (96 * 8),
                    "assumed_phase_overlap_eta": 1.0,
                    "eta_status": "OPTIMISTIC_BOUND_ONLY; HETEROGENEOUS_CONTEXT_NOT_MEASURED",
                    "cct_model": "equal-size groups, exact simultaneous release, ideal 200Gbps cut, exclusive group service",
                    "evidence": "MODEL_PROFILE_DERIVED_THEORETICAL_NOT_SIMULATED",
                }
                rows.append(row)
    finally:
        os.chdir(old_cwd)
    fields = list(rows[0]) if rows else []
    out = OUT / "02_EP_BATCH_CAPACITY_TABLE.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # A/B urgency needs heterogeneous serving work. Build no-contention phase
    # timelines from the real profile while inserting the empirically anchored
    # isolated EP CCT at each barrier. Then count interval intersections across
    # all phase indices (not just same-index pairs). Per-phase saved wire time
    # is still an optimistic bound: it assumes every overlapping phase could
    # get exclusive cut service without moving downstream releases.
    old_cwd = Path.cwd()
    os.chdir(ROOT / "astra-sim")
    overlap_rows = []
    try:
        pairs = ((256, 512), (256, 2048), (256, 8192), (2048, 8192))
        for n in (8, 16, 32, 64):
            for context_a, context_b in pairs:
                rel_a = group_phase_profile(n, context_a, 0)
                rel_b = group_phase_profile(n, context_b, 1)
                if [x[0] for x in rel_a] != [x[0] for x in rel_b]:
                    raise RuntimeError("Group phase order differs")
                for window_us in (11, 16, 24):
                    service_a = [(item[1], item[1] + wire_service_ns(item[0], item[2]))
                                 for item in rel_a]
                    service_b = [(item[1], item[1] + wire_service_ns(item[0], item[2]))
                                 for item in rel_b]
                    overlapping_a = [i for i, (start, end) in enumerate(service_a)
                                     if any(start < bend and bstart < end
                                            for bstart, bend in service_b)]
                    overlapping_b = [j for j, (start, end) in enumerate(service_b)
                                     if any(start < aend and astart < end
                                            for astart, aend in service_a)]
                    # Event-level active intervals include the fitted startup
                    # component; the sensitivity window clips that modeled CCT.
                    barrier_a = [(x[1], x[1] + min(isolated_cct_ns(x[0], x[2]), window_us * 1000))
                                 for x in rel_a]
                    barrier_b = [(x[1], x[1] + min(isolated_cct_ns(x[0], x[2]), window_us * 1000))
                                 for x in rel_b]
                    barrier_active_overlap_ns = union_intersection_ns(barrier_a, barrier_b)
                    cut_service_overlap_ns = union_intersection_ns(service_a, service_b)
                    pair_count = sum(
                        1 for astart, aend in service_a
                        for bstart, bend in service_b
                        if astart < bend and bstart < aend
                    )
                    gain_a_ns = sum(wire_service_ns(rel_a[i][0], rel_a[i][2])
                                     for i in overlapping_a)
                    gain_b_ns = sum(wire_service_ns(rel_b[i][0], rel_b[i][2])
                                     for i in overlapping_b)
                    comp_a, _, _ = group_profile(n, context_a, 0)
                    comp_b, _, _ = group_profile(n, context_b, 1)
                    ep_a_ns = sum(isolated_cct_ns(x[0], x[2]) for x in rel_a)
                    ep_b_ns = sum(isolated_cct_ns(x[0], x[2]) for x in rel_b)
                    overlap_rows.append({
                        "group_active_requests_each": n,
                        "context_A_tokens": context_a,
                        "context_B_tokens": context_b,
                        "phase_release_window_us": window_us,
                        "candidate_phase_count": 96,
                        "profile_compute_release_overlap_phase_count": len(overlapping_a),
                        "profile_compute_release_overlap_fraction": len(overlapping_a) / 96,
                        "unique_B_phases_overlapped": len(overlapping_b),
                        "all_index_service_phase_pair_overlap_count": pair_count,
                        "barrier_active_interval_union_overlap_us": barrier_active_overlap_ns / 1000,
                        "cut_wire_service_interval_union_overlap_us": cut_service_overlap_ns / 1000,
                        "release_time_delta_min_us": min(abs(a[1] - b[1]) for a, b in zip(rel_a, rel_b)) / 1000,
                        "release_time_delta_median_us": sorted(abs(a[1] - b[1]) for a, b in zip(rel_a, rel_b))[47] / 1000,
                        "release_time_delta_max_us": max(abs(a[1] - b[1]) for a, b in zip(rel_a, rel_b)) / 1000,
                        "compute_only_lower_bound_A_ms": comp_a / 1e6,
                        "compute_only_lower_bound_B_ms": comp_b / 1e6,
                        "profile_token_baseline_A_ns": comp_a + ep_a_ns,
                        "profile_token_baseline_B_ns": comp_b + ep_b_ns,
                        "A_contention_removal_optimistic_serialization_bound_us": gain_a_ns / 1000,
                        "B_contention_removal_optimistic_serialization_bound_us": gain_b_ns / 1000,
                        "A_gain_pct_profile_token_baseline": 100 * gain_a_ns / (comp_a + ep_a_ns),
                        "B_gain_pct_profile_token_baseline": 100 * gain_b_ns / (comp_b + ep_b_ns),
                        "assumed_isolated_CCT_ns": "10200ns startup + effective directed-cut bytes/200Gbps",
                        "interpretation": "profile-derived release and cut-service overlap proxy; no network feedback/scheduler replay; each overlapping phase charged its full wire serialization as optimistic removable delay",
                    })
    finally:
        os.chdir(old_cwd)
    overlap_out = OUT / "02_EP_CONTEXT_PHASE_OVERLAP.csv"
    overlap_fields = list(overlap_rows[0]) if overlap_rows else []
    with overlap_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=overlap_fields)
        writer.writeheader()
        writer.writerows(overlap_rows)

    # Screen the small, profile-supported cross-product of independent group
    # batch/context points. This is still theory-only: it selects no winner and
    # launches no serving or network simulation.
    pair_rows = []
    old_cwd = Path.cwd()
    os.chdir(ROOT / "astra-sim")
    try:
        points = [(n, context) for n in (8, 16, 32, 64)
                  for context in CONTEXTS]
        cache = {}
        for n, context in points:
            releases = group_phase_profile(n, context, 0)
            compute_ns, _, _ = group_profile(n, context, 0)
            baseline_ns = compute_ns + sum(
                isolated_cct_ns(kind, size) for kind, _, size in releases)
            cache[(n, context)] = (releases, compute_ns, baseline_ns)
        for n_a, ctx_a in points:
            rel_a, comp_a, base_a = cache[(n_a, ctx_a)]
            service_a = [(item[1], item[1] + wire_service_ns(item[0], item[2]))
                         for item in rel_a]
            for n_b, ctx_b in points:
                if (n_a, ctx_a) == (n_b, ctx_b):
                    continue
                rel_b, comp_b, base_b = cache[(n_b, ctx_b)]
                service_b = [(item[1], item[1] + wire_service_ns(item[0], item[2]))
                             for item in rel_b]
                a_affected = [i for i, (start, end) in enumerate(service_a)
                              if any(start < bend and bstart < end
                                     for bstart, bend in service_b)]
                b_affected = [j for j, (start, end) in enumerate(service_b)
                              if any(start < aend and astart < end
                                     for astart, aend in service_a)]
                a_upper_ns = sum(wire_service_ns(rel_a[i][0], rel_a[i][2])
                                 for i in a_affected)
                b_upper_ns = sum(wire_service_ns(rel_b[i][0], rel_b[i][2])
                                 for i in b_affected)
                pair_rows.append({
                    "group_A_active_requests": n_a,
                    "group_A_context_tokens": ctx_a,
                    "group_B_active_requests": n_b,
                    "group_B_context_tokens": ctx_b,
                    "A_model_compute_lower_bound_ms": comp_a / 1e6,
                    "B_model_compute_lower_bound_ms": comp_b / 1e6,
                    "A_profile_isolated_token_interval_ms": base_a / 1e6,
                    "B_profile_isolated_token_interval_ms": base_b / 1e6,
                    "A_phases_intersecting_B_cut_service": len(a_affected),
                    "B_phases_intersecting_A_cut_service": len(b_affected),
                    "A_priority_optimistic_removable_wire_time_us": a_upper_ns / 1000,
                    "B_priority_optimistic_removable_wire_time_us": b_upper_ns / 1000,
                    "A_optimistic_gain_pct": 100 * a_upper_ns / base_a,
                    "B_optimistic_gain_pct": 100 * b_upper_ns / base_b,
                    "evidence": "PROFILE_RELEASE_TIMELINE_AND_200G_SERIALIZATION_UPPER_BOUND_NOT_SIMULATED",
                })
    finally:
        os.chdir(old_cwd)
    pair_out = OUT / "02_EP_HETEROGENEOUS_GROUP_SCREEN.csv"
    pair_fields = list(pair_rows[0]) if pair_rows else []
    with pair_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=pair_fields)
        writer.writeheader()
        writer.writerows(pair_rows)
    print(f"wrote {len(rows)} profile-derived capacity rows, "
          f"{len(overlap_rows)} context-pair overlap bounds, and "
          f"{len(pair_rows)} heterogeneous group-pair screens")


if __name__ == "__main__":
    main()
