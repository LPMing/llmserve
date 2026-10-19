#!/usr/bin/env python3
"""Screen observed sibling groups against a model-mapped KV copy budget."""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GROUPS = ROOT / "research_autonomous/workloads/freeinference_analysis/fork_groups.csv"
MODEL = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
OUTPUT = Path(__file__).resolve().parent / "agent_fork_screen"
LINK_BYTES_PER_SECOND = 200e9 / 8
PROFILE_CONTEXT_LIMIT = 16384


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def main():
    model = json.loads(MODEL.read_text())
    kv_bytes_per_token = (model["num_hidden_layers"] * 2 *
                          model["num_key_value_heads"] * model["head_dim"] * 2)
    with GROUPS.open(newline="") as handle:
        groups = list(csv.DictReader(handle))
    rows = []
    for group in groups:
        width = int(group["width"])
        shared_tokens = int(group["shared_prefix_tokens_lower_bound"])
        observed_span_ms = int(group["group_span_ms"])
        duplicate_bytes = (width - 1) * shared_tokens * kv_bytes_per_token
        serial_copy_ms = duplicate_bytes / LINK_BYTES_PER_SECOND * 1000
        first_ttft_min = (float(group["first_child_ttft_min_ms"])
                          if group.get("first_child_ttft_min_ms") else None)
        rows.append({
            "parent_session_id": group["parent_session_id"],
            "week": group["week"],
            "width": width,
            "shared_prefix_tokens_lower_bound": shared_tokens,
            "first_child_prompt_max": int(group["first_child_prompt_max"]),
            "first_child_within_attention_context_profile": (
                int(group["first_child_prompt_max"]) <= PROFILE_CONTEXT_LIMIT),
            "group_span_ms_observed_other_provider": observed_span_ms,
            "duplicate_kv_bytes_qwen_proxy": duplicate_bytes,
            "serial_copy_ms_200gbps_qwen_proxy": serial_copy_ms,
            "copy_ms_over_other_provider_span": (
                serial_copy_ms / observed_span_ms if observed_span_ms else None),
            "first_child_ttft_min_ms_observed_other_provider": first_ttft_min,
            "copy_ms_over_fastest_child_ttft": (
                serial_copy_ms / first_ttft_min if first_ttft_min else None),
            "parent_join_lag_ms": group["parent_join_lag_ms"],
        })
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / "groups.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    copy_ms = [row["serial_copy_ms_200gbps_qwen_proxy"] for row in rows]
    fractions = [row["copy_ms_over_other_provider_span"] for row in rows]
    ttft_fractions = [row["copy_ms_over_fastest_child_ttft"]
                      for row in rows if row["copy_ms_over_fastest_child_ttft"]
                      is not None]
    summary = {
        "assumption": ("One 200-Gbps source cut, BF16 Qwen3-30B-A3B KV, "
                       "all width-1 avoidable copies serialize on that cut. "
                       "Observed group spans belong to different provider "
                       "models; their ratio is a cross-model screening "
                       "diagnostic, not a causal upper bound on Qwen JCT."),
        "group_count": len(rows),
        "kv_bytes_per_token_all_layers": kv_bytes_per_token,
        "profile_context_limit_tokens": PROFILE_CONTEXT_LIMIT,
        "first_child_within_attention_context_profile": sum(
            row["first_child_within_attention_context_profile"] for row in rows),
        "first_child_within_2048_tokens": sum(
            row["first_child_prompt_max"] <= 2048 for row in rows),
        "serial_copy_ms_p50_p95_max": [quantile(copy_ms, fraction)
                                       for fraction in (0.5, 0.95, 1.0)],
        "copy_to_observed_span_p50_p95_max": [
            quantile(fractions, fraction) for fraction in (0.5, 0.95, 1.0)],
        "groups_ratio_ge_1pct": sum(value >= 0.01 for value in fractions),
        "groups_ratio_ge_10pct": sum(value >= 0.10 for value in fractions),
        "groups_with_first_child_ttft": len(ttft_fractions),
        "copy_to_fastest_child_ttft_p50_p95_max": [
            quantile(ttft_fractions, fraction)
            for fraction in (0.5, 0.95, 1.0)],
        "groups_ttft_ratio_ge_10pct": sum(
            value >= 0.10 for value in ttft_fractions),
        "groups_with_parent_next_request": sum(
            row["parent_join_lag_ms"] != "" for row in rows),
        "groups_with_negative_parent_lag": sum(
            row["parent_join_lag_ms"] != "" and
            int(row["parent_join_lag_ms"]) < 0 for row in rows),
    }
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
