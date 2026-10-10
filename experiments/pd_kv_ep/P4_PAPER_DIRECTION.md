# P4 Paper Direction: What Is and Is Not a CCF-B/A Story

## 1. Research background

PD disaggregation separates the compute-heavy Prefill stage from the latency-sensitive
Decode stage. The handoff is not just a control-plane message: the Decode worker cannot
admit a request until the required KV shards are available. This creates a max-completion
barrier over many data transfers.

Remote/persistent KV caching adds a second movement path. A repeated prefix may be fetched
from a cache provider rather than regenerated locally. The provider is now part of the
critical path, and repeated hot blocks can create a many-request-to-one-provider egress
pattern. With a MoE Decode pool, the same scale-out fabric also carries recurrent EP
communication whose collective completion is determined by a last peer/last flow.

This is a plausible cross-layer question because the two barriers are different:

- remote KV is a request admission barrier: one last block can delay TTFT;
- MoE EP is an iteration barrier: one last peer can delay a decode step and TBT;
- provider replication is a state-transition cost that can change future source placement.

DistServe motivates why TTFT and TPOT are separately important and why P/D communication
must be considered when placing the two stages. Mooncake motivates KV-centric storage,
prefix reuse, and remote KV movement. MFS motivates application-aware scheduling of
multi-stage communication rather than treating all flows as interchangeable. These works
make the background important, but they also mean that a paper cannot claim novelty from
"P/D + KV transfer" or "network-aware KV placement" alone. See the primary descriptions in
[DistServe](https://arxiv.org/abs/2401.09670),
[Mooncake FAST'25](https://www.usenix.org/conference/fast25/presentation/qin), and
[MFS](https://arxiv.org/abs/2603.17456).

## 2. What our current P4 evidence actually says

The old packet-level P4 result demonstrated that a first-owner provider can have a much
larger request-level last-fetch barrier than a balanced already-replicated oracle. The later
audit showed that most of the gap is provider endpoint pooling and that the oracle had
omitted replication cost. The current minimal integrated extension fixes the most important
semantic issue: remote-hit tokens are no longer duplicated as native P2D bytes, and
replication copies are real same-fabric flows.

The new integrated result is negative for serving propagation:

```
remote fetch finishes
    < native P2D last shard
    = p2d_kv_ready_time
    < first Decode token
```

Consequently the provider completion difference is hidden behind another required barrier.
The data-plane overlap exists, but the remote-provider path is not the exposed barrier in the
real windows tested. This is the correct conclusion to present now.

## 3. The only defensible P4 paper thesis

P4 could become a paper only after a stronger, trace-grounded reformulation:

> **Replica creation and cache ownership determine which KV source becomes the exposed
> request barrier in MoE PD serving; optimizing average KV bandwidth is insufficient because
> the final remote block and the final EP peer are coupled through shared directed cuts.**

This is not the same as claiming that any hot provider always slows Decode EP. The novelty
would have to be the interaction of three facts:

1. block identity and temporal reuse create a non-uniform provider state;
2. replication changes provider egress capacity but consumes the same fabric and may collide
   with active EP rounds;
3. the serving metric is a max barrier, so a small set of last blocks/last EP peers controls
   TTFT/TBT even when aggregate traffic is unchanged.

The proposed paper object is therefore **replication-aware exposed-barrier selection**, not a
static replica-placement oracle and not a generic load balancer.

## 4. Required evidence before calling it CCF-B/A

The current P4 gate is not enough. A publishable version must first pass all of these:

### A. State realism

Use a finite block ownership state with:

- explicit cache capacity and eviction;
- zero, one, or multiple legal replicas;
- request-triggered replication with measured bytes;
- replica warm-up time and source/destination identities;
- a clear policy for whether a remote hit is served from the first owner, a replica, or local
  compute.

The state transition must be driven by trace block identities and arrival order. An offline
oracle may be shown only as an upper bound.

### B. Exposed-barrier dominance

For a selected request, the last remote fetch must be the last required handoff event often
enough to matter. Report:

- native P2D last-shard completion;
- remote-fetch last-block completion;
- `p2d_kv_ready_time`;
- TTFT;
- the slack between remote completion and native P2D completion.

The current gate has the wrong sign: remote completion has positive slack before native P2D.
A future candidate needs this slack to cross zero naturally, not by adding delay.

### C. Shared-cut coupling

The provider and EP must share a real directed physical cut. For every candidate window,
show:

```
provider/link identity
-> remote fetch interval
-> EP critical peer path
-> overlap and residual capacity
-> last-completion delay
-> TTFT/TBT
```

A provider-only FCT result with no change in EP CCT/TBT is a remote-cache systems result, not
a PD-MoE network result.

### D. Replication cost accounting

Compare at least:

- no replication / first owner;
- pre-warmed legal replica;
- online replication whose copy traffic overlaps the serving window;
- compute-local-miss control.

Keep total request bytes and trace requests fixed. Include warm-up bytes in network load and
show when the copy is amortized. A replica that is free and instantly available is not a
valid baseline.

### E. Serving-level headroom

The minimum persuasive target is a stable request/barrier or serving gap in neighboring
trace windows, with at least one integrated metric showing material change. For a CCF-A
claim, aim for:

- TTFT P95/P99 or TBT/ITL P95/P99 at least about 20%;
- or joint SLO/goodput improvement of at least 20 percentage points / a comparable robust
  goodput gain;
- plus a packet-level validation for one representative window.

Do not count a 79% network-only provider oracle gap if the integrated TTFT difference is 0%.

## 5. How to grow the work into a paper

### Paper question

A strong question is:

> When a repeated KV prefix can be computed locally, fetched from a hot provider, or fetched
> from a newly created replica, which choice minimizes the *exposed max barrier* of the next
> Decode admission and preserves the EP iteration barrier under a shared fabric?

This is stronger than "where should a request go?" because it includes a cache state
transition and two different downstream barriers.

### System model

Define each request as a small coflow/barrier object:

- local-miss KV shards;
- remote-hit block fetches;
- optional replication copies;
- Decode EP dispatch/combine peer flows;
- compute intervals and admission dependencies.

For a request `r`:

```
H_r = max(last_native_P2D_r, last_remote_fetch_r, last_replica_dependency_r)
TTFT_r = H_r + first_decode_compute_r - arrival_r
```

For decode step `s`:

```
CCT_s = max(peer_finish_s) - collective_start_s
TBT_s = compute_s + exposed(CCT_s)
```

The research problem is to predict how a placement/replication action changes both maxima,
including the copy traffic it creates.

### Candidate contribution structure

1. **Trace-driven discovery.** Show that block reuse and request arrivals generate provider
   concentration and that the concentration is not visible from average KV bytes alone.
2. **Barrier exposure analysis.** Define the slack between each KV subtype's completion and
   the request handoff; identify when remote KV is hidden by native P2D and when it becomes
   exposed.
3. **Replication-cost model.** Quantify the break-even point where a replica's future
   egress savings repay its same-fabric copy cost.
4. **MoE coupling.** Show that replication placement can help TTFT but hurt an EP critical
   round if the copy crosses the EP critical cut, or can help both when it removes a provider
   hotspot from that cut.
5. **Mechanism, not just policy.** Implement only after the motivation is established:
   a barrier-aware source/replica selector or a replication admission rule that uses
   `remote-fetch slack`, `EP critical-cut load`, and `replication amortization`.

### Evaluation matrix

Use the same real traces already converted in the repository:

- Mooncake Tool/Agent for hot-prefix locality;
- Mooncake Conversation for repeated conversation prefixes;
- BurstGPT for bursty concurrent P2D;
- Azure as a weak-reuse/negative control.

For each trace, sweep only measured or trace-derived states:

- cold/local miss;
- first-owner remote hit;
- finite-cache LRU;
- legal one-replica state;
- two-replica state;
- online copy during low EP pressure;
- online copy during an EP-heavy window.

Use FlowSim for discovery and native ns-3/HTSim only for a few representative windows. Report
both fluid and packet-level semantics separately.

## 6. What would distinguish this from nearby work

- It is not merely PD disaggregation: the key object is the max handoff barrier after cache
  reuse.
- It is not merely Mooncake-style KV-centric scheduling: the new angle must expose the
  replication-copy cost and the Decode MoE EP barrier on the same fabric.
- It is not merely MFS-style application-aware flow priority: the control object includes
  a changing cache ownership state and a replication action whose own traffic can hurt the
  next barrier.
- It is not generic network-aware placement: the decision must jointly account for block
  popularity, source egress concentration, the request's last required fetch, and EP
  critical-path overlap.
- It is not a packet queue paper unless packet-only phenomena such as ECN/PFC/QP state or
  physical-path polarization are shown to change the serving barrier beyond the fluid model.

These distinctions are hypotheses to validate, not novelty guarantees. A final related-work
section must re-check the literature immediately before submission.

## 7. CCF-B versus CCF-A positioning

### CCF-B-feasible version

A CCF-B paper could be credible with:

- a trace-driven provider-concentration observation;
- a finite-cache and replication-cost model;
- FlowSim plus a small native packet validation;
- a simple barrier-aware replication/source policy;
- robust TTFT/TBT or goodput gains across at least two traces.

The key result would be a reproducible system/network interaction rather than a new transport
protocol.

### CCF-A ambition

For CCF-A, add at least one deeper mechanism unavailable to ordinary request routing:

- a formal exposed-barrier / replication-amortization model;
- a topology-aware critical-cut predictor for MoE EP routes;
- an online decision that is proven safe or bounded under stale cache state;
- packet-level validation showing the predictor remains valid under physical queues and
  congestion control;
- large-scale results where the policy wins in one regime without losing the other SLO.

The paper must show a regime change: replication helps under one workload state but hurts or
is not amortized under another. Otherwise the story collapses to "replicate more hot data."

## 8. Current recommendation

Do not write P4 as a finished CCF-A motivation yet. The current strongest honest statement is:

> Trace-driven provider concentration can create a large remote-KV request barrier, but in the
> tested integrated Qwen3/EP64 windows that barrier is hidden behind native P2D completion and
> does not materially change TTFT/TBT. Replica warm-up is now charged correctly, so the
> missing evidence is exposed-barrier dominance, not a missing accounting field.

The next scientifically valuable experiment is not a larger arbitrary topology. It is a
finite-cache, trace-driven state where online replication is triggered near an active Decode
cohort, followed by a matched no-copy control. If the remote/replication completion becomes
the last required barrier and the integrated metric moves robustly, P4 becomes a serious
CCF-B candidate and possibly a CCF-A systems/network paper. If it remains hidden behind
native P2D across representative windows, close P4 as a valid negative characterization and
move to another packet-specific mechanism rather than inflating the provider result.
