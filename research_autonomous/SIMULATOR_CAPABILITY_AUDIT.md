# Simulator capability audit (2026-10-15)

This audit describes the current dirty worktree, not a certified release. The
source commit is `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`; see
`../RESEARCH_LOG.md` for earlier source hashes and matched experiment results.
Source lines below are entry points; every research result must still bind to
its own source and config digest.

| Capability | Implemented causal path and units | Evidence and limit | Research use |
|---|---|---|---|
| Arrival, queue and batch | `serving/core/router.py::load_requests`, `route_arrived_requests`; `serving/core/scheduler.py::schedule`, `_schedule_running`, `_schedule_waiting`. Input timestamps are ns; token budgets and KV blocks are integer tokens/blocks. | vLLM V1-like continuous batching, preemption and slot cap; synthetic request timing is supported. It is not a measured vLLM scheduling equivalence for every load. | Use only with matched bench validation or source-level causal checks. |
| Profiled GPU compute | `serving/core/trace_generator.py::_load_perf_db`, `_lookup_dense`, `_lookup_attention`, `_lookup_moe`, `_emit_sequence`. CSV `time_us` becomes integer ns in the trace, then Chakra µs. | RTX PRO 6000 Qwen3-30B-A3B BF16 has vLLM 0.19.0 single-GPU TP-emulation profiles at TP1/2, profiled token budget 2048; attention sweep spans n=1..256 and KV 16..16384. MoE uses separate TP1 profile. Lookups extrapolate beyond the grid; profile fidelity is not uniform. | Restrict primary claims to measured axis domain; disclose TP emulation and MoE expert-shape limits. |
| P/D KV size and destination | `trace_generator.py::_pd_kv_send_bytes`; `graph_generator.py::resolve_pd_receiver`; `llm_converter.py::_pd_kv_destinations`, `_emit_pd_kv_sends`; `router.py::transfer_prefill_request`. Byte counts are per layer and source TP rank. | One request targets one Decode instance; source shards may redistribute to several destination TP ranks, but converter asserts sum of destination bytes equals source bytes. PP stages map to corresponding Decode stages. A workload may name a per-request Decode target, and the prefix query now checks that actual target. `graph_generator.py` still rejects a Prefill batch whose requests target different Decode layouts, so arbitrary mixed-target P batches are unsupported. Historical 2,352-flow audit verified 201,326,592 B/request for 2048-token Qwen TP2. | Trust only after per-run flow conservation, rank and stage path checks. Multi-Decode fork and mixed-target batches are unsupported. |
| Network backend | `serving/__main__.py` launches analytical ASTRA, ns-3, or `flowsim_worker.py`. FlowSim uses `flowsim_backend.py::FluidFlowNetwork`, directed link capacities in Gbps, release/completion in ns and max-min fluid sharing. | FlowSim has no packet queues, ECN, PFC, drops, DCQCN or measured NIXL overhead. ns-3 is a separate packet backend, not a blanket validation of a FlowSim Serving result. Default `FLOWSIM_NETWORK_CLASSES=KV_MOVEMENT,EP` gives OTHER/TP zero transfer duration. A 2026-10-14 repair now retains a matching SEND→RECV ordering dependency for excluded PP P2P; before that PP2 Prefill stage 1 could run before stage 0. | Network FCT and fluid backlog must not be reported as TTFT or packet queueing. Set and validate traffic classes explicitly. |
| TP/PP/EP/DP and physical ranks | `config_builder.py::_resolve_parallelism`, `_resolve_dp_groups`; `trace_generator.py::_pp_stage_boundaries`; converter stage/rank mapping; FlowSim rank map and topology file. | TP/PP layout is checked, but physical GPU↔NIC affinity is defined by the experiment's rank map, not measured from hardware. MoE default dispatch/combine uses AG/RS over current hidden activations and router data; no historic KV copy per expert. A 2026-10-14 converter repair makes a sole EP1 expert block execute on every TP replica; previously only TP rank 0 ran it. EP>1 sharding is preserved in a synthetic graph test. | Verify rank map, involved dimensions, paths and cut capacities before a network claim. |
| KV memory and prefix reuse | `kv_cache_manager.py::TieredKVCacheManager`, `block_pool.py`; block sizes and pool capacity in blocks/bytes. `scheduler.py::add_decode` claims received KV and may queue by `max_num_seqs`. | NPU KV capacity is an upper bound unless `mem_util` is calibrated to a bench run. Destination DELTA requires a pinned prefix reservation. The current pre-transfer query sees only **resident** D blocks; simultaneous requests to the same missing prefix all send full KV, without in-flight single-flight coalescing. Ordinary CXL `MEM_LOAD` has zero Chakra duration in FlowSim's compute-node path; actual remote-load service is unsupported. Round 16 adds an opt-in D block reservation before P emits KV. | No CXL prefetch latency claim without a timed and validated load event and an observed miss. Compare identical-prefix bursts against a single-flight baseline. Capacity credit is a modeled correctness mechanism; receiver control-plane latency, cancellation and real NIXL backpressure remain unvalidated. |
| GPU/network overlap | Chakra dependencies plus `flowsim_worker.py::AsyncGraphExecutor` release network operations and complete their dependent nodes when flows finish. `LAYERWISE` can send KV during Prefill; `POST_PREFILL` has a graph barrier and currently requires PP1. | Resource overlap follows the generated DAG. It is not a calibrated NIXL pipeline or a true streaming Decode consumer. Check node-level release/finish against theory, not just aggregate FCT. | Use P2D-ready and Decode-admit timestamps to determine exposed delay. |
| Serving metrics | `scheduler.py::add_done` records first token at Prefill graph completion, second token at Decode batch completion, and request end at scheduler completion; CSV rows are ns-derived. | The first timestamp may include P2D drain after sampling. There is no independent client egress callback. `TTFT` is a graph-completion proxy in P/D mode; token 2 and request completion are simulator scheduler-boundary metrics, not measured client latencies. | Mark client TTFT/ITL `METRIC_UNSUPPORTED`; use P2D ready, Decode admission, token 2 and completion separately. |

## Minimal checks already reproduced or retained

- Historical 3P2D matched FlowSim runs and 2,352-flow byte/path audit are in
  `research_receiver_matching/`; the receiver-matching oracle was only
  0.00422% ahead of a balanced greedy on mean token-2 time.
- `experiments/pd_kv_ep/scripts/test_pd_decode_capacity_admission.py` exercises
  the Decode slot waiting path. It does not validate an end-to-end network
  backpressure policy.
- The new branch-group `research_branch_group/theory_gate.py` directly reads
  the model config and rejects the memo's homogeneous N=4 case before an
  unsupported fork implementation is attempted.
- The 4P1D PP2 gate in `research_autonomous/experiments/pp_coflow/` retained
  pre- and post-repair raw traces, exact model-derived P2D bytes, source hashes
  and rank-level flow timestamps. Five targeted simulator regressions and 49
  existing P/D scripts tests pass after the repairs.
- The exact-model Qwen3-32B 1P1D/4P1D TP2 layerwise gate in
  `research_autonomous/experiments/qwen32b_layerwise_gate/` conserves
  536,870,912 B/request and shows the last P2D flow 2.453 ms before identical
  184.907-ms P2D-ready timestamps in the four-source case. This tests the
  unsaturated transfer boundary only; it does not exercise Decode backpressure.
- Round 12 used real prefix block hashes, per-request D state, 24 full-KV
  cases and four D-resident controls. Round 13 used unchanged 3,400-block
  RTX4090 D pools and 64 distinct filler requests; all eight distinct target
  prefixes had P hit and D miss with no capacity wait. The fixed-byte source
  cut finished within 0.045% of its serialization floor. These are controlled
  modeled mechanisms, not hardware/client-SLO validations.

## Current research boundary

The credible small-scale chain is profiled compute -> Chakra DAG -> FlowSim
KV/EP flow completion -> scheduler P2D-ready/Decode admission -> modeled
token-2/request completion, with per-run profile-domain, rank-map and byte
audits. Client egress, in-node TP cost, real transport startup, CXL load time,
and fork group ownership remain outside that chain. A proposal that depends on
any of them needs calibration or a minimal validated extension before its
Serving performance can be claimed.

## Round 15 re-audit: exact checks and remaining invalid paths

The audit below was repeated on the current worktree rather than inferred
from an older CSV. `audit_flow_paths.py` passed for all 2,352 P2D flows in
16 matched 3P2D runs. The Round-13 churn analyzer passed again: eight
distinct target requests each send 268,435,456 B after D eviction or
8,388,608 B with a reserved D prefix, and every flow traverses the declared
100-Gb/s source uplink. The 49 P/D script tests and five focused converter/
FlowSim tests pass with the checked-in simulator environment.

| Boundary | Current verification | Remaining causal limit |
|---|---|---|
| KV byte conservation | `_pd_kv_send_bytes` uses `2 * kv_heads * head_dim * token_count * kv_fp / source_tp` **per layer and source rank**. Converter `_pd_kv_destinations` intersects contiguous TP source and Decode partitions and asserts that its destination byte sum equals the source shard. The independent 2,352-flow replay and Round-13 8P control agree with the model-derived totals. | A fork to more than one Decode is not implemented; the existing mapping represents a single D destination, not expert-distributed KV copies. |
| TP/PP and ranks | The rank-count, receiver-mapping, EP1/TP2 and PP SEND→RECV regression tests pass. Converter `pd_decode_pp` rejects a source PP stage with no target stage. The PP2 repaired run retains stage-1 compute after stage-0 output and 201,326,592 B/request. | TP/OTHER has zero transfer duration in default FlowSim, so absolute TP2 latency is optimistic. This is a dependency check, not measured NVLink service. Mixed D targets in one Prefill batch still fail graph generation. |
| GPU→NIC/rail | FlowSim uses an explicit logical-rank→physical-endpoint JSON and shortest physical paths through a topology file. The 3P2D audit checks D0/D1 rail endpoints for every flow; Round-13 checks the common source cut. | The map is an experiment assumption, not automatic hardware discovery. A paper must bind the physical topology to published hardware or actual inventory and count directed bytes on each claimed cut. |
| Handoff backpressure | The default `add_done` still frees P KV before unconditional D allocation and cannot represent a memory-full receiver. Opt-in `--pd-handoff-capacity-reservation` reserves D blocks before P emits any KV, retries P admission when D memory is full, and commits reserved blocks at handoff. A two-request block-pool regression and a 30-request 2P1D run check zero flows before credit, 30 commits, exact bytes and all completions. | The credit is granted at P admission, so it can hold D memory throughout P compute; its control is zero simulated ns. It is a correctness baseline, not measured backpressure. The 30-request simultaneous burst is a stress fixture, not representative performance evidence. Cancellation and hardware transport credit timing still need validation. |
| Zero-cost communication | Default `FLOWSIM_NETWORK_CLASSES=KV_MOVEMENT,EP` excludes TP/OTHER from service, while an excluded PP P2P still waits for its matching sender. P2D exclusion raises. | A cross-node TP/PP or remote CXL result requires explicit timed transport plus calibration; default zero-cost is not acceptable for it. |
| FlowSim versus ns-3 | FlowSim is directed-link, fluid/max-min service with graph callbacks and ns timestamps. The ns-3 backend uses a separately selected packet topology/config; historical `comm_events.csv` recomputation validates *network* FCT only. The ns-3 topology-selection test passes. | Neither historical ns-3 FCT nor FlowSim backlog is client TTFT/TBT. There is no same-run packet-level P/D Serving feedback validation or measured NIXL startup/registration cost. |
| Skew profiler timing | `AttentionCategory.extract_points()` averages the attention timing samples in a shot. The old `skew.py::_measure()` summed them, making historical skew endpoint microseconds about three times the uniform profile (median ratio 3.004 across 330 exact pure endpoints). Future shots now average; two regression checks pass. | Existing `skew.csv` files are retained unchanged. Their dimensionless alpha remains usable when a row's three shots have equal sample count, but historical raw endpoint times must not be used as per-layer latency or mixed with corrected absolute times without provenance. |

Reproduction of the re-audit:

```bash
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=.:astra-sim/extern/graph_frontend /home/lpm/.conda/envs/llmsim-flowsim/bin/python -m unittest discover -s experiments/pd_kv_ep/scripts -p 'test_*.py' -q
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=.:astra-sim/extern/graph_frontend /home/lpm/.conda/envs/llmsim-flowsim/bin/python -m unittest discover -s research_autonomous/simulator_tests -p 'test_*.py' -q
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_receiver_matching/audit_flow_paths.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/experiments/prefix_inversion/analyze_churn.py
```

## Round 16: capacity-credit repair and its limits

Opt-in `--pd-handoff-capacity-reservation` now pins the required D blocks
before any Prefill graph can emit P2D bytes. The P scheduler leaves a
request waiting, rolls back its tentative local allocation and retries
when D has no credit. The D handoff commits the reservation. The credit
and prefix-query controls are currently zero simulated nanoseconds, so
this validates modeled byte/memory ordering, not production NIXL timing.

The existing under-capacity 2P case was rerun unchanged except for the
flag: target P2D-ready =43,026,875 ns, token 2=60,154,875 ns,
completion=77,282,875 ns, P2D bytes=1,056,964,608, four reservations
and no capacity waits. The normal-size RTX4090 D pool has3,400 blocks.
The 30-request 2P1D stress case exercised378 retry events on requests
27–29 and completed all30. An independent analyzer checks that960 flows
sum to8,053,063,680 B, every request sends268,435,456 B, all first
flows follow their receiver credit, all flows finish before P2D-ready,
and ready≤admit≤token2≤completion. The physical paths all traverse the
declared 100-Gb/s source and destination rails. First-to-credit waits
are4.025,3.429 and0.211 s; this synchronized burst is intentionally a
correctness stress fixture and supplies no policy gain claim. The final
network flow precedes P2D-ready by5.137–5.808 ms for all30 requests.

The first no-chunked version became permanently unschedulable after
Decode preemption: a resumed context exceeded its2,048-token per-step
budget and FCFS could never schedule it. Its raw run is retained with
`INVALID_INTERRUPTED` status. `_schedule_waiting` now raises a clear
error for such unsplittable requests; the completed capacity experiment
uses chunked prefill and retains a regression for the fail-fast case.
This repair does not implement hardware transport credit timing, source
KV retention after P completion, a cancellation handshake or a measured
GPU KV-pool calibration. Saturated-handoff policy claims remain limited
to the modeled reservation protocol and must use a stable, source-backed
arrival process and strong resource-ratio baselines.

## Round 17: agentic sidecar completeness and hash causality

All765 sub-requests in the committed50-session SWE-bench-like workload
declare141 more prompt tokens than supplied in `input_tok_ids`; all765
also have incomplete `output_tok_ids` (20–999 missing output IDs, median
41). The previous `request_block_hashes()` concatenated the two sidecars,
potentially placing future output IDs *before* the declared prompt
boundary. The scheduler's `num_computed_tokens` gate cannot make that
hash chain causal. The function now returns no prefix hashes when the
prompt sidecar length differs from `original_input`. This is conservative:
those requests allocate KV normally but receive no speculative prefix
hits. A regression exercises the exact incomplete-input/future-output
case, and the full52-test P/D suite plus KV manager self-test pass.

`agentic_remote_kv/theory/audit_ids.py` records the input hash and
completeness counts. The older29,086-block agentic capacity estimate
used the invalid concatenated hash representation and is no longer
accepted as a rigorous upper bound. Until exact IDs or measured cache
misses exist, the agentic CXL-prefetch motivation remains `NEED_DATA`;
FlowSim's zero-time CXL load remains `SIMULATOR_UNSUPPORTED` for a
latency-gain claim. The raw workload and historical estimate are retained.

## Round 18: controlled mechanism replay and limits

Five new Llama-3.1-8B RTX4090 TP1/PP1 Serving runs are recorded in
`EXPERIMENT_REGISTRY.jsonl`. Each run has an immutable case directory,
manifest with source/profile/input hashes, explicit logical-rank map
and physical topology, request/event/flow streams, and an independent
`analysis.json` plus flow ledger. The A cases use two P GPUs sharing a
100-Gb/s host source cut and one normal3,400-block D pool. The B cases
use four P GPUs sharing that cut and the same D pool. No TP, PP or EP
collective uses FlowSim's default zero-time traffic classes in these
TP1/PP1/EP1 cases.

The A analyzer checks every P2D flow's request, rank, bytes, source and
destination rails, start/end, prior-work completion, D prefix hit,
target P prefix hit and ready→admit→token2→completion ordering. The
28-filler threshold sends exactly536,870,912 target bytes over the
declared source cut; its42.950-ms serialization floor is only0.077 ms
under the observed43.027-ms P2D-ready event. Twenty-four fillers or
two ordinary refresh requests restore D prefix residency and reduce
the two target transfers to16,777,216 B. The target result is a
modeled Serving chain, not a network FCT substituted for TTFT.

The B analyzer checks four12k versus four14k requests, exact per-request
KV bytes and all flow paths, D block bounds, credit-before-flow order,
P start, D ready/admission and completion. At14k the fourth P waits
3.113511 s for credit; D has no ready job during the first1.644666 s.
This is a causal limitation of the current **early-reservation**
protocol. The simulator does not yet own source KV while a receiver
credit is delayed, and the receiver query/credit still cost zero ns.
The 25.39% late-credit estimate is a separate analytic bound with
optimistic transmission service, not a simulator measurement or a
claim about a real production protocol. Before any JIT mechanism result,
implement and test source-block lifetime, bounded waiting, cancellation
and D release/commit invariants. Two-stage FIFO is the minimum strong
comparator.

## Round 19: opt-in late credit, source ownership and policy boundaries

`--pd-handoff-admission TWO_STAGE_FIFO` is now available for the
FlowSim TP1/PP1 P/D research path with receiver-capacity reservation,
POST_PREFILL full-KV transfer and no DP group. These restrictions are
checked at launch. Prefill emits a compute-only graph; after its final
graph the source KV remains allocated in `source_held` rather than being
freed. The oldest held request obtains a D reservation before its
transfer-only graph is released. Graph completion frees the P blocks;
the ordinary router commits the reserved D blocks. A held cancellation
frees P immediately; an in-flight cancellation waits for graph completion
and then frees P and D without routing the request. This internal cancel
state machine has unit tests but no external abort-workload driver or
measured transport-cancel handshake. Credit/query controls remain zero
simulated ns. The P pool is bounded by its normal block capacity; a
held request consumes source blocks and can backpressure later Prefills.

The first transfer-only run is preserved as
`prompt_14000_two_stage_fifo_r19a/analysis.json`: `fp=16` was mistaken
for 16 bytes, producing an eightfold P2D overcount. The corrected graph
uses `fp//8` (or one byte for FP8 KV); a unit test checks the model-exact
1,835,008,000 B for a 14k Llama-3.1-8B BF16 request and the FP8 half.
The matching analyzer checks every flow's request, source/destination
rank, bytes, physical source/destination rails and time, all reservations
against 3,400 blocks, credit before first flow, source hold until last
flow, and ready/admit/token2/completion order. It passed two uniform,
two heterogeneous admission comparisons and the network-order control.
All valid four-request cases transfer exactly 7,340,032,000 B. The
52-script P/D suite and 13 focused simulator tests pass; `git diff
--check` is clean.

For this trace shape, per-request post-P transfer emits one full-KV
FlowSim flow rather than 32 layerwise flows. This tests the total-byte
and capacity causal path under fluid sharing; it does not calibrate
transport startup, packet bursts or a production per-layer sender.
The matched old/new arms both use the same POST_PREFILL representation.
The original Round-18 LAYERWISE cases remain separate mechanism
observations and are not the denominator for Round-19 policy gains.

The stronger early-credit LAYERWISE protocol was also rerun on the
current code for both Round-19 streams. Its 896 flows per arm sum to
the same7,340,032,000 B and pass the same rail, credit and Serving-event
analyzer. It finishes at5.899737/5.020136 s, versus two-stage FIFO's
4.842298/4.112784 s. Those are comparable whole-protocol outcomes,
but the layerwise/post-P DAG difference prevents treating their gap as
a pure admission-timing treatment effect.

The D-only `--decode-kv-eviction-policy LFU` baseline counts observed
block accesses and evicts the lowest-frequency free cached block,
preferring blank blocks and using the existing free-list order on ties.
Default LRU behavior stays intact. LFU is an online comparator, not
a new proposed mechanism. The two 34-request history/cost experiments
pass 1,536-flow and exact target-byte audits; they use TP1/PP1 so
zero-time TP/PP communication is absent. Their capacity is the same
normal 3,400-block D pool. One warm block per key had one fewer counted
access than the theory assumed, giving 1,968 rather than 1,984 D-hit
tokens. The 10.486-MB residual transfer finishes before Prefill graph
completion, so modeled completion already matches the ideal D-hit
branch. This is a measured/modelled-Serving critical path statement,
not a network FCT or client TTFT claim.

After the matched full-KV experiments, the two-stage path also gained
opt-in `--destination-prefix-handoff DELTA`: it now uses only the prefix
actually pinned by the late D reservation and emits the exact missing
KV bytes. A targeted block-pool test checks that a 16-token cached
prefix is pinned under a 32-token request and a graph-byte test checks
the 64-token Llama delta. This combination has **unit coverage only**;
it is not yet a validated end-to-end policy result or an excuse to use
full-KV as a weak baseline on a prefix-bearing trace. The completed
Round-19 matched B cases remain full-KV and retain their original hashes.
