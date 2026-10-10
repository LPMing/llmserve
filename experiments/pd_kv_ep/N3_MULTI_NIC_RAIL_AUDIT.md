# N3 Multi-NIC / Rail Affinity Mismatch Audit

## Status

`N3_FINAL_FAIL_NO_MULTI_NIC_RAIL_SEMANTICS`

This is a semantic feasibility failure, not a negative performance result. The
current repository cannot distinguish two NICs, two rails, rail affinity, or a
rail-local endpoint resource. Adding a rail label to an event without adding
the corresponding resource and selection semantics would not be a packet-level
experiment.

## Hypothesis

P2D KV and Decode EP may use different NIC/rail resources in a real multi-rail
GPU cluster. A mismatch between the P2D source/destination rail affinity and
the EP collective's rail affinity could create a hidden endpoint bottleneck or
leave one rail underutilized. The proposed causal chain was:

`rail affinity -> endpoint/NIC contention -> EP or KV barrier -> TBT/TTFT`.

## Current topology and configuration audit

Authoritative configuration:

`experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_qwen.json`

- 16 configured servers;
- 32 Prefill instances and 32 Decode instances;
- 2 GPUs per instance (`tp_size=2`);
- 128 logical GPU/rank endpoints in the native topology;
- 200 Gbps configured scale-out link bandwidth;
- no `nic`, `rail`, `port`, or RDMA-interface field in any instance;
- no per-GPU NIC count or rail binding.

Authoritative topology:

`experiments/pd_kv_ep/configs/large_scale/ns3/s16_8p8d_ep64_200g_clos.txt`

- 134 graph nodes: 128 endpoints and 6 switches;
- 256 listed directed physical links;
- endpoint uplinks/downlinks are one 200-Gbps physical link per endpoint;
- each leaf-to-spine directed pair has 16 parallel 200-Gbps links;
- there are no rail identifiers or per-rail endpoint links.

The 16 parallel links are represented as a physical-link bundle by FlowSim.
In `AGGREGATE` mode their capacity is 3.2 Tbps per directed leaf/spine pair;
in `HASHED_PHYSICAL` mode a flow is deterministically assigned to one member
of that bundle. Neither mode models a NIC/rail resource below the endpoint.

## Backend source evidence

`serving/core/flowsim_backend.py` provides:

- `parallel_link_mode` values `AGGREGATE` and `HASHED_PHYSICAL`;
- physical-link parsing and aggregation in `_read_ns3_topology`;
- endpoint discovery as all non-switch node IDs;
- single-path BFS over directed aggregate pairs in `path`;
- optional deterministic selection of one physical parallel link in
  `_materialize_physical_path`.

The backend has no `nic_id`, `rail_id`, NIC capacity, rail capacity, rail
selection, or endpoint-level shared resource. `FlowSpec` carries source,
destination, bytes, start time, class, and path information, but not a rail
binding. A P2D flow and an EP flow with the same endpoint therefore share only
the modeled directed network links; they cannot be made to share or avoid a
particular NIC/rail resource.

## Why no experiment was fabricated

A valid N3 experiment would require an externally justified mapping such as:

`GPU -> NIC/rail -> leaf uplink`

and a transport/runtime rule that chooses the rail for P2D and EP. The current
repository contains neither. Creating two logical rail labels, assigning
flows to them in the workload generator, or splitting a 200-Gbps endpoint
without a runtime source would change the model rather than test it.

The existing native ns-3 topology is therefore sufficient for physical link
and parallel-link sensitivity, but not for multi-NIC/rail affinity research.

## Decision

N3 is closed as unsupported in the current simulator. It is not evidence that
rail mismatch is unimportant in deployed systems. To reopen it legitimately,
the simulator would need a small, independently validated multi-rail resource
model and a real source for rail assignment (runtime configuration, topology
metadata, or packet-level NIC selection). That would be a new simulator
extension, outside the current autonomous negative/bound search.

