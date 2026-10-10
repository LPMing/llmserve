#!/usr/bin/env python3
"""Run a bounded real-trace slice with auditable estimates and provenance."""

import argparse
import csv
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODEL_CONFIG = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
_ACTIVE_PROCESS = None


def _important_log_line(line):
    """Keep summary/error lines while dropping per-rank/per-iteration chatter."""
    markers = (
        "Starting simulation", "Simulation results", "Total simulation time",
        "Total requests:", "Total clocks", "Total latency", "Total input tokens",
        "Total generated tokens", "Request throughput", "Average prompt throughput",
        "Average generation throughput", "Total token throughput", "Saving each request",
        "All Request Has Been Exited", "ERROR", "Error", "WARNING",
    )
    return any(marker in line for marker in markers)


def _stop_process(process, force=False):
    """Stop the serving frontend and its ASTRA child process group."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_compact(command, cwd, env, log_path, timeout_s):
    """Run the frontend while retaining only concise stdout diagnostics."""
    global _ACTIVE_PROCESS
    process = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=env,
        start_new_session=(os.name == "posix"))
    _ACTIVE_PROCESS = process
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    try:
        with log_path.open("w", encoding="utf-8") as log:
            log.write("# compact large-scale simulator log\n")
            log.write("# per-controller-iteration output is intentionally suppressed\n")
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    _stop_process(process)
                    raise subprocess.TimeoutExpired(command, timeout_s)
                events = selector.select(timeout=1.0)
                if not events:
                    if process.poll() is not None:
                        break
                    continue
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                if _important_log_line(line):
                    log.write(line)
                    log.flush()
            return process.wait()
    finally:
        _ACTIVE_PROCESS = None


def _model_estimate(cluster_path, rows):
    with MODEL_CONFIG.open(encoding="utf-8") as stream:
        model = json.load(stream)
    with cluster_path.open(encoding="utf-8") as stream:
        cluster = json.load(stream)
    fp = 2
    layers = int(model["num_hidden_layers"])
    kv_heads = int(model.get("num_key_value_heads", model["num_attention_heads"]))
    head_dim = int(model.get("head_dim", model["hidden_size"] // model["num_attention_heads"]))
    # Use the actual configured Decode EP degree for this run.  This is only
    # a planning estimate; exact EP communication comes from simulator events.
    tp = 2
    kv_bytes_per_input_token_all_prefill_ranks = (
        layers * 2 * (kv_heads * head_dim // tp) * fp * tp
    )
    total_input = sum(int(row["input_toks"]) for row in rows)
    total_output = sum(int(row["output_toks"]) for row in rows)
    active_decode_tokens = sum(1 for row in rows if int(row["output_toks"]) > 0)
    # This is a planning estimate only.  Exact EP bytes come from the GateRouter
    # route matrix in the generated trace and are recorded by the simulator.
    decode_ep_degrees = sorted({
        int(instance.get("ep_size", instance.get("tp_size", 1)))
        for node in cluster.get("nodes", ())
        for instance in node.get("instances", ())
        if str(instance.get("pd_type", "")).lower() == "decode"
    })
    ep_degree = decode_ep_degrees[0] if len(decode_ep_degrees) == 1 else 1
    top_k = int(model.get("num_experts_per_tok", 1))
    hidden = int(model["hidden_size"])
    estimated_ep_per_step = active_decode_tokens * top_k * hidden * fp * 2 * (ep_degree - 1) / ep_degree
    return {
        "model": str(model.get("architectures", ["unknown"])[0]),
        "layers": layers,
        "kv_heads": kv_heads,
        "head_dim": head_dim,
        "kv_bytes_per_input_token_all_prefill_ranks": kv_bytes_per_input_token_all_prefill_ranks,
        "request_count": len(rows),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "estimated_p2d_kv_bytes": total_input * kv_bytes_per_input_token_all_prefill_ranks,
        "estimated_active_decode_requests": active_decode_tokens,
        "configured_decode_ep_degrees": decode_ep_degrees,
        "estimated_ep_bytes_per_decode_step": int(estimated_ep_per_step),
        "estimate_kind": "planning_only_model_formula; exact EP bytes are measured from generated collectives",
        "estimate_is_synthetic_override": False,
    }


def _load_rows(path, limit, offset=0):
    if limit <= 0:
        raise ValueError(
            "real-trace replay requires an explicit positive --num-reqs; "
            "full-trace execution is disabled")
    rows = []
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index < offset:
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    if not rows:
        raise ValueError(f"trace slice is empty: {path}")
    return rows


def _rebase_and_scale_arrivals(rows, interval_scale):
    """Rebase a selected slice and scale only its inter-arrival timeline.

    Request order, token counts, session/prefix fields, and source provenance
    are left unchanged.  A scale below one compresses the intervals (higher
    offered load); a scale above one expands them.  The original timestamp is
    retained in the replay row so the transformation is auditable.
    """
    if interval_scale <= 0:
        raise ValueError("arrival interval scale must be positive")
    first = int(rows[0]["arrival_time_ns"])
    previous = -1
    scaled_rows = []
    for row in rows:
        copied = dict(row)
        original = int(row["arrival_time_ns"])
        arrival = int(round((original - first) * interval_scale))
        if arrival < previous:
            raise ValueError("scaled arrival order is not monotonic")
        copied["source_arrival_time_ns"] = original
        copied["arrival_time_ns"] = arrival
        scaled_rows.append(copied)
        previous = arrival
    return scaled_rows


def _source_trace_count(rows):
    """Return the converted source count without rescanning a huge JSONL file."""
    source_traces = sorted({row.get("source_trace") for row in rows if row.get("source_trace")})
    if len(source_traces) != 1:
        return None
    source = Path(source_traces[0])
    stats_path = source.with_name("conversion_stats.json")
    if not stats_path.is_file():
        return None
    try:
        with stats_path.open(encoding="utf-8") as stream:
            return int(json.load(stream)["request_count"])
    except (OSError, KeyError, TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--cluster-config", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=("analytical", "ns3", "htsim", "flowsim"), default="analytical")
    parser.add_argument("--htsim-topology", type=Path, default=None,
                        help="optional HTSim FatTree topology; cluster ns3_topology is used by default")
    parser.add_argument("--htsim-mtu", type=int, default=4096)
    parser.add_argument("--htsim-queue-sample-us", type=int, default=100)
    parser.add_argument("--num-reqs", type=int, default=0)
    parser.add_argument("--request-offset", type=int, default=0,
                        help="bounded offset within the selected trace window")
    parser.add_argument(
        "--load-scale", type=float, default=1.0,
        help="multiply offered arrival rate; 0.5=half load, 2.0=double load")
    parser.add_argument(
        "--max-sim-reqs", type=int, default=25_000,
        help="hard safety cap for a replay; full production traces are never run")
    parser.add_argument("--output-root", type=Path,
                        default=ROOT / "experiments/pd_kv_ep/results/real_trace",
                        help="artifact directory; defaults to the experiment tree")
    parser.add_argument("--ep-semantics", choices=("NATIVE_AG_RS", "A2A", "A2A_P2P"),
                        default="A2A_P2P")
    parser.add_argument("--policy", choices=("FAIR", "KV_FIRST", "EP_FIRST"),
                        default="FAIR")
    parser.add_argument("--remote-kv-plan", type=Path, default=None,
                        help="optional FlowSim model-derived remote-KV plan")
    parser.add_argument("--remote-kv-mode",
                        choices=("LEGACY", "REMOTE_PREFIX_PD_BASELINE",
                                 "SPLIT_SOURCE_KV_ASSEMBLY"),
                        default="LEGACY",
                        help="remote-KV dependency semantics for FlowSim")
    parser.add_argument("--pd-kv-mode", choices=("LAYERWISE", "POST_PREFILL"),
                        default="POST_PREFILL")
    parser.add_argument("--pd-receiver-mode", choices=("ACTUAL", "SHADOW"),
                        default="ACTUAL")
    parser.add_argument("--pd-pairing-map", type=Path, default=None,
                        help="offline P/D pairing map for matched fan-in serving control")
    parser.add_argument("--disable-prefix-caching", action="store_true")
    parser.add_argument("--disable-chunked-prefill", action="store_true",
                        help="run each prompt as one scheduler prefill batch")
    parser.add_argument("--keep-inputs", action="store_true",
                        help="retain ASTRA inputs for backend replay/debugging")
    parser.add_argument("--max-num-seqs", type=int, default=128)
    parser.add_argument("--max-num-batched-tokens", type=int, default=4096)
    parser.add_argument("--block-size", type=int, default=None,
                        help="Override simulator KV block size; Mooncake runs must use 512")
    parser.add_argument("--log-level", choices=("WARNING", "INFO", "DEBUG"), default="WARNING")
    parser.add_argument("--log-interval", type=float, default=60.0,
                        help="serving summary interval in seconds; large traces default to 60s")
    parser.add_argument("--network-telemetry", choices=("none", "summary", "validation"),
                        default="summary",
                        help="summary keeps link_summary only; validation enables flow/timeseries logs")
    parser.add_argument(
        "--serving-iteration-telemetry", action="store_true",
        help="write per-Decode-iteration timing sidecar for barrier attribution")
    parser.add_argument(
        "--preserve-flowsim-events", action="store_true",
        help="retain bounded FlowSim KV/collective/link sidecars outside temporary inputs")
    parser.add_argument(
        "--omit-flow-detail-telemetry", action="store_true",
        help="when preserving FlowSim events, omit the per-flow JSONL ledger; "
             "KV, collective, and bounded link telemetry remain available")
    parser.add_argument(
        "--omit-a2a-route-audit", action="store_true",
        help="skip observational per-batch A2A route JSON sidecars to reduce replay I/O")
    parser.add_argument(
        "--network-telemetry-interval-ms", type=float, default=1000.0,
        help="sampling interval for native link_timeseries output; default 1000 ms")
    parser.add_argument(
        "--ns3-binary", type=Path, default=None,
        help="optional explicit ns-3 AstraSimNetwork binary (for example the optimized build)")
    parser.add_argument(
        "--packet-payload-size", type=int, default=None,
        help="native ns-3 packet payload override in bytes; default keeps 1000-byte template value")
    parser.add_argument(
        "--controller-trace", action="store_true",
        help="retain verbose frontend/controller IPC trace; disabled by default even in validation")
    parser.add_argument("--timeout-s", type=float, default=None,
                        help="optional wall-clock timeout; timeout is recorded, not a result")
    parser.add_argument(
        "--allow-small-gate", action="store_true",
        help="allow a <=8-server one-request communication gate; never use it for trace results")
    parser.add_argument(
        "--allow-integrated-gate", action="store_true",
        help="allow a bounded integrated serving validation on a small topology; "
             "not a large-scale trace mode")
    args = parser.parse_args()

    if args.preserve_flowsim_events and args.backend != "flowsim":
        parser.error("--preserve-flowsim-events requires --backend=flowsim")
    if args.network_telemetry_interval_ms <= 0:
        parser.error("--network-telemetry-interval-ms must be positive")
    if args.packet_payload_size is not None and args.packet_payload_size <= 0:
        parser.error("--packet-payload-size must be positive")
    if args.max_sim_reqs <= 0:
        parser.error("--max-sim-reqs must be positive")
    if args.request_offset < 0:
        parser.error("--request-offset must be non-negative")
    if args.load_scale <= 0:
        parser.error("--load-scale must be positive")
    if args.num_reqs <= 0:
        parser.error(
            "--num-reqs must be a positive bounded value; full-trace replay is disabled")
    if args.num_reqs > args.max_sim_reqs:
        parser.error(
            f"requested {args.num_reqs} requests exceeds the hard replay cap "
            f"of {args.max_sim_reqs}")

    trace = args.trace.resolve()
    cluster = args.cluster_config.resolve()
    try:
        cluster_server_count = int(json.loads(cluster.read_text(encoding="utf-8"))["num_nodes"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read cluster server count from {cluster}: {exc}")
    if cluster_server_count < 64:
        if not args.allow_small_gate and not args.allow_integrated_gate:
            parser.error(
                f"{cluster_server_count}-server config is a communication gate only; "
                "use --allow-integrated-gate only for bounded serving validation")
        if args.allow_small_gate and args.num_reqs != 1:
            parser.error("--allow-small-gate is restricted to exactly one request")
        if args.allow_integrated_gate and args.num_reqs > 512:
            parser.error("--allow-integrated-gate is restricted to at most 512 requests")
    interval_scale = 1.0 / args.load_scale
    rows = _rebase_and_scale_arrivals(
        _load_rows(trace, args.num_reqs, args.request_offset), interval_scale)
    pairing_map = args.pd_pairing_map.resolve() if args.pd_pairing_map else None
    if pairing_map is not None and not pairing_map.is_file():
        parser.error(f"--pd-pairing-map does not exist: {pairing_map}")
    remote_kv_plan = (args.remote_kv_plan.resolve()
                      if args.remote_kv_plan else None)
    if remote_kv_plan is not None and not remote_kv_plan.is_file():
        parser.error(f"--remote-kv-plan does not exist: {remote_kv_plan}")
    source_trace_count = _source_trace_count(rows)
    estimate = _model_estimate(cluster, rows)
    result_root = args.output_root.resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    manifest_path = result_root / f"{args.run_id}.manifest.json"
    replay_trace = result_root / f"{args.run_id}.replay.jsonl"
    output_csv = result_root / f"{args.run_id}.requests.csv"
    log_path = result_root / f"{args.run_id}.sim.log"
    ns3_binary = args.ns3_binary.resolve() if args.ns3_binary is not None else None
    if ns3_binary is not None and not ns3_binary.is_file():
        parser.error(f"--ns3-binary does not exist: {ns3_binary}")
    # serving/__main__.py changes into astra-sim and its existing path
    # conventions prepend ../ to dataset/cluster paths.  Pass repo-relative
    # paths to preserve that contract while retaining absolute paths in the
    # manifest for provenance.
    # Always materialize the selected rows.  The serving CLI supports a count
    # but not an offset; passing the source path directly would silently run
    # the first N records while the estimate described rows N..N+K.
    with replay_trace.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    trace_arg = os.path.relpath(replay_trace, ROOT)
    cluster_arg = os.path.relpath(cluster, ROOT)
    command = [
        sys.executable, "-m", "serving",
        "--cluster-config", cluster_arg,
        "--dataset", trace_arg,
        "--num-reqs", str(args.num_reqs),
        "--output", str(output_csv),
        "--run-id", args.run_id,
        "--network-backend", args.backend,
        "--ep-collective-semantics", args.ep_semantics,
        "--kv-ep-network-policy", args.policy,
        "--pd-kv-transfer-mode", args.pd_kv_mode,
        "--pd-kv-receiver-mode", args.pd_receiver_mode,
        "--max-num-seqs", str(args.max_num_seqs),
        "--max-num-batched-tokens", str(args.max_num_batched_tokens),
        "--log-interval", str(args.log_interval),
        "--log-level", args.log_level,
    ]
    if remote_kv_plan is not None:
        command.extend(["--flowsim-remote-kv-plan", str(remote_kv_plan)])
        command.extend(["--flowsim-remote-kv-mode", args.remote_kv_mode])
    if args.backend == "htsim":
        if args.htsim_topology is not None:
            command.extend(["--htsim-topology", str(args.htsim_topology.resolve())])
        command.extend([
            "--htsim-mtu", str(args.htsim_mtu),
            "--htsim-queue-sample-us", str(args.htsim_queue_sample_us),
        ])
    if pairing_map is not None:
        command.extend(["--pd-pairing-map", str(pairing_map)])
    if args.packet_payload_size is not None:
        command.extend(["--packet-payload-size", str(args.packet_payload_size)])
    if args.block_size is not None:
        command.extend(["--block-size", str(args.block_size)])
    if args.disable_prefix_caching:
        command.append("--no-enable-prefix-caching")
    if args.disable_chunked_prefill:
        command.append("--no-enable-chunked-prefill")
    if args.keep_inputs:
        command.append("--keep-inputs")
    manifest = {
        "run_id": args.run_id,
        "trace": str(trace),
        "replay_trace": str(replay_trace),
        "cluster_config": str(cluster),
        "cluster_server_count": cluster_server_count,
        "scale_scope": "S64/S256_TRACE" if cluster_server_count >= 64 else "S4/S8_GATE",
        "small_gate_only": cluster_server_count < 64,
        "pd_pairing_map": str(pairing_map) if pairing_map is not None else None,
        "remote_kv_plan": str(remote_kv_plan) if remote_kv_plan is not None else None,
        "remote_kv_mode": args.remote_kv_mode,
        "backend": args.backend,
        "htsim_topology": str(args.htsim_topology.resolve()) if args.htsim_topology else None,
        "htsim_mtu": args.htsim_mtu,
        "htsim_queue_sample_us": args.htsim_queue_sample_us,
        "ep_semantics": args.ep_semantics,
        "kv_ep_network_policy": args.policy,
        "pd_kv_transfer_mode": args.pd_kv_mode,
        "pd_kv_receiver_mode": args.pd_receiver_mode,
        "prefix_caching_disabled": args.disable_prefix_caching,
        "chunked_prefill_disabled": args.disable_chunked_prefill,
        "block_size": args.block_size,
        "hard_replay_cap": args.max_sim_reqs,
        "network_telemetry": args.network_telemetry,
        "serving_iteration_telemetry": args.serving_iteration_telemetry,
        "preserve_flowsim_events": args.preserve_flowsim_events,
        "flow_detail_telemetry": (
            args.preserve_flowsim_events and
            not args.omit_flow_detail_telemetry),
        "a2a_route_audit_enabled": not args.omit_a2a_route_audit,
        "network_telemetry_interval_ms": args.network_telemetry_interval_ms,
        "packet_payload_size": args.packet_payload_size,
        "compact_logs": True,
        "controller_trace": args.controller_trace,
        "ns3_binary": str(ns3_binary) if ns3_binary is not None else None,
        "log_interval_s": args.log_interval,
        "trace_request_count": len(rows),
        "simulated_request_count": len(rows),
        "request_offset": args.request_offset,
        "load_scale": args.load_scale,
        "arrival_interval_scale": interval_scale,
        "source_trace_request_count": source_trace_count,
        "command": command,
        "source_trace_provenance": sorted({row.get("source_trace") for row in rows}),
        "estimate": estimate,
        "started_at_unix": time.time(),
        "status": "RUNNING",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _abort_on_signal(signum, _frame):
        """Persist an auditable state if the wrapper receives a termination signal."""
        global _ACTIVE_PROCESS
        if _ACTIVE_PROCESS is not None and _ACTIVE_PROCESS.poll() is None:
            _stop_process(_ACTIVE_PROCESS, force=True)
        manifest["finished_at_unix"] = time.time()
        manifest["status"] = "ABORTED"
        manifest["returncode"] = 128 + signum
        try:
            signal_name = signal.Signals(signum).name
        except ValueError:
            signal_name = str(signum)
        manifest["abort_reason"] = f"signal_{signal_name.lower()}"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _abort_on_signal)
    signal.signal(signal.SIGTERM, _abort_on_signal)
    sim_env = os.environ.copy()
    compat = "/tmp/llmservingsim-compat"
    chakra = str(ROOT / "astra-sim/extern/graph_frontend")
    sim_pythonpath = sim_env.get("PYTHONPATH", "")
    sim_env["PYTHONPATH"] = ":".join(
        value for value in (chakra, compat, str(ROOT), sim_pythonpath) if value)
    sim_env.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
    sim_env["LLMSERVINGSIM_NETWORK_TELEMETRY"] = args.network_telemetry
    sim_env["LLMSERVINGSIM_NETWORK_TELEMETRY_INTERVAL_MS"] = str(
        args.network_telemetry_interval_ms)
    sim_env["LLMSERVINGSIM_COMPACT_LOGS"] = "1"
    if args.omit_a2a_route_audit:
        sim_env["LLMSERVINGSIM_SAVE_A2A_ROUTE_AUDIT"] = "0"
    else:
        sim_env.pop("LLMSERVINGSIM_SAVE_A2A_ROUTE_AUDIT", None)
    if args.backend == "flowsim" and args.preserve_flowsim_events:
        flowsim_result_dir = result_root / f"{args.run_id}.flowsim"
        flowsim_result_dir.mkdir(parents=True, exist_ok=True)
        flow_telemetry_path = flowsim_result_dir / "flow_telemetry.jsonl"
        sim_env["LLMSERVINGSIM_FLOWSIM_TELEMETRY_PATH"] = str(
            flow_telemetry_path)
        manifest["flowsim_telemetry_path"] = str(flow_telemetry_path)
        manifest_path.write_text(json.dumps(manifest, indent=2),
                                 encoding="utf-8")
    else:
        sim_env.pop("LLMSERVINGSIM_FLOWSIM_TELEMETRY_PATH", None)
    if args.backend == "flowsim" and args.omit_flow_detail_telemetry:
        sim_env["FLOWSIM_FLOW_TELEMETRY"] = "0"
    if args.serving_iteration_telemetry:
        sim_env["LLMSERVINGSIM_SAVE_DECODE_ITERATIONS"] = "1"
    else:
        sim_env.pop("LLMSERVINGSIM_SAVE_DECODE_ITERATIONS", None)
    if ns3_binary is not None:
        sim_env["LLMSERVINGSIM_NS3_BINARY"] = str(ns3_binary)
    else:
        sim_env.pop("LLMSERVINGSIM_NS3_BINARY", None)
    if args.network_telemetry == "validation":
        sim_env["ASTRA_ISSUE_LOG"] = str(result_root / f"{args.run_id}.astra_issue.csv")
        if args.controller_trace:
            sim_env["LLMSERVINGSIM_CONTROLLER_TRACE"] = str(
                result_root / f"{args.run_id}.controller.log")
        else:
            sim_env.pop("LLMSERVINGSIM_CONTROLLER_TRACE", None)
    else:
        sim_env.pop("ASTRA_ISSUE_LOG", None)
        sim_env.pop("LLMSERVINGSIM_CONTROLLER_TRACE", None)
    try:
        process_returncode = _run_compact(
            command, ROOT, sim_env, log_path, args.timeout_s)
    except subprocess.TimeoutExpired:
        manifest["finished_at_unix"] = time.time()
        manifest["status"] = "TIMEOUT"
        manifest["returncode"] = 124
        manifest["timeout_s"] = args.timeout_s
        manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": "TIMEOUT",
            "returncode": 124,
            "manifest": str(manifest_path),
            "log": str(log_path),
        }, indent=2))
        raise SystemExit(124)
    except KeyboardInterrupt:
        manifest["finished_at_unix"] = time.time()
        manifest["status"] = "ABORTED"
        manifest["returncode"] = 130
        manifest["abort_reason"] = "operator_or_session_interrupt"
        manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": "ABORTED",
            "returncode": 130,
            "manifest": str(manifest_path),
            "log": str(log_path),
        }, indent=2))
        raise SystemExit(130)
    manifest["finished_at_unix"] = time.time()
    manifest["returncode"] = process_returncode
    manifest["status"] = "PASS" if process_returncode == 0 else "FAIL"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "returncode": process_returncode,
        "manifest": str(manifest_path),
        "requests_csv": str(output_csv),
        "log": str(log_path),
        "estimate": estimate,
    }, indent=2))
    raise SystemExit(process_returncode)


if __name__ == "__main__":
    main()
