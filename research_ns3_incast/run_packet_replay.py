#!/usr/bin/env python3
"""Run a fixed-event native ns-3 replay with isolated output/provenance."""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / "astra-sim/extern/network_backend/ns-3/build/scratch/ns3.42-KVEPReplay-optimized"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--rank-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cc-mode", choices=("0", "1"), required=True)
    parser.add_argument("--base-config", type=Path, default=ROOT /
                        "research_ns3_incast/results/LAYERWISE4_CC0/replay.conf")
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--stop-guard-ns", type=int, default=100_000_000)
    args = parser.parse_args()

    events = args.events.resolve()
    topology = args.topology.resolve()
    rank_map = args.rank_map.resolve()
    output = args.output.resolve()
    base_config = args.base_config.resolve()
    for path in (events, topology, rank_map, base_config, args.binary):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    output.mkdir(parents=True, exist_ok=False)

    old_run = str(base_config.parent)
    config_text = base_config.read_text(encoding="utf-8")
    config_text = config_text.replace(old_run, str(output))
    config_text = config_text.replace("CC_MODE 0\n", f"CC_MODE {args.cc_mode}\n")
    config_path = output / "replay.conf"
    config_path.write_text(config_text, encoding="utf-8")
    # KVEPReplay's config loader expects a flow-list file even though the
    # replay event ledger creates each QP dynamically. Zero entries is the
    # intentional, valid input for this backend.
    (output / "flow.txt").write_text("0\n", encoding="utf-8")
    # Packet tracing is disabled in this study, but the config parser still
    # opens the trace input before starting the replay.
    (output / "trace.txt").write_text("0\n", encoding="utf-8")
    command = [
        str(args.binary.resolve()),
        f"--network-configuration={config_path}",
        f"--replay-file={events}",
        f"--rank-to-nic-map={rank_map}",
        f"--stop-guard-ns={args.stop_guard_ns}",
        "--traffic-class=FULL",
    ]
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    wall_seconds = time.monotonic() - started
    (output / "replay.log").write_text(result.stdout, encoding="utf-8")

    with events.open(encoding="utf-8") as stream:
        event_count = max(0, sum(1 for _ in stream) - 1)
    manifest = {
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "exit_code": result.returncode,
        "started_unix": time.time() - wall_seconds,
        "wall_seconds": wall_seconds,
        "cc_mode_override": args.cc_mode,
        "traffic_class": "FULL",
        "event_count": event_count,
        "stop_guard_ns": args.stop_guard_ns,
        "events": str(events),
        "events_sha256": sha256(events),
        "topology": str(topology),
        "topology_sha256": sha256(topology),
        "rank_map": str(rank_map),
        "rank_map_sha256": sha256(rank_map),
        "binary": str(args.binary.resolve()),
        "binary_sha256": sha256(args.binary.resolve()),
        "config": str(config_path),
        "config_sha256": sha256(config_path),
        "command": command,
        "replay_stdout": result.stdout,
    }
    (output / "network_run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in (
        "status", "exit_code", "wall_seconds", "cc_mode_override",
        "event_count", "events_sha256", "topology_sha256", "binary_sha256",
        "config_sha256", "command", "replay_stdout")}, indent=2))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
