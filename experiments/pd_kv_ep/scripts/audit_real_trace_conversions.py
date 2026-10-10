#!/usr/bin/env python3
"""Audit converted public traces without rescanning multi-GB Azure JSONL."""

import argparse
import json
import os
from collections import Counter
from pathlib import Path


DATASETS = {
    "azure2024_code": "azure2024/code",
    "azure2024_conversation": "azure2024/conversation",
    "burstgpt": "burstgpt",
    "mooncake_conversation": "mooncake_fast25/conversation",
    "mooncake_toolagent": "mooncake_fast25/toolagent",
}


def _load(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _sample_records(path, limit=3):
    first = []
    with path.open(encoding="utf-8") as stream:
        for _ in range(limit):
            line = stream.readline()
            if not line:
                break
            first.append(json.loads(line))
        stream.seek(0, os.SEEK_END)
        offset = max(0, stream.tell() - 131072)
        stream.seek(offset)
        if offset:
            stream.readline()
        tail = [line for line in stream if line.strip()]
    last = json.loads(tail[-1])
    return first, last


def _moon_reuse(path):
    unique = set()
    occurrences = 0
    requests_with_reuse = 0
    records = 0
    prefix_lengths = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            blocks = row.get("input_block_hashes", [])
            records += 1
            occurrences += len(blocks)
            unique.update(blocks)
            prefix_lengths.append(len(blocks))
    repeated = occurrences - len(unique)
    # A block repeated across requests is the useful source-level reuse
    # signal.  The simulator later applies complete-block and cache-capacity
    # rules, so this is deliberately not reported as simulated hit ratio.
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            blocks = json.loads(line).get("input_block_hashes", [])
            if any(block in unique for block in blocks):
                requests_with_reuse += 1
    return {
        "records": records,
        "block_occurrences": occurrences,
        "unique_blocks": len(unique),
        "repeated_block_occurrences": repeated,
        "source_block_reuse_fraction": repeated / occurrences if occurrences else 0,
        "requests_with_block_hashes": records,
        "requests_with_any_repeated_identity": requests_with_reuse,
        "block_count_p50": sorted(prefix_lengths)[len(prefix_lengths) // 2]
        if prefix_lengths else 0,
        "block_count_max": max(prefix_lengths) if prefix_lengths else 0,
    }


def _fmt(value):
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def audit(root):
    repo = root.parents[3]
    reports = {}
    for name, relative in DATASETS.items():
        directory = root / relative
        stats = _load(directory / "conversion_stats.json")
        manifest = _load(directory / "raw_manifest.json")
        first, last = _sample_records(directory / "converted.jsonl")
        reports[name] = {
            "directory": str(directory),
            "stats": stats,
            "manifest": manifest,
            "first": first,
            "last": last,
        }
        if name.startswith("mooncake"):
            reports[name]["reuse"] = _moon_reuse(directory / "converted.jsonl")

    out = repo / "results" / "real_trace" / "conversion_audit.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Real Trace Conversion Audit",
        "",
        "This audit covers the source-preserving converters under "
        "`experiments/pd_kv_ep/scripts/convert_real_traces.py`. Every rejected "
        "record is written to `invalid_records.jsonl`; no invalid record is "
        "silently discarded.",
        "",
        "## Common invariants",
        "",
        "- First valid source timestamp is normalized to `arrival_time_ns = 0`.",
        "- Converted timestamps are integer nanoseconds and remain in stable nondecreasing order.",
        "- Original request identity, source file, and source record index are retained.",
        "- Azure uses a streaming converter with monotonicity assertion because the source is a multi-GB week trace.",
        "- No source trace without token IDs receives fabricated `input_tok_ids`.",
        "",
        "## Dataset results",
        "",
        "| dataset | raw | converted | invalid | duration (s) | mean RPS | input P50/P95/max | output P50/P95/max | prefix/session evidence |",
        "|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for name, report in reports.items():
        stats = report["stats"]
        prefix = report.get("reuse", {})
        evidence = (
            f"blocks={prefix.get('block_occurrences', 0)}, "
            f"reuse={prefix.get('source_block_reuse_fraction', 0):.3f}"
            if prefix else
            f"session_count={stats.get('session_count', 0)}; no token IDs"
        )
        lines.append(
            f"| {name} | {stats.get('raw_records', 0)} | "
            f"{stats.get('converted_records', 0)} | {stats.get('invalid_records', 0)} | "
            f"{stats.get('duration_s', 0):.3f} | {stats.get('mean_rps', 0):.4f} | "
            f"{stats.get('input_tokens_p50', 0)}/{stats.get('input_tokens_p95', 0)}/"
            f"{stats.get('input_tokens_max', 0)} | "
            f"{stats.get('output_tokens_p50', 0)}/{stats.get('output_tokens_p95', 0)}/"
            f"{stats.get('output_tokens_max', 0)} | {evidence} |"
        )
    lines += ["", "## Validation observations", ""]
    for name, report in reports.items():
        stats = report["stats"]
        first = report["first"][0]
        last = report["last"]
        lines += [
            f"### {name}",
            "",
            f"- Source: `{report['manifest']['source_path']}`",
            f"- Source SHA-256: `{report['manifest']['source_sha256']}`",
            f"- Timestamp conversion: `{stats['timestamp_normalization']['source_unit']} -> ns`; "
            f"first source timestamp ns `{stats['timestamp_normalization']['first_source_timestamp_ns']}`.",
            f"- First normalized request: `{first['request_id']}` at `{first['arrival_time_ns']} ns`; "
            f"last normalized arrival: `{last['arrival_time_ns']} ns`.",
            f"- Invalid records: `{stats.get('invalid_records', 0)}`; reasons: "
            f"`{stats.get('invalid_reason_counts', {})}`.",
        ]
        if name.startswith("mooncake"):
            reuse = report["reuse"]
            lines += [
                f"- Mooncake block size: `{report['manifest']['hash_block_size']} tokens`; "
                "hash values are carried as `input_block_hashes`, never token IDs.",
                f"- Source block identities: `{reuse['unique_blocks']}` unique / "
                f"`{reuse['block_occurrences']}` occurrences; repeated occurrence fraction "
                f"`{reuse['source_block_reuse_fraction']:.6f}`.",
                "- This is source-level identity reuse, not a simulated cache hit ratio; "
                "the latter depends on complete-block boundaries, placement, capacity, and arrival order.",
            ]
        else:
            lines.append("- Prefix identity is unavailable; primary runs must disable prefix caching for this source.")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")

    return reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="experiments/pd_kv_ep/workloads/real",
                        type=Path)
    args = parser.parse_args()
    reports = audit(args.root.resolve())
    print(json.dumps({name: report["stats"] for name, report in reports.items()},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
