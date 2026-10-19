# Baseline validation for NIC-priority motivation

## Provenance

| Item | Current value |
|---|---|
| Repository | `/home/dell/lpm/LLMServingSim` |
| Branch / HEAD | `main` / `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| Worktree | Dirty; preserve all pre-existing modifications and untracked artifacts |
| Tracked diff SHA-256 | `a6c0c46698d4dd1900fa020d31e48d17cedb17d19e242a809631d2b21e22831c` (before this research directory was added) |
| Runtime | Conda Python 3.10.21 at `/home/lpm/.conda/envs/llmsim-flowsim/bin/python` |
| Model/profile | Qwen3-30B-A3B-Instruct-2507; RTXPRO6000 profiler bundle (modeled compute profile, not the machine executing FlowSim) |
| Network backend in this phase | Integrated Python FlowSim, directed fluid max-min |
| Existing network profile | Native ns-3 replay has packet-level queue evidence for a bounded slice, but no serving completion feedback |

The exact source/config/workload identity remains a dirty-worktree identity,
not an immutable Git release. Prior results are accepted only where their
configuration and current-worktree provenance are recorded in
`research_audit/01_REPRODUCIBILITY.md` and the scoped reports cited below.

## Current focused regression run

Ran all ten `experiments/pd_kv_ep/scripts/test_*.py` scripts with the Conda
Python and `PYTHONPATH=.`. Result: **36/36 tests passed** (8 topology rank
count, 4 collective scope, 4 Decode completion wakeup, 3 handoff wakeup, 3
group queue ownership, 6 physical rank mapping, 1 ns-3 config topology
selection, 4 Decode capacity admission, 1 P/D pairing, 2 trace time-unit
tests). `serving/` Python byte-compilation and `git diff --check` completed
without reported errors. This is a targeted regression set, not the full
repository suite.

## Semantics relevant to this experiment

- Serving is cycle/profile driven; FlowSim completions feed the integrated
  scheduler in the current dirty worktree. P2D completion, Decode admission,
  group collective completion and Decode wakeups have focused regression
  coverage.
- The run path has an explicit logical-rank-to-physical-GPU map. Four GPUs
  map to each NIC rail through high-bandwidth GPU/NIC access edges; the
  200G NIC-to-ToR edge is the modeled shared NIC resource. Both directed
  directions are separately represented.
- Multiple Decode `dp_group`s are supported for the tested rectangular,
  group-major layouts. This is not proof for arbitrary rank placements.
- Current MoE dispatch/combine is model-derived ALLGATHER +
  REDUCESCATTER expanded to direct peer flows by the FlowSim adapter. It is
  **not** exact GateRouter A2A_P2P.
- FAIR is max-min fluid bandwidth allocation. EP_FIRST/KV_FIRST allocate
  shared directed-link service by traffic class. They do not model RNIC QP
  dequeue order, packet-level strict priority, packet serialization, ECN,
  PFC, or physical switch buffers.
- `KV_ISOLATED`/`EP_ISOLATED` are cross-class virtual-capacity controls;
  selected-class flows still share capacity with one another. Their result
  must not be described as an uncongested per-flow network.
- FlowSim `queue_bytes` / `fluid_outstanding_bytes` are analytical residual
  work, not packet queue occupancy.
- Existing EP–EP integrated evidence for two EP4 groups found dispatch CCT
  +6.39%, combine CCT +1.58–3.11%, TTFT unchanged and TBT/TPOT +0.75–0.80%.
  It is a bounded capability/negative-motivation result, not a reason to
  assume a large gain in the new high-NIC-load case.
- Existing native ns-3 matched replay found dispatch/combine CCT about +7.1%
  and P2D mean FCT +0.16%, but packet completions were not connected to the
  serving scheduler. These remain network-only.

## Gate 0 disposition

**`PARTIALLY_VALIDATED`**. The focused integrated FlowSim path and its tested
NIC/rank topology are valid for a scoped fluid-allocation experiment. The
baseline is not valid for claims about exact MoE routing, RNIC scheduling,
packet-level priority, or integrated ns-3 TTFT/TBT. The new experiment will
state these limits explicitly and will not mix FlowSim queue metrics with
ns-3 switch-queue metrics.

## GPU question carried forward

The simulator process does not execute its event loop on a GPU. RTX PRO 6000
is the source of the profiled compute-latency bundle used to timestamp
serving work. Selecting a faster profile changes modeled compute durations
and therefore slack/overlap and TTFT/TBT, but does not accelerate the Python
FlowSim simulation itself. The likely runtime cost is CPU-side event/flow
processing and telemetry; changing the profiled accelerator is not a runtime
optimization and would require a matching profile bundle for a valid
comparison.
