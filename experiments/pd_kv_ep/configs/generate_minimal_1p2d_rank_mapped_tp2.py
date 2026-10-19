#!/usr/bin/env python3
"""Generate a matched-TP P/D fixture with an explicit logical/physical map.

The older fixture is intentionally left untouched.  This variant has four
TP2 Prefill workers on P0 paired one-to-one with the four TP2 Decode workers
on D0; the four remaining Decode workers on D1 complete the EP16 group.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "experiments/pd_kv_ep/configs/large_scale"
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
TOPOLOGY = OUT / "ns3/minimal_1p2d_ep16_2x200g_single_tor.txt"
FLOWSIM_TOPOLOGY = OUT / "flowsim/minimal_1p2d_ep16_single_tor_nvlink.txt"
NS3_TOPOLOGY = OUT / "ns3/minimal_1p2d_ep16_logical_ranks_single_tor.txt"
NS3_CONFIG_TEMPLATE = ROOT / "experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf"


def build_flowsim_topology():
    """Add explicit local NVSwitch paths without changing the ns-3 fixture."""
    lines = [line for line in TOPOLOGY.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    declared_nodes, declared_switches, declared_edges = map(
        int, lines[0].split()[:3])
    if declared_nodes != 31 or declared_switches != 1:
        raise ValueError("Unexpected base 1P2D topology header")
    if lines[1].split() != ["30"]:
        raise ValueError("Unexpected base topology switch declaration")

    local_links = []
    for first_gpu, local_switch in ((0, 31), (8, 32), (16, 33)):
        for gpu in range(first_gpu, first_gpu + 8):
            # 7.2 Tbps = 900 GB/s per GPU attachment, modeled as a
            # nonblocking local NVSwitch fabric for this FlowSim fixture.
            local_links.append(
                "%d %d 7200Gbps 0.0001ms 0" % (gpu, local_switch))

    FLOWSIM_TOPOLOGY.parent.mkdir(parents=True, exist_ok=True)
    # NIC nodes 24--29 are forwarding resources, as are the ToR and local
    # switches. The FlowSim graph uses the same node-type declaration for its
    # audit; its route algorithm is independent of the switch type.
    switch_ids = list(range(24, 34))
    FLOWSIM_TOPOLOGY.write_text(
        "%d %d %d\n%s\n%s\n%s\n" % (
            declared_nodes + 3, len(switch_ids),
            declared_edges + len(local_links),
            " ".join(map(str, switch_ids)), "\n".join(local_links),
            "\n".join(lines[2:])),
        encoding="utf-8")


def build_ns3_logical_topology(logical_to_physical):
    """Build an ns-3 graph whose host IDs match Chakra logical rank IDs.

    The 8 P2D shadow receive ranks are explicit logical hosts attached to the
    same Decode-side NIC rail as their mapped physical GPU. All NIC aggregation
    nodes and the ToR/NVSwitch-like nodes are declared switches so the ns-3
    route builder can traverse them. This keeps rank indexing valid while
    preserving each server's shared 2x200G uplink limit.
    """
    endpoint_count = len(logical_to_physical)
    nic_base = endpoint_count
    tor = nic_base + 6
    local_switch_base = tor + 1
    switch_ids = list(range(nic_base, local_switch_base + 3))
    links = []
    for logical_rank, physical_gpu in enumerate(logical_to_physical):
        server = physical_gpu // 8
        rail = (physical_gpu % 8) // 4
        nic = nic_base + server * 2 + rail
        local_switch = local_switch_base + server
        links.append("%d %d 7200Gbps 0.0001ms 0" %
                     (logical_rank, local_switch))
        links.append("%d %d 7200Gbps 0.0001ms 0" %
                     (logical_rank, nic))
    for nic in range(nic_base, nic_base + 6):
        links.append("%d %d 200Gbps 0.005ms 0" % (nic, tor))

    NS3_TOPOLOGY.parent.mkdir(parents=True, exist_ok=True)
    NS3_TOPOLOGY.write_text(
        "%d %d %d\n%s\n%s\n" % (
            local_switch_base + 3, len(switch_ids), len(links),
            " ".join(map(str, switch_ids)), "\n".join(links)),
        encoding="utf-8")


def instance(role, node_id, tp=2, ep=1, dp_group=None):
    result = {
        "model_name": MODEL,
        "hardware": "RTXPRO6000",
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": role,
        "num_npus": tp,
        "tp_size": tp,
        "ep_size": ep,
    }
    if dp_group is not None:
        result["dp_group"] = dp_group
    return result


def node(instances):
    return {
        "num_instances": len(instances),
        "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
        "instances": instances,
    }


def build_logical_to_physical():
    # Rank layout emitted by config_builder for [TP=2, DP=8, P/D-role=2].
    # Each Prefill instance reserves four logical ranks: two senders followed
    # by two legacy receiver/shadow ranks.  The shadow ranks alias the actual
    # paired D0 GPU endpoints in the FlowSim data plane; the Decode scheduler
    # is admitted only after the full model-derived P2D graph completes.
    result = [None] * 32
    for index in range(4):
        p_gpu = 2 * index
        p_base = 4 * index
        d0_gpu = 8 + 2 * index
        result[p_base:p_base + 2] = [p_gpu, p_gpu + 1]
        result[p_base + 2:p_base + 4] = [d0_gpu, d0_gpu + 1]
    result[16:24] = list(range(8, 16))
    result[24:32] = list(range(16, 24))
    if any(value is None for value in result):
        raise AssertionError("logical rank map is incomplete")
    return result


def main():
    if not TOPOLOGY.is_file():
        raise FileNotFoundError(
            "Generate the physical 1P2D topology first: %s" % TOPOLOGY)
    build_flowsim_topology()
    logical_to_physical = build_logical_to_physical()
    build_ns3_logical_topology(logical_to_physical)
    OUT.mkdir(parents=True, exist_ok=True)
    prefill = [instance("prefill", 0) for _ in range(4)]
    decode_d0 = [instance("decode", 1, ep=16, dp_group="decode_ep")
                 for _ in range(4)]
    decode_d1 = [instance("decode", 2, ep=16, dp_group="decode_ep")
                 for _ in range(4)]
    rank_map_path = OUT / "minimal_1p2d_ep16_logical_to_physical.json"
    rank_map_path.write_text(json.dumps({
        "semantics": "logical ASTRA rank to physical GPU endpoint; P2D shadow ranks intentionally alias paired D0 GPU endpoints",
        "logical_to_physical": logical_to_physical,
    }, indent=2) + "\n", encoding="utf-8")

    config_path = OUT / "minimal_1p2d_ep16_rank_mapped_tp2.json"
    config = {
        "num_nodes": 3,
        # ASTRA analytical fallback only; FlowSim reads the explicit topology.
        "link_bw": 50,
        "link_latency": 5000,
        "ns3_topology": str(NS3_TOPOLOGY.relative_to(ROOT)),
        "flowsim_topology": str(FLOWSIM_TOPOLOGY.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_map_path.relative_to(ROOT)),
        "ns3_config_template": str(NS3_CONFIG_TEMPLATE.relative_to(ROOT)),
        "pd_pairing": {str(i): str(4 + i) for i in range(4)},
        "nodes": [node(prefill), node(decode_d0), node(decode_d1)],
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "cluster_config": str(config_path.relative_to(ROOT)),
        "logical_rank_map": str(rank_map_path.relative_to(ROOT)),
        "topology": str(TOPOLOGY.relative_to(ROOT)),
        "flowsim_topology": str(FLOWSIM_TOPOLOGY.relative_to(ROOT)),
        "ns3_topology": str(NS3_TOPOLOGY.relative_to(ROOT)),
        "prefill_to_decode_instance_pairing": config["pd_pairing"],
        "logical_rank_count": 32,
        "physical_gpu_endpoint_count": 24,
        "logical_shadow_aliases": 8,
    }, indent=2))


if __name__ == "__main__":
    main()
