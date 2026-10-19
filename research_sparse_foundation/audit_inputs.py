#!/usr/bin/env python3
"""Recompute sparse-MoE profile and historical route-sidecar audit counts.

This script only reads repository artifacts and writes a compact JSON snapshot
beside itself. It never launches Serving, FlowSim, ns-3, or the profiler.
"""

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / (
    "profiler/perf/RTXPRO6000/Qwen/"
    "Qwen3-30B-A3B-Instruct-2507/bf16/tp1/moe.csv")
RESULTS = ROOT / "experiments/pd_kv_ep/results"
OUTPUT = Path(__file__).with_name("audit_snapshot.json")
HASH_PATHS = (
    "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json",
    "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/meta.yaml",
    "serving/core/gate_function.py",
    "serving/core/trace_generator.py",
    "serving/core/graph_generator.py",
    "serving/core/config_builder.py",
    "astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py",
    "experiments/pd_kv_ep/configs/large_scale/generate_s16_8p8d_ep64_shared_2nic.py",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(*args):
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True).strip()


def profile_audit():
    with PROFILE.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    token_grid = sorted({int(row["tokens"]) for row in rows})
    activated_grid = sorted({int(row["activated_experts"]) for row in rows})
    return {
        "path": str(PROFILE.relative_to(ROOT)),
        "sha256": sha256(PROFILE),
        "row_count": len(rows),
        "token_grid": token_grid,
        "activated_experts_grid": activated_grid,
        "measurement_gpu": "NVIDIA RTX PRO 6000 Blackwell Server Edition",
        "measured_activated_experts_1_2_4": False,
    }


def classify_axis(value, grid):
    if value < grid[0]:
        return "BELOW_MIN_CLAMPED"
    if value > grid[-1]:
        return "ABOVE_MAX_EXTRAPOLATED"
    if value in grid:
        return "IN_DOMAIN_GRID"
    return "IN_DOMAIN_INTERPOLATED"


def sidecar_audit(profile):
    token_grid = profile["token_grid"]
    ae_grid = profile["activated_experts_grid"]
    files = sorted(RESULTS.rglob("*.a2a_routes.json"))
    by_run = defaultdict(lambda: {
        "files": 0, "records": 0, "weighted_queries": 0,
        "ep_sizes": Counter(), "routing_policies": Counter(),
        "realizations": Counter(), "token_status": Counter(),
        "activated_status": Counter(), "joint_status": Counter(),
    })
    total = {
        "files": len(files), "records": 0, "weighted_queries": 0,
        "ep_sizes": Counter(), "routing_policies": Counter(),
        "realizations": Counter(), "token_status": Counter(),
        "activated_status": Counter(), "joint_status": Counter(),
    }
    for path in files:
        relative = path.relative_to(RESULTS)
        run = relative.parts[0] if relative.parts else "UNKNOWN"
        bucket = by_run[run]
        bucket["files"] += 1
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records", [])
        for record in records:
            reps = max(1, int(record.get("trace_repetitions", 1)))
            ep = str(record.get("ep_size", "NOT_AVAILABLE"))
            policy = str(record.get("routing_policy", "NOT_AVAILABLE"))
            realization = str(record.get("realization", payload.get("realization", "NOT_AVAILABLE")))
            local_tokens = record.get("compute_local_tokens") or []
            activated = record.get("compute_activated_experts") or []
            count = min(len(local_tokens), len(activated))
            for index in range(count):
                tok_status = classify_axis(int(local_tokens[index]), token_grid)
                ae_status = classify_axis(int(activated[index]), ae_grid)
                if tok_status == "BELOW_MIN_CLAMPED":
                    tok_status = "BELOW_MIN_CLAMPED_TO_1"
                key = (tok_status, ae_status)
                for target in (bucket, total):
                    target["records"] += 1 if index == 0 else 0
                    target["weighted_queries"] += reps
                    target["ep_sizes"][ep] += reps if index == 0 else 0
                    target["routing_policies"][policy] += reps if index == 0 else 0
                    target["realizations"][realization] += reps if index == 0 else 0
                    target["token_status"][tok_status] += reps
                    target["activated_status"][ae_status] += reps
                    target["joint_status"]["%s|%s" % key] += reps
    def normalize(source):
        result = {}
        for key, value in source.items():
            if isinstance(value, Counter):
                result[key] = dict(sorted(value.items()))
            else:
                result[key] = value
        return result
    return {
        "root": str(RESULTS.relative_to(ROOT)),
        "sidecar_file_count": len(files),
        "all": normalize(total),
        "by_run": {name: normalize(value) for name, value in sorted(by_run.items())},
        "scope_note": (
            "Only retained route sidecars are counted; this is not a census of "
            "every historical Serving run or every emitted graph."),
    }


def s16_rank_audit():
    config_path = ROOT / "experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_shared_2nic_qwen.json"
    topology_path = ROOT / "experiments/pd_kv_ep/configs/large_scale/ns3/s16_8p8d_ep64_shared_2nic_200g_clos.txt"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    effective_ranks = 0
    prefill_instances = 0
    decode_instances = 0
    for node in config["nodes"]:
        for instance in node["instances"]:
            count = int(instance["num_npus"])
            if instance.get("pd_type") == "prefill":
                effective_ranks += 2 * count
                prefill_instances += 1
            else:
                effective_ranks += count
                if instance.get("pd_type") == "decode":
                    decode_instances += 1
    lines = [line.strip() for line in topology_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    node_count, switch_count, edge_count = map(int, lines[0].split()[:3])
    switch_ids = set()
    for item in lines[1].split():
        if item.isdigit():
            switch_ids.add(int(item))
    endpoint_ids = sorted(set(range(node_count)) - switch_ids)
    return {
        "config": str(config_path.relative_to(ROOT)),
        "config_sha256": sha256(config_path),
        "topology": str(topology_path.relative_to(ROOT)),
        "topology_sha256": sha256(topology_path),
        "configured_effective_astarsim_rank_count": effective_ranks,
        "prefill_instance_count": prefill_instances,
        "decode_instance_count": decode_instances,
        "topology_node_count": node_count,
        "topology_switch_count": switch_count,
        "topology_physical_edge_count": edge_count,
        "topology_switch_ids": sorted(switch_ids),
        "topology_non_switch_ids": endpoint_ids,
        "flowsim_topology_configured": bool(config.get("flowsim_topology")),
        "flowsim_rank_map_configured": bool(config.get("flowsim_rank_map")),
    }


def main():
    profile = profile_audit()
    payload = {
        "git_head": git_output("rev-parse", "HEAD"),
        "git_branch": git_output("branch", "--show-current"),
        "tracked_diff_sha256": hashlib.sha256(
            subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
        ).hexdigest(),
        "tracked_status": git_output("status", "--short"),
        "sha256_files": {
            relative: sha256(ROOT / relative) for relative in HASH_PATHS
        },
        "profile": profile,
        "sidecars": sidecar_audit(profile),
        "s16_rank_audit": s16_rank_audit(),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    print(json.dumps({
        "git_head": payload["git_head"],
        "tracked_diff_sha256": payload["tracked_diff_sha256"],
        "profile": profile,
        "sidecars": payload["sidecars"]["all"],
        "s16_rank_audit": payload["s16_rank_audit"],
    }, indent=2))


if __name__ == "__main__":
    main()
