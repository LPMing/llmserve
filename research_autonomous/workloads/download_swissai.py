#!/usr/bin/env python3
"""Download the pinned exact-model SwissAI Qwen3-32B bucket trace."""

import hashlib
import json
import urllib.request
from pathlib import Path


REVISION = "c3dd66602b564ce189f7db81115620413e646cd5"
SOURCE = "https://huggingface.co/datasets/eth-easl/swissai-serving-trace"
FILENAME = "qwen3-32b-buckets.jsonl"
EXPECTED_BYTES = 4617817342
EXPECTED_SHA256 = "58b2265b98a10ec3bb2a0b455c520731c1296967906c7adc7b6d3710a013e402"
SOURCE_ETAG = "a00c42af3365e2cb93e6448bd2672faad715e1e6f10d4214204dd3005e3426ed"
RAW = Path(__file__).resolve().parent / "swissai_raw"


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    RAW.mkdir(exist_ok=True)
    target = RAW / FILENAME
    temporary = RAW / (FILENAME + ".part")
    if not (target.exists() and target.stat().st_size == EXPECTED_BYTES and
            hash_file(target) == EXPECTED_SHA256):
        offset = temporary.stat().st_size if temporary.exists() else 0
        if offset > EXPECTED_BYTES:
            temporary.unlink()
            offset = 0
        request = urllib.request.Request(
            SOURCE + "/resolve/" + REVISION + "/" + FILENAME)
        if offset:
            request.add_header("Range", "bytes=%d-" % offset)
        with urllib.request.urlopen(request, timeout=120) as response:
            if offset and response.status != 206:
                raise ValueError("server did not honor the resume Range")
            with temporary.open("ab" if offset else "wb") as handle:
                while True:
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        if temporary.stat().st_size != EXPECTED_BYTES:
            raise ValueError("download size mismatch: %d" % temporary.stat().st_size)
        if hash_file(temporary) != EXPECTED_SHA256:
            raise ValueError("download SHA256 mismatch")
        temporary.replace(target)
    manifest = {
        "source": SOURCE,
        "revision": REVISION,
        "filename": FILENAME,
        "bytes": EXPECTED_BYTES,
        "sha256": EXPECTED_SHA256,
        "source_etag": SOURCE_ETAG,
        "range_checks": [
            {"offset": 0, "bytes": 4096},
            {"offset": 2310000000, "bytes": 4096},
            {"offset": 4617813246, "bytes": 4096},
        ],
        "license_from_card": "other",
    }
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2,
                                                   sort_keys=True) + "\n")
    print(manifest)


if __name__ == "__main__":
    main()
