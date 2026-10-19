#!/usr/bin/env python3
"""Audit the released ServeGen conversation slice without rate scaling."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
RAW = HERE / "servegen_raw"


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def main():
    manifest = json.loads((RAW / "manifest.json").read_text())
    path = RAW / "conversations_hashed.json"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise ValueError("ServeGen checksum mismatch")
    conversations = json.loads(data)
    turns = [turn for conversation in conversations for turn in conversation]
    gaps = []
    for conversation in conversations:
        ordered = sorted(conversation, key=lambda turn: turn["timestamp"])
        gaps.extend((later["timestamp"] - earlier["timestamp"])
                    for earlier, later in zip(ordered, ordered[1:]))
    report = {
        "source": manifest["source"],
        "commit": manifest["commit"],
        "raw_sha256": manifest["sha256"],
        "conversations": len(conversations),
        "turns": len(turns),
        "turns_prompt_le_2048": sum(turn["input_token_count"] <= 2048
                                     for turn in turns),
        "turns_prompt_le_16384": sum(turn["input_token_count"] <= 16384
                                      for turn in turns),
        "input_count_p50_p95_p99": [
            quantile([turn["input_token_count"] for turn in turns], fraction)
            for fraction in (0.5, 0.95, 0.99)],
        "output_count_p50_p95_p99": [
            quantile([turn["output_token_count"] for turn in turns], fraction)
            for fraction in (0.5, 0.95, 0.99)],
        "turns_per_conversation_p50_p95_p99": [
            quantile([len(conversation) for conversation in conversations],
                     fraction) for fraction in (0.5, 0.95, 0.99)],
        "observed_inter_turn_gap_s_p50_p95_p99": [
            quantile(gaps, fraction) for fraction in (0.5, 0.95, 0.99)],
        "timestamp_span_s": max(turn["timestamp"] for turn in turns) -
                            min(turn["timestamp"] for turn in turns),
        "released_input_id_count_p50": quantile(
            [len(turn["input_tokens"]) for turn in turns], 0.5),
        "input_id_list_matches_prompt_length": sum(
            len(turn["input_tokens"]) == turn["input_token_count"]
            for turn in turns),
        "caveat": "Selectively released conversations; timestamps do not give "
                  "full-fleet arrivals. input_tokens list length does not "
                  "match input_token_count, so its prefix semantics require "
                  "further source validation before KV replay.",
    }
    output = HERE / "servegen_analysis"
    output.mkdir(exist_ok=True)
    (output / "summary.json").write_text(json.dumps(report, indent=2,
                                                   sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
