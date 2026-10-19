#!/usr/bin/env python3
"""Generate fixed-resource 4P1D prefix warm/hit workloads and FlowSim config."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
TOPOLOGY = ROOT / (
    "research_ns3_incast/fixtures_rankcap200g/fixtures/"
    "4p1d_unique_spines/topology.txt")
P2D_RANK_MAP = OUT / "logical_to_physical.json"
BLOCK = 16
PREFIX_TOKENS = 4096
SUFFIX_TOKENS = 9  # 1 token emitted by prior call + 8 genuinely new tokens.
VOCAB_SIZE = 151936


def build_cluster():
    """Use one TP2 instance per physical server, preserving the 4P1D fabric."""
    nodes = []
    for server in range(5):
        role = "prefill" if server < 4 else "decode"
        instance = {
            "model_name": MODEL,
            "hardware": "RTXPRO6000",
            "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
            "pd_type": role,
            "num_npus": 2,
            "tp_size": 2,
            "ep_size": 1,
        }
        nodes.append({
            "num_instances": 1,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
            "instances": [instance],
        })

    # Config order: each P instance owns two data ranks followed by its two
    # legacy shadow receive ranks. All shadows alias the matching Decode rail.
    mapping = []
    for server in range(4):
        mapping.extend([server * 8, server * 8 + 4, 32, 36])
    mapping.extend([32, 36])
    config = {
        "num_nodes": 5,
        "link_bw": 200,
        "link_latency": 5000,
        "flowsim_topology": str(TOPOLOGY.relative_to(ROOT)),
        "flowsim_rank_map": str(P2D_RANK_MAP.relative_to(ROOT)),
        "pd_pairing": {str(i): "4" for i in range(4)},
        "nodes": nodes,
    }
    P2D_RANK_MAP.write_text(json.dumps({
        "semantics": (
            "TP2 data ranks map to one GPU on each 200G rail per server; "
            "P2D shadow receivers alias the actual D0 rail endpoints"),
        "logical_to_physical": mapping,
    }, indent=2) + "\n", encoding="utf-8")
    config_path = OUT / "4p1d_tp2_flowsim.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path


def make_session(index, include_target):
    # Same 4096 real token IDs across all sessions. Values are within the
    # configured vocabulary; session-specific suffix/output IDs are distinct.
    prefix = [1000 + (i % 120000) for i in range(PREFIX_TOKENS)]
    prior_output = 130000 + index
    warmup_output = [prior_output]
    sub_requests = [{
        "input_toks": PREFIX_TOKENS,
        "output_toks": 1,
        "input_tok_ids": prefix,
        "output_tok_ids": warmup_output,
        "tool_duration_ns": 0,
    }]
    if include_target:
        target_input = prefix + warmup_output + [140000 + index * 16 + i
                                                   for i in range(8)]
        assert len(target_input) == PREFIX_TOKENS + SUFFIX_TOKENS
        target_output = [145000 + index * 3 + i for i in range(3)]
        assert max(target_input + target_output) < VOCAB_SIZE
        sub_requests.append({
            "input_toks": len(target_input),
            "output_toks": len(target_output),
            "input_tok_ids": target_input,
            "output_tok_ids": target_output,
            "tool_duration_ns": 0,
        })
    return {
        "session_id": f"prefix-session-{index}",
        "arrival_time_ns": 0,
        "sub_requests": sub_requests,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", type=int, choices=(1, 2, 4), required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = build_cluster()
    workload_path = OUT / f"workload_{args.targets}_targets.jsonl"
    with workload_path.open("w", encoding="utf-8") as stream:
        for index in range(4):
            stream.write(json.dumps(make_session(index, index < args.targets)) + "\n")
    print(json.dumps({
        "cluster_config": str(config_path.relative_to(ROOT)),
        "rank_map": str(P2D_RANK_MAP.relative_to(ROOT)),
        "topology": str(TOPOLOGY.relative_to(ROOT)),
        "workload": str(workload_path.relative_to(ROOT)),
        "warmups": 4,
        "cache_hit_targets": args.targets,
        "prefix_tokens": PREFIX_TOKENS,
        "target_input_tokens": PREFIX_TOKENS + SUFFIX_TOKENS,
        "output_tokens": 3,
        "model_derived_kv_bytes_per_target": (
            (PREFIX_TOKENS + SUFFIX_TOKENS) * 98_304),
        "logical_to_physical_rank_map": json.loads(
            P2D_RANK_MAP.read_text(encoding="utf-8"))["logical_to_physical"],
    }, indent=2))


if __name__ == "__main__":
    main()
