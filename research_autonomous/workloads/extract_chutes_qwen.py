#!/usr/bin/env python3
"""Extract a pinned model from selected Chutes Parquet shards by HTTP range."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

import duckdb


DATASET = "harvardMadsys/chutes_metadata"
REVISION = "85722e694bf7bb8a5a5ccdf70424fa5998372467"
MODEL = "Qwen/Qwen3-32B"
CHUTE_ID = "0d7184a2-32a3-53e0-9607-058c37edaab5"
HERE = Path(__file__).resolve().parent
RAW = HERE / "chutes_raw"
SELECT = ("invocation_id,function_name,chute_id,user_id,rehash_round,"
          "instance_id,started_at,completed_at,it,ot,ct,ttft")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards", nargs="+", type=int, default=[44])
    args = parser.parse_args()
    RAW.mkdir(exist_ok=True)
    db = duckdb.connect()
    db.execute("LOAD httpfs")
    db.execute("SET http_timeout=20000")
    db.execute("SET http_retries=2")
    db.execute("SET threads=2")
    results = {}
    for shard in args.shards:
        if not 0 <= shard < 45:
            raise ValueError("shard must be in [0,44]")
        name = "train-%05d-of-00045.parquet" % shard
        local_source = RAW / name
        if local_source.exists():
            source = str(local_source)
        else:
            url = ("https://huggingface.co/datasets/%s/resolve/%s/data/trace/%s"
                   % (DATASET, REVISION, name))
            request = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(request, timeout=30) as response:
                source = response.url
        target = RAW / ("qwen3_32b_shard%02d.parquet"
                        % shard)
        if not target.exists() or target.stat().st_size == 0:
            temporary = target.with_name(target.name + ".part.parquet")
            if temporary.exists():
                temporary.unlink()
            sql = ("COPY (SELECT %s FROM read_parquet(?) "
                   "WHERE chute_id='%s') TO '%s' (FORMAT PARQUET)"
                   % (SELECT, CHUTE_ID, temporary))
            db.execute(sql, [source])
            temporary.replace(target)
        count = db.execute("SELECT count(*) FROM read_parquet(?)",
                           [str(target)]).fetchone()[0]
        data = target.read_bytes()
        results[name] = {"local_file": target.name, "rows": count,
                         "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()}
        print(name, results[name], flush=True)
    manifest = {
        "source": "https://huggingface.co/datasets/" + DATASET,
        "revision": REVISION,
        "license": "CC-BY-4.0",
        "model": MODEL,
        "chute_id": CHUTE_ID,
        "selection": "Exact chute_id from pinned chute_models.parquet",
        "columns": SELECT.split(","),
        "shards": results,
    }
    (RAW / "qwen3_32b_extract_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
