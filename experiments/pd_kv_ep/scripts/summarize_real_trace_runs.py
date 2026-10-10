#!/usr/bin/env python3
"""Summarize bounded real-trace replay manifests and execution footprints."""

import argparse
import csv
import json
import re
import time
from pathlib import Path


def _artifact_stats(repo_root, run_id, output_root):
    paths = list(output_root.glob(f"{run_id}.*"))
    input_root = repo_root / "astra-sim" / "inputs" / "runs" / run_id
    if input_root.is_dir():
        paths.extend(path for path in input_root.rglob("*") if path.is_file())
    total_bytes = sum(path.stat().st_size for path in paths if path.exists())
    route_files = list(input_root.rglob("*.a2a_routes.json")) if input_root.is_dir() else []
    batches = []
    for path in route_files:
        match = re.search(r"_batch(\d+)\.", path.name)
        if match:
            batches.append(int(match.group(1)))
    request_csv = output_root / f"{run_id}.requests.csv"
    request_rows = None
    if request_csv.is_file():
        with request_csv.open(encoding="utf-8", newline="") as stream:
            request_rows = max(sum(1 for _ in csv.reader(stream)) - 1, 0)
    return {
        "artifact_bytes": total_bytes,
        "artifact_files": len(paths),
        "route_file_count": len(route_files),
        "max_generated_batch": max(batches) if batches else None,
        "request_csv_rows": request_rows,
    }


def summarize(repo_root, output_root, stale_after_s):
    records = []
    now = time.time()
    for manifest_path in sorted(output_root.glob("*.manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        default_run_id = manifest_path.name[:-len(".manifest.json")]
        run_id = manifest.get("run_id", default_run_id)
        estimate = manifest.get("estimate") or {}
        started = manifest.get("started_at_unix")
        finished = manifest.get("finished_at_unix")
        manifest_status = manifest.get("status")
        observed_status = manifest_status
        if (manifest_status == "RUNNING" and finished is None and started is not None
                and now - started > stale_after_s):
            # Do not rewrite the source manifest: it is historical evidence and
            # may have been produced by an earlier process namespace.  The
            # generated audit must nevertheless not present an abandoned run
            # as live forever.
            observed_status = "STALE_RUNNING"
        footprint = _artifact_stats(repo_root, run_id, output_root)
        records.append({
            "run_id": run_id,
            "status": observed_status,
            "manifest_status": manifest_status,
            "backend": manifest.get("backend"),
            "scale_scope": manifest.get("scale_scope"),
            "cluster_server_count": manifest.get("cluster_server_count"),
            "trace_request_count": manifest.get("trace_request_count"),
            "request_offset": manifest.get("request_offset"),
            "input_tokens": estimate.get("input_tokens"),
            "output_tokens": estimate.get("output_tokens"),
            "estimated_p2d_kv_bytes": estimate.get("estimated_p2d_kv_bytes"),
            "estimated_ep_bytes_per_decode_step": estimate.get("estimated_ep_bytes_per_decode_step"),
            "started_at_unix": started,
            "finished_at_unix": finished,
            "wall_seconds": (finished - started) if started is not None and finished is not None else None,
            "timeout_s": manifest.get("timeout_s"),
            "returncode": manifest.get("returncode"),
            "network_event_count": None,
            "packet_payload_size": None,
            "telemetry_interval_ms": None,
            "kv_ep_network_policy": manifest.get("kv_ep_network_policy", "FAIR"),
            "partial_comm_event_rows": None,
            "native_replay_dir": None,
            **footprint,
        })
    for network_path in sorted(output_root.rglob("network_run_manifest.json")):
        try:
            manifest = json.loads(network_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        run_dir = network_path.parent
        started = manifest.get("started_at_unix")
        finished = manifest.get("finished_at_unix")
        records.append({
            "run_id": "native_" + run_dir.name,
            "status": manifest.get("status"),
            "manifest_status": manifest.get("status"),
            "backend": "ns3-native-replay",
            "scale_scope": manifest.get("scale"),
            "cluster_server_count": None,
            "trace_request_count": manifest.get("request_count"),
            "request_offset": None,
            "input_tokens": None,
            "output_tokens": None,
            "estimated_p2d_kv_bytes": None,
            "estimated_ep_bytes_per_decode_step": None,
            "started_at_unix": started,
            "finished_at_unix": finished,
            "wall_seconds": (finished - started) if started is not None and finished is not None else None,
            "timeout_s": None,
            "returncode": manifest.get("exit_code"),
            "artifact_bytes": sum(path.stat().st_size for path in run_dir.rglob("*")
                                   if path.is_file()),
            "artifact_files": sum(1 for path in run_dir.rglob("*") if path.is_file()),
            "route_file_count": None,
            "max_generated_batch": None,
            "request_csv_rows": None,
            "network_event_count": manifest.get("event_count"),
            "packet_payload_size": manifest.get("packet_payload_size"),
            "telemetry_interval_ms": manifest.get("telemetry_interval_ms"),
            "kv_ep_network_policy": manifest.get("kv_ep_network_policy", "FAIR"),
            "partial_comm_event_rows": manifest.get("partial_comm_event_rows"),
            "native_replay_dir": str(run_dir),
        })
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("experiments/pd_kv_ep/results/real_trace"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--stale-after-s", type=float, default=3600.0,
                        help="classify old unfinished RUNNING manifests as STALE_RUNNING in the audit summary")
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    repo_root = args.repo_root.resolve()
    records = summarize(repo_root, output_root, args.stale_after_s)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "real_trace_execution_summary.json"
    csv_path = output_root / "real_trace_execution_summary.csv"
    md_path = output_root / "real_trace_execution_summary.md"
    json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    fields = list(records[0]) if records else ["run_id", "status"]
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    lines = [
        "# Real-trace execution summary",
        "",
        "This is an execution/cost audit. ABORTED, TIMEOUT, and STALE_RUNNING rows are not performance results.",
        "",
        "| run | status | backend | requests | wall s | max batch | artifacts | request CSV rows |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in records:
        lines.append(
            f"| `{row['run_id']}` | {row.get('status')} | {row.get('backend')} | "
            f"{row.get('trace_request_count')} | {row.get('wall_seconds') or ''} | "
            f"{row.get('max_generated_batch') or ''} | {row.get('artifact_bytes') or 0} | "
            f"{row.get('request_csv_rows') if row.get('request_csv_rows') is not None else ''} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"runs": len(records), "csv": str(csv_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
