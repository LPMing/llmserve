#!/usr/bin/env python3
"""Replay an unmodified real-trace prefix under matched FlowSim policies.

The selected records retain the original trace timestamps and token counts.
This runner is intentionally separate from the synchronized mechanism runner.
"""

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = Path(
    "experiments/pd_kv_ep/configs/large_scale/"
    "s16_8p8d_ep64_shared_2nic_qwen.json")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_prefix(path, limit):
    rows = []
    raw = bytearray()
    with path.open("rb") as stream:
        for line in stream:
            if not line.strip():
                continue
            raw.extend(line)
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    if not rows:
        raise ValueError("workload has no non-empty JSONL records")
    arrivals = [int(row["arrival_time_ns"]) for row in rows]
    if arrivals != sorted(arrivals):
        raise ValueError("selected workload records are not time ordered")
    return rows, bytes(raw)


def stats(values):
    values = sorted(float(value) for value in values
                    if value is not None and math.isfinite(float(value)))
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None,
                "p99": None, "max": None}

    def nearest(q):
        return values[max(0, math.ceil(q * len(values)) - 1)]

    return {"count": len(values), "mean": sum(values) / len(values),
            "p50": nearest(0.50), "p95": nearest(0.95),
            "p99": nearest(0.99), "max": values[-1]}


def read_jsonl_gz(path):
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.lstrip().startswith("{"):
                rows.append(json.loads(line))
    return rows


def summarize_policy(policy_dir, policy, source_rows):
    with (policy_dir / "requests.csv").open(
            newline="", encoding="utf-8") as stream:
        requests = list(csv.DictReader(stream))
    if len(requests) != len(source_rows):
        raise RuntimeError("request CSV count does not match selected trace rows")

    ttft_ms, tpot_ms, tbt_ms, ready_ms = [], [], [], []
    request_ledger = []
    for row, source in zip(requests, source_rows):
        if (int(row["input"]) != int(source["input_toks"]) or
                int(row["output"]) != int(source["output_toks"]) or
                int(row["arrival"]) != int(source["arrival_time_ns"])):
            raise RuntimeError("serving output differs from source request semantics")
        ttft = float(row["TTFT"]) / 1e6
        tpot = float(row["TPOT"]) / 1e6
        tbts = [float(value) / 1e6
                for value in json.loads(row.get("TBT") or "[]")]
        ready = row.get("p2d_kv_ready_time_ns")
        ready_from_arrival = (None if ready in (None, "", "None") else
                              (float(ready) - int(source["arrival_time_ns"])) / 1e6)
        ttft_ms.append(ttft)
        tpot_ms.append(tpot)
        tbt_ms.extend(tbts)
        if ready_from_arrival is not None:
            ready_ms.append(ready_from_arrival)
        request_ledger.append({
            "sim_request_id": int(row["request id"]),
            "source_request_id": source.get("request_id",
                                            source.get("source_request_id")),
            "source_record_index": source.get("source_record_index"),
            "source_trace": source.get("source_trace"),
            "input_toks": int(source["input_toks"]),
            "output_toks": int(source["output_toks"]),
            "arrival_time_ns": int(source["arrival_time_ns"]),
            "TTFT_ms": ttft,
            "TPOT_ms": tpot,
            "TBT_ms": tbts,
            "p2d_kv_ready_from_arrival_ms": ready_from_arrival,
            "decode_admit_time_ns": row.get("decode_admit_time_ns"),
            "decode_first_token_time_ns": row.get("decode_first_token_time_ns"),
            "trace_record_status": row.get("trace_record_status"),
        })

    collectives = read_jsonl_gz(policy_dir / "collectives.jsonl.gz")
    cct_us = [float(event["cct_ns"]) / 1000.0 for event in collectives
              if event.get("traffic_class") == "EP" and
              event.get("cct_ns") is not None]
    kv_events = read_jsonl_gz(policy_dir / "kv_events.jsonl.gz")
    kv_generated = sum(int(event.get("bytes", 0) or 0)
                       for event in kv_events
                       if event.get("event") == "KV_GENERATED")
    return {
        "policy": policy,
        "request_count": len(requests),
        "TTFT_ms": stats(ttft_ms),
        "TPOT_ms": stats(tpot_ms),
        "token_TBT_ms": stats(tbt_ms),
        "P2D_KV_ready_from_arrival_ms": stats(ready_ms),
        "EP_collective_CCT_us": stats(cct_us),
        "EP_collective_count": len(cct_us),
        "model_generated_KV_bytes": kv_generated,
        "KV_event_count": len(kv_events),
        "collective_event_count": len(collectives),
        "request_ledger": request_ledger,
        "queue_semantics": "FlowSim analytical fluid backlog; not packet queue",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", required=True, type=Path)
    parser.add_argument("--request-limit", required=True, type=int)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--policies", nargs="+", default=["FAIR", "EP_FIRST"],
                        choices=["FAIR", "EP_FIRST", "KV_FIRST"])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    workload = args.workload if args.workload.is_absolute() else ROOT / args.workload
    config = args.config if args.config.is_absolute() else ROOT / args.config
    output_dir = (args.output_dir if args.output_dir.is_absolute()
                  else ROOT / args.output_dir)
    if args.request_limit <= 0:
        parser.error("--request-limit must be positive")
    if len(set(args.policies)) != len(args.policies):
        parser.error("policies must be unique")

    source_rows, selected_raw = read_prefix(workload, args.request_limit)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_meta = [{key: row.get(key) for key in (
        "request_id", "source_request_id", "source_record_index",
        "input_toks", "output_toks", "arrival_time_ns", "trace_slice_window_id")}
        for row in source_rows]
    metadata = {
        "config": str(config.relative_to(ROOT)),
        "config_sha256": sha256_file(config),
        "source_workload": str(workload.relative_to(ROOT)),
        "source_workload_sha256": sha256_file(workload),
        "selected_prefix_sha256": sha256_bytes(selected_raw),
        "request_count": len(source_rows),
        "selection": "first N consecutive records in a preselected trace window; no timestamp/token edits",
        "selected_arrival_span_ns": (int(source_rows[-1]["arrival_time_ns"]) -
                                      int(source_rows[0]["arrival_time_ns"])),
        "selected_requests": selected_meta,
        "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "topology": "S16 8P8D, EP64, 2 x 200-Gbps NIC/server, 1:1 Clos",
        "network_backend": "FlowSim analytical fluid model",
        "p2d_mode": "LAYERWISE",
        "ep_collective_semantics": "A2A_P2P",
        "request_routing": "RR",
        "expert_routing": "BALANCED",
        "synthetic_byte_override": False,
        "policies": {},
    }

    for policy in args.policies:
        policy_dir = output_dir / policy.lower()
        policy_dir.mkdir(parents=True, exist_ok=True)
        request_csv = policy_dir / "requests.csv"
        command = [sys.executable, "-m", "serving",
                   "--cluster-config", str(config.relative_to(ROOT)),
                   "--dataset", str(workload.relative_to(ROOT)),
                   "--num-reqs", str(len(source_rows)),
                   "--output", str(request_csv.relative_to(ROOT)),
                   "--run-id", "real_trace_ep64_" + policy.lower(),
                   "--inputs-root", "PLACEHOLDER",
                   "--network-backend", "flowsim",
                   "--kv-ep-network-policy", policy,
                   "--ep-collective-semantics", "A2A_P2P",
                   "--pd-kv-transfer-mode", "LAYERWISE",
                   "--pd-kv-receiver-mode", "ACTUAL",
                   "--request-routing-policy", "RR",
                   "--expert-routing-policy", "BALANCED",
                   "--no-enable-prefix-caching",
                   "--log-level", "WARNING", "--log-interval", "60",
                   "--keep-inputs"]
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="real_trace_ep64_") as tmp:
            inputs_root = Path(tmp) / "inputs"
            command[command.index("PLACEHOLDER")] = str(inputs_root)
            env = os.environ.copy()
            env["LLMSERVINGSIM_COMPACT_LOGS"] = "1"
            env["FLOWSIM_FLOW_TELEMETRY"] = "0"
            env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "0"
            env["FLOWSIM_MAX_TELEMETRY_ROWS"] = "0"
            env["FLOWSIM_EP_FLOW_TELEMETRY"] = "0"
            env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT,EP"
            env["FLOWSIM_NETWORK_CLASSES"] = "KV_MOVEMENT,EP"
            log_path = policy_dir / "run.log"
            with log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run(command, cwd=ROOT, env=env,
                                        stdout=log, stderr=subprocess.STDOUT,
                                        check=False)
            if result.returncode != 0 or not request_csv.is_file():
                raise RuntimeError("%s serving run failed (exit=%d): %s" %
                                   (policy, result.returncode, log_path))
            flowsim_dir = inputs_root / "flowsim"
            for source, target in (
                    ("collective_telemetry.jsonl", "collectives.jsonl.gz"),
                    ("kv_event_telemetry.jsonl", "kv_events.jsonl.gz")):
                source_path = flowsim_dir / source
                if not source_path.exists():
                    raise RuntimeError("missing required telemetry %s" % source)
                with source_path.open("rb") as src, gzip.open(
                        policy_dir / target, "wb", compresslevel=6) as dst:
                    shutil.copyfileobj(src, dst)
        elapsed = time.monotonic() - started
        metadata["policies"][policy] = {
            "wall_seconds": elapsed,
            "request_csv": str(request_csv.relative_to(ROOT)),
            "request_csv_sha256": sha256_file(request_csv),
            "collectives_sha256": sha256_file(policy_dir / "collectives.jsonl.gz"),
            "kv_events_sha256": sha256_file(policy_dir / "kv_events.jsonl.gz"),
            "command": command,
        }
        print("DONE", policy, "wall_seconds=%.1f" % elapsed, flush=True)

    metadata["results"] = {
        policy: summarize_policy(output_dir / policy.lower(), policy, source_rows)
        for policy in args.policies
    }
    (output_dir / "summary.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print("SUMMARY", output_dir / "summary.json", flush=True)


if __name__ == "__main__":
    main()
