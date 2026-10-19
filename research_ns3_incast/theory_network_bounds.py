#!/usr/bin/env python3
"""Independent single-cut fluid bounds for the fixed receiver-incast cases."""

import json


def equal_share_fair_completion(sizes_bytes, release_seconds, capacity_Bps):
    """Event-driven max-min fluid sharing on one work-conserving cut."""
    jobs = [{"remaining": float(size), "release": float(release), "done": None}
            for size, release in zip(sizes_bytes, release_seconds)]
    now = 0.0
    while any(job["done"] is None for job in jobs):
        active = [job for job in jobs if job["done"] is None and job["release"] <= now]
        if not active:
            now = min(job["release"] for job in jobs if job["done"] is None)
            active = [job for job in jobs if job["done"] is None and job["release"] <= now]
        next_release = min((job["release"] for job in jobs if job["done"] is None
                            and job["release"] > now), default=float("inf"))
        next_finish = min(job["remaining"] * len(active) / capacity_Bps
                          for job in active)
        elapsed = min(next_finish, next_release - now)
        for job in active:
            job["remaining"] -= capacity_Bps * elapsed / len(active)
        now += elapsed
        for job in active:
            if job["remaining"] <= 1e-7:
                job["remaining"] = 0.0
                job["done"] = now
    return [job["done"] for job in jobs]


def main():
    payload_bytes = 201_326_592
    capacity_Bps = 200e9 / 8
    count = 4
    solo_s = payload_bytes / capacity_Bps
    fair = equal_share_fair_completion([payload_bytes] * count, [0.0] * count,
                                       capacity_Bps)
    ordered = [solo_s * (index + 1) for index in range(count)]
    packet_full_mean_ms = 32.4813095
    packet_order_mean_ms = 20.451317
    profile_prefill_end_ms = 135.319248
    packet_layerwise_ready_ms = 134.059112
    result = {
        "method": "independent event-driven single-cut max-min fluid model",
        "bytes_per_tp2_shard": payload_bytes,
        "one_receiver_nic_capacity_Gbps": 200,
        "single_shard_serialization_lower_bound_ms": solo_s * 1e3,
        "simultaneous_fair": {
            "completion_ms": [value * 1e3 for value in fair],
            "mean_ready_ms": sum(fair) / count * 1e3,
            "makespan_ms": max(fair) * 1e3,
        },
        "request_ordered_one_at_a_time_oracle": {
            "completion_ms": [value * 1e3 for value in ordered],
            "mean_ready_ms": sum(ordered) / count * 1e3,
            "makespan_ms": max(ordered) * 1e3,
            "mean_improvement_vs_fair_percent":
                (1 - sum(ordered) / sum(fair)) * 100,
        },
        "packet_fixed_replay": {
            "fair_mean_ready_ms": packet_full_mean_ms,
            "order_8p2ms_mean_ready_ms": packet_order_mean_ms,
            "mean_ready_improvement_percent":
                (1 - packet_order_mean_ms / packet_full_mean_ms) * 100,
            "fair_makespan_ms": 32.481557,
            "order_makespan_ms": 32.751317,
            "makespan_change_percent":
                (32.751317 / 32.481557 - 1) * 100,
            "scope": "network-only; fixed issue ledger; not serving feedback",
        },
        "profiled_layerwise_exposure_bound": {
            "profiled_prefill_compute_end_ms": profile_prefill_end_ms,
            "packet_p2d_ready_max_ms": packet_layerwise_ready_ms,
            "compute_slack_after_network_ready_ms":
                profile_prefill_end_ms - packet_layerwise_ready_ms,
            "network_exposed_decode_admission_delay_ms": max(
                0.0, packet_layerwise_ready_ms - profile_prefill_end_ms),
            "scope": "CC_MODE=0 frozen profile release; excludes runtime feedback",
        },
        "assumptions": [
            "Each request has one 192-MiB TP2 shard per 200-Gbps receiver rail.",
            "Two rails are independent; each rail is solved as one shared directed cut.",
            "No propagation, packet headers, ACK, QP startup, ECN/CNP, or PFC in fluid bounds.",
            "The ordered oracle changes network release/serialization only; it is not an implemented serving policy.",
        ],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
