# A/B theoretical pre-screen — before new runs

Date: 2026-10-12  
Scope: current dirty-worktree FlowSim, Qwen3-30B-A3B-Instruct-2507, BF16,
layerwise P2D, 8 GPU/server, 2 x 200-Gbps NIC/server. This is a theory gate,
not a result claim.

## Shared model-derived quantities

The checked-in model config gives 48 layers, 4 KV heads, head dimension 128,
BF16 (2 B), hidden size 2048, 128 experts and top-k 8. At TP=1:

```text
KV/token = 48 * 2(K,V) * 4 * 128 * 2 = 98,304 B
KV/request(2048 tokens) = 201,326,592 B = 192 MiB
KV/layer/request = 4,194,304 B = 4 MiB
200 Gbps = 25,000,000,000 B/s per directed NIC link
```

The 4-MiB value is the full TP=1 per-layer KV transfer. It is not multiplied
by TP shards in the planned TP=1 fixture. Four GPUs share each NIC-facing
200-Gbps directed edge through modeled high-bandwidth GPU/NIC access links.
TX and RX are separate directed resources.

Profile-backed trace synthesis gives QKV-layer release intervals of
1.537064 ms for a 2048-token prefill and 1.190772 ms for a 1024-token
prefill. These are simulated compute-profile intervals, not physical GPU
measurements made by FlowSim. The respective per-layer KV shards are 4 MiB
and 2 MiB, yielding sustained model-derived demands of 21.830 and 14.089
Gbps/request. A recurrent four-token EP4 seed cohort adds about 1.405
Gbps/rail as derived below. Receiver-rail points are:

| P2D requests per rail | KV mix | KV average | EP seed average | Total / 200G | Interpretation |
|---|---|---:|---:|---:|---|
| 8 | 8 x 2048 | 174.642 Gbps | 1.405 Gbps | 88.02% | high-load neighbor |
| 9 | 7 x 2048 + 2 x 1024 | 180.990 Gbps | 1.405 Gbps | 91.20% | primary high-load point |
| 9 | 8 x 2048 + 1 x 1024 | 188.731 Gbps | 1.405 Gbps | 95.07% | outside selected envelope |
| 9 | 9 x 2048 | 196.472 Gbps | 1.405 Gbps | 98.94% | near-capacity sensitivity only |
| 10 | 10 x 2048 | 218.302 Gbps | 1.405 Gbps | 109.85% | sustained overload; excluded |

These are profile-derived average offered-load estimates, not packet results
or measured utilization. Synchronized release bursts and finite-run queues
still require measurement. N=10 is excluded because KV alone exceeds
receiver capacity and would test overload, not an arbitration opportunity.

## Direction A — cross-request KV/EP fabric contention

### Smallest network mechanism topology

The lower-bound physical topology is 2 Prefill servers + 2 Decode servers,
each 8 GPUs and 2 x 200G NICs, one ToR. At the primary point, seven
2048-token and two 1024-token Prefill requests send model-derived layerwise
KV to one D0 receiver rail. One legal EP4 Decode group spans D0/D1, with all
four ranks pinned behind that same rail. The shared directed resource is the
D0 NIC RX/uplink path, not an assumed switch-wide bottleneck.

For a serving-integrated version under the current static P/D pairing and
group-major rank layout, reserve eight Prefill instances for one seed request
per EP rank and nine Prefill instances for candidates: 17 total Prefill
instances over 3 physical Prefill servers + 2 Decode servers (5 physical
servers). Candidates are split across the two D0 Decode instances on that
rail to respect instance capacity while retaining the shared NIC. The seed
Decode cohort completes at least four iterations before candidate arrival.

### Model-derived EP load and expected bound

Current EP4 is direct-peer FlowSim expansion of frontend ALLGATHER dispatch
and REDUCESCATTER combine, not GateRouter A2A. For the audited 4-token EP4
batch, the trace has 4352 B per participant for ALLGATHER dispatch and 4096 B
per participant for REDUCESCATTER combine. The adapter expands a group round
to 12 direct peer flows. One full EP4 group is pinned to one D0 NIC rail, so
the four cross-server peer flows from its two D1 ranks to its two D0 ranks
all traverse that rail. REDUCESCATTER uses a participant-sized chunk
(`4096/4 = 1024 B`) per peer:

```text
dispatch on one D0 rail/layer = 4 * 4352 = 17,408 B
combine on one D0 rail/layer  = 4 * (4096/4) = 4,096 B
total per 48-layer Decode token = 1,032,192 B per rail
at the measured 5.875528-ms TBT = 1.405 Gbps average per rail
```

The primary 7-long/2-medium mix plus the seed EP4 group requests about
182.396 Gbps (91.20%) on the shared directed rail; the 8-long neighbor
requests 176.047 Gbps (88.02%). These are profile-derived average offered
loads, not measured utilization. Release alignment and collective bursts
determine the actual queue and barrier response.

At the nine-request mixed point, an idealized max-min cut with four
simultaneous critical EP peer messages per collective phase and nine
same-cut KV flows gives a network-only
FAIR-vs-EP-isolated serialization difference of about 1.57 us for dispatch
and 0.37 us for combine per MoE layer. If fully exposed across 48 serial
layers, that is about 93 us/token, or 1.58% of the measured 5.876-ms TBT.
This transmission-only upper bound excludes compute hiding and assumes each
affected peer is on the critical path. It predicts a small serving effect,
not a 20% gain.

### Pre-screen disposition

**A theory gate: PASS for one bounded mechanism/serving experiment; not a
paper-motivation PASS.** The 8-long neighbor and seven-long/two-medium point
place request-derived P2D and EP peer traffic on the same real receiver cut
at approximately 88% and 91% mean offered load. Test those two points plus
an EP-isolated counterfactual. Exclude the sustained-overload N=10 point.

## Direction B — multiple GPUs sharing two NICs

### Smallest integrated topology/workload capable of loading both rails

For an 8-GPU D0 server, place four GPUs behind each 200G rail. Two
independent EP4 groups are mapped across D0 and D1, one complete group per
rail (all four ranks of a group use that rail). Put nine P2D requests on each
D0 receiving rail (seven 2048-token and two 1024-token; 18 candidates total),
spread over distinct Prefill GPU ranks and split across the two D0 Decode
instances attached to each rail.
Add eight seed requests (four per EP group) to establish recurrent Decode
collectives before candidate KV starts. Under current fixed pairing this
requires 26 Prefill instances (8 seed + 18 candidate-capable ranks) on four
Prefill servers and two Decode servers: six physical servers. The N=9/rail
near-capacity sensitivity requires 18 candidates and the same six-server
fixture.

At the primary mixed point, model-derived KV is 180.990 Gbps per D0 rail; a
4-token EP4 seed group adds about 1.405 Gbps average in the relevant receive
direction, for approximately 182.396 Gbps (91.20%). The eight-long neighbor
is 176.047 Gbps (88.02%). Both NICs must be reported separately by direction;
this plan targets high RX on both D0 NICs, not a claim that every NIC TX/RX
direction in every server is simultaneously saturated.

### Request urgency and theoretical scheduling headroom

For nine same-rail requests, an exclusive-service oracle can reduce one
designated request's layer-shard service relative to max-min sharing. The
exact bound depends on whether the designated request is 2048 or 1024 tokens;
it is only a network upper bound, not a TTFT claim. Integrated serving must
establish whether any of it is exposed. This is not an implemented or
deployable policy.

For EP-vs-KV, the 4-token EP4 transmission-only bound is at most about
1.58% of one 5.875528-ms TBT at nine same-rail KV requests, before compute
hiding. Existing
EP_FIRST is class-wide strict fluid priority; it is not per-request NIC-QP
arbitration. FlowSim has no RNIC FIFO/QP scheduler, packet priority queue,
packet serialization, ECN/PFC, or packet-level HOL. Its modeled mechanism is
per-directed-link fluid bandwidth allocation.

### Pre-screen disposition

**B theory gate: PASS for a bounded integrated resource-sharing test, with an
explicitly small EP/TBT upper bound.** The two independent D0 rails each
target about 91% mean offered load using model/profile-derived request sizes.
An ideal same-class KV request oracle may produce a visible flow-level bound,
but its serving-barrier value is unknown. Do not invent deadlines or use an
after-the-fact SLO.

## Experiment gate

Gate 0 is only **partially validated** (see `01_BASELINE_VALIDATION.md`).
Focused current-worktree tests pass, and FlowSim can represent rank-to-NIC
sharing and integrated completion feedback. Exact GateRouter A2A and
packet-level serving feedback are not validated. Proceed only with a
clearly labeled FlowSim/AG-RS characterization. Any ns-3 check is
network-only unless completion is actually fed back to the serving scheduler.

The minimum experiments selected by this pre-screen are:

1. A: eight full-size requests and a seven-long/two-medium P2D mix on one
   receiver rail, with a recurrent legal EP4 group; FAIR and EP-isolated
   network controls.
2. B: a seven-long/two-medium P2D mix on both D0 receiving rails, two
   independent EP4 groups, FAIR / EP_FIRST / KV_FIRST, and event-derived
   service slack.
3. Only if B exposes a same-class urgency difference in serving events, a
   bounded offline request-order upper-bound calculation. No online scheduler
   or new production policy is implemented.

No request timing, bytes, model profile, link capacity, or SLO threshold may
be altered to force a positive result.
