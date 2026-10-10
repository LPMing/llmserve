#!/usr/bin/env python3
"""Run native request-driven LLMServingSim smoke scenarios.

This wrapper never accepts a byte-sized KV or EP override. It varies request
tokens and lets the simulator derive communication from the model.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {
    "colocated": "configs/cluster/single_node_single_instance.json",
    "pd": "configs/cluster/single_node_pd_instance.json",
    "kv_only": "experiments/pd_kv_ep/configs/small_qwen_pd.json",
    "moe": "configs/cluster/single_node_moe_single_instance.json",
    "ep_only": "experiments/pd_kv_ep/configs/small_moe_ep.json",
    "pd_moe": "configs/cluster/single_node_moe_pd_instance.json",
    "mixed": "experiments/pd_kv_ep/configs/small_pd_moe_ep.json",
}


def make_workload(path, count, input_tokens, output_tokens, interval_us):
    """Write a deterministic token workload; bytes are not part of its schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(count):
        arrival = index * interval_us * 1000
        input_ids = list(range(1, input_tokens + 1))
        output_ids = list(range(input_tokens + 1, input_tokens + output_tokens + 1))
        rows.append({
            "input_toks": input_tokens,
            "output_toks": output_tokens,
            "arrival_time_ns": arrival,
            "input_tok_ids": input_ids,
            "output_tok_ids": output_ids,
        })
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="moe")
    parser.add_argument("--cluster-config", type=Path,
                        help="optional repository-relative cluster config override")
    parser.add_argument("--workload", type=Path, default=ROOT / "workloads/example_trace.jsonl")
    parser.add_argument("--generate", action="store_true",
                        help="generate a native token workload under results/workloads")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--input-toks", type=int, default=1024)
    parser.add_argument("--output-toks", type=int, default=128)
    parser.add_argument("--interval-us", type=int, default=10000)
    parser.add_argument("--network-backend", default="ns3",
                        choices=("analytical", "ns3", "htsim"))
    parser.add_argument("--kv-ep-network-policy", default="FAIR",
                        choices=("FAIR", "KV_FIRST", "EP_FIRST"),
                        help="data-plane-only arbitration class for native ns-3")
    parser.add_argument("--ep-collective-semantics", default="NATIVE_AG_RS",
                        choices=("NATIVE_AG_RS", "A2A", "A2A_P2P"),
                        help="native AG/RS, padded ASTRA ALLTOALL, or exact routed P2P A2A")
    parser.add_argument("--pd-kv-transfer-mode", default="LAYERWISE",
                        choices=("LAYERWISE", "POST_PREFILL"),
                        help="upstream-compatible layerwise P2D or an explicit "
                        "model-derived post-prefill cache chunk")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--num-reqs", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-unsupported-mixed", action="store_true",
                        help="retained for compatibility; mixed is now validated")
    args = parser.parse_args()

    workload = args.workload.resolve()
    if args.generate:
        workload = ROOT / "experiments/pd_kv_ep/workloads" / (
            "%s_i%s_o%s_n%s.jsonl" % (args.scenario, args.input_toks,
                                        args.output_toks, args.count))
        make_workload(workload, args.count, args.input_toks,
                      args.output_toks, args.interval_us)

    config = (args.cluster_config.resolve() if args.cluster_config else
              ROOT / SCENARIOS[args.scenario])
    run_id = args.run_id or "pd-kv-ep-%s" % args.scenario
    output = (args.output or ROOT / "experiments/pd_kv_ep/results" /
              (run_id + ".csv")).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # serving resolves repository inputs relative to its ASTRA working tree;
    # pass repository-relative paths just like the official run.sh examples.
    config_arg = str(config.relative_to(ROOT))
    try:
        workload_arg = str(workload.relative_to(ROOT))
    except ValueError:
        workload_arg = str(workload)
    command = [
        sys.executable, "-m", "serving",
        "--cluster-config", config_arg,
        "--dataset", workload_arg,
        "--network-backend", args.network_backend,
        "--kv-ep-network-policy", args.kv_ep_network_policy,
        "--ep-collective-semantics", args.ep_collective_semantics,
        "--pd-kv-transfer-mode", args.pd_kv_transfer_mode,
        "--run-id", run_id,
        "--keep-inputs",
        "--output", str(output),
    ]
    if args.num_reqs is not None:
        command.extend(["--num-reqs", str(args.num_reqs)])
    command.append("--save-trace-text")

    print(json.dumps({
        "scenario": args.scenario,
        "native_workload": True,
        "synthetic_byte_override": False,
        "kv_ep_network_policy": args.kv_ep_network_policy,
        "ep_collective_semantics": args.ep_collective_semantics,
        "config": config_arg,
        "workload": workload_arg,
        "command": command,
    }, indent=2))
    if not args.dry_run:
        environment = os.environ.copy()
        source_chakra = ROOT / "astra-sim" / "extern" / "graph_frontend"
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(source_chakra), environment.get("PYTHONPATH", "")])
        if args.network_backend == "ns3":
            event_log = output.with_suffix(".astra_events.csv")
            environment["ASTRA_ISSUE_LOG"] = str(event_log)
            print(json.dumps({"backend_event_log": str(event_log)}))
        subprocess.run(command, cwd=str(ROOT), check=True, env=environment)
        if args.network_backend == "ns3":
            input_root = ROOT / "astra-sim" / "inputs" / "runs" / run_id
            comm_events = input_root / "ns3" / "output" / "comm_events.csv"
            traces = sorted(input_root.glob("trace/**/instance*_batch*.txt"))
            if comm_events.exists() and traces and event_log.exists():
                timeline = output.with_suffix(".timeline.csv")
                audit_command = [
                    sys.executable,
                    str(ROOT / "experiments/pd_kv_ep/audit_trace.py"),
                    str(traces[0]),
                    "--comm-events", str(comm_events),
                    "--astra-events", str(event_log),
                    "--timeline", str(timeline),
                    "--link-summary", str(input_root / "ns3" / "output" /
                                         "link_summary.csv"),
                    "--directed-link-overlap", str(output.with_suffix(
                        ".directed_link_overlap.csv")),
                ]
                subprocess.run(audit_command, cwd=str(ROOT), check=True,
                               env=environment)
                figure = ROOT / "experiments/pd_kv_ep/figures" / (
                    run_id + "_timeline.png")
                plot_command = [
                    sys.executable,
                    str(ROOT / "experiments/pd_kv_ep/plot_results.py"),
                    str(timeline), "--output", str(figure),
                ]
                subprocess.run(plot_command, cwd=str(ROOT), check=False,
                               env=environment)


if __name__ == "__main__":
    main()
