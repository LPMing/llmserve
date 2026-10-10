#!/usr/bin/env python3
"""Matched EP64 integrated FlowSim FAIR/EP_FIRST validation.

Uses the existing 32-Decode + 64-P2D, output=4 workload and a separate S16
topology where eight GPU ranks share two physical 200-Gbps NICs per server.
Only compact serving CSVs and compressed KV/collective telemetry are retained.
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
CONFIG = Path(
    "experiments/pd_kv_ep/configs/large_scale/"
    "s16_8p8d_ep64_shared_2nic_qwen.json")
WORKLOAD = Path(
    "experiments/pd_kv_ep/workloads/autonomous/"
    "ep64_integrated_high_32d64p2d_decode4.jsonl")
POLICIES = ("FAIR", "EP_FIRST")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stats(values):
    values = sorted(float(value) for value in values
                    if value is not None and math.isfinite(float(value)))
    if not values:
        return {"count": 0, "mean": None, "p50": None,
                "p95": None, "p99": None, "max": None}

    def nearest(q):
        return values[max(0, math.ceil(q * len(values)) - 1)]

    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": nearest(0.50),
        "p95": nearest(0.95),
        "p99": nearest(0.99),
        "max": values[-1],
    }


def _read_jsonl_gz(path):
    rows = []
    if not path.exists():
        return rows
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.lstrip().startswith("{"):
                rows.append(json.loads(line))
    return rows


def _policy_summary(policy_dir, policy):
    with (policy_dir / "requests.csv").open(
            newline="", encoding="utf-8") as stream:
        requests = list(csv.DictReader(stream))

    decoded = []
    p2d = []
    all_decode_tbt_ms = []
    for row in requests:
        rid = int(row["request id"])
        row["_rid"] = rid
        row["_ttft_ms"] = float(row["TTFT"]) / 1e6
        row["_tpot_ms"] = float(row["TPOT"]) / 1e6
        row["_tbt_ms"] = [float(item) / 1e6
                          for item in json.loads(row.get("TBT") or "[]")]
        (decoded if rid < 32 else p2d).append(row)
        if rid < 32:
            all_decode_tbt_ms.extend(row["_tbt_ms"])

    collectives = _read_jsonl_gz(policy_dir / "collectives.jsonl.gz")
    ep_cct_us = [float(row["cct_ns"]) / 1000.0 for row in collectives
                 if row.get("traffic_class") == "EP" and
                 row.get("cct_ns") is not None]

    kv_events = _read_jsonl_gz(policy_dir / "kv_events.jsonl.gz")
    kv_generated = 0
    for event in kv_events:
        if event.get("event") != "KV_GENERATED":
            continue
        ids = {int(value) for value in event.get("request_ids", ())}
        if ids.intersection(range(32, 96)):
            kv_generated += int(event.get("bytes", 0) or 0)

    def ready_ms(row):
        ready = row.get("p2d_kv_ready_time_ns")
        if ready in (None, "", "None"):
            return None
        return (float(ready) - float(row["arrival"])) / 1e6

    return {
        "policy": policy,
        "decode_request_count": len(decoded),
        "p2d_request_count": len(p2d),
        "decode_TTFT_ms": _stats([row["_ttft_ms"] for row in decoded]),
        "decode_TPOT_ms": _stats([row["_tpot_ms"] for row in decoded]),
        "decode_token_TBT_ms": _stats(all_decode_tbt_ms),
        "p2d_TTFT_ms": _stats([row["_ttft_ms"] for row in p2d]),
        "p2d_KV_ready_from_arrival_ms": _stats(
            [ready_ms(row) for row in p2d]),
        "EP_collective_CCT_us": _stats(ep_cct_us),
        "EP_collective_count": len(ep_cct_us),
        "model_generated_P2D_KV_bytes": kv_generated,
        "KV_event_count": len(kv_events),
        "collective_event_count": len(collectives),
        "serving_metric_provenance": "integrated request CSV",
        "queue_semantics": "not recorded; FlowSim fluid backlog is not packet queue",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("experiments/pd_kv_ep/results/pd_moe_phase_search/"
                     "ep64_shared_2nic"))
    args = parser.parse_args()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    config_path = ROOT / CONFIG
    workload_path = ROOT / WORKLOAD
    workload_count = sum(1 for line in workload_path.open(encoding="utf-8")
                         if line.strip())
    if workload_count != 96:
        raise RuntimeError("expected 96 requests in the frozen workload")

    metadata = {
        "config": str(CONFIG),
        "config_sha256": _sha256(config_path),
        "workload": str(WORKLOAD),
        "workload_sha256": _sha256(workload_path),
        "request_count": workload_count,
        "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "topology": "S16 8P8D, EP64, 2 x 200-Gbps NIC/server, 1:1 Clos",
        "p2d_mode": "LAYERWISE",
        "ep_collective_semantics": "A2A_P2P",
        "request_routing": "RR",
        "expert_routing": "BALANCED",
        "synthetic_byte_override": False,
        "policies": {},
    }

    for policy in POLICIES:
        policy_dir = output_dir / policy.lower()
        policy_dir.mkdir(parents=True, exist_ok=True)
        request_csv = policy_dir / "requests.csv"
        command = [
            sys.executable, "-m", "serving",
            "--cluster-config", CONFIG.as_posix(),
            "--dataset", WORKLOAD.as_posix(),
            "--num-reqs", str(workload_count),
            "--output", request_csv.relative_to(ROOT).as_posix(),
            "--run-id", "pd_moe_ep64_shared_nic_" + policy.lower(),
            "--inputs-root", "PLACEHOLDER",
            "--network-backend", "flowsim",
            "--kv-ep-network-policy", policy,
            "--ep-collective-semantics", "A2A_P2P",
            "--pd-kv-transfer-mode", "LAYERWISE",
            "--pd-kv-receiver-mode", "ACTUAL",
            "--request-routing-policy", "RR",
            "--expert-routing-policy", "BALANCED",
            "--no-enable-prefix-caching",
            "--log-level", "WARNING",
            "--log-interval", "60",
            "--keep-inputs",
        ]
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="pd_moe_ep64_shared_nic_") as tmp:
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
                result = subprocess.run(
                    command, cwd=ROOT, env=env,
                    stdout=log, stderr=subprocess.STDOUT, check=False)
            if result.returncode != 0 or not request_csv.is_file():
                raise RuntimeError(
                    "%s serving run failed (exit=%d): %s" %
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

        wall = time.monotonic() - started
        metadata["policies"][policy] = {
            "wall_seconds": wall,
            "request_csv": str(request_csv.relative_to(ROOT)),
            "request_csv_sha256": _sha256(request_csv),
            "collectives_sha256": _sha256(policy_dir / "collectives.jsonl.gz"),
            "kv_events_sha256": _sha256(policy_dir / "kv_events.jsonl.gz"),
            "command": command,
        }
        print("DONE", policy, "wall_seconds=%.3f" % wall, flush=True)

    metadata["results"] = {
        policy: _policy_summary(output_dir / policy.lower(), policy)
        for policy in POLICIES
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(metadata, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps(metadata["results"], indent=2))
    print("SUMMARY", summary_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
