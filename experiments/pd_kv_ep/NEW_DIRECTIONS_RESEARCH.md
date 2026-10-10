# New Packet-Level Research Directions

## Scope and evidence rule

This ledger follows the latest sequential search order. Earlier P1/P2/P3/P4
and split-source results remain authoritative negative/bound evidence. A
network-only effect is not promoted to a serving claim; a PASS requires a
real scheduler/runtime mechanism, a matched counterfactual, and a request or
serving-level improvement of roughly 20% that survives a neighboring point or
window.

## P5 — Layerwise burst shaping

**Status: `P5_FINAL_FAIL_CURRENT_BACKEND_NO_TRANSPORT_GRANULARITY`.**

The current replay has model-layer release timestamps and packetization, but
does not model the NIXL/UCX/WQE/rendezvous transport state needed to compare
legal burst/pacing policies. `max_flow_bytes` only splits an event into flows
with the same start timestamp. Adding pacing only to make ECN/PFC react would
be an invented transport model. Details are in
`P5_LAYERWISE_BURST_SHAPING_AUDIT.md`.

## N1 — Decode batch-boundary amplification

**Status: `N1_FINAL_FAIL_SERVING_HEADROOM`.**

Hypothesis: a P2D handoff that becomes ready during an already-issued Decode
group batch cannot join that iteration. If the request is naturally close to
the group barrier, a small packet-level completion difference may move its
admission across the boundary and amplify into TTFT.

### Scheduler reality audit

`router.transfer_prefill_request()` records the P2D-ready event and calls
`DecodeScheduler.add_decode()`. `_build_batch()` is the actual Decode batch
formation point. FlowSim sets `LLMSERVINGSIM_FLOWSIM`, and the scheduler keeps
one group Decode batch in flight until the group barrier completes. The new
telemetry separates P2D-ready time from actual Decode scheduler admission;
see `N1_DECODE_BATCH_BOUNDARY_AUDIT.md`.

### Natural controls already completed

| workload | requests | backend | result |
|---|---:|---|---|
| 8 Decode + 8 P2D, output 4 | 16 | FlowSim | all waits 0; no missed iteration |
| 16 Decode + 16 P2D, output 4 | 32 | FlowSim | all waits 0; no missed iteration |

These are valid integrated TTFT/TBT controls but do not trigger N1.

### Current high point

The first 64 rows of the existing 32 Decode + 64 P2D, output-16 workload
(32 Decode + 32 P2D) produced a positive natural boundary case: all 32 P2D
requests became ready at 107.763 ms while Decode batch 9 was in flight from
107.205 to 114.331 ms. They were admitted at 114.331 ms, so each incurred
6.568 ms of scheduler-boundary wait and missed one Decode iteration. Their
TTFT was 101.586 ms; the boundary component was about 6.5% of TTFT.

The full 32 Decode + 64 P2D neighboring point also missed one iteration, but
its wait was only 1.418 ms against 116.232 ms TTFT (about 1.2%). No request
bytes, arrival timestamps, routing, or parallelism were changed. The natural
mechanism exists, but it is not a paper-level serving candidate in this
scheduler/backend: low and medium points had no wait, the 32-P2D point was
about 6.5%, and the 64-P2D point fell to about 1.2%. More P2D population
shifted the P2D-ready phase rather than increasing the missed-boundary
penalty. N1 is marked FINAL_FAIL without native packet replay.

### Decision rule

Only positive per-request scheduler wait/missed-iteration telemetry, aligned
with the P2D/EP event timeline, can establish N1. N1 did observe the first
condition, but failed the serving-headroom and neighboring-point criterion;
the next direction is N2 phase synchronization.

## N2 — P2D-handoff-induced Decode/EP phase synchronization

**Status: `N2_FINAL_FAIL_NO_NATURAL_HANDOFF_CLUSTERING`.**

Two real Mooncake 16-request discovery windows were converted and replayed
with model-derived LAYERWISE P2D and GateRouter EP64. Conversation had at most
2 request-level last-P2D completions in any 5/10/20/50-ms bin; Tool/Agent had
at most 2 in 5/10-ms, 4 in 20-ms and 6 in 50-ms bins. Completion spans were
29.5 ms–3.47 s and 50.1 ms–3.23 s respectively. Arrival bursts were therefore
not compressed into a narrow handoff wave. FlowSim EP CCT stayed about
0.099–0.107 ms. The network discovery metrics are not integrated TTFT/TBT and
are not promoted as such. Details are in `N2_PHASE_SYNCHRONIZATION_AUDIT.md`.

## Remaining order

After N1 and N2, audit multi-NIC/rail affinity mismatch, cross-request KV
batching/HOL, and KV recovery/rehydration storms only if the corresponding
runtime semantics exist. No synthetic transport, replica state, or scheduler
policy is to be added merely to obtain a large number.

## N3 — Multi-NIC / rail affinity mismatch

**Status: `N3_FINAL_FAIL_NO_MULTI_NIC_RAIL_SEMANTICS`.**

The S16 authoritative configuration has 128 logical endpoint/rank nodes and
200-Gbps endpoint links, but no NIC count, rail identifier, rail binding, or
per-rail capacity. `serving/core/flowsim_backend.py` exposes only aggregate
parallel-link capacity or a deterministic hash to one physical parallel link;
its route is a single BFS path over endpoint/switch links. A FlowSpec has no
NIC or rail field. Therefore P2D and EP can share modeled directed fabric
links, but cannot be assigned to distinct or common NIC/rail resources.

The proposed mechanism cannot be tested by adding labels to the event ledger:
that would invent the missing resource and transport-selection semantics. The
full audit, including the 16-member leaf-to-spine bundles, is in
`N3_MULTI_NIC_RAIL_AUDIT.md`.

## N4 — Cross-request KV batching / head-of-line blocking

**Status: `N4_FINAL_FAIL_NO_RUNTIME_KV_BATCHING_OR_HOL`.**

Current P2D and remote-fetch events are request/layer/shard scoped. The replay
option `--coalesce-ep-window-us` only aggregates EP events for FluidSim memory
reduction; it deliberately retains KV rows and creates no batching queue. The
`request_ids` tuple is provenance metadata, not a demultiplexed batch
completion mechanism. `max_flow_bytes` splits same-start events and does not
implement WQE, rendezvous, flush, or HOL semantics.

Merging KV rows or inserting a smaller-request wait would destroy the
request-level barrier or create an artificial delay. Details are in
`N4_KV_BATCHING_HOL_AUDIT.md`.

## N5 — KV recovery / rehydration storm

**Status: `N5_FINAL_FAIL_NO_FAILURE_OR_REHYDRATION_EVENT_MODEL`.**

The tiered cache manager models lower-tier prefix hits, recall-byte accounting,
and recomputation after preemption. The FlowSim worker models explicit remote
KV fetches and planned replica warm-up. None of these is a failure, restart,
invalidation, migration epoch, or recovery-triggered rehydration wave. There
is no input event for a provider loss or request-level recovery barrier.

Reusing remote fetches as a fake recovery event would simply repeat the already
closed P4 remote-KV placement direction. Details are in
`N5_KV_REHYDRATION_STORM_AUDIT.md`.

## Current autonomous-search outcome

The new N1–N5 sequence did not produce a valid new CCF-B/CCF-A motivation
candidate in the current simulator. N1 is a real serving mechanism but its
strongest natural integrated point exposed about 6.5% TTFT boundary wait and
the adjacent larger point fell to about 1.2%. N2 found no narrow real-trace
handoff clustering. N3–N5 fail semantic feasibility gates rather than
performance gates. P5 likewise lacks a validated transport-granularity model.

This is a bounded negative result, not permission to fabricate a scheduler,
NIC rail, batching, recovery, or pacing model. A future positive paper
direction requires a runtime-grounded extension first; until then the current
packet-level evidence does not support claiming a new >=20% serving-level
headroom result.
