#!/usr/bin/env python3
"""Resume a pinned Chutes Parquet shard download for local filtering."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


REVISION = "85722e694bf7bb8a5a5ccdf70424fa5998372467"
RAW = Path(__file__).resolve().parent / "chutes_raw"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, default=44)
    args = parser.parse_args()
    if not 0 <= args.shard < 45:
        raise ValueError("shard must be in [0,44]")
    RAW.mkdir(exist_ok=True)
    name = "train-%05d-of-00045.parquet" % args.shard
    url = ("https://huggingface.co/datasets/harvardMadsys/"
           "chutes_metadata/resolve/%s/data/trace/%s" % (REVISION, name))
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"),
                                timeout=30) as response:
        signed_url = response.url
        size = int(response.headers["Content-Length"])
        source_etag = response.headers.get("ETag", "").strip('"')
    target = RAW / name
    temporary = RAW / (name + ".part")
    if not target.exists():
        start = temporary.stat().st_size if temporary.exists() else 0
        if start > size:
            raise ValueError("local partial download exceeds source length")
        if start < size:
            request = urllib.request.Request(
                signed_url, headers={"Range": "bytes=%d-" % start})
            with urllib.request.urlopen(request, timeout=90) as response:
                if response.status != 206:
                    raise ValueError("source did not honor resume range")
                with temporary.open("ab") as handle:
                    while True:
                        chunk = response.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        start += len(chunk)
                        if start // (128 * 1024 * 1024) != (
                                start - len(chunk)) // (128 * 1024 * 1024):
                            print("downloaded", start, "of", size, flush=True)
        if temporary.stat().st_size != size:
            raise ValueError("incomplete download")
        temporary.replace(target)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    manifest = {
        "source": url,
        "revision": REVISION,
        "file": name,
        "bytes": size,
        "sha256": digest.hexdigest(),
        "source_etag": source_etag,
    }
    (RAW / ("shard%02d_manifest.json" % args.shard)).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
