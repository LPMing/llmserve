# KV Movement vs. Decode EP: System Audit

This is the consolidated system audit for the P/D and MoE experiments. It
replaces the former collection of separate P2D, EP, rank-mapping, official
example, instrumentation, and network-limitation notes.

## Repository snapshot

| item | value |
|---|---|
| remote | `https://github.com/casys-kaist/LLMServingSim.git` |
| branch | `main` |
| audited commit | `a4053bc1161872420e1e0607cb3409ef659b828e` |
| version | `v1.1.0-122-ga4053bc` |
| serving frontend | Python continuous-batching scheduler |
| analytical backend | ASTRA-Sim |
| packet backend used for contention evidence | native ns-3 |
| model used for the primary native study | Qwen3-30B-A3B-Instruct-2507, BF16 |

The worktree contains study instrumentation and experiment code in addition to
the upstream simulator. The upstream source tree was not reset as part of this
documentation cleanup.

## P/D control path and TTFT

The serving path is:

```text
request arrival
  -> Prefill scheduling and model compute
  -> model-derived P2D K+V shard sends
  -> prefill graph completion / KV-ready barrier
  -> router.transfer_prefill_request()
  -> Decode scheduler admission
  -> first Decode compute and EP communication
```

`Request.set_ttft()` records the time from request arrival to first-token
completion. The prefill scheduler retires the prefill request and performs the
handoff only after its initial graph has completed; the Decode scheduler cannot
admit that request before the P2D completion gate. Therefore P2D KV is on the
implemented TTFT critical path. A request's own P2D and first Decode EP phase
are ordered, so the intended contention is cross-request:

```text
R1: Decode EP  <---- shared network ---->  R2: new-request P2D KV
```

The current large-scale rank ledger uses the actual Decode receiver for P2D.
Older exploratory artifacts may contain prefill/shadow bookkeeping; they are
not used as current large-scale performance evidence.

P2D is layer-wise/chunk-wise in the generated graph rather than one artificial
bulk flow. For the Qwen3 study, model-derived K+V bytes are:

```text
2 * KV_heads * head_dim * input_tokens * layers * bytes_per_element / TP
```

The Q projection is not transferred. KV-ready time is the completion of the
last required shard.

## Decode MoE / EP path

The Decode path is:

```text
active Decode batch
  -> GateRouter token routing
  -> EP dispatch
  -> expert compute
  -> EP combine
```

The upstream/native trace represents the MoE exchange as EP-scoped
`ALLGATHER` dispatch and `REDUCESCATTER` combine. This is not a literal
`ALLTOALL` opcode. The research harness also provides `A2A_P2P`, which uses
the GateRouter source-to-expert-owner route matrix and emits exact variable-size
P2P dispatch/combine flows. Both modes are retained; `A2A_P2P` is preferred for
large-scale problem discovery because it exposes route-level traffic.

EP degree, active Decode tokens, hidden size, top-k, expert routing, precision,
and the route matrix determine communication bytes. No paper-facing result is
allowed to replace these with an arbitrary EP byte parameter. EP CCT is always
the collective metric:

```text
last communication completion - collective start
```

It is never the latency of one constituent P2P flow.

## Data plane and backend

The serving scheduler/control plane decides admission, pairing, batch contents,
and completion callbacks. The data plane carries P2D and EP communication. In
the native contention path both classes become ASTRA communication requests,
enter the native ns-3 frontend, follow the same generated physical topology,
and share directed-link serialization and Qbb queue state. The telemetry can
record flow identity, source/destination, bytes, start/end, path, queue,
ECN, PFC, and drops.

The old analytical backend can estimate communication time but does not model
shared packet queues. The FlowSim replay path is useful for fast flow/event
counterfactuals and can report completion, overlap, and policy effects, but it
is not a replacement for packet-level queue/ECN/PFC evidence and does not by
itself close the serving scheduler loop. This distinction is preserved in the
experiment reports.

The old small shared-spine placement has Prefill ranks on one side and Decode
ranks on the other. P2D traffic and one direction of Decode EP naturally share
core and Decode-ingress links; no forced ECMP collision or artificial path
pinning is used.

## Instrumentation contract

The canonical event schema includes:

```text
request_id, session_id, traffic_class, traffic_subtype, collective_id,
layer, src_gpu, dst_gpu, bytes, start, end, path, directed_link_ids
```

Traffic classes are `KV_MOVEMENT` (with subtypes such as `P2D` and
`REMOTE_KV_FETCH`), `EP` (`DISPATCH`/`COMBINE`), and `OTHER`. A mixed link is
reported only when KV and EP are active on the same directed physical link in
the same interval. A coarse event-envelope intersection is diagnostic, not a
causal contention proof.

Discovery keeps compact aggregate summaries. Validation enables per-flow paths,
per-link queue samples, ECN/PFC/drop counters, and exact overlap rows only for
selected windows. Larger sampling intervals reduce telemetry volume but do not
change packet completion semantics.

## Official examples and validation gates

The official colocated, P/D, MoE/EP, and available P/D+MoE analytical examples
were run successfully with the current frontend. The official P/D+MoE example
uses EP degree 1; it is a software-path gate, not evidence for EP=16/64
performance. Native EP=2 contention is validated. EP=4 startup semantics and
large-scale actual-rank communication gates are validated, but no EP=64
performance claim is made.

## Audit boundaries

- P2D is serving-semantic and model-derived; it is not a converted 1-GiB flow.
- Current native MoE collectives are AG/RS unless the exact-routed A2A mode is
  explicitly selected.
- Shared-link contention is established only where exact native link overlap
  and matched collective metadata are available.
- ECN/PFC/congestion-control conclusions require packet-level validation; a
  FlowSim or analytical completion ratio is not such evidence.
- S64/S256 topology artifacts are scale gates unless the corresponding replay
  has complete event coverage and a stated telemetry model.

The current canonical results are in
[`MOTIVATION_RESULTS.md`](MOTIVATION_RESULTS.md) and the final four-request
FlowSim artifact is
[`experiments/pd_kv_ep/results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md`](experiments/pd_kv_ep/results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md).

## Follow-up full-chain audit (worktree after the parallel-link recheck)

The end-to-end FlowSim path was re-audited after the topology correction.  The
following chain is now exercised by the integrated frontend:

```text
request arrival
  -> Prefill scheduler and profile-backed compute
  -> model-derived layerwise P2D SENDs to actual Decode ranks
  -> persistent FlowSim shared fabric
  -> all required P2D SEND completion barrier
  -> router.transfer_prefill_request()
  -> Decode scheduler admission
  -> Decode MoE EP dispatch/combine barrier
  -> first token and subsequent token accounting
  -> TTFT / TPOT / TBT in the request CSV
```

For `LAYERWISE`, a layer's P2D SEND is dependent on that layer's K/V
production, but the next Prefill layer is not made dependent on the SEND
completion.  This is the implemented nonblocking streaming model.  Decode
admission nevertheless waits for the final required shard, so a request's own
P2D and first Decode EP do not overlap; cross-request overlap remains possible.

One data-plane correctness issue was found and fixed in
`serving/core/flowsim_worker.py`.  The previous FlowSim adapter expanded every
Chakra collective as `comm_size/(N-1)` bytes from each rank to every peer.  It
therefore under-modeled native AllGather and did not preserve the
per-destination payload semantics of ReduceScatter/AllToAll.  The adapter now
uses the Chakra collective type:

| collective | FlowSim direct-peer approximation |
|---|---|
| AllGather | each source sends its local `comm_size` chunk to every remote peer |
| ReduceScatter | each source sends one `comm_size/N` destination shard to every remote peer |
| AllToAll | each source sends one `comm_size/N` destination shard to every remote peer |

The collective remains a barrier on the last peer completion.  This is still a
fluid direct-peer approximation, not a replacement for ASTRA's configured ring
or tree implementation; it now has the correct input-size contract before any
algorithm-specific path model is claimed.

The converter metadata is now authoritative for traffic classification
(`event_type=1` P2D, `2` dispatch, `3` combine), with name matching retained
only for legacy ET graphs.  This prevents a future layer name from silently
turning a serving communication event into `OTHER`.

### Regression gates

- Python compile check: passed for the serving and experiment Python modules.
- Integrated `A2A_P2P`, one request, actual Decode receiver, layerwise P2D:
  completed with legal CSV values: TTFT `46.84 ms`, TPOT `2.30 ms`, and two
  token intervals of `4.60 ms`; 96 P2D flows and 768 EP peer flows completed.
- Integrated `NATIVE_AG_RS`, the same request and topology: completed with
  TTFT `46.74 ms`, TPOT `2.25 ms`, and two token intervals of `4.49 ms`.
  The collective telemetry reported 4 participants and 12 peer flows per
  dispatch/combine round; AllGather used the full 4,352-byte local chunk per
  peer and ReduceScatter used the 1,024-byte per-destination shard.
- Same-request overlap check on the actual-rank layerwise A2A run: no
  P2D--EP overlap; P2D ran through `40,967,986 ns` and the first EP flow began
  at `42,282,000 ns`.  This is the expected serving barrier, not a missing
  contention opportunity.
- Standalone FlowSim replay regression: the existing 4-request ledger still
  completed all 2 KV flows and all 768 EP flows in the matched KV-only and
  EP-only controls.

### What “full-chain” means here

The integrated path is full with respect to the studied serving semantics and
the two selected scale-out traffic classes.  TP/PP/control traffic is still
classified as `OTHER` and completes locally unless explicitly included through
`FLOWSIM_NETWORK_CLASSES`; this is deliberate because the study scopes the
fabric to P2D KV versus Decode EP.  It must not be described as a complete
packet-level model of all accelerator traffic.

The physical network abstraction is also explicit.  A parallel leaf--spine
bundle is one fluid resource whose capacity is the sum of identical physical
links, while each GPU endpoint still has its own 200-Gbps access link.  Thus a
single end-to-end GPU flow remains limited by its endpoint link; the aggregate
3.2-Tbps resource is shared by many flows crossing the bundle.  The model does
not simulate per-physical-link ECMP hashing, packet serialization, packet
buffers, ECN, PFC, or drops.  Any claim about those quantities requires a
matched HTSim/ns-3 replay.

The integrated FlowSim model is therefore suitable for fast, model-derived
serving and fluid-contention characterization after this fix.  It is not by
itself sufficient for a paper claim about packet queue behavior or for a
claim that one application flow independently receives the full parallel-bundle
capacity.

### Batch-granularity boundary

The serving frontend aggregates the P2D payload generated by all requests
scheduled in one Prefill batch into the per-rank `pd_kv_send_tokens` value.
The resulting trace is a rank/batch coflow: its bytes are model-derived and
its completion gates the batch's P2D handoff, but the FlowSim event is not
split into independently scheduled request-level flows when several requests
share that Prefill batch.  Consequently, a request-level KV FCT claim is
exact only for a one-request batch (or for a workload whose event ledger has
one request per P2D event).  For mixed batches the valid claim is batch/coflow
handoff completion and its effect on the Decode admission barrier.  Splitting
those bytes by request would require a separate request-level batching/coflow
model and must not be inferred from the current aggregate telemetry.

This does not invalidate the current cross-request contention experiment: the
network still sees model-derived P2D coflows and Decode EP collectives from
different serving batches on the same directed fabric.  It does constrain the
granularity used in later TTFT attribution and is now part of the simulator's
validity statement.
