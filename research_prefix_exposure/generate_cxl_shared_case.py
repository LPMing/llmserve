#!/usr/bin/env python3
"""Create a controlled cross-Prefill CXL prefix-pool hit case.

Five initial routes advance RR so the session continuation is assigned to a
different Prefill instance from its warm-up. Four unrelated prompts are
ordinary load, not cache-hash aliases. The CXL resource values match the
repository's existing single_node_cxl_instance configuration.
"""

import json
from pathlib import Path

from generate_fixture import MODEL, OUT, PREFIX_TOKENS, SUFFIX_TOKENS, build_cluster


def main():
    base_config = build_cluster()
    config = json.loads(base_config.read_text(encoding="utf-8"))
    config["cxl_mem"] = {
        "mem_size": 1024,
        "mem_latency": 250,
        "mem_bw": 60,
        "num_devices": 4,
    }
    for node in config["nodes"]:
        for instance in node["instances"]:
            if instance["pd_type"] == "prefill":
                instance["placement"] = {
                    "default": {
                        "weights": "npu",
                        "kv_loc": "npu",
                        "kv_evict_loc": "cxl:0",
                    }
                }
    config_path = OUT / "4p1d_tp2_flowsim_cxl.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    prefix = [1000 + (i % 120000) for i in range(PREFIX_TOKENS)]
    prior_output = 130000
    target = prefix + [prior_output] + [140000 + i for i in range(8)]
    assert len(target) == PREFIX_TOKENS + SUFFIX_TOKENS
    workload = [{
        "session_id": "cxl-shared-prefix-session",
        "arrival_time_ns": 0,
        "sub_requests": [
            {
                "input_toks": PREFIX_TOKENS,
                "output_toks": 1,
                "input_tok_ids": prefix,
                "output_tok_ids": [prior_output],
                "tool_duration_ns": 0,
            },
            {
                "input_toks": len(target),
                "output_toks": 3,
                "input_tok_ids": target,
                "output_tok_ids": [145000, 145001, 145002],
                "tool_duration_ns": 0,
            },
        ],
    }]
    for index in range(4):
        workload.append({
            "input_toks": PREFIX_TOKENS,
            "output_toks": 1,
            "arrival_time_ns": 0,
        })

    workload_path = OUT / "workload_cxl_shared_target.jsonl"
    with workload_path.open("w", encoding="utf-8") as stream:
        for row in workload:
            stream.write(json.dumps(row) + "\n")

    print(json.dumps({
        "cluster_config": str(config_path.relative_to(OUT.parent)),
        "workload": str(workload_path.relative_to(OUT.parent)),
        "request_routing_policy": "RR",
        "initial_routes_before_target": 5,
        "warmup_expected_prefill_instance": 0,
        "target_expected_prefill_instance": 1,
        "cxl_mem": config["cxl_mem"],
        "input_tokens": PREFIX_TOKENS + SUFFIX_TOKENS,
        "prefix_tokens": PREFIX_TOKENS,
        "suffix_compute_tokens": len(target) - PREFIX_TOKENS,
        "target_request_id": 1,
        "model_kv_bytes_per_token": 98_304,
        "model_kv_bytes_target": len(target) * 98_304,
    }, indent=2))


if __name__ == "__main__":
    main()
