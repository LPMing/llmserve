#!/usr/bin/env python3
"""Download revision-pinned FreeInference raw traces with file hashes."""

import argparse
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DATASET = "harvardMadsys/freeinference_agentic_trace"
REVISION = "16d3c04dae6ccaa0c48a9064e204e3a8f1eb9ade"
HERE = Path(__file__).resolve().parent
API = "https://huggingface.co/api/datasets/%s/revision/%s" % (
    DATASET, REVISION)
RESOLVE = "https://huggingface.co/datasets/%s/resolve/%s/" % (
    DATASET, REVISION)


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as stream:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            stream.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    temporary.replace(target)
    return size, digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", nargs="*", default=[],
                        help="week directory names; omit for all weeks")
    args = parser.parse_args()
    metadata = fetch_json(API)
    if metadata.get("sha") != REVISION:
        raise RuntimeError("dataset revision changed during download")
    paths = sorted(
        item["rfilename"] for item in metadata.get("siblings", ())
        if item["rfilename"].endswith(".jsonl.zst") and
        "/traces/" in item["rfilename"]
    )
    if args.weeks:
        selected = set(args.weeks)
        paths = [path for path in paths if path.split("/")[1] in selected]
        if not paths:
            raise ValueError("no trace paths match selected weeks")
    raw = HERE / "freeinference_raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest_path = HERE / "freeinference_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("revision") != REVISION:
            raise RuntimeError("existing manifest has a different revision")
    else:
        manifest = {
            "dataset": DATASET,
            "revision": REVISION,
            "license": "CC-BY-4.0",
            "source": "https://huggingface.co/datasets/" + DATASET,
            "download_script": Path(__file__).name,
            "files": {},
        }
    for index, path in enumerate(paths, 1):
        target = raw / path
        if target.exists():
            data = target.read_bytes()
            size, sha = len(data), hashlib.sha256(data).hexdigest()
        else:
            size, sha = download(RESOLVE + path, target)
        manifest["files"][path] = {"bytes": size, "sha256": sha}
        manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2,
                                            sort_keys=True) + "\n")
        print("%d/%d %s %d %s" % (index, len(paths), path, size, sha),
              flush=True)


if __name__ == "__main__":
    main()
