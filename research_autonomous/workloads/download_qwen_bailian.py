#!/usr/bin/env python3
"""Download pinned Qwen-Bailian LFS traces and verify their object hashes."""

import hashlib
import json
import re
import urllib.request
from pathlib import Path


COMMIT = "5f7439c51ec248a0c585f7d90a41a6f57773b912"
REPOSITORY = "alibaba-edu/qwen-bailian-usagetraces-anon"
FILES = ("qwen_traceA_blksz_16.jsonl", "qwen_traceB_blksz_16.jsonl",
         "qwen_thinking_blksz_16.jsonl", "qwen_coder_blksz_16.jsonl")
RAW = Path(__file__).resolve().parent / "qwen_bailian_raw"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    RAW.mkdir(exist_ok=True)
    results = {}
    for name in FILES:
        pointer_url = ("https://raw.githubusercontent.com/%s/%s/%s" %
                       (REPOSITORY, COMMIT, name))
        pointer = urllib.request.urlopen(pointer_url, timeout=30).read().decode()
        hash_match = re.search(r"^oid sha256:([0-9a-f]{64})$", pointer, re.M)
        size_match = re.search(r"^size (\d+)$", pointer, re.M)
        if not hash_match or not size_match:
            raise ValueError("invalid Git LFS pointer: %s" % name)
        expected_hash = hash_match.group(1)
        expected_size = int(size_match.group(1))
        target = RAW / name
        if not target.exists() or (target.stat().st_size != expected_size or
                                   sha256_file(target) != expected_hash):
            media_url = ("https://media.githubusercontent.com/media/%s/%s/%s"
                         % (REPOSITORY, COMMIT, name))
            temporary = RAW / (name + ".part")
            with urllib.request.urlopen(media_url, timeout=90) as response:
                with temporary.open("wb") as handle:
                    while True:
                        chunk = response.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            if (temporary.stat().st_size != expected_size or
                    sha256_file(temporary) != expected_hash):
                raise ValueError("Git LFS hash mismatch: %s" % name)
            temporary.replace(target)
        results[name] = {"bytes": expected_size, "sha256": expected_hash}
        print(name, results[name], flush=True)
        (RAW / "manifest.json").write_text(json.dumps({
            "source": "https://github.com/" + REPOSITORY,
            "commit": COMMIT,
            "license": "Apache-2.0",
            "files": results,
        }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
