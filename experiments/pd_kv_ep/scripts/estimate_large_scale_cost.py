#!/usr/bin/env python3
"""Estimate large-scale replay pressure without starting the simulator.

The estimates use the selected model and the converted request rows. They are
planning bounds, not a replacement for simulator telemetry: scheduler
batching changes the number of ASTRA iterations, and exact A2A_P2P peer counts
come from the GateRouter route matrix at runtime.
"""

import argparse
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODEL_CONFIG = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
SCALE_CONFIGS = {
    "S64": ROOT / "experiments/pd_kv_ep/configs/large_scale/s64_64_servers_manifest.json",
    "S256": ROOT / "experiments/pd_kv_ep/configs/large_scale/s256_256_servers_manifest.json",
}


def _rows(path, offset, limit):
    if offset < 0 or limit <= 0:
        raise ValueError("offset must be non-negative and limit must be positive")
    result = []
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index < offset:
                continue
            result.append(json.loads(line))
            if len(result) == limit:
                break
    if not result:
        raise ValueError(f"no rows selected from {path} at offset {offset}")
    return result


def _estimate(trace, rows, model, scale, max_batched_tokens):
    layers = int(model["num_hidden_layers"])
    hidden = int(model["hidden_size"])
    kv_heads = int(model.get("num_key_value_heads", model["num_attention_heads"]))
    head_dim = int(model.get("head_dim", hidden // int(model["num_attention_heads"])))
    fp_bytes = 2 if str(model.get("torch_dtype", "bfloat16")) in {"bfloat16", "float16"} else 4
    tp = 2
    ep = 16
    top_k = int(model.get("num_experts_per_tok", 1))
    total_input = sum(int(row["input_toks"]) for row in rows)
    total_output = sum(int(row["output_toks"]) for row in rows)
    max_output = max(int(row["output_toks"]) for row in rows)
    active_requests = sum(1 for row in rows if int(row["output_toks"]) > 0)

    # K and V for every transformer layer, across all TP=2 source ranks.
    kv_bytes_per_input_token = layers * 2 * kv_heads * head_dim * fp_bytes
    p2d_bytes = total_input * kv_bytes_per_input_token
    p2d_shards = len(rows) * tp

    # One decode token traverses every MoE layer. Exact P2P peer counts are
    # route-dependent; a balanced EP=16 wave can expose up to 15 remote peers
    # per source for each dispatch and combine phase.
    ep_collectives = total_output * layers
    remote_peer_upper = ep - 1
    ep_flow_upper = ep_collectives * 2 * remote_peer_upper
    ep_flow_lower = ep_collectives * 2
    routed_token_bytes = total_output * top_k * hidden * fp_bytes
    ep_bytes_balanced = routed_token_bytes * 2 * (ep - 1) / ep

    prefill_lower = math.ceil(total_input / max_batched_tokens)
    prefill_upper = total_input
    decode_lower = max_output
    decode_upper = total_output
    iterations_lower = prefill_lower + decode_lower
    iterations_upper = prefill_upper + decode_upper

    # These are intentionally coarse metadata-size planning numbers. They are
    # useful for deciding whether VALIDATION telemetry is safe to enable, but
    # are not reported as measured disk usage.
    flow_records = p2d_shards + ep_flow_upper
    flow_telemetry_bytes = flow_records * 512
    with SCALE_CONFIGS[scale].open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    link_count = int(manifest["topology"]["edge_count"])
    discovery_bytes_lower = link_count * iterations_lower * 64
    discovery_bytes_upper = link_count * iterations_upper * 64
    return {
        "trace": str(trace),
        "scale": scale,
        "server_count": int(manifest["server_count"]),
        "physical_gpu_count": int(manifest["physical_gpu_count"]),
        "rank_count": int(manifest["logical_rank_count"]),
        "link_count": link_count,
        "request_count": len(rows),
        "request_offset": None,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "active_decode_requests": active_requests,
        "model": str(model["architectures"][0]),
        "tp": tp,
        "ep": ep,
        "top_k": top_k,
        "layers": layers,
        "kv_bytes_per_input_token": kv_bytes_per_input_token,
        "estimated_p2d_kv_bytes": p2d_bytes,
        "estimated_p2d_shard_send_events": p2d_shards,
        "estimated_ep_collectives": ep_collectives,
        "estimated_ep_remote_bytes_balanced_dispatch_plus_combine": int(ep_bytes_balanced),
        "estimated_ep_p2p_flow_count_lower": ep_flow_lower,
        "estimated_ep_p2p_flow_count_upper": ep_flow_upper,
        "estimated_total_network_flow_count_upper": flow_records,
        "estimated_scheduler_iterations_lower": iterations_lower,
        "estimated_scheduler_iterations_upper": iterations_upper,
        "estimated_validation_flow_telemetry_bytes_upper": flow_telemetry_bytes,
        "estimated_discovery_link_telemetry_bytes_range": [
            discovery_bytes_lower, discovery_bytes_upper],
        "runtime_estimate": {
            "status": "UNCALIBRATED",
            "reason": "No S64/S256 multi-request calibration is used; tiny gates are not extrapolated.",
        },
        "model_derived_bytes": True,
        "synthetic_override": False,
        "hard_request_cap": 25000,
        "notes": [
            "P2D estimate assumes POST_PREFILL and TP=2 model-derived K/V shards.",
            "EP flow range is a planning bound; exact A2A_P2P route sparsity is runtime-derived.",
            "Full production traces are not implicitly selected by this tool.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--scale", choices=tuple(SCALE_CONFIGS), required=True)
    parser.add_argument("--num-reqs", type=int, required=True)
    parser.add_argument("--request-offset", type=int, default=0)
    parser.add_argument("--max-num-batched-tokens", type=int, default=4096)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.num_reqs > 25000:
        parser.error("a single large-scale trace run is capped at 25,000 requests")
    trace = args.trace.resolve()
    rows = _rows(trace, args.request_offset, args.num_reqs)
    with MODEL_CONFIG.open(encoding="utf-8") as stream:
        model = json.load(stream)
    estimate = _estimate(trace, rows, model, args.scale, args.max_num_batched_tokens)
    estimate["request_offset"] = args.request_offset
    payload = json.dumps(estimate, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
