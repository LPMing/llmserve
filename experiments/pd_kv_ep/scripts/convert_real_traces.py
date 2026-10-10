#!/usr/bin/env python3
"""Convert public LLM serving traces without inventing prompt token IDs.

The converter deliberately keeps the raw schema visible in ``raw_manifest``
and writes every rejected row to ``invalid_records.jsonl``.  The simulator's
flat JSONL format is extended only with provenance fields and, for Mooncake,
``input_block_hashes``.  Mooncake block hashes are never copied into
``input_tok_ids``.
"""

import argparse
import csv
import datetime
import hashlib
import json
import math
import os
import random
from collections import Counter


DATASET_DEFAULTS = {
    "azure2024": {
        "timestamp_unit": "s",
        "input_field": "ContextTokens",
        "output_field": "GeneratedTokens",
    },
    "burstgpt": {
        "timestamp_unit": "s",
        "input_field": "Request tokens",
        "output_field": "Response tokens",
    },
    "mooncake_conversation": {
        "timestamp_unit": "ms",
        "input_field": "input_length",
        "output_field": "output_length",
    },
    "mooncake_toolagent": {
        "timestamp_unit": "ms",
        "input_field": "input_length",
        "output_field": "output_length",
    },
}


def _json_default(value):
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(type(value).__name__)


def _as_number(value):
    if value is None or str(value).strip() == "":
        raise ValueError("empty numeric field")
    number = float(str(value).strip())
    if not math.isfinite(number):
        raise ValueError("non-finite numeric field")
    return number


def _to_ns(value, unit):
    text = str(value).strip()
    if "-" in text and ("T" in text or " " in text):
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return int(round(parsed.timestamp() * 1e9))
    multiplier = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0}[unit]
    result = int(round(_as_number(value) * multiplier))
    if result < 0:
        raise ValueError("negative timestamp")
    return result


def _first_present(row, names):
    for name in names:
        if name in row and str(row[name]).strip() != "":
            return row[name], name
    return None, None


def _stable_source_id(dataset, raw_id, ordinal):
    if raw_id is None or str(raw_id).strip() == "":
        return f"{dataset}:{ordinal}"
    return f"{dataset}:{str(raw_id).strip()}"


def _hash_namespace(dataset, source_id, value):
    # The released Mooncake values are remapped block identities, not tokens.
    # Namespace by trace family, but deliberately *not* by request: equal
    # hash_ids in different requests are the evidence for shared prefixes.
    # ``source_id`` remains an argument so callers cannot accidentally omit
    # the provenance field while changing this cache-key policy.
    del source_id
    return f"{dataset}:{value}"


def _read_jsonl(path):
    with open(path, "r", encoding="utf-8") as source:
        for ordinal, line in enumerate(source):
            if not line.strip():
                continue
            yield ordinal, json.loads(line)


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        headers = list(reader.fieldnames or [])
        if not headers:
            raise ValueError(f"CSV has no header: {path}")
        yield headers, reader


def _convert_row(dataset, row, ordinal, timestamp_unit, input_field,
                 output_field, raw_path, hash_block_size):
    if not isinstance(row, dict):
        raise ValueError("record is not an object")

    timestamp, timestamp_name = _first_present(
        row, ["TIMESTAMP", "Timestamp", "timestamp", "arrival_time_ns"])
    input_value, input_name = _first_present(
        row, [input_field, "ContextTokens", "Request tokens", "input_length",
              "input_toks"])
    output_value, output_name = _first_present(
        row, [output_field, "GeneratedTokens", "Response tokens", "output_length",
              "output_toks"])
    if timestamp is None or input_value is None or output_value is None:
        raise ValueError(
            f"missing required fields timestamp={timestamp_name!r}, "
            f"input={input_name!r}, output={output_name!r}")

    arrival_ns = (_to_ns(timestamp, timestamp_unit)
                  if timestamp_name != "arrival_time_ns" else
                  int(_as_number(timestamp)))
    input_toks = int(_as_number(input_value))
    output_toks = int(_as_number(output_value))
    if input_toks < 0 or output_toks < 0:
        raise ValueError("negative token count")

    raw_id, _ = _first_present(
        row, ["request_id", "RequestID", "Request Id", "id", "ID"])
    source_id = _stable_source_id(dataset, raw_id, ordinal)
    converted = {
        "request_id": source_id,
        "source_request_id": raw_id if raw_id is not None else str(ordinal),
        "source_trace": os.path.abspath(raw_path),
        "source_record_index": ordinal,
        "input_toks": input_toks,
        "output_toks": output_toks,
        "arrival_time_ns_raw": arrival_ns,
    }

    session_id, _ = _first_present(row, ["session_id", "SessionID", "session"])
    if session_id is not None and str(session_id).strip():
        converted["session_id"] = str(session_id).strip()

    model, _ = _first_present(row, ["Model", "model"])
    if model is not None and str(model).strip():
        converted["source_model"] = str(model).strip()

    hash_values = row.get("hash_ids")
    if hash_values is not None:
        if not isinstance(hash_values, list):
            raise ValueError("hash_ids must be a JSON list")
        converted["input_block_hashes"] = [
            _hash_namespace(dataset, source_id, value) for value in hash_values
        ]
        converted["prefix_block_hashes"] = list(converted["input_block_hashes"])
        converted["hash_block_size"] = int(hash_block_size)
        converted["hash_semantics"] = "remapped_prefix_block_identity"

    return converted


def _reservoir_add(sample, value, seen, limit, rng):
    """Keep a deterministic bounded sample for quantiles on week traces."""
    if len(sample) < limit:
        sample.append(value)
        return
    slot = rng.randrange(seen)
    if slot < limit:
        sample[slot] = value


def _convert_sorted_stream(args):
    """Convert a timestamp-sorted source without retaining the whole trace.

    Azure's week traces are chronologically sorted and too large for the
    previous list-then-sort implementation.  This path asserts monotonicity,
    writes normalized JSONL incrementally, and uses deterministic reservoir
    samples for distribution statistics.
    """
    defaults = DATASET_DEFAULTS[args.dataset]
    timestamp_unit = args.timestamp_unit or defaults["timestamp_unit"]
    input_field = args.input_field or defaults["input_field"]
    output_field = args.output_field or defaults["output_field"]
    os.makedirs(args.output_dir, exist_ok=True)
    converted_path = os.path.join(args.output_dir, "converted.jsonl")
    invalid_path = os.path.join(args.output_dir, "invalid_records.jsonl")
    manifest_path = os.path.join(args.output_dir, "raw_manifest.json")
    stats_path = os.path.join(args.output_dir, "conversion_stats.json")

    stats = Counter()
    invalid_reasons = Counter()
    sessions = set()
    input_sample = []
    output_sample = []
    interarrival_sample = []
    rng = random.Random(0)
    first_timestamp = None
    previous_raw = None
    previous_normalized = None
    last_normalized = 0
    has_blocks = False
    headers = []
    iterator = _read_jsonl(args.input) if args.input.lower().endswith(".jsonl") else None
    csv_source = None
    if iterator is None:
        csv_source = _read_csv(args.input)
        headers, csv_reader = next(csv_source)
        iterator = enumerate(csv_reader)

    with open(invalid_path, "w", encoding="utf-8") as invalid, \
            open(converted_path, "w", encoding="utf-8") as output:
        for ordinal, row in iterator:
            stats["raw_records"] += 1
            if args.max_records and stats["raw_records"] > args.max_records:
                break
            try:
                converted = _convert_row(
                    args.dataset, row, ordinal, timestamp_unit, input_field,
                    output_field, args.input, args.hash_block_size)
                raw_timestamp = converted.pop("arrival_time_ns_raw")
                if previous_raw is not None and raw_timestamp < previous_raw:
                    raise ValueError(
                        "source timestamps are not nondecreasing; rerun without "
                        "--assume-sorted to use the bounded external-sort path"
                    )
                if first_timestamp is None:
                    first_timestamp = raw_timestamp
                normalized = raw_timestamp - first_timestamp
                converted["arrival_time_ns"] = normalized
                output.write(json.dumps(converted, ensure_ascii=False) + "\n")
                previous_raw = raw_timestamp
                if previous_normalized is not None:
                    _reservoir_add(
                        interarrival_sample, normalized - previous_normalized,
                        stats["converted_records"], 100000, rng)
                previous_normalized = normalized
                last_normalized = normalized
                stats["converted_records"] += 1
                if converted["output_toks"] == 0:
                    stats["zero_output_records"] += 1
                if "input_block_hashes" in converted:
                    has_blocks = True
                    stats["records_with_block_hashes"] += 1
                    stats["source_hash_blocks"] += len(
                        converted["input_block_hashes"])
                if "session_id" in converted:
                    sessions.add(converted["session_id"])
                    stats["records_with_session_id"] += 1
                _reservoir_add(input_sample, converted["input_toks"],
                               stats["converted_records"], 100000, rng)
                _reservoir_add(output_sample, converted["output_toks"],
                               stats["converted_records"], 100000, rng)
            except Exception as error:
                reason = str(error)
                invalid_reasons[reason] += 1
                stats["invalid_records"] += 1
                invalid.write(json.dumps({
                    "source_record_index": ordinal,
                    "reason": reason,
                    "raw": row,
                }, ensure_ascii=False) + "\n")
                if "source timestamps are not nondecreasing" in reason:
                    raise

    if not stats["converted_records"] or first_timestamp is None:
        raise RuntimeError(f"no valid records converted from {args.input}")

    def percentile(values, p):
        if not values:
            return 0
        values = sorted(values)
        index = min(len(values) - 1, int(round((len(values) - 1) * p)))
        return values[index]

    reported_timestamp_unit = (
        "iso8601" if args.dataset == "azure2024" else timestamp_unit
    )
    summary = dict(stats)
    summary.update({
        "duration_ns": last_normalized,
        "duration_s": last_normalized / 1e9,
        "mean_rps": stats["converted_records"] / max(last_normalized / 1e9, 1e-9),
        "session_count": len(sessions),
        "input_tokens_p50": percentile(input_sample, 0.50),
        "input_tokens_p95": percentile(input_sample, 0.95),
        "input_tokens_max": max(input_sample),
        "output_tokens_p50": percentile(output_sample, 0.50),
        "output_tokens_p95": percentile(output_sample, 0.95),
        "output_tokens_max": max(output_sample),
        "interarrival_p50_ns": percentile(interarrival_sample, 0.50),
        "interarrival_p95_ns": percentile(interarrival_sample, 0.95),
        "interarrival_min_ns": min(interarrival_sample) if interarrival_sample else 0,
        "statistics_sampling": "deterministic reservoir, max 100000 values per field",
        "timestamp_normalization": {
            "source_unit": reported_timestamp_unit,
            "first_source_timestamp_ns": first_timestamp,
            "output_unit": "ns",
        },
        "ordering": "source order asserted nondecreasing; normalized online",
        "hash_block_size": args.hash_block_size if has_blocks else None,
    })
    summary["invalid_reason_counts"] = dict(invalid_reasons)
    with open(stats_path, "w", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False,
                  default=_json_default)

    manifest = {
        "dataset": args.dataset,
        "source_path": os.path.abspath(args.input),
        "source_sha256": _sha256(args.input),
        "source_size_bytes": os.path.getsize(args.input),
        "source_headers": headers,
        "timestamp_unit": reported_timestamp_unit,
        "input_field": input_field,
        "output_field": output_field,
        "hash_block_size": args.hash_block_size,
        "converter": os.path.abspath(__file__),
        "output_format": "LLMServingSim flat JSONL plus provenance fields",
        "prefix_policy": (
            "Mooncake hash_ids become input_block_hashes; no input_tok_ids are created"
            if has_blocks else
            "No prompt token IDs are available; prefix caching is disabled by default"
        ),
    }
    with open(manifest_path, "w", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2, ensure_ascii=False)
    return summary


def convert(args):
    if args.assume_sorted or args.dataset == "azure2024":
        return _convert_sorted_stream(args)
    defaults = DATASET_DEFAULTS[args.dataset]
    timestamp_unit = args.timestamp_unit or defaults["timestamp_unit"]
    input_field = args.input_field or defaults["input_field"]
    output_field = args.output_field or defaults["output_field"]
    if timestamp_unit not in ("s", "ms", "us", "ns"):
        raise ValueError(f"unsupported timestamp unit: {timestamp_unit}")

    os.makedirs(args.output_dir, exist_ok=True)
    converted_path = os.path.join(args.output_dir, "converted.jsonl")
    invalid_path = os.path.join(args.output_dir, "invalid_records.jsonl")
    manifest_path = os.path.join(args.output_dir, "raw_manifest.json")
    stats_path = os.path.join(args.output_dir, "conversion_stats.json")

    stats = Counter()
    invalid_reasons = Counter()
    rows = []
    headers = []
    iterator = _read_jsonl(args.input) if args.input.lower().endswith(".jsonl") else None
    csv_reader = None
    csv_source = None
    if iterator is None:
        csv_source = _read_csv(args.input)
        headers, csv_reader = next(csv_source)
        iterator = enumerate(csv_reader)

    with open(invalid_path, "w", encoding="utf-8") as invalid:
        for ordinal, row in iterator:
            stats["raw_records"] += 1
            if args.max_records and stats["raw_records"] > args.max_records:
                break
            try:
                converted = _convert_row(
                    args.dataset, row, ordinal, timestamp_unit, input_field,
                    output_field, args.input, args.hash_block_size)
                rows.append(converted)
                stats["converted_records"] += 1
                if converted["output_toks"] == 0:
                    stats["zero_output_records"] += 1
                if "input_block_hashes" in converted:
                    stats["records_with_block_hashes"] += 1
                    stats["source_hash_blocks"] += len(converted["input_block_hashes"])
                if "session_id" in converted:
                    stats["records_with_session_id"] += 1
            except Exception as error:  # keep the bad row auditable
                reason = str(error)
                invalid_reasons[reason] += 1
                stats["invalid_records"] += 1
                invalid.write(json.dumps({
                    "source_record_index": ordinal,
                    "reason": reason,
                    "raw": row,
                }, ensure_ascii=False) + "\n")

    if not rows:
        raise RuntimeError(f"no valid records converted from {args.input}")
    rows.sort(key=lambda row: (row["arrival_time_ns_raw"],
                               row["source_record_index"]))
    first_timestamp = rows[0]["arrival_time_ns_raw"]
    previous = None
    interarrival = []
    sessions = set()
    input_lengths = []
    output_lengths = []
    with open(converted_path, "w", encoding="utf-8") as output:
        for row in rows:
            row["arrival_time_ns"] = row.pop("arrival_time_ns_raw") - first_timestamp
            if previous is not None:
                interarrival.append(row["arrival_time_ns"] - previous)
            previous = row["arrival_time_ns"]
            if "session_id" in row:
                sessions.add(row["session_id"])
            input_lengths.append(row["input_toks"])
            output_lengths.append(row["output_toks"])
            output.write(json.dumps(row, ensure_ascii=False) + "\n")

    def percentile(values, p):
        if not values:
            return 0
        values = sorted(values)
        index = min(len(values) - 1, int(round((len(values) - 1) * p)))
        return values[index]

    duration_ns = max(row["arrival_time_ns"] for row in rows)
    summary = dict(stats)
    reported_timestamp_unit = (
        "iso8601" if args.dataset == "azure2024" else timestamp_unit
    )
    summary.update({
        "duration_ns": duration_ns,
        "duration_s": duration_ns / 1e9,
        "mean_rps": len(rows) / max(duration_ns / 1e9, 1e-9),
        "session_count": len(sessions),
        "input_tokens_p50": percentile(input_lengths, 0.50),
        "input_tokens_p95": percentile(input_lengths, 0.95),
        "input_tokens_max": max(input_lengths),
        "output_tokens_p50": percentile(output_lengths, 0.50),
        "output_tokens_p95": percentile(output_lengths, 0.95),
        "output_tokens_max": max(output_lengths),
        "interarrival_p50_ns": percentile(interarrival, 0.50),
        "interarrival_p95_ns": percentile(interarrival, 0.95),
        "interarrival_min_ns": min(interarrival) if interarrival else 0,
        "timestamp_normalization": {
            "source_unit": reported_timestamp_unit,
            "first_source_timestamp_ns": first_timestamp,
            "output_unit": "ns",
        },
        "ordering": "stable source order after nondecreasing timestamp sort",
        "hash_block_size": args.hash_block_size if "input_block_hashes" in rows[0] else None,
    })
    summary["invalid_reason_counts"] = dict(invalid_reasons)
    with open(stats_path, "w", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False, default=_json_default)

    manifest = {
        "dataset": args.dataset,
        "source_path": os.path.abspath(args.input),
        "source_sha256": _sha256(args.input),
        "source_size_bytes": os.path.getsize(args.input),
        "source_headers": headers,
        "timestamp_unit": reported_timestamp_unit,
        "input_field": input_field,
        "output_field": output_field,
        "hash_block_size": args.hash_block_size,
        "converter": os.path.abspath(__file__),
        "output_format": "LLMServingSim flat JSONL plus provenance fields",
        "prefix_policy": (
            "Mooncake hash_ids become input_block_hashes; no input_tok_ids are created"
            if "input_block_hashes" in rows[0] else
            "No prompt token IDs are available; prefix caching is disabled by default"
        ),
    }
    with open(manifest_path, "w", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2, ensure_ascii=False)
    return summary


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, choices=sorted(DATASET_DEFAULTS))
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timestamp-unit", choices=("s", "ms", "us", "ns"))
    parser.add_argument("--input-field")
    parser.add_argument("--output-field")
    parser.add_argument("--hash-block-size", type=int, default=512)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--assume-sorted", action="store_true",
                        help="stream a source after asserting nondecreasing timestamps")
    args = parser.parse_args()
    print(json.dumps(convert(args), indent=2, ensure_ascii=False, default=_json_default))


if __name__ == "__main__":
    main()
