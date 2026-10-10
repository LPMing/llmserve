#!/usr/bin/env python3
"""Compare FAIR, EP_FIRST, and KV_FIRST native replay policies."""

import argparse
import csv
import json
from pathlib import Path


def _load(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _p99(summary, field):
    value = summary.get(field, {}).get("p99")
    return None if value is None else float(value) / 1e6


def _ratio(value, base):
    return None if value is None or base in (None, 0) else value / base


def _case_rows(label, fair_path, ep_first_path, kv_first_path,
               kv_only_path, ep_only_path):
    summaries = {
        "FAIR": _load(fair_path),
        "EP_FIRST": _load(ep_first_path),
        "KV_FIRST": _load(kv_first_path),
        "KV_ONLY": _load(kv_only_path),
        "EP_ONLY": _load(ep_only_path),
    }
    ep_base = _p99(summaries["EP_ONLY"], "ep_collective_cct_ns")
    kv_base = _p99(summaries["KV_ONLY"], "kv_request_completion_ns")
    fair_ep = _p99(summaries["FAIR"], "ep_collective_cct_ns")
    fair_kv = _p99(summaries["FAIR"], "kv_request_completion_ns")
    rows = []
    for policy in ("FAIR", "EP_FIRST", "KV_FIRST"):
        summary = summaries[policy]
        ep = _p99(summary, "ep_collective_cct_ns")
        kv = _p99(summary, "kv_request_completion_ns")
        rows.append({
            "case": label,
            "policy": policy,
            "packet_payload_size": summary.get("packet_payload_size"),
            "request_count": summary.get("request_count"),
            "ep_p99_ms": ep,
            "ep_ratio_vs_ep_only": _ratio(ep, ep_base),
            "ep_slowdown_vs_fair_pct": None if ep is None or fair_ep is None else (ep / fair_ep - 1.0) * 100.0,
            "kv_p99_ms": kv,
            "kv_ratio_vs_kv_only": _ratio(kv, kv_base),
            "kv_slowdown_vs_fair_pct": None if kv is None or fair_kv is None else (kv / fair_kv - 1.0) * 100.0,
            "overlap_pairs": summary.get("directed_link_overlap", {}).get("pair_count"),
            "overlap_links": summary.get("directed_link_overlap", {}).get("link_count"),
            "completion_coverage": summary.get("completion_coverage"),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", nargs=6,
                        metavar=("LABEL", "FAIR", "EP_FIRST", "KV_FIRST", "KV_ONLY", "EP_ONLY"),
                        required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = []
    for label, fair, ep_first, kv_first, kv_only, ep_only in args.case:
        rows.extend(_case_rows(label, Path(fair), Path(ep_first), Path(kv_first),
                               Path(kv_only), Path(ep_only)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with args.output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    args.output.with_suffix(".json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Native KV/EP policy comparison",
        "",
        "The rows use identical trace slices and native completed-flow counters.",
        "EP CCT is collective-level P99; KV is request-level completion P99.",
        "",
        "| case | policy | EP P99 (ms) | EP / EP_ONLY | KV P99 (ms) | KV / KV_ONLY | overlap | coverage |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['policy']} | {row['ep_p99_ms']:.6f} | "
            f"{row['ep_ratio_vs_ep_only']:.6f} | {row['kv_p99_ms']:.6f} | "
            f"{row['kv_ratio_vs_kv_only']:.6f} | {row['overlap_pairs']} pairs / "
            f"{row['overlap_links']} links | {row['completion_coverage']:.3f} |"
        )
    args.output.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "csv": str(args.output.with_suffix('.csv'))}, indent=2))


if __name__ == "__main__":
    main()
