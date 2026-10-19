#!/usr/bin/env python3
"""Summarize exact-model Chutes arrivals without inferring hidden topology."""

import argparse
import json
from pathlib import Path

import duckdb


HERE = Path(__file__).resolve().parent
RAW = HERE / "chutes_raw"
OUTPUT = HERE / "chutes_qwen3_32b_analysis"
CACHE_HIT_GATE = 0.8833275253994244


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, default=44)
    args = parser.parse_args()
    source = RAW / ("qwen3_32b_shard%02d.parquet" % args.shard)
    if not source.exists() or source.stat().st_size == 0:
        raise FileNotFoundError(source)
    db = duckdb.connect()
    db.execute("SET memory_limit='12GB'")
    db.execute("SET temp_directory='/tmp/duckdb_chutes_qwen'")
    db.execute("SET threads=4")
    path = str(source)
    scalar = db.execute("""
        SELECT count(*), min(started_at), max(started_at),
               count(DISTINCT instance_id),
               count(DISTINCT (user_id,rehash_round)),
               count(*) FILTER (WHERE it IS NOT NULL AND ot IS NOT NULL),
               count(*) FILTER (WHERE it <= 16384),
               count(*) FILTER (WHERE it <= 2048),
               count(*) FILTER (WHERE ct IS NOT NULL),
               count(*) FILTER (WHERE ct > 0),
               count(*) FILTER (WHERE ct > it),
               count(*) FILTER (WHERE it > 0 AND ct >= 0 AND ct <= it
                                AND ct / it >= ?),
               count(*) FILTER (WHERE it > 0 AND it <= 16384
                                AND ct >= 0 AND ct <= it
                                AND ct / it >= ?
                                AND ttft IS NOT NULL),
               count(*) FILTER (WHERE ttft IS NOT NULL),
               count(*) FILTER (WHERE completed_at >= started_at),
               quantile_cont(it, [0.5,0.9,0.95,0.99]),
               quantile_cont(ot, [0.5,0.9,0.95,0.99]),
               quantile_cont(ct, [0.5,0.9,0.95,0.99]),
               quantile_cont(ct / it, [0.5,0.9,0.95,0.99])
                   FILTER (WHERE it > 0 AND ct >= 0 AND ct <= it),
               quantile_cont(ttft, [0.5,0.9,0.95,0.99]),
               quantile_cont(date_diff('millisecond',started_at,completed_at),
                             [0.5,0.9,0.95,0.99])
                   FILTER (WHERE completed_at >= started_at),
               avg(date_diff('millisecond',started_at,completed_at))
                   FILTER (WHERE completed_at >= started_at)
        FROM read_parquet(?)
    """, [CACHE_HIT_GATE, CACHE_HIT_GATE, path]).fetchone()
    keys = ["rows", "first_arrival", "last_arrival", "instances", "users",
            "rows_with_lengths", "input_le_16384", "input_le_2048",
            "cached_token_observed", "cached_token_positive",
            "cached_token_gt_input", "cached_ratio_ge_gate",
            "cached_ratio_ge_gate_profile_length_streaming", "ttft_observed",
            "duration_observed",
            "input_quantiles", "output_quantiles", "cached_quantiles",
            "cached_ratio_quantiles", "ttft_seconds_quantiles", "duration_ms_quantiles",
            "duration_ms_mean"]
    summary = dict(zip(keys, scalar))
    summary["conditional_cache_hit_gate"] = CACHE_HIT_GATE
    span_seconds = (scalar[2] - scalar[1]).total_seconds()
    summary["arrival_rate_rps_over_shard_span"] = scalar[0] / span_seconds
    summary["first_arrival"] = str(summary["first_arrival"])
    summary["last_arrival"] = str(summary["last_arrival"])
    summary["function_counts"] = dict(db.execute("""
        SELECT function_name,count(*) FROM read_parquet(?)
        GROUP BY function_name ORDER BY count(*) DESC
    """, [path]).fetchall())
    instance_counts = [row[0] for row in db.execute("""
        SELECT count(*) FROM read_parquet(?) GROUP BY instance_id
    """, [path]).fetchall()]
    instance_counts.sort()
    summary["instance_request_count_p50_p95_max"] = (
        [instance_counts[int((len(instance_counts) - 1) * fraction)]
         for fraction in (0.5, 0.95, 1.0)] if instance_counts else [])
    db.execute("""
        CREATE TEMP TABLE arrivals_100ms AS
        SELECT CAST(floor(epoch_us(started_at) / 100000) AS BIGINT) AS bin,
               instance_id, count(*) AS n
        FROM read_parquet(?) WHERE started_at IS NOT NULL
        GROUP BY bin,instance_id
    """, [path])
    summary["arrival_bucket_max_all_instances"] = {}
    summary["arrival_bucket_max_one_instance"] = {}
    summary["arrival_bucket_max_distinct_instances"] = {}
    summary["arrival_bucket_requests_with_ge_9_distinct_instances"] = {}
    summary["arrival_bucket_count_with_ge_9_distinct_instances"] = {}
    for width_ms in (200, 1000, 2000, 10000):
        width_bins = width_ms // 100
        for offset_bins in (0, width_bins // 2):
            all_max, instance_max, distinct_max, affected_requests, bins = db.execute("""
                WITH per_instance AS (
                    SELECT CAST(floor((bin - ?) / ?) AS BIGINT) AS bucket,
                           instance_id,sum(n) AS n
                    FROM arrivals_100ms GROUP BY bucket,instance_id
                ), per_bucket AS (
                    SELECT bucket,sum(n) AS total_n,max(n) AS instance_max,
                           count(*) AS distinct_instances
                    FROM per_instance GROUP BY bucket
                )
                SELECT max(total_n),max(instance_max),max(distinct_instances),
                       sum(total_n) FILTER (WHERE distinct_instances >= 9),
                       count(*) FILTER (WHERE distinct_instances >= 9)
                FROM per_bucket
            """, [offset_bins, width_bins]).fetchone()
            key = "%dms_offset%dms" % (width_ms, offset_bins * 100)
            summary["arrival_bucket_max_all_instances"][key] = all_max
            summary["arrival_bucket_max_one_instance"][key] = instance_max
            summary["arrival_bucket_max_distinct_instances"][key] = distinct_max
            summary["arrival_bucket_requests_with_ge_9_distinct_instances"][key] = (
                affected_requests or 0)
            summary["arrival_bucket_count_with_ge_9_distinct_instances"][key] = (
                bins or 0)
    summary["interpretation"] = (
        "Aligned arrival buckets count requests to this model, not Prefill starts or "
        "flows on one physical network cut. TTFT values are production "
        "seconds on unknown instance GPUs and cannot calibrate local "
        "RTXPRO6000 P/D transfer time directly. Cached tokens are observed "
        "outcomes, not exact reusable prefix identities.")
    summary["source_file"] = source.name
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / ("summary_shard%02d.json" % args.shard)).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
