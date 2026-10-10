# P4 Current Simulation Audit

Date: 2026-09-28

> **Superseding integrated follow-up (2026-09-28):** The minimal FlowSim integrated
> remote-KV extension has now been implemented and run, including model-derived remote-hit
> accounting and same-fabric replica warm-up. See
> [`P4_INTEGRATED_SERVING_VALIDATION.md`](P4_INTEGRATED_SERVING_VALIDATION.md) for the
> serving CSV/SLO audit. It confirms the barrier implementation but does not establish
> material TTFT/TBT impact: native P2D remains the last handoff event in the tested windows.


Status: **Gates 1–3 complete; the current P4 packet-specific candidate is final-fail.**

This document records the initial audit and the completed Gate 1--3 validation of the current
hot-prefix / remote-KV provider-egress experiment. The previous P4_PASS_HOT_PREFIX_PROVIDER_EGRESS_BARRIER label is
therefore treated as a **provisional network replay result**, not as a paper-ready conclusion.

The central question is:

> Is the observed headroom caused by a genuinely trace-driven, distributed KV retrieval
> barrier, or is it primarily the result of giving a provider endpoint a different aggregate
> bandwidth pool?

The current implementation does not yet permit that question to be answered rigorously.

---

## 1. Experiment under audit

The existing P4 artifact uses:

- trace: Mooncake FAST'25 Tool/Agent converted workload;
- selected window: offset 13327, 8 requests;
- topology: S16_EP64, 8 Prefill servers + 8 Decode servers, each with 4 TP2 instances (32 Prefill + 32 Decode instances);
- each P/D instance: TP=2;
- model: Qwen3-30B-A3B-Instruct-2507;
- 48 layers, 128 experts, top-k=8, EP=64;
- endpoint rate: 200 Gbps;
- packet payload: 4096 bytes;
- KV mode: LAYERWISE;
- EP realization: GateRouter-derived A2A_P2P;
- native backend: ns-3 RDMA/Qbb packet simulation;
- controls:
  - FIRST_PRODUCER;
  - BALANCED_REPLICA_ORACLE.

The prior summary reported:

- low-pressure selected window:
  - FIRST request-barrier mean: 7.604891 ms;
  - oracle request-barrier mean: 1.632796 ms;
  - reported mean improvement: 78.53%;
- hot selected window:
  - FIRST request-barrier mean: 6.059611 ms;
  - oracle request-barrier mean: 3.807683 ms;
  - reported mean improvement: 37.16%.

These values are useful for debugging, but they do not yet establish a valid deployable
remote-cache placement result.

---

## 2. Trace facts versus simulator assumptions

### 2.1 What comes from the Mooncake trace

The conversion preserves:

- source request id;
- arrival timestamp;
- input token length;
- output token length;
- input_block_hashes;
- 512-token hash block size;
- hash semantic label remapped_prefix_block_identity.

The converter correctly does **not** treat Mooncake hashes as token ids. The current
replay reads input_block_hashes or prefix_block_hashes in
build_model_derived_replay.py:133-153.

The trace establishes block identity and request timing. It does **not**, by itself, establish:

- which GPU currently owns a block;
- which provider will serve a block;
- whether a block has been replicated;
- whether a cache copy is still resident;
- whether a cache copy is evicted;
- which provider NIC is used at replay time.

### 2.2 What the current replay invents or assumes

The current builder creates a process-local dictionary:

    cache_blocks[block_hash] =
      source_instance
      source_leaf
      ready_ns
      producer_request_id

A block is inserted after the current request's local prefill at
build_model_derived_replay.py:629-638. The first request that produces a block becomes
its permanent owner for the remainder of the selected replay.

The consequences are:

1. There is no finite cache capacity.
2. There is no LRU or other eviction.
3. There is no multi-holder state.
4. There is no replication traffic.
5. The first producer is the only native owner.
6. Reuse of the same hash later is automatically a remote fetch from that first producer.
7. A repeated block's source placement is therefore determined by request-to-Prefill RR
   assignment plus first-seen order, not by source trace metadata.

This is not a criticism of the replay as a debugging model; it is a critical limitation for
the current P4 claim. The present FIRST_PRODUCER hotspot is partly a **simulator ownership
policy**, not an observed production ownership fact.

The code also removes duplicate hashes within one request at
build_model_derived_replay.py:487-494. That is reasonable for block accounting, but
it means the remote request is represented as one fetch per distinct block, not as an
independent fetch for every hash occurrence.

---

## 3. Model-derived KV byte calculation

For Qwen3, the replay loads:

- number of layers;
- KV heads;
- head dimension;
- hidden size;
- model dtype;
- EP degree;
- top-k

at build_model_derived_replay.py:444-460.

The per-token, per-TP-rank KV byte formula is:

    layers * 2 * kv_heads * head_dim * dtype_bytes / TP

and the per-layer formula is:

    2 * kv_heads * head_dim * dtype_bytes / TP

at build_model_derived_replay.py:451-453.

For each matched block, the replay computes:

    block_tokens * kv_per_token_per_tp_rank

and sends one copy per provider rank at
build_model_derived_replay.py:539-572.

Therefore the **byte volume is model-derived**, but the following are still replay assumptions:

- the matched-block set;
- the provider owner;
- the number of provider ranks used;
- the provider-to-destination pairing;
- the absence of replication cost;
- the absence of finite cache and eviction.

The bytes are not synthetic arbitrary MB values, but the network experiment is not yet a
complete remote-KV serving model.

---

## 4. Provider policies are not matched physical states

### 4.1 FIRST_PRODUCER

For FIRST_PRODUCER, the provider is:

    source_instance = cached["source_instance"]

at build_model_derived_replay.py:553-554.

For non-dedicated cache placement, the provider's two ranks are paired with the two
destination ranks at build_model_derived_replay.py:605-609.

This creates provider egress concentration whenever many repeated blocks were first
produced on the same Prefill instance. The resulting bottleneck is real **inside this
replay**, but the ownership concentration is not yet trace-proven.

### 4.2 BALANCED_REPLICA_ORACLE

For BALANCED_REPLICA_ORACLE, the code assumes:

> every matched block already has a legal replica on every Prefill worker.

It then selects:

    prefill_instances[(request_id + block_index) % len(prefill_instances)]

at build_model_derived_replay.py:544-552.

The oracle does not add the traffic needed to create those replicas. It also freezes the
serving anchor to the native first-producer aggregation at
build_model_derived_replay.py:573-596, so EP issue times and the analytical decode
anchor remain matched.

Thus the old comparison is:

- current permanent first-owner state, with no replication cost;
- versus a hypothetical already-replicated state, with no replication cost and a
  deterministic balanced provider choice.

It is a valid **offline upper-bound question**:

> How much could provider concentration matter if replicas were already available?

It is not yet a valid comparison of two deployable systems, nor a same-cache-state
counterfactual.

---

## 5. Event-generation semantics

### 5.1 P2D / remote-KV events

For a request, local-miss KV is released layerwise. The code computes:

    layer_ready = min(
        prefill_done,
        arrival + (layer_id + 1) * layer_ns)

at build_model_derived_replay.py:510-523.

Every event is then split by --max-flow-bytes at
build_model_derived_replay.py:524-533.

Remote fetch events use event type P2D_KV, but are marked with
serving_role=remote_kv at build_model_derived_replay.py:597-618. The native event
type alone therefore cannot distinguish local P2D from remote fetch; analysis must use both
event_type and serving_role.

### 5.2 EP events

EP traffic is generated from the GateRouter-derived source-to-expert-owner matrix. The
builder coalesces decode activity into --ep-bin-us bins, accumulates token counts, and
emits dispatch and combine pairs at build_model_derived_replay.py:650-710.

This is not a per-token native collective timeline. It is a bounded replay approximation:

- all tokens in a bin are represented by one route matrix;
- all layers represented by the bin are coalesced;
- the event starts at the earliest constituent decode step;
- the total bytes for the bin are retained.

The event ledger is useful for matched network comparison, but it is not sufficient by
itself to claim exact integrated TBT.

---

## 6. Native ns-3 call chain

The native replay path is:

    events.csv
      -> KVEPReplay::read_events()
      -> Simulator::Schedule(start_ns, issue_event)
      -> issue_event()
      -> send_flow()
      -> RdmaClientHelper::Install()
      -> RdmaClient::StartApplication()
      -> RdmaDriver::AddQueuePair()
      -> RdmaHw::AddQueuePair()
      -> packet-level Qbb/RDMA
      -> RdmaHw::QpComplete()
      -> qp_finish()
      -> comm_events.csv END

Concrete source locations:

- KVEPReplay.cc:44-78: CSV parsing and stable start-time sort;
- KVEPReplay.cc:83-103: construction of sim_request and send_flow;
- KVEPReplay.cc:146-152: schedule every event and run ns-3;
- entry.h:144-178: allocate port, record START, install RDMA client;
- rdma-client.cc:118-130: StartApplication calls AddQueuePair;
- rdma-hw.cc:239-277: create and initialize a new QP;
- rdma-hw.cc:471-473: complete when ACK advances the QP to finished;
- rdma-hw.cc:560-575: completion callback and QP deletion;
- common.h:288-312: record completion and notify the replay callback.

### Important consequence: one event chunk is one QP

send_flow allocates a new source port for every replay event. Every chunk created by
_split_bytes() therefore becomes a separate QP. The QP is initialized at line 239 of
rdma-hw.cc, and deleted after completion at lines 560-575.

Therefore:

- the native replay does not reuse a persistent QP across requests;
- P4 cannot currently demonstrate QP congestion-state inheritance;
- a logical remote block may become multiple packet-level QPs if it exceeds
  max_flow_bytes;
- the remote flow count is not the same as block count or request count.

This is why request-level aggregation must be performed from the event-level END records,
not from the number of logical blocks.

---

## 7. What is and is not a request-level KV barrier

### 7.1 Correct network-only reconstruction

For a remote-KV request r, the network-only remote barrier should be:

    remote_barrier_ns(r) =
      max(network_end_ns(e))
      over e where request_id == r
          and event_type == P2D_KV
          and serving_role == remote_kv

Equivalently, it is the last completed remote fetch QP for the request. It is not:

- the sum of all flow latencies;
- the mean flow FCT;
- the maximum logical block size;
- the requests.csv decode anchor.

The previous P4 calculations did use a max over remote END records for each request. That
aggregation concept is correct, but it was performed by an ad-hoc analysis command rather
than by a checked-in authoritative analyzer. The repository currently lacks a reproducible
P4 barrier-statistics implementation.

### 7.2 Current replay does not deliver this barrier back to serving

The native replay is a standalone network replay. KVEPReplay.cc uses a no-op message
handler at line 81 and does not call the serving scheduler or release a Decode request
when all remote shards finish.

The builder writes decode_start_anchor_ns to requests.csv, but that anchor is
analytical:

- line-rate bytes;
- hop delay;
- prefill clock;
- provider aggregation;
- and, for the oracle, an explicitly frozen first-producer anchor.

It is not obtained from native packet completion.

Consequently, the old P4 request-barrier result is:

- a valid **packet-level remote completion barrier** reconstructed from
  comm_events.csv;
- not an integrated TTFT;
- not a scheduler-observed KV-ready event;
- not proof that the same delay appears on the serving critical path.

This distinction must be maintained in every later report.

---

## 8. Queue, ECN, PFC, and rate telemetry

The native backend does provide useful packet-level signals:

- comm_events.csv: QP START/END, event identity, bytes, request and collective labels;
- link_timeseries.csv: per physical device transmit bytes/packets, queue bytes/packets,
  ECN marks, PFC pauses, drops;
- link_summary.csv: mean/peak utilization and queue aggregates;
- compact CNP/rate telemetry from common.h;
- legacy qlen.txt and pfc.txt.

The relevant implementations are in:

- common.h:116-167: event and link telemetry state;
- common.h:175-210: endpoint-path string reconstruction;
- common.h:212-306: queue, physical transmit, ECN, PFC, drop, CNP and rate recording;
- common.h:353-439: communication START/END output;
- common.h:955-1098: file headers, topology parsing, physical link telemetry and
  routing setup.

However, link telemetry is not yet traffic-class aware. It measures total bytes/queue state
per physical device. KV/EP attribution currently requires joining flow intervals to flow paths.

---

## 9. Parallel-link correctness and path telemetry limitation

The topology construction preserves all physical interfaces:

- each topology row creates a separate Qbb device;
- nbr2ifs[src][dst] stores every parallel interface;
- SetRoutingEntries() adds every available interface to the ECMP table.

This means the actual routing table can use the physical parallel links.

But two different representations coexist:

1. nbr2ifs: vector of all physical interfaces, used for ECMP setup;
2. directed_link_ids: map keyed only by (src,dst), which stores one link id.

At common.h:1049-1059, every parallel topology row overwrites the same
directed_link_ids[{src,dst}] entry. The later path reconstruction at
common.h:175-210 performs BFS over node adjacency and emits that one stored link id.

Therefore the path string in comm_events.csv is **not the actual ECMP physical-link
choice** when parallel links exist. It is a representative node path plus an overwritten
link-id label.

This affects the current P4 claim directly:

- endpoint completion times are still generated by packet-level physical links;
- physical link queue telemetry exists;
- but a particular last-completing provider flow cannot yet be reliably mapped from
  comm_events.csv to the exact parallel leaf-spine link it used;
- "critical flow used link X" is not currently auditable from the event CSV alone.

Before Gate 1, this must be corrected by carrying the actual selected interface/link id into
the event state, or by recording per-QP route/interface selection at QP creation.

---

## 10. Existing P4 numbers: percentile audit

The hot-window prior report contains only five remote-fetch request barriers. It reported:

- FIRST samples:
  [4.373805, 4.373970, 4.374135, 4.374300, 12.801845] ms;
- oracle samples:
  [1.126407, 1.333020, 2.068023, 2.080893, 12.430071] ms.

The prior P99 implementation used an index of int(0.99 * (n - 1)). With n=5, this
selects the second-largest sample rather than interpolating toward the maximum. This is why
the old report could show:

    mean > P99

for the hot window.

That is a statistics/reporting problem, not evidence that the barrier aggregation itself is
wrong.

Using linear interpolation over the sorted five-sample arrays:

- FIRST:
  - mean: 6.059611 ms;
  - P50: 4.374135 ms;
  - P95: approximately 11.116336 ms;
  - P99: approximately 12.464743 ms;
  - max: 12.801845 ms.
- oracle:
  - mean: 3.807683 ms;
  - P50: 2.068023 ms;
  - P95: approximately 10.360236 ms;
  - P99: approximately 12.016104 ms;
  - max: 12.430071 ms.

Under this correct small-sample interpolation:

- mean improvement remains 37.16%;
- P50 improvement remains approximately 52.70%;
- P99 improvement is only approximately 3.60%;
- max improvement is approximately 2.90%.

Thus the previous hot-window claim of 52.45% P99 improvement is **not valid**. With only
five request-level samples, the report must show all samples and emphasize mean/P50/max;
P99 is statistically unstable and cannot be the headline result.

The low window has seven remote-request samples. Its mean improvement remains large, but
its P99 is also a small-sample statistic and must be reported with the full sample list and
the quantile definition.

No old P4 P99 number should be used as a paper claim until the corrected analyzer is
checked in and rerun.

---

## 11. Current evidence classification

### Valid evidence

- Mooncake contains repeated block identities and real arrival/input/output fields.
- The replay computes KV bytes from Qwen3 model fields.
- GateRouter produces model-derived EP peer matrices.
- Native ns-3 transmits packetized QBB/RDMA traffic over the physical topology.
- A request-level network remote barrier can be reconstructed as the last remote END.
- First-producer source concentration can produce a large packet-level completion difference
  in the selected artifact.

### Not yet established

- The provider concentration is a fact of the production trace.
- The balanced oracle is a deployable policy.
- Replica creation cost is negligible.
- Current cache ownership is finite and realistic.
- The oracle and first-producer runs start from the same physical cache state.
- The exact parallel physical path of each critical QP is recoverable from comm_events.
- Remote barrier delay propagates to integrated TTFT.
- Remote barrier delay propagates to integrated TBT.
- The effect is not merely aggregate provider NIC/bandwidth pooling.
- The effect is at least 20 percent at corrected request-tail metrics across a sufficiently
  large sample.

### Current audit verdict

    P4_CURRENT_SIMULATION_AUDIT = NOT_PAPER_READY

This is not yet a final P4 failure. It means the prior P4 PASS must be downgraded to an
offline packet-level candidate until:

1. percentile/statistics are corrected;
2. exact physical-path attribution is fixed;
3. finite-cache ownership and trace-driven concentration are audited;
4. an analytical/provider-capacity decomposition is made;
5. legal strong baselines are compared;
6. only then is integrated TTFT/TBT worth running.

---

## 12. Original audit plan (completed and superseded)

The following list was the pre-run plan; Gates 1--3 and the final disposition are recorded below:

1. Add a checked-in P4 analyzer that emits complete request-barrier samples and uses a
   documented percentile definition.
2. Generate P4_CAPACITY_DECOMPOSITION.csv for:
   - one provider;
   - per-provider pair;
   - per-destination endpoint;
   - leaf/uplink;
   - aggregate balanced capacity.
3. Repair native path telemetry so the actual physical parallel link selected by each QP is
   recorded.
4. Run Gate 1 with:
   - analytical endpoint bound;
   - corrected FlowSim;
   - simplified packet case;
   - full native ns-3 only on the selected low-output window.
5. Add finite cache ownership with explicit LRU/current ownership audit before calling a
   provider hotspot trace-natural.
6. Compare strong baselines:
   - first owner;
   - random holder;
   - least-loaded holder;
   - network/load-aware holder;
   - barrier oracle.
7. Run integrated TTFT/TBT/SLO only if the strong-baseline gap remains large after the
   above controls.

No final scheduler, replication algorithm, placement algorithm, or transport mechanism is
implemented by this audit.


## Gate 2/3 completion and final P4 disposition

The verified S16 mapping is 8 Prefill servers plus 8 Decode servers, four TP2 instances per
server: 32 Prefill and 32 Decode instances.  A Qwen3 BF16 KV block at 512 tokens is
25,165,824 bytes per TP rank and 48 MiB per TP2 instance.  The finite audit used explicit
per-instance LRU ownership at 128, 512, 1024, 2048, 2366, and 4096 blocks; the 2366 point
is the model/config-derived audit point, not a measured runtime cache allocation.

Gate2 found that the real Mooncake tool-agent trace contains a persistent hot block:
`mooncake_toolagent:0` appears in 10,938 requests and remains owned by one provider in the
2366-block audit.  In the selected 512-request window, 492 requests fetched 3,003 blocks
(144,124.40625 MiB), with provider 8 carrying 77.13% of remote bytes.  Over the full 23,608
requests, the same finite audit had 22,994 remote requests, 218,232 remote blocks,
10,468,366.78125 MiB, all 32 providers active, and a 50.21% maximum provider share.
This makes the trace-supported provider concentration credible, but it does not create
multiple holders: local-miss-only insertion leaves each block with at most one owner.

Gate3 used a matched 64-request FlowSim event ledger at offset 13327.  FULL versus
KV_ONLY changed the finite-first remote-KV P99 by 0.00% and the replica-oracle P99 by only
0.33%; EP CCT P99 was 0.106508 ms in both FULL cases.  The large first-owner/oracle remote
barrier gap therefore survives when EP is removed and is provider endpoint pooling, not a
stable remote-KV/Decode-EP packet interaction.  FlowSim queue values remain analytical
fluid backlog, not packet queue/ECN/PFC evidence.

Final disposition:

- `P4_TRACE_SUPPORTED_PROVIDER_POOLING`: supported as a separate remote-KV/cache-ownership observation.
- `P4_PACKET_SPECIFIC_REMOTE_KV_X_EP`: final fail for the current candidate.
- integrated TTFT/TBT/SLO: intentionally not run; the matched causal control removed the
  claimed EP mechanism, and network-only results cannot be promoted to serving metrics.
- no scheduler, placement algorithm, replication mechanism, or transport mechanism was
  implemented.
