#!/usr/bin/env python3
"""Check KV conservation and the P2D-to-Serving causal boundary."""

import csv
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
EXPECTED_BYTES_PER_REQUEST = 536870912


def main():
    summary = {}
    for n in (1, 4):
        case = HERE / ("p%d" % n)
        with (case / "requests.csv").open(newline="") as source:
            requests = list(csv.DictReader(source))
        flows = [json.loads(line) for line in (case / "flows.jsonl").open()
                 if line.startswith("{")]
        flows = [row for row in flows
                 if row.get("traffic_subtype") == "P2D"]
        if len(requests) != n:
            raise AssertionError("completed request count mismatch")
        per_request = {
            str(i): sum(row["bytes"] for row in flows
                        if i in row["request_ids"])
            for i in range(n)}
        source_ranks = {
            str(i): sorted({row["src"] for row in flows
                            if i in row["request_ids"]})
            for i in range(n)}
        if any(value != EXPECTED_BYTES_PER_REQUEST
               for value in per_request.values()):
            raise AssertionError("P2D KV bytes do not conserve")
        if len({tuple(ranks) for ranks in source_ranks.values()}) != n:
            raise AssertionError("requests did not use distinct Prefill instances")
        ready_ns = [int(row["p2d_kv_ready_time_ns"])
                    for row in requests]
        token2_ns = [int(row["second_token_visible_ns"])
                     for row in requests]
        last_flow_ns = max(row["end_ns"] for row in flows)
        if last_flow_ns > min(ready_ns):
            raise AssertionError("KV flow finished after P2D ready")
        summary[str(n)] = {
            "requests": n,
            "p2d_flows": len(flows),
            "per_request_bytes": per_request,
            "source_ranks_by_request": source_ranks,
            "aggregate_bytes": sum(row["bytes"] for row in flows),
            "destination_rail_bytes": {
                str(dst): sum(row["bytes"] for row in flows
                              if row["dst"] == dst)
                for dst in sorted({row["dst"] for row in flows})},
            "first_flow_release_ms": min(row["start_ns"] for row in flows) / 1e6,
            "last_flow_finish_ms": last_flow_ns / 1e6,
            "maximum_flow_fct_ms": max(row["end_ns"] - row["start_ns"]
                                       for row in flows) / 1e6,
            "p2d_ready_ms": [value / 1e6 for value in ready_ns],
            "last_flow_to_ready_slack_ms":
                (min(ready_ns) - last_flow_ns) / 1e6,
            "token2_ms": [value / 1e6 for value in token2_ns],
        }
    summary["four_minus_one_request_ready_ms"] = (
        summary["4"]["p2d_ready_ms"][0] -
        summary["1"]["p2d_ready_ms"][0])
    target = HERE / "summary.json"
    target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
