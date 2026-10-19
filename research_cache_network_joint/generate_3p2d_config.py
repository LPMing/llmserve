#!/usr/bin/env python3
"""Create the fixed-10-rank 3P2D sibling of the audited 4P1D setup."""

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "research_prefix_exposure/4p1d_tp2_flowsim.json"
CONFIG_OUT = ROOT / "research_cache_network_joint/3p2d_tp2_flowsim.json"
RANK_MAP_OUT = ROOT / "research_cache_network_joint/3p2d_logical_to_physical.json"


def main():
    config = json.loads(BASE.read_text())
    if len(config["nodes"]) != 5:
        raise RuntimeError("Expected the audited five-server / ten-rank base")

    for index, node in enumerate(config["nodes"]):
        instance = node["instances"][0]
        instance["pd_type"] = "prefill" if index < 3 else "decode"

    # Two Prefill groups map to D0, one maps to D1. Each Prefill graph has a
    # single concrete Decode receiver, matching the current graph semantics.
    config["pd_pairing"] = {"0": "3", "1": "3", "2": "4"}
    config["flowsim_rank_map"] = (
        "research_cache_network_joint/3p2d_logical_to_physical.json")

    # The existing graph adapter uses two logical rank IDs per instance with
    # four-ID spacing (the intervening pair is the P2D shadow-rank slot).
    # Physical hosts are unchanged: 2 selected GPU/NIC-rail endpoints on each
    # of the same five servers. P0/P1/P2 occupy hosts 0/1/2, D0/D1 hosts 3/4.
    physical = [24, 28, 24, 28, 8, 12, 24, 28, 16, 20,
                32, 36, 24, 28, 32, 36, 32, 36]
    physical[0:2] = [0, 4]
    physical[4:6] = [8, 12]
    physical[8:10] = [16, 20]
    physical[12:14] = [24, 28]
    physical[16:18] = [32, 36]

    CONFIG_OUT.write_text(json.dumps(config, indent=2) + "\n")
    RANK_MAP_OUT.write_text(json.dumps({
        "semantics": (
            "same five physical servers and 10 active TP2 ranks as 4P1D; "
            "P0/P1/P2 use hosts 0/1/2, D0/D1 use hosts 3/4; each host "
            "selects one endpoint on each of its two 200G NIC rails"),
        "logical_to_physical": physical,
    }, indent=2) + "\n")
    print(CONFIG_OUT)
    print(RANK_MAP_OUT)


if __name__ == "__main__":
    main()
