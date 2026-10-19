#!/usr/bin/env python3
"""Generate the explicit 400-Gbps-per-rail sensitivity configuration."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE_CONFIG = ROOT / "research_motivation/batch_miss/minimal_1p2d_ep4_config.json"
OUT = ROOT / "research_motivation/batch_miss"


def main():
    config = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    source_topology = ROOT / config["flowsim_topology"]
    topology_lines = source_topology.read_text(encoding="utf-8").splitlines()
    changed = 0
    for index, line in enumerate(topology_lines):
        fields = line.split()
        if len(fields) >= 5 and fields[0].isdigit() and fields[1] == "30":
            if fields[2] != "200Gbps":
                raise ValueError("unexpected NIC rail capacity: %s" % line)
            fields[2] = "400Gbps"
            topology_lines[index] = " ".join(fields)
            changed += 1
    if changed != 6:
        raise ValueError("expected six server-to-ToR NIC rails, changed %d" % changed)

    topology_path = OUT / "minimal_1p2d_ep4_400g_topology.txt"
    topology_path.write_text("\n".join(topology_lines) + "\n", encoding="utf-8")
    config["flowsim_topology"] = str(topology_path.relative_to(ROOT))
    config_path = OUT / "minimal_1p2d_ep4_400g_config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "config": str(config_path.relative_to(ROOT)),
        "topology": str(topology_path.relative_to(ROOT)),
        "changed_server_to_tor_rails": changed,
        "per_rail_gbps": 400,
        "per_server_aggregate_gbps": 800,
        "note": "Sensitivity only; not the authoritative 2x200G/server topology.",
    }, indent=2))


if __name__ == "__main__":
    main()
