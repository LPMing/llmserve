#!/usr/bin/env python3
"""Read only Parquet chute_id pages from pinned public Chutes shards."""

import argparse
import concurrent.futures
import json
import os
import struct
import time
import urllib.request
from pathlib import Path

import duckdb


REVISION = "85722e694bf7bb8a5a5ccdf70424fa5998372467"
MODEL_CHUTE_ID = "0d7184a2-32a3-53e0-9607-058c37edaab5"
RAW = Path(__file__).resolve().parent / "chutes_raw"


def byte_range(url, start, length):
    last = start + length - 1
    request = urllib.request.Request(
        url, headers={"Range": "bytes=%d-%d" % (start, last)})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read()
                if response.status != 206 or len(data) != length:
                    raise ValueError("short or non-range HTTP response")
                return data
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def scan(shard, workers):
    name = "train-%05d-of-00045.parquet" % shard
    source = ("https://huggingface.co/datasets/harvardMadsys/"
              "chutes_metadata/resolve/%s/data/trace/%s" % (REVISION, name))
    with urllib.request.urlopen(urllib.request.Request(source, method="HEAD"),
                                timeout=30) as response:
        signed_url = response.url
        size = int(response.headers["Content-Length"])
        etag = response.headers.get("ETag", "").strip('"')
    target = RAW / ("chute_ids_shard%02d.parquet" % shard)
    if not target.exists():
        trailer = byte_range(signed_url, size - 8, 8)
        if trailer[4:] != b"PAR1":
            raise ValueError("invalid Parquet trailer")
        metadata_length = struct.unpack("<I", trailer[:4])[0]
        footer_offset = size - metadata_length - 8
        footer = byte_range(signed_url, footer_offset, metadata_length + 8)
        with target.open("wb") as handle:
            handle.truncate(size)
            handle.seek(footer_offset)
            handle.write(footer)
        db = duckdb.connect()
        chunks = db.execute("""
            SELECT coalesce(dictionary_page_offset,data_page_offset),
                   total_compressed_size
            FROM parquet_metadata(?) WHERE path_in_schema='chute_id'
            ORDER BY row_group_id
        """, [str(target)]).fetchall()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(byte_range, signed_url, int(offset),
                                   int(length)): (int(offset), int(length))
                       for offset, length in chunks}
            with target.open("r+b") as handle:
                for completed, future in enumerate(
                        concurrent.futures.as_completed(futures), 1):
                    offset, _ = futures[future]
                    handle.seek(offset)
                    handle.write(future.result())
                    if completed % 32 == 0:
                        print(name, "column chunks", completed, "of",
                              len(chunks), flush=True)
    db = duckdb.connect()
    count = db.execute("""
        SELECT count(*) FROM read_parquet(?) WHERE chute_id=?
    """, [str(target), MODEL_CHUTE_ID]).fetchone()[0]
    row_count = db.execute("""
        SELECT sum(row_group_num_rows) FROM
          (SELECT DISTINCT row_group_id,row_group_num_rows
           FROM parquet_metadata(?))
    """, [str(target)]).fetchone()[0]
    result = {"source": source, "revision": REVISION, "shard": shard,
              "logical_bytes": size, "sparse_allocated_bytes":
              os.stat(target).st_blocks * 512,
              "source_etag": etag, "model_chute_id": MODEL_CHUTE_ID,
              "model_rows": count, "all_rows": row_count,
              "local_chute_column_file": target.name}
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards", nargs="+", type=int, required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    RAW.mkdir(exist_ok=True)
    results = {}
    for shard in args.shards:
        if not 0 <= shard < 45:
            raise ValueError("shard must be in [0,44]")
        results[str(shard)] = scan(shard, args.workers)
        (RAW / "id_scan_manifest.json").write_text(
            json.dumps(results, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
