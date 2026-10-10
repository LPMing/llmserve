#!/usr/bin/env python3
"""Run one matched integrated FlowSim point for the minimal 1P2D/EP16 gate.

The script never overrides communication bytes. A D-only warm-up supplies an
event-derived K injection timestamp: every intended Decode request must have
been admitted and must have completed four Decode token boundaries. The
resulting timestamp is checked against the same requests in the FULL replay.
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
CONFIG_REL = Path(
    "experiments/pd_kv_ep/configs/large_scale/"
    "minimal_1p2d_ep16_shared_400g.json")
PAIRING_REL = Path(
    "experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_pairing.json")
RESULTS = ROOT / "experiments/pd_kv_ep/results/minimal_ideal_kv_ep"
LEDGER_NAME = "MINIMAL_IDEAL_KV_EP_EXPERIMENTS.csv"
MODEL_NAME = "Qwen/Qwen3-30B-A3B-Instruct-2507"
EP_FLOW_DETAIL_MAX_ROWS = 500000
OVERLAP_TIME_BIN_NS = 1_000_000
TOR_UPLINKS = {
    "%d->30" % node for node in range(24, 30)
} | {
    "30->%d" % node for node in range(24, 30)
}


def _percentile(values, q):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * float(q)
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (pos - lower)


def _stats(values):
    clean = [float(value) for value in values if value is not None]
    return {
        "count": len(clean),
        "mean": (sum(clean) / len(clean) if clean else None),
        "p50": _percentile(clean, .50),
        "p95": _percentile(clean, .95),
        "p99": _percentile(clean, .99),
        "max": (max(clean) if clean else None),
    }


def _read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("{"):
                rows.append(json.loads(line))
    return rows


def _read_requests(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _int_cell(row, key):
    value = row.get(key)
    return int(float(value)) if value not in (None, "", "None") else None


def _load_tbt(row):
    value = row.get("TBT", "")
    if not value:
        return []
    parsed = json.loads(value)
    return [int(float(item)) for item in parsed]


def _tbt_after(rows, request_ids, time_ns):
    values = []
    for row in rows:
        if int(row["request id"]) not in request_ids:
            continue
        cursor = _int_cell(row, "decode_admit_time_ns")
        if cursor is None:
            continue
        for delta in _load_tbt(row):
            cursor += delta
            if cursor > int(time_ns):
                values.append(delta / 1e6)
    return values


def _tbt_in_window(rows, request_ids, start_ns, end_ns):
    values = []
    for row in rows:
        if int(row["request id"]) not in request_ids:
            continue
        cursor = _int_cell(row, "decode_admit_time_ns")
        if cursor is None:
            continue
        for delta in _load_tbt(row):
            interval_start = cursor
            cursor += delta
            if cursor > int(start_ns) and interval_start < int(end_ns):
                values.append(delta / 1e6)
    return values


def _write_requests(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_gzip(source, target):
    if not source.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, gzip.open(target, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    return target


def _run_serving(phase, workload_path, output_path, injection_ns,
                 detailed_ep=False, capture_network=False,
                 pd_kv_transfer_mode="LAYERWISE"):
    run_dir = RESULTS / "points" / phase
    request_dir = run_dir / "requests"
    event_dir = run_dir / "events"
    request_dir.mkdir(parents=True, exist_ok=True)
    event_dir.mkdir(parents=True, exist_ok=True)
    final_requests = Path(output_path)
    final_requests.parent.mkdir(parents=True, exist_ok=True)
    log_path = request_dir / (phase + ".failed.log")
    with workload_path.open(encoding="utf-8") as stream:
        request_count = sum(1 for line in stream if line.strip())
    command = [
        sys.executable, "-m", "serving",
        "--cluster-config", str(CONFIG_REL),
        "--dataset", str(workload_path.relative_to(ROOT)),
        "--num-reqs", str(request_count),
        "--output", str(final_requests),
        "--run-id", "minimal_ideal_" + phase.replace("/", "_"),
        "--inputs-root", "PLACEHOLDER",
        "--network-backend", "flowsim",
        "--kv-ep-network-policy", "FAIR",
        "--ep-collective-semantics", "A2A_P2P",
        "--pd-kv-transfer-mode", str(pd_kv_transfer_mode).upper(),
        "--pd-kv-receiver-mode", "ACTUAL",
        "--pd-pairing-map", "../" + PAIRING_REL.as_posix(),
        "--request-routing-policy", "RR",
        "--expert-routing-policy", "BALANCED",
        "--no-enable-prefix-caching",
        "--log-level", "WARNING",
        "--log-interval", "60",
        "--keep-inputs",
    ]
    started_wall = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="llmservingsim_minimal_") as tmp:
        inputs_root = Path(tmp) / "inputs"
        command[command.index("PLACEHOLDER")] = str(inputs_root)
        env = os.environ.copy()
        env["FLOWSIM_FLOW_TELEMETRY"] = "0"
        env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "0"
        # Keep the time series focused on the 12 directed NIC↔ToR uplinks.
        # This covers the complete shared-fabric observation window with a
        # bounded ledger instead of truncating after a few milliseconds on
        # the many GPU/NIC attachment links.
        env["FLOWSIM_MAX_TELEMETRY_ROWS"] = (
            "500000" if injection_ns is not None or capture_network else "0")
        env["FLOWSIM_TELEMETRY_LINK_IDS"] = (
            "24->30,25->30,26->30,27->30,28->30,29->30,"
            "30->24,30->25,30->26,30->27,30->28,30->29")
        env["FLOWSIM_TELEMETRY_START_NS"] = str(injection_ns or 0)
        env.pop("FLOWSIM_TELEMETRY_END_NS", None)
        env["FLOWSIM_EP_FLOW_TELEMETRY"] = "1" if detailed_ep else "0"
        env["FLOWSIM_MAX_EP_FLOW_TELEMETRY_ROWS"] = str(
            EP_FLOW_DETAIL_MAX_ROWS)
        # The CCT ledger already covers every collective. Per-peer detail is
        # only needed to attribute exposure on the shared scale-out fabric;
        # omit intra-server EP peers to keep a complete bounded time window.
        env["FLOWSIM_EP_FLOW_TELEMETRY_LINK_IDS"] = ",".join(
            sorted(TOR_UPLINKS)) if detailed_ep else ""
        env["FLOWSIM_EP_FLOW_TELEMETRY_START_NS"] = str(injection_ns or 0)
        env.pop("FLOWSIM_EP_FLOW_TELEMETRY_END_NS", None)
        print("RUN", phase, "requests=", workload_path.name, flush=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         prefix="minimal-", suffix=".log",
                                         delete=False) as log_stream:
            tmp_log = Path(log_stream.name)
        try:
            with tmp_log.open("w", encoding="utf-8") as log_stream:
                result = subprocess.run(
                    command, cwd=str(ROOT), env=env, stdout=log_stream,
                    stderr=subprocess.STDOUT, check=False)
            if result.returncode != 0 or not final_requests.exists():
                log_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(tmp_log, log_path)
                raise RuntimeError(
                    "%s failed (exit=%s); compact failure log: %s" %
                    (phase, result.returncode, log_path))

            flowsim = inputs_root / "flowsim"
            artifacts = {
                "kv_event_telemetry.jsonl": "kv_events.jsonl.gz",
                "collective_telemetry.jsonl": "collectives.jsonl.gz",
                "link_telemetry.jsonl": "fluid_links.jsonl.gz",
                "ep_flow_telemetry.jsonl": "ep_flows.jsonl.gz",
            }
            for source_name, target_name in artifacts.items():
                _save_gzip(flowsim / source_name, event_dir / (phase + "_" + target_name))
            rows = _read_requests(final_requests)
            if not rows:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(tmp_log, log_path)
                raise RuntimeError("%s produced an empty request ledger" % phase)
            return {
                "phase": phase,
                "requests": rows,
                "request_csv": str(final_requests),
                "flowsim_dir": str(event_dir),
                "wall_seconds": time.monotonic() - started_wall,
                "simulated_finish_ns": max(
                    _int_cell(row, "end_time") or 0 for row in rows),
                "log_tail": _tail(tmp_log, 30),
            }
        finally:
            try:
                tmp_log.unlink()
            except OSError:
                pass


def _tail(path, lines):
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            content = stream.readlines()
        return "".join(content[-lines:])
    except OSError:
        return ""


def _arrival_rows(d_count, k_count, d_input, d_output, k_input, k_arrival):
    rows = []
    for index in range(d_count):
        rows.append({
            "request_id": "D%03d" % index,
            "input_toks": int(d_input),
            "output_toks": int(d_output),
            "arrival_time_ns": 0,
        })
    for index in range(k_count):
        rows.append({
            "request_id": "K%03d" % index,
            "input_toks": int(k_input),
            # One prefill-produced token plus one real Decode token is the
            # smallest completed P/D request in this simulator. output=1
            # hands off a request with no Decode work and never retires it.
            "output_toks": 2,
            "arrival_time_ns": int(k_arrival),
        })
    return rows


def _warmup_arrival_ns(rows, d_count):
    by_id = {int(row["request id"]): row for row in rows}
    missing = sorted(set(range(d_count)) - set(by_id))
    if missing:
        raise RuntimeError("D-only run is missing request IDs %s" % missing)
    fourth_token_times = []
    for request_id in range(d_count):
        row = by_id[request_id]
        admitted = _int_cell(row, "decode_admit_time_ns")
        tbt = _load_tbt(row)
        if admitted is None or len(tbt) < 4:
            raise RuntimeError(
                "request %d lacks Decode admission or four TBT boundaries" %
                request_id)
        fourth_token_times.append(admitted + sum(tbt[:4]))
    return max(fourth_token_times) + 1


def _assert_full_prefix(warmup_rows, full_rows, d_count, k_arrival):
    warmup = {int(row["request id"]): row for row in warmup_rows}
    full = {int(row["request id"]): row for row in full_rows}
    for request_id in range(d_count):
        a, b = warmup[request_id], full[request_id]
        for key in ("decode_admit_time_ns", "p2d_kv_ready_time_ns",
                    "decode_first_token_time_ns"):
            if _int_cell(a, key) != _int_cell(b, key):
                raise RuntimeError(
                    "pre-injection prefix diverged for D request %d field %s" %
                    (request_id, key))
        if _load_tbt(a)[:4] != _load_tbt(b)[:4]:
            raise RuntimeError(
                "pre-injection first four Decode token boundaries diverged "
                "for D request %d" % request_id)
        fourth = _int_cell(b, "decode_admit_time_ns") + sum(_load_tbt(b)[:4])
        if fourth >= int(k_arrival):
            raise RuntimeError(
                "K injection preceded four Decode token boundaries for D%d" %
                request_id)
        if (_int_cell(b, "end_time") or 0) <= int(k_arrival):
            raise RuntimeError(
                "D%d was no longer active at K injection" % request_id)


def _event_requests(row):
    values = row.get("request_ids", ())
    return {int(item) for item in values}


def _kv_request_metrics(rows, target_request_ids):
    events = _read_jsonl(Path(rows["flowsim_dir"]) / "unused") if False else []
    # The compact event files are gzip-compressed after the simulator exits.
    path = next(Path(rows["flowsim_dir"]).glob(rows["phase"] + "_kv_events.jsonl.gz"))
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream if line.startswith("{")]
    result = {}
    for request_id in target_request_ids:
        generated = [item for item in events
                     if item.get("event") == "KV_GENERATED" and
                     request_id in _event_requests(item)]
        completed = [item for item in events
                     if item.get("event") == "KV_COMPLETED" and
                     request_id in _event_requests(item)]
        if not generated or not completed:
            result[request_id] = {"valid": False}
            continue
        first_issue = min(int(item.get("requested_start_ns",
                                      item.get("timestamp_ns", 0)) or 0)
                          for item in completed)
        last_completion = max(int(item.get("end_ns",
                                           item.get("timestamp_ns", 0)) or 0)
                              for item in completed)
        last_release = max(int(item.get("timestamp_ns", 0) or 0)
                           for item in generated)
        result[request_id] = {
            "valid": True,
            "bytes": sum(int(item.get("bytes", 0) or 0) for item in generated),
            "flow_count": len(completed),
            "first_issue_ns": first_issue,
            "last_release_ns": last_release,
            "last_completion_ns": last_completion,
            "network_handoff_span_ns": last_completion - first_issue,
            "residual_drain_ns": last_completion - last_release,
            "intervals": [
                (int(item.get("start_ns", 0)), int(item.get("end_ns", 0)))
                for item in completed],
            "paths": [item.get("path", []) for item in completed],
        }
    return result


def _collectives(run, min_start_ns=0, request_ids=None, max_end_ns=None):
    path = Path(run["flowsim_dir"]) / "unused"
    path = next(Path(run["flowsim_dir"]).glob(
        run["phase"] + "_collectives.jsonl.gz"))
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        values = [json.loads(line) for line in stream if line.startswith("{")]
    result = []
    for item in values:
        if item.get("traffic_class") != "EP":
            continue
        # A barrier already in flight at K injection is exposed and belongs
        # in the post-injection window if it completes afterward.
        if int(item.get("end_ns", 0)) <= int(min_start_ns):
            continue
        if max_end_ns is not None and int(item.get("start_ns", 0)) >= int(max_end_ns):
            continue
        if request_ids is not None and not (_event_requests(item) & request_ids):
            continue
        result.append(item)
    return result


def _link_queue_metrics(run, min_time_ns=None, max_time_ns=None):
    path = next(Path(run["flowsim_dir"]).glob(
        run["phase"] + "_fluid_links.jsonl.gz"), None)
    if path is None:
        return {"episode_p95_ns": None, "max_fluid_backlog_bytes": None,
                "sample_count": 0, "telemetry_truncated": None,
                "window_complete": False}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = []
        truncated = None
        truncated_at_ns = None
        for line in stream:
            if not line.startswith("{"):
                continue
            row = json.loads(line)
            if row.get("record_type") == "link_timeseries":
                if row.get("link_id") not in TOR_UPLINKS:
                    continue
                end_ns = int(row.get("timestamp_ns", 0))
                start_ns = int(row.get("interval_start_ns", end_ns))
                if min_time_ns is not None and end_ns <= int(min_time_ns):
                    continue
                if max_time_ns is not None and start_ns >= int(max_time_ns):
                    continue
                rows.append(row)
            elif row.get("record_type") == "metadata":
                truncated = bool(row.get("telemetry_truncated"))
                truncated_at_ns = row.get("telemetry_truncated_at_ns")

    if min_time_ns is None:
        window_start = min(
            (int(item.get("interval_start_ns", item["timestamp_ns"]))
             for item in rows), default=0)
    else:
        window_start = int(min_time_ns)
    if max_time_ns is None:
        window_end = max(
            (int(item["timestamp_ns"]) for item in rows),
            default=window_start)
    else:
        window_end = int(max_time_ns)
    window_ns = max(0, window_end - window_start)

    by_link = {link_id: [] for link_id in TOR_UPLINKS}
    for row in rows:
        by_link[row["link_id"]].append(row)

    def make_segments(link_rows):
        link_rows = sorted(link_rows, key=lambda item: (
            int(item.get("interval_start_ns", item["timestamp_ns"])),
            int(item["timestamp_ns"])))
        segments = []
        cursor = window_start
        for item in link_rows:
            start_ns = max(window_start, int(item.get(
                "interval_start_ns", item["timestamp_ns"])))
            end_ns = min(window_end, int(item["timestamp_ns"]))
            if end_ns <= start_ns or end_ns <= cursor:
                continue
            if start_ns > cursor:
                segments.append({"start_ns": cursor, "end_ns": start_ns,
                                "utilization": 0.0, "active_flows": 0,
                                "active_kv_flows": 0, "active_ep_flows": 0,
                                "allocated_rate_Bps": 0.0,
                                "kv_allocated_rate_Bps": 0.0,
                                "ep_allocated_rate_Bps": 0.0})
            start_ns = max(start_ns, cursor)
            if end_ns <= start_ns:
                continue
            segments.append({
                "start_ns": start_ns,
                "end_ns": end_ns,
                "utilization": float(item.get("utilization", 0.0) or 0.0),
                "active_flows": int(item.get("active_flows", 0) or 0),
                "active_kv_flows": int(item.get("active_kv_flows", 0) or 0),
                "active_ep_flows": int(item.get("active_ep_flows", 0) or 0),
                "allocated_rate_Bps": float(
                    item.get("allocated_rate_Bps", 0.0) or 0.0),
                "kv_allocated_rate_Bps": float(
                    item.get("kv_allocated_rate_Bps", 0.0) or 0.0),
                "ep_allocated_rate_Bps": float(
                    item.get("ep_allocated_rate_Bps", 0.0) or 0.0),
            })
            cursor = end_ns
        if cursor < window_end:
            segments.append({"start_ns": cursor, "end_ns": window_end,
                            "utilization": 0.0, "active_flows": 0,
                            "active_kv_flows": 0, "active_ep_flows": 0,
                            "allocated_rate_Bps": 0.0,
                            "kv_allocated_rate_Bps": 0.0,
                            "ep_allocated_rate_Bps": 0.0})
        return segments

    def weighted_percentile(segments, key, q):
        samples = [(float(item[key]), item["end_ns"] - item["start_ns"])
                   for item in segments if item["end_ns"] > item["start_ns"]]
        total = sum(duration for _, duration in samples)
        if not total:
            return None
        target = max(1, int(math.ceil(float(q) * total)))
        elapsed = 0
        for value, duration in sorted(samples):
            elapsed += duration
            if elapsed >= target:
                return value
        return max(value for value, _ in samples)

    def longest_episode(segments, predicate):
        longest = current = 0
        previous_end = None
        for item in segments:
            start_ns, end_ns = item["start_ns"], item["end_ns"]
            if end_ns <= start_ns:
                continue
            if predicate(item):
                if previous_end == start_ns:
                    current += end_ns - start_ns
                else:
                    current = end_ns - start_ns
                longest = max(longest, current)
            else:
                current = 0
            previous_end = end_ns
        return longest

    per_link = {}
    all_segments = []
    decoder_links = {"30->26", "30->27", "30->28", "30->29"}
    decoder_segments = []
    full_backlog_samples = []
    released_kv_bytes = released_ep_bytes = released_bytes = 0
    sample_count = 0
    for link_id, link_rows in by_link.items():
        segments = make_segments(link_rows)
        all_segments.extend(segments)
        if link_id in decoder_links:
            decoder_segments.extend(segments)
        sample_count += len(link_rows)
        queues = [int(item.get("fluid_outstanding_bytes",
                               item.get("queue_bytes", 0)) or 0)
                  for item in link_rows]
        full_backlog_samples.extend(queues)
        if link_id in decoder_links:
            released_kv_bytes += sum(
                int(item.get("released_kv_bytes", 0) or 0)
                for item in link_rows)
            released_ep_bytes += sum(
                int(item.get("released_ep_bytes", 0) or 0)
                for item in link_rows)
            released_bytes += sum(
                int(item.get("released_bytes", 0) or 0)
                for item in link_rows)
        utilization_segments = [item for item in segments
                                if item["end_ns"] > item["start_ns"]]
        same_link_overlap_ns = sum(
            item["end_ns"] - item["start_ns"]
            for item in utilization_segments
            if item["active_kv_flows"] > 0 and item["active_ep_flows"] > 0)
        per_link[link_id] = {
            "samples": len(link_rows),
            "utilization_p50_time_weighted": weighted_percentile(
                utilization_segments, "utilization", .50),
            "utilization_p95_time_weighted": weighted_percentile(
                utilization_segments, "utilization", .95),
            "utilization_p99_time_weighted": weighted_percentile(
                utilization_segments, "utilization", .99),
            "utilization_max": max(
                (item["utilization"] for item in utilization_segments),
                default=0.0),
            "fraction_time_ge90": (
                sum(item["end_ns"] - item["start_ns"]
                    for item in utilization_segments
                    if item["utilization"] >= .9) / float(window_ns)
                if window_ns else None),
            "fraction_time_at_capacity": (
                sum(item["end_ns"] - item["start_ns"]
                    for item in utilization_segments
                    if item["utilization"] >= 1.0 - 1e-9) / float(window_ns)
                if window_ns else None),
            "longest_ge90_episode_ns": longest_episode(
                utilization_segments,
                lambda item: item["utilization"] >= .9),
            "fluid_outstanding_p95_bytes": _percentile(queues, .95),
            "fluid_outstanding_max_bytes": max(queues, default=0),
            "active_kv_flows_p95_time_weighted": weighted_percentile(
                segments, "active_kv_flows", .95),
            "active_ep_flows_p95_time_weighted": weighted_percentile(
                segments, "active_ep_flows", .95),
            "kv_ep_same_link_overlap_ns": same_link_overlap_ns,
        }

    cut_util = {
        "p50": weighted_percentile(decoder_segments, "utilization", .50),
        "p95": weighted_percentile(decoder_segments, "utilization", .95),
        "p99": weighted_percentile(decoder_segments, "utilization", .99),
    }
    decoder_time_ns = window_ns * len(decoder_links)
    cut_fraction_ge90 = (
        sum(item["end_ns"] - item["start_ns"] for item in decoder_segments
            if item["utilization"] >= .9) / float(decoder_time_ns)
        if decoder_time_ns else None)
    cut_fraction_at_capacity = (
        sum(item["end_ns"] - item["start_ns"] for item in decoder_segments
            if item["utilization"] >= 1.0 - 1e-9) / float(decoder_time_ns)
        if decoder_time_ns else None)
    cut_longest_ge90 = max((per_link[link]["longest_ge90_episode_ns"]
                            for link in decoder_links), default=0)
    cut_kv_ep_overlap_ns = sum(
        per_link[link]["kv_ep_same_link_overlap_ns"]
        for link in decoder_links)
    weighted_active_kv = weighted_percentile(
        decoder_segments, "active_kv_flows", .95)
    weighted_active_ep = weighted_percentile(
        decoder_segments, "active_ep_flows", .95)
    offered_rate_available = False
    telemetry_complete = (
        window_ns > 0 and
        (not truncated or truncated_at_ns is None or
         int(truncated_at_ns) >= window_end) and
        all(any(seg["end_ns"] > seg["start_ns"] for seg in
                make_segments(by_link[link])) for link in decoder_links))
    return {
        "episode_p95_ns": None,
        "max_fluid_backlog_bytes": max(full_backlog_samples, default=0),
        "queue_p95_bytes": _percentile(full_backlog_samples, .95),
        "sampled_time_start_ns": window_start,
        "sampled_time_end_ns": window_end,
        "sample_count": sample_count,
        "telemetry_truncated": truncated,
        "telemetry_truncated_at_ns": truncated_at_ns,
        "window_complete": telemetry_complete,
        "window_duration_ns": window_ns,
        "decode_ingress_utilization_p50": cut_util["p50"],
        "decode_ingress_utilization_p95": cut_util["p95"],
        "decode_ingress_utilization_p99": cut_util["p99"],
        "decode_ingress_utilization_max": max(
            (per_link[link]["utilization_max"] for link in decoder_links),
            default=0.0),
        "decode_ingress_fraction_time_ge90": cut_fraction_ge90,
        "decode_ingress_fraction_time_at_capacity": cut_fraction_at_capacity,
        "decode_ingress_longest_ge90_episode_ns": cut_longest_ge90,
        "decode_ingress_kv_ep_same_link_overlap_ns": cut_kv_ep_overlap_ns,
        "decode_ingress_kv_ep_overlap_fraction": (
            cut_kv_ep_overlap_ns / float(decoder_time_ns)
            if decoder_time_ns else None),
        "decode_ingress_active_kv_flows_p95": weighted_active_kv,
        "decode_ingress_active_ep_flows_p95": weighted_active_ep,
        "decode_ingress_fluid_outstanding_max_bytes": max(
            (per_link[link]["fluid_outstanding_max_bytes"]
             for link in decoder_links), default=0),
        "released_kv_bytes": released_kv_bytes,
        "released_ep_bytes": released_ep_bytes,
        "released_bytes": released_bytes,
        "released_kv_rate_proxy_gbps": (
            released_kv_bytes * 8 / window_ns if window_ns else None),
        "released_ep_rate_proxy_gbps": (
            released_ep_bytes * 8 / window_ns if window_ns else None),
        "offered_rate_available": offered_rate_available,
        "offered_rho_p50": None,
        "offered_rho_p95": None,
        "offered_rho_p99": None,
        "per_link": per_link,
    }


def _shared_path_overlap(kv_metrics, ep_details_path, target_request_ids,
                         min_start_ns, max_end_ns=None):
    if not ep_details_path.exists():
        return None
    kv_intervals = []
    kv_event_path = ep_details_path.parent / (
        ep_details_path.name.replace("ep_flows", "kv_events"))
    if not kv_event_path.exists():
        return None
    with gzip.open(kv_event_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.startswith("{"):
                continue
            item = json.loads(line)
            if item.get("event") != "KV_COMPLETED":
                continue
            if not (_event_requests(item) & target_request_ids):
                continue
            start_ns = int(item.get("start_ns", 0))
            end_ns = int(item.get("end_ns", 0))
            if end_ns > start_ns:
                kv_intervals.append((start_ns, end_ns,
                                     set(item.get("path", ()))))
    # Index each KV interval by simulated-time bins. EP peer records are
    # numerous, but only intervals in the same one-millisecond bins can
    # overlap; this preserves exact interval checks while avoiding a costly
    # all-EP-flows × all-KV-flows scan.
    kv_by_time_bin = {}
    for index, (start_ns, end_ns, _) in enumerate(kv_intervals):
        first_bin = start_ns // OVERLAP_TIME_BIN_NS
        last_bin = end_ns // OVERLAP_TIME_BIN_NS
        for time_bin in range(first_bin, last_bin + 1):
            kv_by_time_bin.setdefault(time_bin, []).append(index)
    any_pairs = set()
    critical_pairs = set()
    scaleout_pairs = set()
    critical_scaleout_pairs = set()
    overlap_ns_by_link = {}
    with gzip.open(ep_details_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.startswith("{"):
                continue
            item = json.loads(line)
            if (int(item.get("collective_end_ns", 0)) <= min_start_ns or
                    (max_end_ns is not None and
                     int(item.get("collective_start_ns", 0)) >= max_end_ns)):
                continue
            ep_start_ns = int(item.get("start_ns", 0))
            ep_end_ns = int(item.get("end_ns", 0))
            if ep_end_ns <= ep_start_ns:
                continue
            ep_path = set(item.get("path", ()))
            candidate_indices = set()
            first_bin = ep_start_ns // OVERLAP_TIME_BIN_NS
            last_bin = ep_end_ns // OVERLAP_TIME_BIN_NS
            for time_bin in range(first_bin, last_bin + 1):
                candidate_indices.update(kv_by_time_bin.get(time_bin, ()))
            for index in candidate_indices:
                start, end, kv_path = kv_intervals[index]
                overlap_ns = min(end, ep_end_ns) - max(start, ep_start_ns)
                common = ep_path & kv_path
                if overlap_ns <= 0 or not common:
                    continue
                pair = (str(item.get("round_id")),
                        str(item.get("flow_id")))
                any_pairs.add(pair)
                if item.get("is_last_completing"):
                    critical_pairs.add(pair)
                for link in common:
                    overlap_ns_by_link[link] = (
                        overlap_ns_by_link.get(link, 0) + overlap_ns)
                    if link in TOR_UPLINKS:
                        scaleout_pairs.add(pair)
                        if item.get("is_last_completing"):
                            critical_scaleout_pairs.add(pair)
    return {
        "ep_flow_pair_count": len(any_pairs),
        "critical_ep_flow_pair_count": len(critical_pairs),
        "scaleout_ep_flow_pair_count": len(scaleout_pairs),
        "critical_scaleout_ep_flow_pair_count": len(critical_scaleout_pairs),
        "overlap_ns_by_link": overlap_ns_by_link,
    }


def _ep_flow_coverage(ep_details_path):
    if not ep_details_path or not ep_details_path.exists():
        return {"rows": 0, "capture_end_ns": None, "truncated": None}
    count = 0
    capture_end = None
    with gzip.open(ep_details_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.startswith("{"):
                continue
            item = json.loads(line)
            count += 1
            value = int(item.get("collective_end_ns", 0) or 0)
            capture_end = value if capture_end is None else max(capture_end, value)
    # The old first D2 capture used 30,000 rows; current runs use the explicit
    # 120,000-row cap. Reaching either exact limit means it may have truncated.
    reached_limit = count in (30000, EP_FLOW_DETAIL_MAX_ROWS)
    return {
        "rows": count,
        "capture_end_ns": capture_end,
        "configured_limit_rows": (count if reached_limit else
                                  EP_FLOW_DETAIL_MAX_ROWS),
        "truncated_or_at_limit": reached_limit,
    }


def _distribution_for_kv(kv_rows, key):
    values = [row[key] for row in kv_rows.values() if row.get("valid")]
    return _stats(values)


def _warmup_cache_path(d_count, d_input, d_output, pd_kv_transfer_mode):
    mode_suffix = ("" if str(pd_kv_transfer_mode).upper() == "LAYERWISE"
                   else "_" + str(pd_kv_transfer_mode).lower())
    return RESULTS / "warmups" / (
        "d%d_i%d_o%d%s.json" %
        (d_count, d_input, d_output, mode_suffix))


def _maybe_read_cached_warmup(d_count, d_input, d_output, force=False,
                              pd_kv_transfer_mode="LAYERWISE"):
    path = _warmup_cache_path(
        d_count, d_input, d_output, pd_kv_transfer_mode)
    if path.exists() and not force:
        with path.open(encoding="utf-8") as stream:
            record = json.load(stream)
        request_path = Path(record["request_csv"])
        if not request_path.exists():
            old_phase_path = (
                RESULTS / "points" / record["phase"] / "requests" /
                (record["phase"] + ".csv"))
            if old_phase_path.exists():
                request_path = old_phase_path
                record["request_csv"] = str(old_phase_path)
        if request_path.exists():
            record["requests"] = _read_requests(request_path)
            return record
    return None


def _save_metrics_csv(row):
    path = RESULTS / LEDGER_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    fields = list(row.keys())
    if exists:
        with path.open(newline="", encoding="utf-8") as stream:
            old_fields = next(csv.reader(stream))
        if old_fields != fields:
            raise RuntimeError("experiment CSV schema changed; refusing append")
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    global RESULTS, LEDGER_NAME
    parser = argparse.ArgumentParser()
    parser.add_argument("--d", type=int, required=True, dest="d_count")
    parser.add_argument("--k", type=int, required=True, dest="k_count")
    parser.add_argument("--d-input", type=int, default=128)
    parser.add_argument("--d-output", type=int, default=128)
    parser.add_argument("--k-input", type=int, default=8192)
    parser.add_argument("--pd-kv-transfer-mode",
                        choices=("LAYERWISE", "POST_PREFILL"),
                        default="LAYERWISE",
                        help=("POST_PREFILL is a mechanism sensitivity only; "
                              "the capacity characterization default is "
                              "LAYERWISE"))
    parser.add_argument("--force-warmup", action="store_true")
    parser.add_argument("--ep-flow-detail", action="store_true",
                        help=("write bounded per-peer detail for EP flows "
                              "using scale-out links after K injection"))
    parser.add_argument(
        "--results-root", default=None,
        help=("write a separate characterization phase under this path; "
              "when set, only new D>=32, K<=2 points are accepted"))
    args = parser.parse_args()
    allowed_d = (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024)
    if args.d_count not in allowed_d or args.k_count not in (1, 2, 4, 8):
        parser.error("D must be a supported gate point through 1024; K one of 1/2/4/8")
    if args.results_root:
        if args.d_count < 32 or args.k_count > 2:
            parser.error(
                "the capacity-calibrated phase accepts only new D>=32, K=1/2 points")
        result_root = Path(args.results_root)
        RESULTS = (result_root if result_root.is_absolute()
                   else ROOT / result_root).resolve()
        LEDGER_NAME = "CAPACITY_CALIBRATED_KV_EP_EXPERIMENTS.csv"
    if args.d_input < 1 or args.d_output < 1 or args.k_input < 1:
        parser.error("token lengths must be positive")
    RESULTS.mkdir(parents=True, exist_ok=True)
    point_id = "d%d_k%d_i%d" % (args.d_count, args.k_count, args.k_input)
    if args.pd_kv_transfer_mode != "LAYERWISE":
        # An earlier rejected POST_PREFILL attempt reused the LAYERWISE
        # warm-up and failed the pre-injection-prefix invariant. Keep the
        # corrected, mode-matched replay in a distinct point directory.
        point_id = "%s_matched_%s" % (
            args.pd_kv_transfer_mode.lower(), point_id)
    point_dir = RESULTS / "points" / point_id
    workload_dir = point_dir / "workloads"
    workload_dir.mkdir(parents=True, exist_ok=True)

    warmup = _maybe_read_cached_warmup(
        args.d_count, args.d_input, args.d_output, args.force_warmup,
        args.pd_kv_transfer_mode)
    if warmup is None:
        d_rows = _arrival_rows(args.d_count, 0, args.d_input,
                               args.d_output, args.k_input, 0)
        d_workload = workload_dir / "decode_cohort_only.jsonl"
        _write_requests(d_workload, d_rows)
        warmup_phase = (
            "warmup_d%d" % args.d_count
            if args.pd_kv_transfer_mode == "LAYERWISE" else
            "warmup_%s_d%d" % (
                args.pd_kv_transfer_mode.lower(), args.d_count))
        warmup_filename = (
            "warmup_d%d.csv" % args.d_count
            if args.pd_kv_transfer_mode == "LAYERWISE" else
            "warmup_%s_d%d.csv" % (
                args.pd_kv_transfer_mode.lower(), args.d_count))
        warmup = _run_serving(
            warmup_phase, d_workload,
            point_dir / "requests" / warmup_filename,
            injection_ns=None, detailed_ep=False,
            capture_network=bool(args.results_root),
            pd_kv_transfer_mode=args.pd_kv_transfer_mode)
        injection_ns = _warmup_arrival_ns(warmup["requests"], args.d_count)
        warmup["injection_ns"] = injection_ns
        warmup["request_csv"] = str(
            point_dir / "requests" / ("warmup_d%d.csv" % args.d_count))
        warmup["workload_sha256"] = _sha256(d_workload)
        warmup["d_input"] = args.d_input
        warmup["d_output"] = args.d_output
        cached = dict(warmup)
        cached.pop("requests", None)
        warmup_cache = _warmup_cache_path(
            args.d_count, args.d_input, args.d_output,
            args.pd_kv_transfer_mode)
        warmup_cache.parent.mkdir(parents=True, exist_ok=True)
        warmup_cache.write_text(json.dumps(cached, indent=2) + "\n",
                                 encoding="utf-8")
    else:
        injection_ns = int(warmup["injection_ns"])
    print("EVENT_DERIVED_K_INJECTION_NS", injection_ns, flush=True)

    k_rows_only = _arrival_rows(0, args.k_count, args.d_input,
                                args.d_output, args.k_input, injection_ns)
    kv_workload = workload_dir / "kv_cohort_only.jsonl"
    _write_requests(kv_workload, k_rows_only)
    kv_only = _run_serving(
        "kv_only_" + point_id, kv_workload,
        point_dir / "requests" / ("kv_only_" + point_id + ".csv"),
        injection_ns=injection_ns,
        pd_kv_transfer_mode=args.pd_kv_transfer_mode)

    full_rows = _arrival_rows(args.d_count, args.k_count, args.d_input,
                              args.d_output, args.k_input, injection_ns)
    full_workload = workload_dir / "full_fair.jsonl"
    _write_requests(full_workload, full_rows)
    full = _run_serving(
        "full_fair_" + point_id, full_workload,
        point_dir / "requests" / ("full_fair_" + point_id + ".csv"),
        injection_ns=injection_ns, detailed_ep=args.ep_flow_detail,
        pd_kv_transfer_mode=args.pd_kv_transfer_mode)
    _assert_full_prefix(warmup["requests"], full["requests"],
                        args.d_count, injection_ns)

    d_ids = set(range(args.d_count))
    k_full_ids = set(range(args.d_count, args.d_count + args.k_count))
    k_iso_ids = set(range(args.k_count))
    full_req = {int(row["request id"]): row for row in full["requests"]}
    kv_req = {int(row["request id"]): row for row in kv_only["requests"]}
    k_full_admits = [_int_cell(full_req[rid], "decode_admit_time_ns")
                     for rid in k_full_ids]
    if any(value is None for value in k_full_admits):
        raise RuntimeError("completed K requests lack Decode admission times")
    ep_window_end_ns = min(k_full_admits)
    if ep_window_end_ns <= injection_ns:
        raise RuntimeError("K Decode admission did not follow P2D injection")
    # Collective-level FlowSim records currently omit request_ids for
    # A2A_P2P rounds. The experiment-derived time window is the cohort
    # discriminator: it starts at the observed K injection and ends at the
    # first K Decode admission, so only the pre-existing D cohort can
    # participate in measured Decode rounds.
    ep_only = _collectives(warmup, injection_ns, max_end_ns=ep_window_end_ns)
    ep_full = _collectives(full, injection_ns, max_end_ns=ep_window_end_ns)
    ep_only_stats = _stats([item.get("cct_ns", 0) / 1000.0
                            for item in ep_only])
    ep_full_stats = _stats([item.get("cct_ns", 0) / 1000.0
                            for item in ep_full])
    kv_isolated = _kv_request_metrics(kv_only, k_iso_ids)
    kv_full = _kv_request_metrics(full, k_full_ids)
    kv_only_span = _distribution_for_kv(kv_isolated,
                                        "network_handoff_span_ns")
    kv_full_span = _distribution_for_kv(kv_full,
                                        "network_handoff_span_ns")
    kv_only_resid = _distribution_for_kv(kv_isolated, "residual_drain_ns")
    kv_full_resid = _distribution_for_kv(kv_full, "residual_drain_ns")
    k_ttft_full = [float(full_req[rid]["TTFT"]) / 1e6 for rid in k_full_ids]
    k_ttft_iso = [float(kv_req[rid]["TTFT"]) / 1e6 for rid in k_iso_ids]
    d_tbt_full = _tbt_in_window(
        full["requests"], d_ids, injection_ns, ep_window_end_ns)
    d_tbt_iso = _tbt_in_window(
        warmup["requests"], d_ids, injection_ns, ep_window_end_ns)
    d_tpot_full = [float(full_req[rid]["TPOT"]) / 1e6 for rid in d_ids]
    d_tpot_iso = [float(row["TPOT"]) / 1e6 for row in warmup["requests"]]
    link_metrics = _link_queue_metrics(
        full, injection_ns, ep_window_end_ns)
    d_only_link_metrics = _link_queue_metrics(
        warmup, injection_ns, ep_window_end_ns)
    ep_period_us = []
    buckets = {}
    for item in ep_full:
        key = (str(item.get("layer_id")), str(item.get("event_type")),
               str(item.get("collective_type")))
        buckets.setdefault(key, []).append(int(item["start_ns"]))
    for starts in buckets.values():
        starts.sort()
        ep_period_us.extend((b - a) / 1000.0
                            for a, b in zip(starts, starts[1:]) if b > a)
    median_ep_period_us = _percentile(ep_period_us, .50)
    queue_ratio = (
        None if link_metrics["episode_p95_ns"] is None or
        not median_ep_period_us else
        link_metrics["episode_p95_ns"] / 1000.0 / median_ep_period_us)

    ep_slow = (ep_full_stats["p99"] / ep_only_stats["p99"]
               if ep_full_stats["p99"] is not None and
               ep_only_stats["p99"] not in (None, 0) else None)
    ep_mean_slow = (ep_full_stats["mean"] / ep_only_stats["mean"]
                    if ep_full_stats["mean"] is not None and
                    ep_only_stats["mean"] not in (None, 0) else None)
    kv_resid_slow = (kv_full_resid["p99"] / kv_only_resid["p99"]
                     if kv_full_resid["p99"] is not None and
                     kv_only_resid["p99"] not in (None, 0) else None)
    kv_handoff_full_ms = _stats([
        float(full_req[rid]["p2d_kv_ready_time_ns"]) -
        float(full_req[rid]["arrival"]) for rid in k_full_ids])
    flow_overlap_ns = _active_overlap_ns(kv_full, ep_full, k_full_ids)
    ep_flow_file = next(Path(full["flowsim_dir"]).glob(
        full["phase"] + "_ep_flows.jsonl.gz"), None)
    shared_paths = _shared_path_overlap(
        kv_full, ep_flow_file, k_full_ids, injection_ns,
        ep_window_end_ns) if ep_flow_file else None
    shared_critical = (shared_paths["critical_ep_flow_pair_count"]
                       if shared_paths else None)
    shared_scaleout = (shared_paths["scaleout_ep_flow_pair_count"]
                       if shared_paths else None)
    ep_flow_coverage = _ep_flow_coverage(ep_flow_file)

    model_cfg = json.loads((ROOT / "configs/model/Qwen/"
                            "Qwen3-30B-A3B-Instruct-2507.json").read_text())
    bytes_per_layer_per_request = (
        2 * int(model_cfg["num_key_value_heads"]) *
        int(model_cfg["head_dim"]) * args.k_input * 2)
    legal_decode_capacity = 8 * 128
    k_spacing_ms = 0.0
    row = {
        "experiment_id": point_id,
        "legal_decode_capacity": legal_decode_capacity,
        "topology_mode": "1P2D_SINGLE_TOR_ACTUAL",
        "P_servers": 1,
        "D_servers": 2,
        "GPUs_per_server": 8,
        "NICs_per_server": 2,
        "NIC_bandwidth_Gbps": 200,
        "aggregate_server_bandwidth_Gbps": 400,
        "EP_degree": 16,
        "D_active": args.d_count,
        "D_input": args.d_input,
        "D_output": args.d_output,
        "K_active": args.k_count,
        "K_input": args.k_input,
        "K_output": 2,
        "K_spacing_ms": k_spacing_ms,
        "P2D_mode": args.pd_kv_transfer_mode,
        "policy": "FAIR",
        "KV_bytes": sum(item.get("bytes", 0) for item in kv_full.values()
                        if item.get("valid")),
        "EP_bytes": sum(int(item.get("bytes_sum", 0) or 0)
                        for item in ep_full),
        "shared_resource_verified": (
            "TOPOLOGY+TIME+SAME_DIRECTED_LINK_CLASS_TELEMETRY"
            if link_metrics["decode_ingress_kv_ep_same_link_overlap_ns"] > 0 else
            "TOPOLOGY+TIME+SCALEOUT_DIRECTED_PATH"
            if shared_scaleout and shared_scaleout > 0 else
            "TOPOLOGY+TIME_NO_SCALEOUT_PATH_OBSERVED"
            if flow_overlap_ns > 0 else "TOPOLOGY_ONLY"),
        "shared_ep_flow_path_overlap_count": (
            shared_paths["ep_flow_pair_count"] if shared_paths else None),
        "critical_ep_flow_path_overlap_count": shared_critical,
        "shared_scaleout_ep_flow_path_overlap_count": shared_scaleout,
        "critical_ep_scaleout_path_overlap_count": (
            shared_paths["critical_scaleout_ep_flow_pair_count"]
            if shared_paths else None),
        "overlap_duration_ms": flow_overlap_ns / 1e6,
        "shared_cut": "ToR->D0/D1 NIC uplinks (30->26..29)",
        "cut_capacity_Gbps_per_link": 200,
        "cut_util_p50": link_metrics["decode_ingress_utilization_p50"],
        "cut_util_p95": link_metrics["decode_ingress_utilization_p95"],
        "cut_util_p99": link_metrics["decode_ingress_utilization_p99"],
        "cut_util_ge90_fraction": link_metrics[
            "decode_ingress_fraction_time_ge90"],
        "cut_util_at_capacity_fraction": link_metrics[
            "decode_ingress_fraction_time_at_capacity"],
        "cut_longest_ge90_episode_us": (
            link_metrics["decode_ingress_longest_ge90_episode_ns"] / 1000.0),
        "cut_kv_ep_same_link_overlap_us": (
            link_metrics["decode_ingress_kv_ep_same_link_overlap_ns"] / 1000.0),
        "cut_kv_ep_overlap_fraction": (
            link_metrics["decode_ingress_kv_ep_overlap_fraction"]),
        "d_only_cut_util_p95": (
            d_only_link_metrics["decode_ingress_utilization_p95"]),
        "d_only_cut_util_ge90_fraction": (
            d_only_link_metrics["decode_ingress_fraction_time_ge90"]),
        "d_only_cut_util_at_capacity_fraction": (
            d_only_link_metrics["decode_ingress_fraction_time_at_capacity"]),
        "offered_rho_p50": link_metrics["offered_rho_p50"],
        "offered_rho_p95": link_metrics["offered_rho_p95"],
        "offered_rho_p99": link_metrics["offered_rho_p99"],
        "rho_gt1_fraction": None,
        "longest_rho_gt1_us": None,
        "queue_episode_p50_us": None,
        "queue_episode_p95_us": None,
        "queue_episode_max_us": None,
        "queue_persistence_ratio": queue_ratio,
        "fluid_backlog_max_bytes": link_metrics["max_fluid_backlog_bytes"],
        "decode_ingress_fluid_backlog_max_bytes": (
            link_metrics["decode_ingress_fluid_outstanding_max_bytes"]),
        "cut_active_kv_flows_p95": (
            link_metrics["decode_ingress_active_kv_flows_p95"]),
        "cut_active_ep_flows_p95": (
            link_metrics["decode_ingress_active_ep_flows_p95"]),
        "cut_released_kv_bytes": link_metrics["released_kv_bytes"],
        "cut_released_ep_bytes": link_metrics["released_ep_bytes"],
        "cut_released_kv_rate_proxy_Gbps": (
            link_metrics["released_kv_rate_proxy_gbps"]),
        "cut_released_ep_rate_proxy_Gbps": (
            link_metrics["released_ep_rate_proxy_gbps"]),
        "offered_load_semantics": (
            "LOAD_PROXY; FlowSpec has no unconstrained source-rate cap; "
            "rho is unavailable"),
        "decode_ingress_utilization_max": (
            link_metrics["decode_ingress_utilization_max"]),
        "fluid_link_sample_count": link_metrics["sample_count"],
        "fluid_telemetry_window_complete": link_metrics["window_complete"],
        "EP_CCT_p50_us": ep_full_stats["p50"],
        "EP_CCT_mean_us": ep_full_stats["mean"],
        "EP_CCT_p95_us": ep_full_stats["p95"],
        "EP_CCT_p99_us": ep_full_stats["p99"],
        "EP_CCT_mean_slowdown": ep_mean_slow,
        "EP_slowdown": ep_slow,
        "KV_residual_mean_us": kv_full_resid["mean"] / 1000.0
        if kv_full_resid["mean"] is not None else None,
        "KV_residual_p50_us": kv_full_resid["p50"] / 1000.0
        if kv_full_resid["p50"] is not None else None,
        "KV_residual_p95_us": kv_full_resid["p95"] / 1000.0
        if kv_full_resid["p95"] is not None else None,
        "KV_residual_p99_us": kv_full_resid["p99"] / 1000.0
        if kv_full_resid["p99"] is not None else None,
        "KV_residual_slowdown": kv_resid_slow,
        "KV_handoff_mean_ms": kv_handoff_full_ms["mean"] / 1e6
        if kv_handoff_full_ms["mean"] is not None else None,
        "KV_handoff_p99_ms": kv_handoff_full_ms["p99"] / 1e6
        if kv_handoff_full_ms["p99"] is not None else None,
        "TTFT_full_K_mean_ms": _stats(k_ttft_full)["mean"],
        "TTFT_full_p99_ms": _percentile(k_ttft_full, .99),
        "TTFT_KV_ONLY_K_mean_ms": _stats(k_ttft_iso)["mean"],
        "TTFT_KV_ONLY_p99_ms": _percentile(k_ttft_iso, .99),
        "TBT_full_D_mean_ms": _stats(d_tbt_full)["mean"],
        "TBT_full_p99_ms": _percentile(d_tbt_full, .99),
        "TBT_EP_ONLY_D_mean_ms": _stats(d_tbt_iso)["mean"],
        "TBT_EP_ONLY_p99_ms": _percentile(d_tbt_iso, .99),
        "TPOT_full_D_mean_ms": _stats(d_tpot_full)["mean"],
        "TPOT_full_p99_ms": _percentile(d_tpot_full, .99),
        "classification": _classify(
            ep_slow, kv_resid_slow, flow_overlap_ns, link_metrics,
            shared_scaleout),
        "notes": "Integrated FlowSim; see compact per-point summary.json; "
                 "queue is analytical residual fluid backlog; "
                 "POST_PREFILL is mechanism sensitivity only."
        if args.pd_kv_transfer_mode == "POST_PREFILL" else
                 "Integrated FlowSim; see compact per-point summary.json; "
                 "queue is analytical residual fluid backlog.",
    }
    _save_metrics_csv(row)
    point_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "experiment": row,
        "model": MODEL_NAME,
        "model_derived_kv_bytes_per_layer_per_request": bytes_per_layer_per_request,
        "event_derived_k_injection_ns": injection_ns,
        "EP_measurement_window_end_ns": ep_window_end_ns,
        "EP_measurement_window_end_reason": (
            "first K Decode admission; excludes K's own Decode EP so the "
            "measured change isolates concurrent P2D overlap"),
        "warmup_D_only": {
            "wall_seconds": warmup.get("wall_seconds"),
            "decode_admit_times_ns": [
                _int_cell(item, "decode_admit_time_ns")
                for item in warmup["requests"]],
            "fourth_token_boundary_ns": [
                _int_cell(item, "decode_admit_time_ns") + sum(_load_tbt(item)[:4])
                for item in warmup["requests"]],
        },
        "wall_seconds": {
            "warmup": warmup.get("wall_seconds"),
            "kv_only": kv_only.get("wall_seconds"),
            "full_fair": full.get("wall_seconds"),
        },
        "simulated_ep_only_cct_us_after_injection": ep_only_stats,
        "simulated_full_fair_ep_cct_us_after_injection": ep_full_stats,
        "ep_cct_p99_slowdown": ep_slow,
        "kv_only_request_network_handoff_span_ns": kv_only_span,
        "full_request_network_handoff_span_ns": kv_full_span,
        "kv_only_residual_drain_ns": kv_only_resid,
        "full_residual_drain_ns": kv_full_resid,
        "kv_residual_p99_slowdown": kv_resid_slow,
        "full_kv_ready_delay_ns": kv_handoff_full_ms,
        "full_K_TTFT_ms": _stats(k_ttft_full),
        "isolated_K_TTFT_ms": _stats(k_ttft_iso),
        "full_D_TBT_ms": _stats(d_tbt_full),
        "isolated_D_TBT_ms": _stats(d_tbt_iso),
        "full_D_TPOT_ms": _stats(d_tpot_full),
        "isolated_D_TPOT_ms": _stats(d_tpot_iso),
        "fluid_link_telemetry": link_metrics,
        "D_ONLY_fluid_link_telemetry": d_only_link_metrics,
        "median_EP_period_us": median_ep_period_us,
        "flow_overlap_ns": flow_overlap_ns,
        "critical_EP_flow_shared_path_overlaps": shared_critical,
        "shared_EP_KV_flow_path_overlap": shared_paths,
        "EP_flow_telemetry_coverage": ep_flow_coverage,
        "EP_flow_telemetry_scope": (
            "EP peer flows whose paths use a directed ToR uplink"
            if args.ep_flow_detail else "disabled"),
        "full_request_ids": {
            "D": sorted(d_ids), "K": sorted(k_full_ids)},
        "synthetic_communication_byte_override": False,
        "priority_policies_run": ["FAIR"],
        "serving_metrics_source": "completed integrated request CSV",
        "network_model": "FlowSim max-min fluid; queue_bytes is residual fluid backlog",
        "link_telemetry_truncated": link_metrics.get("telemetry_truncated"),
    }
    (point_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment_id": point_id,
        "K_injection_ns": injection_ns,
        "EP_CCT_P99_us": row["EP_CCT_p99_us"],
        "EP_slowdown": ep_slow,
        "KV_residual_P99_us": row["KV_residual_p99_us"],
        "KV_residual_slowdown": kv_resid_slow,
        "TTFT_full_K_P99_ms": row["TTFT_full_p99_ms"],
        "TTFT_KV_ONLY_P99_ms": row["TTFT_KV_ONLY_p99_ms"],
        "TBT_full_D_P99_ms": row["TBT_full_p99_ms"],
        "TBT_EP_ONLY_D_P99_ms": row["TBT_EP_ONLY_p99_ms"],
        "classification": row["classification"],
        "wall_seconds": summary["wall_seconds"],
    }, indent=2), flush=True)


def _active_overlap_ns(kv_by_request, ep_rows, k_ids):
    intervals = []
    for request_id in k_ids:
        item = kv_by_request.get(request_id, {})
        if item.get("valid"):
            intervals.extend(item.get("intervals", ()))
    # As above, collective rows lack request_ids. `ep_rows` has already been
    # restricted to the event-derived interval before K Decode admission.
    ep_intervals = [(int(item["start_ns"]), int(item["end_ns"]))
                    for item in ep_rows]
    pieces = []
    for a, b in intervals:
        for c, d in ep_intervals:
            start, end = max(a, c), min(b, d)
            if end > start:
                pieces.append((start, end))
    if not pieces:
        return 0
    pieces.sort()
    merged = []
    start, end = pieces[0]
    for next_start, next_end in pieces[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            merged.append((start, end))
            start, end = next_start, next_end
    merged.append((start, end))
    return sum(end - start for start, end in merged)


def _classify(ep_slow, kv_slow, overlap_ns, link_metrics,
              shared_scaleout_pairs=None):
    if overlap_ns <= 0:
        return "NO_OVERLAP"
    if (not shared_scaleout_pairs and
            not link_metrics.get("decode_ingress_kv_ep_same_link_overlap_ns")):
        return "TIME_OVERLAP_NO_SCALEOUT_PATH_OBSERVED"
    if not link_metrics.get("sample_count"):
        return "OVERLAP_NO_LINK_TELEMETRY"
    if ep_slow is not None and ep_slow >= 1.20 and kv_slow is not None and kv_slow >= 1.20:
        return "BOTH_BARRIER_CANDIDATE"
    if ep_slow is not None and ep_slow >= 1.20:
        return "EP_BARRIER_CANDIDATE"
    if kv_slow is not None and kv_slow >= 1.20:
        return "KV_BARRIER_CANDIDATE"
    if link_metrics.get("max_fluid_backlog_bytes", 0) > 0:
        return "SHARED_SCALEOUT_OVERLAP_WITH_FLUID_BACKLOG_NO_20P_BARRIER"
    return "SHARED_SCALEOUT_OVERLAP_NO_QUEUE"


if __name__ == "__main__":
    main()
