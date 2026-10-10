#!/usr/bin/env python3
"""Pre-analyse bounded production traces using model-derived KV/EP demand.

This stage deliberately does not run LLMServingSim or invent completion times.
It maps each converted request to model-derived communication demand at its
source arrival timestamp, then selects candidate windows for an expensive
serving/network replay.  ``kv_ep_coarrival`` therefore means offered-demand
co-arrival, not proof of packet-level overlap; packet-level overlap is only
claimed from native network telemetry.
"""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
SCALE_MANIFESTS = {
    "S64": ROOT / "experiments/pd_kv_ep/configs/large_scale/s64_64_servers_manifest.json",
    "S256": ROOT / "experiments/pd_kv_ep/configs/large_scale/s256_256_servers_manifest.json",
}


def _read_rows(path, offset, limit):
    if offset < 0 or limit <= 0 or limit > 25000:
        raise ValueError("require 0 <= offset and 1 <= limit <= 25,000")
    rows = []
    with path.open(encoding="utf-8") as stream:
        previous = None
        for index, line in enumerate(stream):
            if index < offset:
                continue
            row = json.loads(line)
            timestamp = int(row["arrival_time_ns"])
            if previous is not None and timestamp < previous:
                raise ValueError(f"arrival order decreases at source row {index}")
            previous = timestamp
            rows.append(row)
            if len(rows) >= limit:
                break
    if not rows:
        raise ValueError(f"no rows selected from {path}")
    return rows


def _percentile(values, fraction):
    if not values:
        return 0
    values = sorted(values)
    position = (len(values) - 1) * fraction
    left = math.floor(position)
    right = math.ceil(position)
    if left == right:
        return values[left]
    return values[left] + (values[right] - values[left]) * (position - left)


def _model_terms(model, ep_degree):
    hidden = int(model["hidden_size"])
    heads = int(model["num_attention_heads"])
    kv_heads = int(model.get("num_key_value_heads", heads))
    head_dim = int(model.get("head_dim", hidden // heads))
    layers = int(model["num_hidden_layers"])
    top_k = int(model.get("num_experts_per_tok", 1))
    weight_dtype = str(model.get("torch_dtype", "bfloat16"))
    fp_bytes = 2 if weight_dtype in {"float16", "bfloat16"} else 4
    kv_bytes_per_token = layers * 2 * kv_heads * head_dim * fp_bytes
    # A balanced EP=degree wave sends each routed token to a remote owner with
    # probability (degree-1)/degree. Dispatch and combine are both counted.
    ep_bytes_per_output_token = (
        layers * top_k * hidden * fp_bytes * 2 * (ep_degree - 1) / ep_degree)
    return {
        "layers": layers,
        "hidden_size": hidden,
        "kv_heads": kv_heads,
        "head_dim": head_dim,
        "top_k": top_k,
        "fp_bytes": fp_bytes,
        "kv_bytes_per_input_token": kv_bytes_per_token,
        "ep_bytes_per_output_token_balanced_dispatch_plus_combine": ep_bytes_per_output_token,
        "ep_collectives_per_output_token": layers,
        "ep_degree": ep_degree,
    }


def _bin_rows(rows, bin_ns, terms):
    buckets = {}
    for row in rows:
        timestamp = int(row["arrival_time_ns"])
        bucket_id = timestamp // bin_ns
        bucket = buckets.setdefault(bucket_id, {
            "bin_id": bucket_id,
            "bin_start_ns": bucket_id * bin_ns,
            "bin_end_ns": (bucket_id + 1) * bin_ns,
            "arrival_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "kv_request_count": 0,
            "ep_request_count": 0,
            "kv_bytes": 0,
            "ep_bytes": 0.0,
            "ep_collectives": 0,
            "decode_eligible_arrivals": 0,
        })
        input_tokens = int(row["input_toks"])
        output_tokens = int(row["output_toks"])
        kv_bytes = input_tokens * terms["kv_bytes_per_input_token"]
        ep_bytes = output_tokens * terms[
            "ep_bytes_per_output_token_balanced_dispatch_plus_combine"]
        bucket["arrival_count"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["kv_request_count"] += 1 if input_tokens > 0 else 0
        bucket["ep_request_count"] += 1 if output_tokens > 0 else 0
        bucket["kv_bytes"] += kv_bytes
        bucket["ep_bytes"] += ep_bytes
        bucket["ep_collectives"] += output_tokens * terms["layers"]
        bucket["decode_eligible_arrivals"] += 1 if output_tokens > 0 else 0
    duration_s = bin_ns / 1e9
    for bucket in buckets.values():
        bucket["kv_gbps_offered"] = bucket["kv_bytes"] * 8 / duration_s / 1e9
        bucket["ep_gbps_offered"] = bucket["ep_bytes"] * 8 / duration_s / 1e9
        bucket["mixed_offered_demand"] = bool(
            bucket["kv_bytes"] > 0 and bucket["ep_bytes"] > 0)
        bucket["total_offered_gbps"] = (
            bucket["kv_gbps_offered"] + bucket["ep_gbps_offered"])
    return [buckets[key] for key in sorted(buckets)]


def _window_rows(rows, duration_ns, terms):
    buckets = {}
    for row in rows:
        timestamp = int(row["arrival_time_ns"])
        window_id = timestamp // duration_ns
        bucket = buckets.setdefault(window_id, {
            "window_id": window_id,
            "window_start_ns": window_id * duration_ns,
            "window_end_ns": (window_id + 1) * duration_ns,
            "request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "kv_bytes": 0,
            "ep_bytes": 0.0,
            "ep_collectives": 0,
            "max_input_tokens": 0,
            "max_output_tokens": 0,
        })
        input_tokens = int(row["input_toks"])
        output_tokens = int(row["output_toks"])
        bucket["request_count"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["kv_bytes"] += input_tokens * terms["kv_bytes_per_input_token"]
        bucket["ep_bytes"] += output_tokens * terms[
            "ep_bytes_per_output_token_balanced_dispatch_plus_combine"]
        bucket["ep_collectives"] += output_tokens * terms["layers"]
        bucket["max_input_tokens"] = max(bucket["max_input_tokens"], input_tokens)
        bucket["max_output_tokens"] = max(bucket["max_output_tokens"], output_tokens)
    duration_s = duration_ns / 1e9
    result = []
    for bucket in buckets.values():
        bucket["rps"] = bucket["request_count"] / duration_s
        bucket["kv_gbps_offered"] = bucket["kv_bytes"] * 8 / duration_s / 1e9
        bucket["ep_gbps_offered"] = bucket["ep_bytes"] * 8 / duration_s / 1e9
        bucket["total_offered_gbps"] = (
            bucket["kv_gbps_offered"] + bucket["ep_gbps_offered"])
        bucket["mixed_demand_score"] = min(
            bucket["kv_gbps_offered"], bucket["ep_gbps_offered"])
        bucket["kv_ep_coarrival"] = bool(
            bucket["kv_bytes"] > 0 and bucket["ep_bytes"] > 0)
        result.append(bucket)
    return sorted(result, key=lambda item: (-item["mixed_demand_score"], item["window_id"]))


def _write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot(path_prefix, bins, label):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    if not bins:
        return False
    x = [row["bin_start_ns"] / 1e9 for row in bins]
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    axes[0].plot(x, [row["kv_gbps_offered"] for row in bins], label="KV movement")
    axes[0].plot(x, [row["ep_gbps_offered"] for row in bins], label="Decode EP")
    axes[0].set_ylabel("offered Gbps")
    axes[0].legend(loc="upper right")
    axes[0].set_title(f"{label}: model-derived offered demand (not packet overlap)")
    axes[1].bar(x, [row["arrival_count"] for row in bins], width=0.8,
                label="request arrivals")
    axes[1].set_ylabel("requests/bin")
    axes[1].set_xlabel("trace-relative time (s)")
    axes[1].legend(loc="upper right")
    fig.tight_layout()
    path_prefix.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path_prefix.with_suffix(".png"), dpi=160)
    fig.savefig(path_prefix.with_suffix(".pdf"))
    plt.close(fig)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--scale", choices=tuple(SCALE_MANIFESTS), default="S64")
    parser.add_argument("--num-reqs", type=int, required=True)
    parser.add_argument("--request-offset", type=int, default=0)
    parser.add_argument("--bin-ms", type=int, default=1000)
    parser.add_argument("--model-config", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    if args.bin_ms <= 0 or args.top_k <= 0:
        parser.error("--bin-ms and --top-k must be positive")
    trace = args.trace.resolve()
    rows = _read_rows(trace, args.request_offset, args.num_reqs)
    with args.model_config.open(encoding="utf-8") as stream:
        model = json.load(stream)
    with SCALE_MANIFESTS[args.scale].open(encoding="utf-8") as stream:
        scale_manifest = json.load(stream)
    terms = _model_terms(model, int(scale_manifest["decode_ep_degree"]))
    bin_rows = _bin_rows(rows, args.bin_ms * 1_000_000, terms)
    request_rows = []
    for row in rows:
        input_tokens = int(row["input_toks"])
        output_tokens = int(row["output_toks"])
        request_rows.append({
            "request_id": row.get("request_id", ""),
            "source_request_id": row.get("source_request_id", ""),
            "session_id": row.get("session_id", ""),
            "arrival_time_ns": int(row["arrival_time_ns"]),
            "input_toks": input_tokens,
            "output_toks": output_tokens,
            "kv_bytes_model_derived": input_tokens * terms["kv_bytes_per_input_token"],
            "ep_bytes_model_derived_balanced": output_tokens * terms[
                "ep_bytes_per_output_token_balanced_dispatch_plus_combine"],
            "ep_collectives_model_derived": output_tokens * terms["layers"],
            "source_trace": row.get("source_trace", ""),
            "source_record_index": row.get("source_record_index", ""),
        })
    windows = []
    for duration_s in (30, 60, 300):
        selected = _window_rows(rows, duration_s * 1_000_000_000, terms)
        for rank, item in enumerate(selected[:args.top_k], 1):
            item = dict(item)
            item["window_duration_s"] = duration_s
            item["candidate_rank"] = rank
            item["candidate_selection"] = "max_min_kv_ep_offered_gbps"
            windows.append(item)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output_dir / "request_demand.csv", request_rows)
    _write_csv(args.output_dir / f"bins_{args.bin_ms}ms.csv", bin_rows)
    _write_csv(args.output_dir / "candidate_windows.csv", windows)
    input_values = [int(row["input_toks"]) for row in rows]
    output_values = [int(row["output_toks"]) for row in rows]
    timestamps = [int(row["arrival_time_ns"]) for row in rows]
    duration_ns = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 0
    mixed_bins = sum(1 for row in bin_rows if row["mixed_offered_demand"])
    summary = {
        "label": args.label,
        "trace": str(trace),
        "scale": args.scale,
        "request_offset": args.request_offset,
        "request_count": len(rows),
        "duration_ns": duration_ns,
        "mean_rps": len(rows) / max(duration_ns / 1e9, 1e-9),
        "input_tokens": sum(input_values),
        "output_tokens": sum(output_values),
        "input_p50": _percentile(input_values, 0.50),
        "input_p95": _percentile(input_values, 0.95),
        "output_p50": _percentile(output_values, 0.50),
        "output_p95": _percentile(output_values, 0.95),
        "kv_bytes_model_derived": sum(row["kv_bytes_model_derived"] for row in request_rows),
        "ep_bytes_model_derived_balanced": sum(
            row["ep_bytes_model_derived_balanced"] for row in request_rows),
        "ep_collectives_model_derived": sum(
            row["ep_collectives_model_derived"] for row in request_rows),
        "bin_ms": args.bin_ms,
        "offered_demand_mixed_bin_count": mixed_bins,
        "offered_demand_mixed_bin_fraction": mixed_bins / max(len(bin_rows), 1),
        "model": str(model.get("architectures", ["unknown"])[0]),
        "model_terms": terms,
        "topology_manifest": str(SCALE_MANIFESTS[args.scale].resolve()),
        "synthetic_override": False,
        "timing_status": "arrival_offered_demand_only",
        "network_overlap_claim": "none; validate selected windows with native network telemetry",
        "source_trace_provenance": sorted({row.get("source_trace", "") for row in rows}),
        "artifacts": {
            "request_demand": str(args.output_dir / "request_demand.csv"),
            "bins": str(args.output_dir / f"bins_{args.bin_ms}ms.csv"),
            "candidate_windows": str(args.output_dir / "candidate_windows.csv"),
        },
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    _plot(args.output_dir / "traffic_demand", bin_rows, args.label)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
