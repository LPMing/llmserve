#!/usr/bin/env python3
"""Write a machine-readable provenance manifest for the recovered baseline."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]


def run(*args):
    return subprocess.run(
        args, cwd=str(ROOT), check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE).stdout


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path):
    absolute = ROOT / path
    if not absolute.is_file():
        return {"path": path, "exists": False}
    return {
        "path": path,
        "exists": True,
        "bytes": absolute.stat().st_size,
        "sha256": sha256(absolute),
    }


def file_records(paths):
    return [artifact(path) for path in paths]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="research_audit/results/01_baseline_run_manifest.json")
    args = parser.parse_args()

    diff = run("git", "diff", "--binary")
    status = [
        line for line in run(
            "git", "status", "--porcelain=v1", "-uall").decode().splitlines()
        if line[3:] != args.output
    ]
    source_paths = [
        "serving/__main__.py",
        "serving/core/config_builder.py",
        "serving/core/controller.py",
        "serving/core/flowsim_backend.py",
        "serving/core/flowsim_groups.py",
        "serving/core/flowsim_worker.py",
        "serving/core/graph_generator.py",
        "serving/core/request.py",
        "serving/core/router.py",
        "serving/core/scheduler.py",
        "serving/core/trace_generator.py",
        "astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py",
        "astra-sim/extern/graph_frontend/chakra/schema/protobuf/et_def.proto",
        "astra-sim/extern/network_backend/ns-3/scratch/common.h",
        "astra-sim/astra-sim/network_frontend/ns3/KVEPReplay.cc",
        "research_audit/scripts/write_baseline_manifest.py",
        "research_audit/scripts/validate_baseline_barriers.py",
        "research_audit/scripts/build_ns3_baseline_smoke_input.py",
        "research_audit/scripts/analyze_corrected_ns3_moe_layer.py",
        "experiments/pd_kv_ep/configs/generate_two_decode_ep4_groups_flowsim.py",
    ]
    test_paths = [
        "experiments/pd_kv_ep/scripts/test_config_topology_rank_count.py",
        "experiments/pd_kv_ep/scripts/test_flowsim_collective_scope.py",
        "experiments/pd_kv_ep/scripts/test_flowsim_decode_completion_wakeup.py",
        "experiments/pd_kv_ep/scripts/test_flowsim_decode_handoff_wakeup.py",
        "experiments/pd_kv_ep/scripts/test_flowsim_group_queue_ownership.py",
        "experiments/pd_kv_ep/scripts/test_flowsim_rank_mapping.py",
        "experiments/pd_kv_ep/scripts/test_ns3_config_topology_selection.py",
        "experiments/pd_kv_ep/scripts/test_pd_decode_capacity_admission.py",
        "experiments/pd_kv_ep/scripts/test_pd_request_pairing.py",
        "experiments/pd_kv_ep/scripts/test_trace_time_units.py",
    ]
    config_paths = [
        "experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json",
        "experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_logical_to_physical.json",
        "experiments/pd_kv_ep/configs/large_scale/flowsim/minimal_1p2d_ep16_single_tor_nvlink.txt",
        "experiments/pd_kv_ep/configs/large_scale/ns3/minimal_1p2d_ep16_logical_ranks_single_tor.txt",
        "experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf",
        "experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_full.json",
        "experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_full_logical_to_physical.json",
        "experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_a_only.json",
        "experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_a_only_logical_to_physical.json",
    ]
    workload_paths = [
        "experiments/pd_kv_ep/workloads/minimal_cross_request_ep_round_aligned.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_cross_request_no_overlap_control.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_cross_request_overlap.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_time_unit_corrected_kv_control.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_time_unit_corrected_kv_ep_overlap.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_kv_kv_distinct_sizes.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_kv_kv_i128_i2048.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_kv_kv_i128_i8192.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_ep4_decode_cohort.jsonl",
        "experiments/pd_kv_ep/workloads/minimal_ep4_then_kv8192.jsonl",
        "experiments/pd_kv_ep/workloads/moe_i1_o2_n1.jsonl",
        "experiments/pd_kv_ep/workloads/moe_i1_o3_n1.jsonl",
        "experiments/pd_kv_ep/workloads/two_ep4_groups_full_4req.jsonl",
        "experiments/pd_kv_ep/workloads/two_ep4_groups_full_8req.jsonl",
        "experiments/pd_kv_ep/workloads/two_ep4_groups_a_only_2req.jsonl",
        "experiments/pd_kv_ep/workloads/two_ep4_groups_a_only_4req.jsonl",
    ]
    model_paths = [
        "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json",
    ]
    audit_paths = [
        "research_audit/01_BASELINE_AUDIT.md",
        "research_audit/01_CODE_FIXES.md",
        "research_audit/01_REPRODUCIBILITY.md",
        "research_audit/scripts/write_baseline_manifest.py",
        "research_audit/scripts/validate_baseline_barriers.py",
        "research_audit/scripts/build_ns3_baseline_smoke_input.py",
        "research_audit/scripts/analyze_corrected_ns3_moe_layer.py",
        "research_audit/02_THEORETICAL_CONTENTION_MODEL.md",
        "research_audit/02_MINIMAL_MOTIVATION_CASES.md",
        "research_audit/02_MOTIVATION_RESULTS.csv",
        "research_audit/02_CONTENTION_GO_NO_GO.md",
        "research_audit/03_NUSKA_FULL_AUDIT.md",
        "research_audit/03_NOVELTY_DIFFERENCE.md",
        "research_audit/04_RELATED_WORK_MATRIX.md",
        "research_audit/04_NOVELTY_AUDIT.md",
        "research_audit/05_PRIORITY_ORACLE_RESULTS.md",
        "research_audit/06_MINIMAL_SCHEDULER_DESIGN.md",
        "research_audit/07_EXPERIMENT_RESULTS.md",
        "research_audit/08_FINAL_PAPER_DIRECTION.md",
        "research_audit/09_PAPER_BLUEPRINT.md",
        "research_audit/10_NEXT_ACTIONS.md",
        "research_audit/11_FINAL_QA.md",
        "research_audit/12_EP_EP_GROUP_VALIDATION.md",
    ]
    profile_root = Path(
        "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16")
    profile_paths = [str(profile_root / "meta.yaml")]
    profile_paths += [
        str(profile_root / "tp2" / name)
        for name in ("dense.csv", "per_sequence.csv", "attention.csv",
                     "skew.csv", "skew_fit.csv")
    ]
    profile_paths += [str(profile_root / "tp1" / "moe.csv")]

    flowsim_command = (
        "timeout 60s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs "
        "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python "
        "FLOWSIM_FLOW_TELEMETRY=1 "
        "FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP "
        "FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=0 "
        "/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving "
        "--network-backend flowsim "
        "--cluster-config experiments/pd_kv_ep/configs/large_scale/"
        "minimal_1p2d_ep16_rank_mapped_tp2.json "
        "--dataset experiments/pd_kv_ep/workloads/"
        "minimal_cross_request_ep_round_aligned.jsonl --num-reqs 2 "
        "--output research_audit/results/current_baseline_flowsim_handoff_fix.csv "
        "--run-id baseline-flowsim-handoff-fix-20261011 "
        "--inputs-root /tmp/llmsim-baseline-handoff-fix-20261011 "
        "--flowsim-policy FAIR "
        "--flowsim-telemetry research_audit/results/"
        "current_baseline_flowsim_handoff_fix.jsonl.gz "
        "--log-interval 100 --log-level WARNING"
    )
    ns3_command = (
        "python research_audit/scripts/build_ns3_baseline_smoke_input.py "
        "--output-dir <fresh-temp>/input && python "
        "experiments/pd_kv_ep/scripts/run_model_derived_replay.py "
        "--replay-dir <fresh-temp>/run --input-replay-dir <fresh-temp>/input "
        "--scale S1P2D_EP16 --template "
        "experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf "
        "--packet-payload-size 4096 --telemetry-interval-ms 0.1 "
        "--policy FAIR --cc-mode 1 --timeout-s 60"
    )
    corrected_one_command = (
        "timeout 120s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs "
        "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python "
        "FLOWSIM_FLOW_TELEMETRY=1 FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP "
        "FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=0 "
        "/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving "
        "--network-backend flowsim --cluster-config "
        "experiments/pd_kv_ep/configs/large_scale/"
        "minimal_1p2d_ep16_rank_mapped_tp2.json "
        "--dataset experiments/pd_kv_ep/workloads/moe_i1_o3_n1.jsonl "
        "--num-reqs 1 --output "
        "research_audit/results/time_unit_fix_flowsim_ep16_i1_o3.csv "
        "--run-id time-unit-fix-flowsim-ep16-i1-o3-20261011 "
        "--inputs-root /tmp/llmsim-time-unit-fix-flowsim-ep16-i1-o3-20261011 "
        "--flowsim-policy FAIR --flowsim-telemetry "
        "research_audit/results/time_unit_fix_flowsim_ep16_i1_o3.jsonl "
        "--log-interval 100 --log-level WARNING"
    )
    corrected_full_command = (
        "timeout 90s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs "
        "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python "
        "FLOWSIM_FLOW_TELEMETRY=1 FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP "
        "FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=0 "
        "/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving "
        "--network-backend flowsim --cluster-config "
        "experiments/pd_kv_ep/configs/large_scale/"
        "minimal_1p2d_ep16_rank_mapped_tp2.json "
        "--dataset experiments/pd_kv_ep/workloads/"
        "minimal_time_unit_corrected_kv_ep_overlap.jsonl --num-reqs 2 "
        "--output research_audit/results/time_unit_fix_two_req/requests.csv "
        "--run-id time-unit-fix-two-req-20261011 "
        "--inputs-root /tmp/llmsim-time-unit-fix-two-req-20261011 "
        "--flowsim-policy FAIR --flowsim-telemetry "
        "research_audit/results/time_unit_fix_two_req/flows.jsonl "
        "--log-interval 100 --log-level WARNING"
    )
    corrected_kv_command = (
        "timeout 90s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs "
        "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python "
        "FLOWSIM_FLOW_TELEMETRY=1 FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP "
        "FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=0 "
        "/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving "
        "--network-backend flowsim --cluster-config "
        "experiments/pd_kv_ep/configs/large_scale/"
        "minimal_1p2d_ep16_rank_mapped_tp2.json "
        "--dataset experiments/pd_kv_ep/workloads/"
        "minimal_time_unit_corrected_kv_control.jsonl --num-reqs 1 "
        "--output research_audit/results/time_unit_fix_kv_control/requests.csv "
        "--run-id time-unit-fix-kv-control-20261011 "
        "--inputs-root /tmp/llmsim-time-unit-fix-kv-control-20261011 "
        "--flowsim-policy FAIR --flowsim-telemetry "
        "research_audit/results/time_unit_fix_kv_control/flows.jsonl "
        "--log-interval 100 --log-level WARNING"
    )
    corrected_ns3_command = (
        "/home/lpm/.conda/envs/llmsim-flowsim/bin/python "
        "research_audit/scripts/build_ns3_baseline_smoke_input.py "
        "--ledger research_audit/results/time_unit_fix_two_req/flows.jsonl.gz "
        "--kv-request-id 1 --ep-request-id 0 "
        "--ep-collective-id 1082 --ep-collective-id 1103 "
        "--expected-kv-flows 96 --expected-ep-flows 480 "
        "--output-dir research_audit/results/ns3_corrected_full_moe_layer_108/input "
        "&& /home/lpm/.conda/envs/llmsim-flowsim/bin/python "
        "experiments/pd_kv_ep/scripts/run_model_derived_replay.py "
        "--replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/full "
        "--input-replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/input "
        "--scale S1P2D_EP16 --template experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf "
        "--packet-payload-size 4096 --telemetry-interval-ms 0.01 "
        "--policy FAIR --traffic-class FULL --cc-mode 1 --timeout-s 60 "
        "&& /home/lpm/.conda/envs/llmsim-flowsim/bin/python "
        "experiments/pd_kv_ep/scripts/run_model_derived_replay.py "
        "--replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/ep_only "
        "--input-replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/input "
        "--scale S1P2D_EP16 --template experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf "
        "--packet-payload-size 4096 --telemetry-interval-ms 0.01 "
        "--policy FAIR --traffic-class EP_ONLY --cc-mode 1 --timeout-s 60 "
        "&& /home/lpm/.conda/envs/llmsim-flowsim/bin/python "
        "experiments/pd_kv_ep/scripts/run_model_derived_replay.py "
        "--replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/kv_only "
        "--input-replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/input "
        "--scale S1P2D_EP16 --template experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf "
        "--packet-payload-size 4096 --telemetry-interval-ms 0.01 "
        "--policy FAIR --traffic-class KV_ONLY --cc-mode 1 --timeout-s 60 "
        "&& /home/lpm/.conda/envs/llmsim-flowsim/bin/python "
        "experiments/pd_kv_ep/scripts/run_model_derived_replay.py "
        "--replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/full_repeat "
        "--input-replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/input "
        "--scale S1P2D_EP16 --template experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf "
        "--packet-payload-size 4096 --telemetry-interval-ms 0.01 "
        "--policy FAIR --traffic-class FULL --cc-mode 1 --timeout-s 60"
    )

    manifest = {
        "schema": "llmservingsim-baseline-provenance-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "root": str(ROOT),
            "head": run("git", "rev-parse", "HEAD").decode().strip(),
            "branch": run("git", "branch", "--show-current").decode().strip(),
            "describe": run("git", "describe", "--tags", "--always").decode().strip(),
            "remote_origin": run("git", "remote", "get-url", "origin").decode().strip(),
            "tracked_binary_diff_sha256": hashlib.sha256(diff).hexdigest(),
            "worktree_status_porcelain": status,
            "source_files": file_records(source_paths),
            "regression_tests": file_records(test_paths),
            "configs_and_topologies": file_records(config_paths),
            "workloads": file_records(workload_paths),
            "model_configs": file_records(model_paths),
            "audit_and_analysis_files": file_records(audit_paths),
            "profile_inputs": file_records(profile_paths),
        },
        "bounded_ep_ep_validation": {
            "backend": "integrated FlowSim analytical fluid network",
            "model": artifact(
                "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"),
            "topology": artifact(
                "experiments/pd_kv_ep/configs/large_scale/flowsim/"
                "minimal_1p2d_ep16_single_tor_nvlink.txt"),
            "common_settings": {
                "network_policy": "FAIR",
                "input_tokens": 128,
                "output_tokens": 32,
                "arrival_time_ns": 0,
                "decode_ep_group_size": 4,
                "physical_scaleout_link_gbps": 200,
                "prefix_caching": False,
                "chunked_prefill": False,
                "collective_realization": "ALLGATHER dispatch + REDUCESCATTER combine",
                "expert_routing": "BALANCED",
            },
            "runs": [
                {
                    "condition": "two groups, 2 requests per group",
                    "run_id": "ep_ep_minimal_full4",
                    "config": artifact(
                        "experiments/pd_kv_ep/configs/ep_ep_minimal/"
                        "two_ep4_groups_full.json"),
                    "workload": artifact(
                        "experiments/pd_kv_ep/workloads/"
                        "two_ep4_groups_full_4req.jsonl"),
                    "request_count": 4,
                    "transient_request_output": "/tmp/ep_ep_minimal_full4_requests.csv",
                    "transient_telemetry_directory": "/tmp/ep_ep_minimal_full4",
                },
                {
                    "condition": "one group, matched 2 requests",
                    "run_id": "ep_ep_minimal_a_only2",
                    "config": artifact(
                        "experiments/pd_kv_ep/configs/ep_ep_minimal/"
                        "two_ep4_groups_a_only.json"),
                    "workload": artifact(
                        "experiments/pd_kv_ep/workloads/"
                        "two_ep4_groups_a_only_2req.jsonl"),
                    "request_count": 2,
                    "transient_request_output": "/tmp/ep_ep_minimal_a_only2_requests.csv",
                    "transient_telemetry_directory": "/tmp/ep_ep_minimal_a_only2",
                },
                {
                    "condition": "two groups, 4 requests per group",
                    "run_id": "ep_ep_minimal_full",
                    "config": artifact(
                        "experiments/pd_kv_ep/configs/ep_ep_minimal/"
                        "two_ep4_groups_full.json"),
                    "workload": artifact(
                        "experiments/pd_kv_ep/workloads/"
                        "two_ep4_groups_full_8req.jsonl"),
                    "request_count": 8,
                    "transient_request_output": "/tmp/ep_ep_minimal_full_requests.csv",
                    "transient_telemetry_directory": "/tmp",
                },
                {
                    "condition": "one group, matched 4 requests",
                    "run_id": "ep_ep_minimal_a_only4",
                    "config": artifact(
                        "experiments/pd_kv_ep/configs/ep_ep_minimal/"
                        "two_ep4_groups_a_only.json"),
                    "workload": artifact(
                        "experiments/pd_kv_ep/workloads/"
                        "two_ep4_groups_a_only_4req.jsonl"),
                    "request_count": 4,
                    "transient_request_output": "/tmp/ep_ep_minimal_a_only4_requests.csv",
                    "transient_telemetry_directory": "/tmp/ep_ep_minimal_a_only4",
                },
            ],
            "compact_results": "research_audit/02_MOTIVATION_RESULTS.csv",
            "raw_output_retention": "scratch under /tmp; not archived in repository",
            "interpretation": "Shared-link contention exists; serving effect below 1% TPOT/TBT. Capability PASS, motivation NO-GO.",
        },
        "runtime": {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "protobuf_implementation": os.environ.get(
                "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "default"),
            "chakra_import_path": "/tmp/llmsim-chakra-shim.TzDOXs (temporary, environment-specific)",
        },
        "post_fix_diagnostics": [
            {
                "run_group": "decode-completion-wakeup-post-fix",
                "backend": "integrated FlowSim fluid model",
                "worktree_source_binding": "same dirty worktree as repository tracked diff hash",
                "exact_original_argv": "NOT_PRESERVED; canonical rerun recipe is in 01_REPRODUCIBILITY.md",
                "config": artifact("experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json"),
                "workload": artifact("experiments/pd_kv_ep/workloads/minimal_ep4_then_kv8192.jsonl"),
                "fair_outputs": file_records([
                    "research_audit/results/minimal_ep4_then_kv8192_wakefix/requests.csv",
                    "research_audit/results/minimal_ep4_then_kv8192_wakefix/collective_telemetry.jsonl",
                    "research_audit/results/minimal_ep4_then_kv8192_wakefix/kv_event_telemetry.jsonl",
                    "research_audit/results/minimal_ep4_then_kv8192_wakefix/link_telemetry.jsonl",
                ]),
                "kv_isolated_outputs": file_records([
                    "research_audit/results/minimal_ep4_then_kv8192_wakefix_kv_isolated/requests.csv",
                    "research_audit/results/minimal_ep4_then_kv8192_wakefix_kv_isolated/collective_telemetry.jsonl",
                    "research_audit/results/minimal_ep4_then_kv8192_wakefix_kv_isolated/kv_event_telemetry.jsonl",
                    "research_audit/results/minimal_ep4_then_kv8192_wakefix_kv_isolated/link_telemetry.jsonl",
                ]),
                "interpretation": "Post-fix matched controlled result; overlap exists, EP CCT P99 +1.08%, TTFT/KV-ready unchanged, Decode TPOT delta <0.01%. The isolated case uses independent virtual link copies and is not deployable.",
            },
            {
                "run_group": "kv-kv-size-skew",
                "backend": "integrated FlowSim fluid model",
                "worktree_source_binding": "same dirty worktree as repository tracked diff hash",
                "exact_original_argv": "Recorded for the 32+128 case in 01_REPRODUCIBILITY.md; larger-pair original argv was not preserved",
                "config": artifact("experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json"),
                "workloads": file_records([
                    "experiments/pd_kv_ep/workloads/minimal_kv_kv_distinct_sizes.jsonl",
                    "experiments/pd_kv_ep/workloads/minimal_kv_kv_i128_i2048.jsonl",
                    "experiments/pd_kv_ep/workloads/minimal_kv_kv_i128_i8192.jsonl",
                ]),
                "outputs": file_records([
                    "research_audit/results/minimal_kv_kv_distinct_sizes/requests.csv",
                    "research_audit/results/minimal_kv_kv_distinct_sizes/kv_event_telemetry.jsonl",
                    "research_audit/results/minimal_kv_kv_i128_i2048/requests.csv",
                    "research_audit/results/minimal_kv_kv_i128_i2048/kv_event_telemetry.jsonl",
                    "research_audit/results/minimal_kv_kv_i128_i8192/requests.csv",
                    "research_audit/results/minimal_kv_kv_i128_i8192/kv_event_telemetry.jsonl",
                ]),
                "interpretation": "Request-level barrier/TTFT did not move even when the short request's per-shard FCT P99 rose 25.35%; one run per condition.",
            },
        ],
        "runs": [
            {
                "run_id": "time-unit-fix-flowsim-ep16-i1-o3-20261011",
                "backend": "integrated FlowSim fluid model",
                "scope": "corrected Chakra ns-to-us duration adaptation; one-request timing-unit smoke",
                "command": corrected_one_command,
                "config": artifact("experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json"),
                "workload": artifact("experiments/pd_kv_ep/workloads/moe_i1_o3_n1.jsonl"),
                "outputs": file_records([
                    "research_audit/results/time_unit_fix_flowsim_ep16_i1_o3.csv",
                    "research_audit/results/time_unit_fix_flowsim_ep16_i1_o3.jsonl.gz",
                    "research_audit/results/time_unit_fix_flowsim_ep16_i1_o3_collectives.jsonl.gz",
                    "research_audit/results/time_unit_fix_flowsim_ep16_i1_o3_links.jsonl.gz",
                ]),
                "interpretation": "TTFT/TPOT/ITL are valid raw outputs for this corrected simulator path; one request is only a smoke, not a contention or SLO result.",
            },
            {
                "run_id": "time-unit-fix-two-req-20261011",
                "backend": "integrated FlowSim fluid model",
                "scope": "controlled cross-request P2D/EP overlap with model-derived traffic; matched to same-arrival KV-only control",
                "command": corrected_full_command,
                "config": artifact("experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json"),
                "workload": artifact("experiments/pd_kv_ep/workloads/minimal_time_unit_corrected_kv_ep_overlap.jsonl"),
                "outputs": file_records([
                    "research_audit/results/time_unit_fix_two_req/requests.csv",
                    "research_audit/results/time_unit_fix_two_req/flows.jsonl.gz",
                    "research_audit/results/time_unit_fix_two_req/collective_telemetry.jsonl.gz",
                    "research_audit/results/time_unit_fix_two_req/link_telemetry.jsonl.gz",
                    "research_audit/results/time_unit_fix_two_req/kv_event_telemetry.jsonl",
                ]),
                "interpretation": "Actual same-directed-link active interval overlap is present. Matched effects are small: EP CCT P99 about +1.08%, KV shard FCT mean/P99 about +3.88%/+3.17%, and no meaningful TTFT/TBT change. Controlled mechanism evidence only.",
            },
            {
                "run_id": "time-unit-fix-kv-control-20261011",
                "backend": "integrated FlowSim fluid model",
                "scope": "same KV request and absolute arrival as controlled FULL run, without Decode background request",
                "command": corrected_kv_command,
                "config": artifact("experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json"),
                "workload": artifact("experiments/pd_kv_ep/workloads/minimal_time_unit_corrected_kv_control.jsonl"),
                "outputs": file_records([
                    "research_audit/results/time_unit_fix_kv_control/requests.csv",
                    "research_audit/results/time_unit_fix_kv_control/flows.jsonl.gz",
                    "research_audit/results/time_unit_fix_kv_control/collective_telemetry.jsonl.gz",
                    "research_audit/results/time_unit_fix_kv_control/link_telemetry.jsonl.gz",
                    "research_audit/results/time_unit_fix_kv_control/kv_event_telemetry.jsonl",
                ]),
                "interpretation": "Matched KV-only control; request handoff and TTFT equal the FULL run in this controlled point. Not a general no-contention conclusion.",
            },
            {
                "run_id": "ns3-corrected-full-moe-layer-108-20261011",
                "backend": "native ns-3 packet replay, CC_MODE=1 (DCQCN), 4096-byte payload",
                "scope": "network-only matched FULL/EP_ONLY/KV_ONLY replay of 96 model-derived P2D shards plus one complete MoE-layer dispatch and combine pair; FULL repeated once",
                "command": corrected_ns3_command,
                "topology": artifact("experiments/pd_kv_ep/configs/large_scale/ns3/minimal_1p2d_ep16_logical_ranks_single_tor.txt"),
                "template": artifact("experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf"),
                "generated_inputs": file_records([
                    "research_audit/results/ns3_corrected_full_moe_layer_108/input/events.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/input/rank_to_nic_map.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/input/replay_manifest.json",
                ]),
                "outputs": file_records([
                    "research_audit/results/ns3_corrected_full_moe_layer_108/matched_network_summary.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/full/comm_events.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/full/link_summary.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/full/fct.txt",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/full/cc_events.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/ep_only/comm_events.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/ep_only/link_summary.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/kv_only/comm_events.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/kv_only/link_summary.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/full_repeat/comm_events.csv",
                    "research_audit/results/ns3_corrected_full_moe_layer_108/full_repeat/link_summary.csv",
                ]),
                "binary": artifact("astra-sim/extern/network_backend/ns-3/build/scratch/ns3.42-KVEPReplay-optimized"),
                "interpretation": "FULL vs EP_ONLY network CCT rises 7.11% (dispatch) and 7.20% (combine); P2D message mean FCT rises 0.16%, P99 is unchanged. The 200-Gbps ToR-to-NIC NetDevice TX queue peak is 121404 B in FULL vs 70244 B EP_ONLY and 4132 B KV_ONLY; ECN/PFC/drop/CNP/rate-change are absent. Packet replay has no serving scheduler feedback and cannot produce TTFT/TBT.",
            },
            {
                "run_id": "baseline-flowsim-handoff-fix-20261011",
                "status": "INVALIDATED_TIME_UNIT",
                "backend": "integrated FlowSim fluid model",
                "scope": "two-request serving lifecycle/cross-phase smoke; zero KV/EP service overlap on common directed links",
                "command": flowsim_command,
                "config": artifact("experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json"),
                "workload": artifact("experiments/pd_kv_ep/workloads/minimal_cross_request_ep_round_aligned.jsonl"),
                "outputs": file_records([
                    "research_audit/results/current_baseline_flowsim_handoff_fix.csv",
                    "research_audit/results/current_baseline_flowsim_handoff_fix.jsonl.gz",
                ]),
                "interpretation": "Serving metrics are real outputs of the current simulator run but are not a contention/tail/SLO result; traffic uses AG/RS, not exact routed A2A.",
            },
            {
                "run_id": "ns3-packet-smoke-minimal-logical-20261011-reproduced",
                "status": "INVALIDATED_RELEASE_TIMES",
                "backend": "native ns-3 KVEPReplay, CC_MODE=1 DCQCN",
                "scope": "bounded packet/network-only replay; no scheduler feedback; deterministic artifacts across two runs",
                "command": ns3_command,
                "topology": artifact("experiments/pd_kv_ep/configs/large_scale/ns3/minimal_1p2d_ep16_logical_ranks_single_tor.txt"),
                "template": artifact("experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf"),
                "generated_inputs": file_records([
                    "research_audit/results/ns3_packet_smoke_minimal_logical_20261011/input/events.csv",
                    "research_audit/results/ns3_packet_smoke_minimal_logical_20261011/input/rank_to_nic_map.csv",
                    "research_audit/results/ns3_packet_smoke_minimal_logical_20261011/input/replay_manifest.json",
                ]),
                "outputs": file_records([
                    "research_audit/results/ns3_packet_smoke_minimal_logical_20261011_reproduced/fct.txt",
                    "research_audit/results/ns3_packet_smoke_minimal_logical_20261011_reproduced/comm_events.csv",
                    "research_audit/results/ns3_packet_smoke_minimal_logical_20261011_reproduced/link_summary.csv",
                    "research_audit/results/ns3_packet_smoke_minimal_logical_20261011_reproduced/cc_events.csv",
                    "research_audit/results/ns3_packet_smoke_minimal_logical_20261011_reproduced/network_run_manifest.json",
                ]),
                "binary": artifact("astra-sim/extern/network_backend/ns-3/build/scratch/ns3.42-KVEPReplay-optimized"),
                "interpretation": "Message completion/path smoke only; not request KV FCT, EP CCT, TTFT, TPOT, TBT, or switch-MMU queue validation.",
            },
        ],
        "superseded_evidence": [
            {
                "artifact_prefix": "current_baseline_flowsim_* and prior integrated serving outputs using raw ns profile durations as Chakra duration_micros",
                "status": "INVALIDATED_TIME_UNIT",
                "reason": "Serving trace computation was converted from profile microseconds to nanoseconds, but the Chakra adapter passed the nanosecond integer directly into duration_micros. Recovered by trace_generator.indexed_cols conversion and fixed-point reruns above. Do not cite old simulated latency, overlap, or serving metrics.",
            },
            {
                "artifact_prefix": "ns-3 replay slices whose event timestamps were sourced from pre-fix FlowSim timing",
                "status": "INVALIDATED_RELEASE_TIMES",
                "reason": "Packet inputs may retain bytes/endpoints but their release-time alignment derives from invalid integrated timing. Rebuild packet slices from corrected FlowSim ledger before timing/overlap comparisons.",
            },
            {
                "artifact_prefix": "research_audit/results/ns3_corrected_overlap_collective1082/",
                "status": "SUPERSEDED_INCOMPLETE_COLLECTIVE_SLICE",
                "reason": "This corrected-timestamp replay included only EP dispatch, not its matching combine. It is retained as a debug artifact; the full-layer matched replay including collectives 1082 and 1103 is authoritative for packet network timing.",
            },
        ],
    }

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(str(output))
    print("HEAD=%s" % manifest["repository"]["head"])
    print("dirty_paths=%d" % len(status))
    print("tracked_diff_sha256=%s" % manifest["repository"]["tracked_binary_diff_sha256"])


if __name__ == "__main__":
    main()
