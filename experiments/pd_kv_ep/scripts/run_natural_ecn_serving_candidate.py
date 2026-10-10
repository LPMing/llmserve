#!/usr/bin/env python3
"""Generate one integrated, model-derived S8 workload for packet replay."""

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CLUSTER = Path(
    "experiments/pd_kv_ep/configs/large_scale/"
    "s8_4p4d_ep32_4gpu_per_200g_nic.json")
DEFAULT_TOPOLOGY = Path(
    "experiments/pd_kv_ep/configs/large_scale/ns3/"
    "s8_4p4d_ep32_4gpu_per_200g_nic_200g_clos.txt")
DEFAULT_MODEL = Path(
    "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json")
DEFAULT_RANKS = Path(
    "experiments/pd_kv_ep/configs/large_scale/"
    "s8_4p4d_ep32_rank_metadata.csv")
DEFAULT_NIC_MAP = Path(
    "experiments/pd_kv_ep/configs/large_scale/"
    "s8_4p4d_ep32_gpu_to_nic.csv")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def read_requests(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def integer(row, field):
    value = row.get(field)
    return int(float(value)) if value not in (None, "", "None") else None


def read_tbt(row):
    value = row.get("TBT", "")
    return [int(float(item)) for item in json.loads(value)] if value else []


def run_serving(workload, output_csv, inputs_root, run_id, keep_inputs,
                telemetry_enabled):
    count = sum(1 for line in workload.open(encoding="utf-8") if line.strip())
    command = [
        sys.executable, "-m", "serving",
        "--cluster-config", str(DEFAULT_CLUSTER),
        "--dataset", str(workload.relative_to(ROOT)),
        "--num-reqs", str(count),
        "--output", str(output_csv),
        "--run-id", run_id,
        "--inputs-root", str(inputs_root),
        "--network-backend", "flowsim",
        "--flowsim-parallel-link-mode", "AGGREGATE",
        "--kv-ep-network-policy", "FAIR",
        "--ep-collective-semantics", "A2A_P2P",
        "--pd-kv-transfer-mode", "LAYERWISE",
        "--pd-kv-receiver-mode", "ACTUAL",
        "--request-routing-policy", "RR",
        "--expert-routing-policy", "BALANCED",
        "--max-num-seqs", "128",
        "--max-num-batched-tokens", "2048",
        "--no-enable-prefix-caching",
        "--log-level", "WARNING",
        "--log-interval", "60",
    ]
    if keep_inputs:
        command.append("--keep-inputs")
    else:
        command.append("--no-keep-inputs")

    env = os.environ.copy()
    env["LLMSERVINGSIM_COMPACT_LOGS"] = "1"
    env["FLOWSIM_FLOW_TELEMETRY"] = "1" if telemetry_enabled else "0"
    env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "0"
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT,EP"
    env["FLOWSIM_NETWORK_CLASSES"] = "KV_MOVEMENT,EP"
    env["FLOWSIM_MAX_TELEMETRY_ROWS"] = "1"
    env["FLOWSIM_EP_FLOW_TELEMETRY"] = "0"
    log_path = output_csv.with_suffix(".log")
    started = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            check=False)
    if result.returncode != 0 or not output_csv.is_file():
        tail = ""
        if log_path.exists():
            tail = "\n".join(log_path.read_text(
                encoding="utf-8", errors="replace").splitlines()[-40:])
        raise RuntimeError(
            "serving run failed (exit=%d): %s\n%s" %
            (result.returncode, log_path, tail))
    return {"command": command, "wall_seconds": time.time() - started,
            "log": str(log_path)}


def inspect_flow_ledger(path):
    counts = {"KV_MOVEMENT": 0, "EP": 0, "OTHER": 0}
    byte_counts = {"KV_MOVEMENT": 0, "EP": 0, "OTHER": 0}
    event_type_counts = {}
    row_count = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            row = json.loads(line)
            if row.get("record_type") == "metadata":
                continue
            traffic_class = str(row.get("traffic_class", "OTHER"))
            if traffic_class not in counts:
                traffic_class = "OTHER"
            event_type = int(row.get("event_type", -1))
            if event_type not in (1, 2, 3):
                raise ValueError("unsupported event_type at line %d" % line_number)
            if "requested_start_ns" not in row:
                raise ValueError("missing requested_start_ns at line %d" % line_number)
            if int(row.get("bytes", 0)) <= 0:
                raise ValueError("non-positive flow bytes at line %d" % line_number)
            if "src" not in row or "dst" not in row:
                raise ValueError("missing rank endpoints at line %d" % line_number)
            counts[traffic_class] += 1
            byte_counts[traffic_class] += int(row["bytes"])
            event_type_counts[str(event_type)] = event_type_counts.get(
                str(event_type), 0) + 1
            row_count += 1
    if not counts["KV_MOVEMENT"] or not counts["EP"]:
        raise ValueError("full serving ledger must contain both P2D KV and EP")
    return {"event_count": row_count,
            "event_counts_by_class": counts,
            "bytes_by_class": byte_counts,
            "event_type_counts": event_type_counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--d", type=int, required=True, help="active Decode request count")
    parser.add_argument("--k", type=int, required=True, help="concurrent P2D request count")
    parser.add_argument("--d-input", type=int, default=128)
    parser.add_argument("--d-output", type=int, default=64)
    parser.add_argument("--k-input", type=int, default=8192)
    parser.add_argument("--k-output", type=int, default=2)
    parser.add_argument("--k-spacing-ms", type=float, default=5.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.d not in (8, 16, 32) or args.k not in (2, 4, 8):
        parser.error("D must be 8/16/32 and K must be 2/4/8 for this bounded search")
    if min(args.d_input, args.d_output, args.k_input, args.k_output) < 1:
        parser.error("token counts must be positive")
    if args.k_spacing_ms < 0:
        parser.error("K arrival spacing must be nonnegative")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    warmup_dir = output_dir / "warmup"
    full_dir = output_dir / "integrated_full"
    workload_dir = output_dir / "workloads"
    for directory in (warmup_dir, full_dir, workload_dir):
        directory.mkdir(parents=True, exist_ok=True)

    warmup_rows = [{
        "request_id": "D%03d" % index,
        "input_toks": args.d_input,
        "output_toks": args.d_output,
        "arrival_time_ns": 0,
    } for index in range(args.d)]
    warmup_workload = workload_dir / "decode_warmup.jsonl"
    write_jsonl(warmup_workload, warmup_rows)
    warmup_output = warmup_dir / "requests.csv"
    warmup_run = run_serving(
        warmup_workload, warmup_output, warmup_dir / "inputs",
        "natural_ecn_warmup_%d" % args.d, False, False)

    warmup_results = read_requests(warmup_output)
    if len(warmup_results) != args.d:
        raise RuntimeError("D-only warm-up did not return every request")
    by_id = {integer(row, "request id"): row for row in warmup_results}
    required_ids = set(range(args.d))
    if set(by_id) != required_ids:
        raise RuntimeError("D-only warm-up request IDs are not contiguous")
    fourth_boundaries = []
    for request_id, row in by_id.items():
        admission = integer(row, "decode_admit_time_ns")
        boundaries = read_tbt(row)
        if admission is None or len(boundaries) < 4:
            raise RuntimeError(
                "D%d lacks admission or four completed Decode boundaries" % request_id)
        fourth_boundaries.append(admission + sum(boundaries[:4]))
    inject_ns = max(fourth_boundaries) + 1
    gap_ns = int(round(args.k_spacing_ms * 1_000_000))
    final_k_arrival_ns = inject_ns + (args.k - 1) * gap_ns

    full_rows = list(warmup_rows)
    for index in range(args.k):
        full_rows.append({
            "request_id": "K%03d" % index,
            "input_toks": args.k_input,
            "output_toks": args.k_output,
            "arrival_time_ns": inject_ns + index * gap_ns,
        })
    full_workload = workload_dir / "full.jsonl"
    write_jsonl(full_workload, full_rows)
    full_output = full_dir / "requests.csv"
    full_inputs = full_dir / "inputs"
    full_run = run_serving(
        full_workload, full_output, full_inputs,
        "natural_ecn_full_d%d_k%d_i%d" % (args.d, args.k, args.k_input),
        True, True)

    full_results = read_requests(full_output)
    if len(full_results) != args.d + args.k:
        raise RuntimeError("integrated FULL run did not complete all requests")
    full_by_id = {integer(row, "request id"): row for row in full_results}
    for request_id in range(args.d):
        old = by_id[request_id]
        new = full_by_id[request_id]
        for field in ("decode_admit_time_ns", "p2d_kv_ready_time_ns",
                      "decode_first_token_time_ns"):
            if integer(old, field) != integer(new, field):
                raise RuntimeError(
                    "pre-injection D prefix differs for request %d / %s" %
                    (request_id, field))
        if read_tbt(old)[:4] != read_tbt(new)[:4]:
            raise RuntimeError("pre-injection first-four-token prefix changed")
        if integer(new, "end_time") <= final_k_arrival_ns:
            raise RuntimeError("D cohort drained before the final K arrival")
        if integer(new, "decode_admit_time_ns") + sum(read_tbt(new)[:4]) >= inject_ns:
            raise RuntimeError("K arrived before all D requests completed four boundaries")

    flow_ledger = full_inputs / "flowsim" / "flow_telemetry.jsonl"
    if not flow_ledger.is_file():
        raise RuntimeError("integrated full run did not preserve flow telemetry")
    ledger_metrics = inspect_flow_ledger(flow_ledger)
    if ledger_metrics["event_counts_by_class"]["OTHER"]:
        raise RuntimeError("unexpected OTHER traffic was present in the saved ledger")

    artifact_paths = [
        DEFAULT_CLUSTER, DEFAULT_TOPOLOGY, DEFAULT_MODEL, DEFAULT_RANKS,
        DEFAULT_NIC_MAP, warmup_workload, warmup_output, full_workload,
        full_output, flow_ledger,
    ]
    for source in (DEFAULT_CLUSTER, DEFAULT_TOPOLOGY, DEFAULT_MODEL,
                   DEFAULT_RANKS, DEFAULT_NIC_MAP):
        destination = output_dir / "frozen_config" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())

    manifest = {
        "status": "SERVING_LEDGER_READY_FOR_PACKET_REPLAY",
        "experiment_id": output_dir.name,
        "source": "integrated LLMServingSim FlowSim serving execution",
        "topology": "S8_4P4D_EP32_SHARED_NIC",
        "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "EP_degree": 32,
        "D_active": args.d,
        "K_active": args.k,
        "D_input_tokens": args.d_input,
        "D_output_tokens": args.d_output,
        "K_input_tokens": args.k_input,
        "K_output_tokens": args.k_output,
        "K_arrival_spacing_ms": args.k_spacing_ms,
        "event_derived_K_first_arrival_ns": inject_ns,
        "K_last_arrival_ns": final_k_arrival_ns,
        "warmup_rule": "all D requests admitted and each completed four TBT boundaries",
        "P2D_mode": "LAYERWISE",
        "P2D_receiver_mode": "ACTUAL",
        "EP_collective_semantics": "A2A_P2P",
        "request_routing": "RR",
        "expert_routing": "BALANCED",
        "parallel_link_mode": "AGGREGATE",
        "synthetic_byte_override": False,
        "serving_metrics_are_integrated": True,
        "packet_level_results_exist": False,
        "flowsim_link_telemetry_cap_rows": 1,
        "serving_wall_seconds": {
            "decode_warmup": warmup_run["wall_seconds"],
            "full": full_run["wall_seconds"],
        },
        **ledger_metrics,
        "artifact_sha256": {
            str(path.relative_to(ROOT)) if path.is_relative_to(ROOT)
            else str(path): sha256(path) for path in artifact_paths
        },
        "frozen_config_sha256": {
            path.name: sha256(output_dir / "frozen_config" / path.name)
            for path in (DEFAULT_CLUSTER, DEFAULT_TOPOLOGY, DEFAULT_MODEL,
                         DEFAULT_RANKS, DEFAULT_NIC_MAP)
        },
        "run_commands": {
            "warmup": warmup_run["command"],
            "full": full_run["command"],
        },
    }
    manifest_path = output_dir / "SERVING_CANDIDATE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), **manifest}, indent=2))


if __name__ == "__main__":
    main()
