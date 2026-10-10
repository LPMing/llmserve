#!/usr/bin/env python3
"""Run a bounded model-derived event replay through native ns-3.

This runner owns only the network data-plane experiment.  It does not start
the LLMServingSim serving control loop, so its output is network attribution
(completion, CCT, queue, and link telemetry), not TTFT/TPOT.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BINARY = (ROOT / "astra-sim/extern/network_backend/ns-3/build/scratch"
                  / "ns3.42-KVEPReplay-optimized")
DEFAULT_TEMPLATE = ROOT / "experiments/pd_kv_ep/configs/ns3/replay_template.conf"
MANIFESTS = {
    "S64": ROOT / "experiments/pd_kv_ep/configs/large_scale/s64_64_servers_manifest.json",
    "S256": ROOT / "experiments/pd_kv_ep/configs/large_scale/s256_256_servers_manifest.json",
    "S16_EP64": ROOT / "experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_manifest.json",
    "S2P4D_EP32_SHARED_NIC": ROOT / "experiments/pd_kv_ep/configs/large_scale/s2p4d_6_servers_shared_nic_manifest.json",
    "S2P4D_EP32_DEDICATED_NIC": ROOT / "experiments/pd_kv_ep/configs/large_scale/s2p4d_6_servers_manifest.json",
    "S8_4P4D_EP32_SHARED_NIC": ROOT / "experiments/pd_kv_ep/configs/large_scale/s8_4p4d_ep32_shared_nic_manifest.json",
    "S1P2D_EP16": ROOT / "experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_manifest.json",
}


def _load(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _replace_config(template, output_dir, topology, packet_payload_size,
                    telemetry_interval_ms, policy,
                    local_ecn_mark_trace=False, cc_mode_override=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    flow = output_dir / "flow.txt"
    trace = output_dir / "trace.txt"
    flow.write_text("0\n", encoding="utf-8")
    trace.write_text("0\n", encoding="utf-8")
    paths = {
        "TOPOLOGY_FILE": topology,
        "FLOW_FILE": flow,
        "TRACE_FILE": trace,
        "TRACE_OUTPUT_FILE": Path("/dev/null"),
        "FCT_OUTPUT_FILE": output_dir / "fct.txt",
        "PFC_OUTPUT_FILE": output_dir / "pfc.txt",
        "QLEN_MON_FILE": output_dir / "qlen.txt",
        "COMM_EVENTS_FILE": output_dir / "comm_events.csv",
        "LINK_TIMESERIES_FILE": output_dir / "link_timeseries.csv",
        "LINK_SUMMARY_FILE": output_dir / "link_summary.csv",
    }
    template_lines = template.read_text(encoding="utf-8").splitlines()
    if any(line.split() and line.split()[0] == "CC_TELEMETRY_FILE"
           for line in template_lines):
        paths["CC_TELEMETRY_FILE"] = output_dir / "cc_events.csv"
    if local_ecn_mark_trace:
        paths["LOCAL_ECN_MARK_FILE"] = output_dir / "local_ecn_marks.csv"
    replacements = {key: str(value) for key, value in paths.items()}
    replacements.update({
        "QLEN_MON_START": "0",
        "QLEN_MON_END": "9223372036854775807",
        "QLEN_MON_INTERVAL_NS": str(int(telemetry_interval_ms * 1_000_000)),
        "LINK_TELEMETRY_INTERVAL_NS": str(int(telemetry_interval_ms * 1_000_000)),
        "ENABLE_TRACE": "0",
        "KV_EP_NETWORK_POLICY": policy,
        "PACKET_PAYLOAD_SIZE": str(packet_payload_size),
    })
    if cc_mode_override is not None:
        replacements["CC_MODE"] = str(cc_mode_override)
    lines = []
    pattern = re.compile(r"^(\S+)(?:\s+.*)?$")
    replaced = set()
    for line in template_lines:
        match = pattern.match(line)
        key = match.group(1) if match else ""
        if key in replacements:
            lines.append(f"{key} {replacements[key]}")
            replaced.add(key)
        else:
            lines.append(line)
    for key, value in replacements.items():
        if key not in replaced:
            lines.append(f"{key} {value}")
    config = output_dir / "replay.conf"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def _event_end_ns(event_path):
    last = 0
    with event_path.open(encoding="utf-8") as stream:
        next(stream, None)
        for line in stream:
            fields = line.rstrip("\n").split(",")
            if fields and fields[0].isdigit():
                last = max(last, int(fields[0]))
    return last


def _line_count(path):
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as stream:
        return max(0, sum(1 for _ in stream) - 1)


def _stop_process(process, force=False):
    """Stop the native replay and its process group without leaving a child."""
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", required=True, type=Path)
    parser.add_argument(
        "--input-replay-dir", type=Path, default=None,
        help="reuse an existing immutable events.csv/replay_manifest.json source")
    parser.add_argument("--scale", choices=tuple(MANIFESTS), required=True)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--timeout-s", type=int, default=1800)
    parser.add_argument("--packet-payload-size", type=int, default=1000,
                        help="discovery-only packet payload override in bytes")
    parser.add_argument(
        "--load-scale", type=float, default=None,
        help="provenance check: expected load scale embedded by the builder")
    parser.add_argument("--telemetry-interval-ms", type=float, default=1000.0,
                        help="coarse link/queue telemetry interval; default 1000 ms")
    parser.add_argument("--policy", choices=("FAIR", "KV_FIRST", "EP_FIRST"),
                        default="FAIR",
                        help="data-plane QP/switch priority policy; default FAIR")
    parser.add_argument(
        "--traffic-class", choices=("FULL", "KV_ONLY", "EP_ONLY"),
        default="FULL",
        help="keep the full event/port schedule but suppress the other traffic class")
    parser.add_argument("--persistent-ep-qps", action="store_true",
                        help="reuse one QP per recurrent directed EP peer")
    parser.add_argument("--stable-ep-ports", action="store_true",
                        help="keep EP 5-tuples stable while recreating fresh QPs")
    parser.add_argument("--local-ecn-mark-trace", action="store_true",
                        help="record only local non-CE to CE switch marking decisions")
    parser.add_argument("--exclude-kv-request-id", action="append", type=int,
                        default=[],
                        help="matched counterfactual: suppress only P2D KV events for this request")
    parser.add_argument("--cc-mode", choices=("0", "1"), default=None,
                        help="optional override for CC_MODE in the frozen replay template")
    parser.add_argument("--stop-guard-ns", type=int, default=None,
                        help="override the post-final-issue simulation guard")
    parser.add_argument("--allow-overwrite", action="store_true",
                        help="allow reuse of a replay directory with prior output; "
                             "default rejects this to prevent artifact races")
    args = parser.parse_args()

    replay_dir = args.replay_dir.resolve()
    input_replay_dir = (args.input_replay_dir or replay_dir).resolve()
    event_path = input_replay_dir / "events.csv"
    if not event_path.is_file():
        parser.error(f"missing replay input: {event_path}")
    existing_outputs = [replay_dir / name for name in (
        "network_run_manifest.json", "comm_events.csv", "link_summary.csv")
        if (replay_dir / name).exists()]
    if existing_outputs and not args.allow_overwrite:
        parser.error(
            "replay directory already contains output artifacts; use a new directory "
            "or pass --allow-overwrite: "
            + ", ".join(str(path) for path in existing_outputs))
    manifest = _load(MANIFESTS[args.scale])
    replay_manifest = _load(input_replay_dir / "replay_manifest.json")
    if args.load_scale is not None and args.load_scale <= 0:
        parser.error("--load-scale must be positive")
    if (args.load_scale is not None and
            abs(float(replay_manifest.get("load_scale", 1.0)) - args.load_scale) > 1e-12):
        parser.error(
            "--load-scale disagrees with replay_manifest.json; rebuild the replay")
    topology_value = replay_manifest.get("ns3_topology", manifest["ns3_topology"])
    topology = Path(topology_value)
    if not topology.is_absolute():
        topology = ROOT / topology
    topology = topology.resolve()
    if args.packet_payload_size <= 0:
        parser.error("--packet-payload-size must be positive")
    if args.telemetry_interval_ms <= 0:
        parser.error("--telemetry-interval-ms must be positive")
    if any(request_id < 0 for request_id in args.exclude_kv_request_id):
        parser.error("--exclude-kv-request-id must be non-negative")
    config = _replace_config(args.template.resolve(), replay_dir, topology,
                             args.packet_payload_size, args.telemetry_interval_ms,
                             args.policy, args.local_ecn_mark_trace,
                             args.cc_mode)
    stop_guard = (args.stop_guard_ns if args.stop_guard_ns is not None else
                  max(5_000_000_000, _event_end_ns(event_path) + 5_000_000_000))
    if stop_guard <= 0:
        parser.error("--stop-guard-ns must be positive")
    command = [
        str(args.binary.resolve()),
        f"--network-configuration={config}",
        f"--replay-file={event_path}",
        f"--stop-guard-ns={stop_guard}",
        f"--traffic-class={args.traffic_class}",
    ]
    command.extend(f"--exclude-kv-request-id={request_id}"
                   for request_id in args.exclude_kv_request_id)
    rank_map_value = replay_manifest.get("rank_to_nic_map")
    if rank_map_value:
        rank_map_path = Path(rank_map_value)
        if not rank_map_path.is_absolute():
            rank_map_path = ROOT / rank_map_path
        rank_map_path = rank_map_path.resolve()
        if not rank_map_path.is_file():
            parser.error(f"rank-to-NIC map does not exist: {rank_map_path}")
        command.append(f"--rank-to-nic-map={rank_map_path}")
    if args.persistent_ep_qps:
        command.append("--persistent-ep-qps=1")
    if args.stable_ep_ports:
        command.append("--stable-ep-ports=1")
    log_path = replay_dir / "replay.log"
    env = os.environ.copy()
    env["LLMSERVINGSIM_COMPACT_LOGS"] = "1"
    started_at = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=(os.name == "posix"))
        try:
            result_code = process.wait(timeout=args.timeout_s)
            status = "PASS" if result_code == 0 else "FAIL"
            exit_code = result_code
        except subprocess.TimeoutExpired:
            _stop_process(process)
            status = "TIMEOUT"
            exit_code = 124
        except KeyboardInterrupt:
            _stop_process(process, force=True)
            status = "ABORTED"
            exit_code = 130
    finished_at = time.time()
    summary = {
        "status": status,
        "exit_code": exit_code,
        "scale": args.scale,
        "request_count": replay_manifest["request_count"],
        "event_count": sum(1 for _ in event_path.open(encoding="utf-8")) - 1,
        "partial_comm_event_rows": _line_count(replay_dir / "comm_events.csv"),
        "started_at_unix": started_at,
        "finished_at_unix": finished_at,
        "wall_seconds": finished_at - started_at,
        "stop_guard_ns": stop_guard,
        "packet_payload_size": args.packet_payload_size,
        "telemetry_interval_ms": args.telemetry_interval_ms,
        "load_scale": replay_manifest.get("load_scale", 1.0),
        "arrival_interval_scale": replay_manifest.get("arrival_interval_scale", 1.0),
        "kv_ep_network_policy": args.policy,
        "traffic_class": args.traffic_class,
        "excluded_kv_request_ids": args.exclude_kv_request_id,
        "cc_mode_override": args.cc_mode,
        "persistent_ep_qps": args.persistent_ep_qps,
        "stable_ep_ports": args.stable_ep_ports,
        "local_ecn_mark_trace": args.local_ecn_mark_trace,
        "rank_to_nic_map": str(rank_map_path) if rank_map_value else None,
        "input_replay_dir": str(input_replay_dir),
        "binary": str(args.binary.resolve()),
        "config": str(config),
        "log": str(log_path),
    }
    cc_telemetry = replay_dir / "cc_events.csv"
    summary["cc_telemetry_file"] = (
        str(cc_telemetry) if cc_telemetry.exists() else None)
    summary["cc_telemetry_rows"] = _line_count(cc_telemetry)
    mark_telemetry = replay_dir / "local_ecn_marks.csv"
    summary["local_ecn_mark_file"] = (
        str(mark_telemetry) if mark_telemetry.exists() else None)
    summary["local_ecn_mark_rows"] = _line_count(mark_telemetry)
    replay_log = log_path.read_text(encoding="utf-8", errors="replace")
    event_match = re.search(
        r"KVEP replay completed: events=(\d+) issued=(\d+) suppressed=(\d+)"
        r" excluded_kv=(\d+) local_ep=(\d+)",
        replay_log)
    if event_match:
        summary["input_events"] = int(event_match.group(1))
        summary["issued_events"] = int(event_match.group(2))
        summary["suppressed_events"] = int(event_match.group(3))
        summary["excluded_kv_events"] = int(event_match.group(4))
        summary["local_ep_events"] = int(event_match.group(5))
    (replay_dir / "network_run_manifest.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if status != "PASS":
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
