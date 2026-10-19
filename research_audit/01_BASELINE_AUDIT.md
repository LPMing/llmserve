# 01 — Current simulator baseline audit

**Current gate: `PARTIALLY_VALIDATED` — motivation experiments remain gated.**

## Critical timing-unit correction — 2026-10-11

A newly audited serving-to-Chakra boundary contained a 1000× compute-duration
unit error. Profile CSV `time_us` values were converted to internal
`latency_ns`, but `indexed_cols()` passed those integers directly to Chakra's
`duration_micros` field. The fix converts nanoseconds to rounded-up
microseconds at that boundary, with a 1-µs minimum. Focused regression tests
and corrected one- and two-request integrated FlowSim runs now pass. This
invalidates prior FlowSim serving-time and time-alignment claims whose trace
durations were produced by the old adapter. Prior packet replay inputs derived
from those release timestamps are likewise not timing evidence; their bytes
and endpoint mapping may still be used only if independently revalidated.

Corrected, bounded observations:

| Measurement | Corrected observation | Scope |
|---|---:|---|
| One request, input 1/output 3 | TTFT 4.266 ms; TPOT 2.339088 ms; ITLs 2.339149/2.339088 ms | Serving smoke, not a distribution or realistic-load result |
| Two-request controlled overlap | Request 0 EP CCT P99 16.273 µs vs EP-only 16.099 µs (+1.08%) | 192 within-run collective samples, not independent-request P99 |
| Same two-request case, request 1 KV shards | Mean FCT 0.016156 ms vs KV-only 0.015552 ms (+3.88%); P99 0.021342 ms vs 0.020686 ms (+3.17%) | 96 model-derived shards in each matched run |
| Request-level handoff / TTFT | 47.353 ms ready and 43.051 ms TTFT in both FULL and matched KV-only | No serving-visible KV penalty at this point |
| Shared directed-link service overlap | 28.912 µs on 26→10; 289.688 µs on 26→11; 318.600 µs on 30→26 | FlowSim fluid active-service intervals, not packet queues |
| Decode token timing | TPOT 2.339088 ms solo vs 2.339118 ms in FULL (~+0.0013%) | No meaningful serving degradation |

### Corrected same-class KV–KV controlled case — 2026-10-11

Two requests (`input=32` and `input=128`, both `output=1`, both arrive at
zero) are routed to distinct Prefill instances but share the same P-server
200-Gbps NIC rail and D0 receiver rail. Each produces 96 per-layer×TP KV
shards from the Qwen3 model configuration. Their P2D flows overlap on the
directed links `24->30` and `30->26` for 267,408 ns of pairwise shard-service
intersection per link. The corresponding model-derived Decode-received KV
totals are 3,145,728 B and 12,582,912 B.

Each request was also run alone with the same input length and arrival at
zero. The two-request FULL run versus that per-request isolation control:

| Request/input | KV shard FCT mean, FULL/control | KV shard FCT P99, FULL/control | TTFT, FULL/control | KV-ready, FULL/control |
|---|---:|---:|---:|---:|
| 0 / 32 tokens | 11.632 / 11.538 µs (+0.81%) | 13.443 / 12.822 µs (+4.84%) | 41.466 / 41.466 ms | 41.466 / 41.466 ms |
| 1 / 128 tokens | 15.693 / 15.552 µs (+0.90%) | 21.308 / 20.686 µs (+3.01%) | 43.051 / 43.051 ms | 43.051 / 43.051 ms |

These are 96 shard samples *within one run per condition*, not independent
request percentile estimates or repeated-run confidence intervals. The two
requests' own KV completion and TTFT did not move; the observed per-shard
differences were absorbed by the existing layerwise release/serving slack.
This is evidence that same-class P2D flows can share physical service and
slightly perturb shard FCT, but it does **not** demonstrate a useful
request-level scheduling opportunity. FlowSim's `queue_bytes` remains a
residual-fluid backlog proxy, not a physical switch queue.

### EP–EP independent-group validation update — 2026-10-11

The paragraph below in the original audit was a valid historical limitation,
but is now superseded for one bounded supported layout. The grouped topology
builder in the current dirty worktree now adds a group/lane axis for multiple
independent Decode groups and for a single Decode group with a multi-lane P/D
prefix. The generated `two_ep4_groups_full.json` has 24 serving/shadow ranks
and `[2, 2, 6]` topology coordinates; its A-only control has 12 ranks and
`[2, 2, 3]`. Both validate rank-count equality, and the group-scope tests
confirm separate collective lanes. Other non-rectangular, interleaved, or
unmatched group layouts remain unsupported and fail closed.

An integrated FlowSim EP–EP case now completes with two independent Decode
EP4 groups placed across the same two physical Decode servers and sharing
directed 200-Gbps links. Matched group-isolated comparisons show dispatch CCT
increase +6.39%, combine CCT +1.58–3.11%, TTFT unchanged, and TPOT/TBT increase
only +0.75–0.80%. This is a bounded **network capability PASS but serving
motivation NO-GO**. It supersedes the old “NOT RUN / unsupported” statements
where those described EP–EP topology feasibility; it does not change the
overall baseline gate from `PARTIALLY_VALIDATED`, because exact GateRouter
A2A, POST_PREFILL, integrated native packet feedback, and broader topology
coverage are still unvalidated. Full setup, controls, and limitations are in
[`12_EP_EP_GROUP_VALIDATION.md`](12_EP_EP_GROUP_VALIDATION.md).

The original failed EP8 attempt remains historical context only: the initial
first-group-only dimension inference returned 16 coordinates for 32 configured
ranks and correctly failed fast. It is not a result from the corrected code.

The workload is a controlled phase: request 0 (input 1/output 3) starts at
zero; request 1 (input 128/output 1) arrives at 4.302 ms, aligned to an EP
collective start observed in the corrected solo run. This is
`CONTROLLED_MODEL_DERIVED_WORKLOAD`, not a natural arrival trace. It proves
that cross-request KV/EP service overlap is representable in this FlowSim
path, but the matched network effects are small and do not establish a
motivation PASS. The previous pre-correction serving outputs are retained but
withdrawn as latency/timing evidence; see `superseded_evidence` in the
machine-readable manifest and exact commands in
[`01_REPRODUCIBILITY.md`](01_REPRODUCIBILITY.md).

### MoE communication model boundary

The serving trace's MoE network phase is currently **ALLGATHER dispatch plus
REDUCESCATTER combine**, not strict All-to-All. `_emit_moe_block()` uses
GateRouter output to derive per-rank expert-compute workload, while collective
communication sizes are formed from hidden/router-logit and hidden-payload
formulas and passed as ASTRA-Sim AG/RS inputs. The actual network-wide bytes
must be taken from collective/network event telemetry; neither `comm_size`
nor the power model's `total_ring_data()` should be misreported as the total
transmitted bytes. Thus current FlowSim and ns-3 observations do not validate
GateRouter source→expert-owner route geometry. See
[`02_THEORETICAL_CONTENTION_MODEL.md`](02_THEORETICAL_CONTENTION_MODEL.md) for
the formulas and limitations.

### Corrected native ns-3 matched replay of a complete MoE-layer pair

The first corrected packet slice contained dispatch only and is superseded as
incomplete. The authoritative packet slice contains request 1's 96 P2D shards
and request 0's complete MoE-layer communication pair: dispatch collective
1082 and combine collective 1103, 240 peer flows each. Same-server EP peers
are local and not packetized; 128 remote messages remain per collective.
Original bytes and `requested_start_ns` come from the corrected integrated
FlowSim ledger. Packet completion is recomputed, but the replay does not call
the serving scheduler.

Three matched native ns-3 replays used the same event file, one-ToR topology,
200-Gbps physical links, `CC_MODE=1` (DCQCN), FAIR, and 4,096-byte payload:

| Metric | EP-only | KV-only | FULL |
|---|---:|---:|---:|
| Dispatch network CCT (128 remote peers) | 29.262 µs | — | 31.342 µs (+7.11%) |
| Combine network CCT (128 remote peers) | 28.878 µs | — | 30.958 µs (+7.20%) |
| P2D message FCT mean | — | 25.967 µs | 26.009 µs (+0.16%) |
| P2D message FCT P99 | — | 31.139 µs | 31.139 µs (0%) |
| Shared 200-Gbps directed link 38→34 queue max | 70,244 B | 4,132 B | 121,404 B |
| ECN / PFC / packet drops | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

The queue metric is `PointToPointNetDevice::GetQueue()->GetNBytesTotal()`
sampled on enqueue/dequeue/physical-TX events in
`ns-3/scratch/common.h`; it is a packet-device TX queue, **not direct
switch-MMU or per-priority queue occupancy**. On directed link 38→34, FULL
transmitted 12,849,024 B, versus 12,693,504 B KV-only and 155,520 B EP-only.
Its queue peak increases under mixed traffic, while the global maximum
260,316-B queue on the P-side uplink is unchanged between FULL and KV-only.
No ECN/PFC/drop/CNP/rate-change event occurred at this operating point.

The FULL packet replay was repeated once. Hashes of `comm_events.csv`,
`link_summary.csv`, and `fct.txt` match exactly; each run took about 5–6 s
wall time. This is reproducible, modest **network-only** evidence. It cannot
produce or imply TTFT/TBT and is not a scheduler/policy result.

## Recovery update — 2026-10-11 worktree

**Historical snapshot warning:** the run metrics and no-overlap claims in the
following older recovery notes predate the Chakra ns→µs fix and are not current
timing evidence. They remain here to explain the defect/fix history only.

This addendum describes the current, dirty worktree and supersedes stale
"current source" statements below where noted. `HEAD` is still
`0c0839aff54ec0abb1810dc09cf3d66f06b1b078`; the FlowSim integration, topology,
and regression fixes are **uncommitted** and must not be represented as part of
that commit.

The two-request serving metrics described later in this recovery section were
collected before the handoff-wakeup fix below. Their FlowSim network ledger is
still useful for path/flow accounting, but their TBT difference is withdrawn
as serving evidence: Decode was incorrectly held behind a future-arrival
poll. The corrected matched rerun supersedes those serving metrics.

| Gate item | Current worktree evidence | Status |
|---|---|---|
| Serving ↔ FlowSim feedback | `--network-backend flowsim` starts the event-driven fluid worker; a one-request, EP16 run completed and produced request TTFT/TPOT/TBT fields. | **PASS, one-request smoke only** |
| Decode admission capacity | `add_decode()` requires the real completion time and queues at `max_num_seqs`; four targeted tests pass. | **PASS, targeted** |
| P/D pairing and FlowSim physical rank mapping | Pairing is fixed before prefill; the P2D shadow destination maps to its paired physical Decode GPU endpoint. | **PASS, targeted and one-request smoke** |
| Cross-request integrated P2D/EP overlap | After the Chakra time-unit correction, the controlled two-request FlowSim case finds nonzero overlap on three common directed links; matched serving effects are small. | **PASS, representable; no motivation pass** |
| FlowSim physical topology | Three local NVSwitch-like graphs are present; exhaustive same-server GPU-pair routes avoid NIC/ToR, while cross-server EP and P2D use 200-Gbps NIC uplinks. | **PASS, topology/unit tests** |
| FlowSim shared-path unit case | Two 1-MB unit-test flows sharing ToR→Decode-NIC complete at 90.2 µs versus 50.2 µs isolated; disjoint local traffic does not change P2D completion. This is a synthetic unit test, not a model/workload result. | **PASS, backend arithmetic only** |
| Native ns-3 network-only packet path | A bounded 336-event replay on the configured 32-logical-rank topology completed twice in 3.22/3.37 s wall time with byte-identical FCT, communication, link, and CC artifacts. Switch-MMU queue dynamics are not yet validated. | **PASS, path/completion smoke only** |
| Native ns-3 serving feedback | `KVEPReplay` invokes a no-op completion callback; the ASTRA/ns-3 integrated serving attempt has not produced a request result. | **NOT VALIDATED** |
| Exact MoE routing | The serving trace still emits AG/RS collective semantics with balanced expert routing; it is not GateRouter-derived exact A2A-P2P peer traffic. | **PARTIAL** |
| P2D granularity controls | Native trace produces per-layer P2D; no supported `POST_PREFILL` mode/CLI has been found or tested. | **PARTIAL** |
| Historical result identity | Historical result SHA is absent from Git; current edits are not committed. | **FAIL for historical binding** |

The latest FlowSim smoke used one request (`input=1`, `output=3`), Qwen3-30B-A3B,
TP2/EP16, four P instances and eight Decode DP members, one request paired to
Decode instance 4, and `FAIR`. It completed with simulated request end
7.307044176 s, TTFT 4.042694 s, TPOT 1.632175088 s, and two recorded ITL values
of 1.632175088 s. These are **single-request correctness outputs**, not a
distribution, SLO, contention result, or realistic workload characterization.
All 96 layerwise P2D shards (48 layers × 2 TP shards) totaled 98,304
model-derived bytes. The 192 EP collectives each expanded to 240 rank-pair
flows; their aggregate traffic used the current native AG/RS model. The first
EP flow was issued after P2D-ready. No same-request P2D/EP overlap was observed.

An additional two-request controlled FlowSim run completed in 19.2 s wall
time. Request 0 decoded while request 1 was in Prefill/P2D; each produced 96
model-derived P2D shards (98,304 bytes/request). Request 0 generated 46,080 EP
flow rows totaling 106,168,320 bytes. Their route sets shared the directed
ToR→D0-NIC link `30->26`, and their global active-time ranges overlapped.
However, complete per-flow interval matching found **zero** request-1 P2D /
request-0 EP interval intersections on that link. The link telemetry likewise
had no sample with both active KV and EP flows; the observed maximum 147,356
fluid-backlog bytes occurred during EP-only activity, while KV-active samples
had zero backlog. The original phase therefore is not evidence of cross-class
contention.

Two phase-targeted probes used observed EP-round times to choose request 1
arrival. Both still had zero exact flow/link overlap. With arrival 4.092426 s,
the P2D layer-12 release was 4.131944 s while the realized EP round started
4.124370 s. With arrival 4.960607680 s, the P2D layer-12 release was
5.000125680 s while the realized EP round started 4.992551680 s. Both leave
the same 7.574-ms offset: the integrated serving schedule shifts the EP
timeline along with the phase-targeted prefill arrival. The target therefore
did not survive integrated scheduling. In the later probe, request 0's first
recorded ITL also changed relative to the one-request smoke, but with no KV/EP
service overlap this delta is **unattributed** and must not be called a
network effect. No further arrival-phase tuning is authorized by this
recovery check.

## Corrected Decode handoff wakeup — 2026-10-11

The serving worker initially allowed a Decode rank's `pass <next-arrival>`
suppression to remain active after `Router.transfer_prefill_request()` made a
P2D-ready request runnable. In the fixed phase probe, request 0 became
KV-ready at 4.042694 s, but Decode ranks had been told at simulation time 0 to
sleep until request 1's arrival. This delayed the first Decode EP collective
until `request-1 arrival + 31.944 ms`; the delay matched the phase shift.
That was a frontend wakeup defect, not network contention.

The FlowSim response protocol now accepts `wake-decode <normal-response>`.
After a Prefill handoff, the frontend decorates its next response with this
marker; the worker invalidates pending Decode arrival deadlines and polls the
Decode ranks before processing the normal graph/pass/done response. This also
works when the Prefill rank immediately submits another graph. Three focused
worker protocol regression tests pass.

The exact same two-request workload/configuration was rerun after the fix:

| Request | TTFT | TPOT | TBT/ITL sequence | P2D-ready / Decode admission |
|---|---:|---:|---|---:|
| 0 (already decoding) | 4.042694 s | 1.632175088 s | [1.632175088, 1.632175088] s | 4.042694 s |
| 1 (new P2D) | 4.042694 s | 0 (one output token) | [1.632175088] s | 9.003301680 s |

Request 0's first TBT returns exactly to the one-request value; the prior
2.091131928-s TPOT / 2.550088768-s first ITL is not a network effect and must
not be cited. The corrected 69,312-row flow ledger contains 96 P2D shard flows
for request 1 (98,304 bytes) and 46,080 EP rows for request 0. Even though
their physical paths include the same D-side directed links, interval-level
intersection remains zero. The 192 request-0 collective CCT observations have
mean 13.4775 µs, P50 10.856 µs, and P95/P99 16.099 µs; these are within-run
collective samples, not independent-request tail estimates. Thus this small
case validates request lifecycle
and exposes/fixes a scheduling wake bug, but does **not** establish shared
network contention. It uses native AG/RS, balanced routing, one-token prompts,
and provides no SLO or tail-distribution evidence.

The corrected request CSV and compressed flow ledger are retained under
`research_audit/results/current_baseline_flowsim_handoff_fix.*`; the exact
command and hashes are in `01_REPRODUCIBILITY.md`.

## Bounded native ns-3 packet smoke — 2026-10-11

The replay input was extracted from the corrected two-request FlowSim ledger:
request 1's 96 model-derived layerwise P2D shards and request 0's collective
`10000303` (240 logical EP flows). Original `requested_start_ns` and byte
counts were retained. FlowSim physical endpoint IDs were translated using
the saved logical-to-physical map to the logical ASTRA ranks used by the
configured ns-3 topology. The 32-entry logical rank-to-NIC map preserves
P/D pairing and server membership.

With the configured one-ToR topology, `CC_MODE=1` (DCQCN), 4,096-byte packet
payload, and FAIR policy, ns-3 completed 336 input events in 3.22 s wall time.
It issued 96 P2D events and 128 cross-server EP events; 112 same-server EP
events were excluded as NVSwitch-local. All 224 issued events completed. The
packet event ledger reports mean shard/message completion of 20.490 us for
the 96 P2D messages and 20.711 us for the 128 cross-server EP messages; these
are network-only message samples, not request FCT, KV handoff, or EP collective
CCT. NetDevice-queue telemetry reports a 4,964-byte maximum on the
ToR→D0-NIC directed link; this is **not** a direct switch-MMU occupancy
measurement. The MMU monitor samples every 100 μs and only prints a port when
the sampled occupancy is at least 1 KB; `qlen.txt` had no such samples. Since
message service is about 20 μs, this cannot establish that the MMU queue stayed
empty between samples. Across packet event intervals, no directed link had
simultaneous KV and EP service; ECN marks, PFC pauses, and drops were all zero.
CC telemetry contains QP_START events but no CNP/rate-change event.

The same retained input was rerun in 3.37 s; `comm_events.csv`, `fct.txt`,
`link_summary.csv`, and `cc_events.csv` SHA-256 hashes matched exactly. This
validates the configured logical endpoint paths and bounded packet completion
plumbing. It does **not** validate scheduler feedback: the replay uses a no-op
message callback, and it does not generate TTFT/TPOT/TBT. The independent
physical-ID manifest topology (`minimal_1p2d_ep16_2x200g_single_tor.txt`) is
not the topology used for this smoke; it has NIC-aggregation nodes declared
as hosts and fails route lookup if used as though those IDs were logical ASTRA
rank endpoints. Do not substitute that file for the configured logical-rank
topology.

The corrected FlowSim ledger was also independently interval-swept by
directed link. It contains 192 P2D rows (96 per request, 196,608 bytes total)
and 69,120 EP rows (159,252,480 bytes total). The two traffic classes' global
time ranges overlap, but only five directed links are common to both route
sets and all five have zero service-interval overlap. The closest KV/EP pair
on link `30->26` is separated by 131.879 us. Thus shared path and overlapping
global activity windows alone did not create contemporaneous link service.

Accordingly, the baseline remains `PARTIALLY_VALIDATED`, not `BASELINE_PASS`:
network-only packet path/message completion is validated, but switch-MMU queue
dynamics and integrated ns-3 completion feedback are not; integrated
cross-request KV/EP link overlap is not demonstrated; exact routed A2A and
`POST_PREFILL` are unsupported in the selected serving path; and historical
results are not all bound to an immutable source version. No theoretical
motivation matrix or scheduler experiment has been started.

## Initial read-only audit at HEAD (historical snapshot)

The section below records what was true at the initial clean `HEAD` audit,
before the current worktree recovery. It is retained for audit history; do not
read it as a description of the current modified worktree.

This audit is against the checked-out source, not the historical experiment
reports. The audited source snapshot is `main`, Git `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`
(`v1.1.0-123-g0c0839a`, README describes LLMServingSim 2.0). The worktree
contains the audit fixes listed in [`01_CODE_FIXES.md`](01_CODE_FIXES.md).

## Gate summary

| Area | Finding | Status |
|---|---|---|
| FlowSim serving entry point | `flowsim_worker.py` exists, but the current `serving` CLI accepts only `analytical` and `ns3`; the PD/EP research flags are absent and no source path launches the worker from the serving loop. | **FAIL** for integrated FlowSim on this HEAD |
| Decode capacity on P/D handoff | `add_decode()` previously bypassed `max_num_seqs`. Fixed and covered by unit tests. | **PASS, targeted** |
| ASTRA topology rank cardinality | One saved P/D+MoE config resolves to 4 serving ranks but a 3-rank topology. A fail-fast check and regression tests were added. | **PASS, targeted guard; affected config invalid** |
| Actual P2D receiver | Current graph generation leaves `pd_decode_offset` unset, so the bundled Chakra converter emits synthetic/shadow receive ranks. It does not connect P2D receive events to the real Decode scheduler ranks. | **FAIL** for target data-path fidelity |
| Qwen3 EP communication form | Native serving trace emits EP-scoped `ALLGATHER` dispatch and `REDUCESCATTER` combine, not exact routed A2A. | **PARTIAL**; exact A2A is not on this current CLI path |
| Saved 1P2D / EP16 / shared-400G fixture | A P/D role axis has now been added in the worktree: logical dimensions resolve to `[2, 8, 2]` (32 ranks), and Decode EP excludes the role axis. This only repairs logical cardinality. The native topology has 24 GPU endpoints plus NIC/ToR nodes, there is no logical→physical rank map in the serving path, and the pairing JSON remains unused. | **PARTIAL**; not executable as a validated physical data path |
| Historical result provenance | A report cites commit `a4053bc1161872420e1e0607cb3409ef659b828e`, which is absent from this checkout's Git object database. Existing reports/configs/results are not consistently bound to the current HEAD. | **FAIL** as authoritative evidence |
| End-to-end smoke | One small P/D+EP2 analytical serving request completed, but its P2D endpoint was shadow rank 2/3 rather than Decode rank 4/5. It validates execution only, not the target network path or contention. | **PARTIAL** |
| P/D role-axis smoke | One request completed with the saved 1P2D/EP16 logical shape `[2,8,2]`; the Decode DP/EP graph was emitted on ranks 16–31 and the ASTRA analytical run exited normally. It validates current logical group convergence, not physical P2D delivery or network contention. | **PASS, analytical/control only** |

## P0-A — FlowSim path and completion feedback

The current `serving/__main__.py` parser declares:

```text
--network-backend {analytical,ns3}
```

It does not declare `flowsim`, `--pd-kv-transfer-mode`,
`--ep-collective-semantics`, or `--kv-ep-network-policy`. Several experiment
wrappers pass these flags to `python -m serving`, so those commands do not
describe this checkout. A direct probe of `--network-backend flowsim` is
rejected by argparse.

`serving/core/flowsim_worker.py` implements a separate interactive worker and
fluid-flow backend. However, `serving/__main__.py` creates only the ASTRA
analytical or native ns-3 subprocess; no serving source imports or launches
`flowsim_worker`. The worker's `R <rank> <iteration> <time> 0` response is
also not the ASTRA iteration line parsed by `serving/core/controller.py`.
Therefore this worker is not an integrated scheduler/network completion path
on the audited HEAD. Historical integrated-FlowSim TTFT/TBT results cannot be
reproduced from this source snapshot without restoring the missing integration.

The `--network-backend ns3` option is present, but this audit did not run a
packet-level request experiment: the P2D receiver mapping described below is
not the real Decode rank, so such a run would not pass the target correctness
gate.

## P0-B — Decode admission and serving timestamps

Before the worktree fix, `Scheduler.add_decode()` inserted every P2D-ready
request directly into `running` without checking `max_num_seqs`. A saved test
already expected a `completion_time_ns` argument and failed against the
unmodified implementation. The fix now:

1. requires the actual simulator completion timestamp (it no longer substitutes
   request arrival for KV-ready time);
2. records P2D-ready time and the Decode population/capacity at handoff;
3. reserves the received KV state but queues the request when the Decode
   sequence limit is full;
4. admits queued work through the regular waiting-queue scheduling path and
   records its capacity wait separately;
5. exports those fields in request CSV without changing the existing leading
   columns.

Four focused Decode-admission tests pass, including no-timestamp rejection,
full-capacity queuing, admission after a slot opens, under-capacity fast path,
and ready-time ordering. A separate integrated overload case that holds a
Decode slot across P2D completion has **not** been demonstrated; the small
serving smoke below had zero Decode capacity wait.

## P0-C — version and historical result binding

The current `origin` URL is `https://github.com/LPMing/llmserve.git`; the local
`origin/main` ref equals the checked-out HEAD. The repo includes release tags
through `v1.1.0`, while HEAD is 123 commits after that tag. ASTRA-Sim/ns-3
sources are vendored in this monorepo rather than represented as Git submodules
(there are no gitlink entries in the tree).

At least one consolidated historical audit claims a different upstream remote,
the missing `a4053bc...` SHA, actual Decode P2D receivers, and integrated
FlowSim. Those claims conflict with the files at the current HEAD. Treat the
old reports and result tables as `UNVERIFIED_HISTORICAL` unless each run can be
rebound to its exact source, config, workload, backend, invocation, and output.
See [`01_REPRODUCIBILITY.md`](01_REPRODUCIBILITY.md).

## Serving DAG and P2D/EP semantics observed in source

The current request control path schedules Prefill, waits for the Prefill
graph completion, calls `Router.transfer_prefill_request()`, and then adds the
request to a Decode scheduler. The one-request smoke recorded
`p2d_kv_ready_time_ns == decode_admit_time_ns == 16,766,583 ns`; this supports
the ordering in this narrow run. It does **not** show that a real Decode rank
received the bytes.

The Chakra converter bundled in `astra-sim/extern/graph_frontend/chakra`
already has optional `pd_decode_offset`, `pd_decode_tp`, and `pd_decode_pp`
arguments and a shard-aware destination mapper. But
`serving/core/graph_generator.py` constructs `LLMConverter` with only the
legacy positional arguments and supplies none of those P/D receiver values.
The converter therefore takes its documented legacy path and pairs each
Prefill sender with a shadow rank at `sender_rank + num_npus`.

For the reproduced Qwen3 TP2/EP2 smoke, Chakra ET inspection found:

- rank 0 sends 48 layer-sized KV messages of 8,192 bytes each to shadow rank 2;
- rank 1 sends 48 messages of 8,192 bytes each to shadow rank 3;
- total model-derived KV bytes in that short request: 786,432 bytes;
- actual Decode MoE ranks are 4 and 5;
- each Decode rank's trace contains per-MoE-layer `ALLGATHER` dispatch (4,352
  bytes in the inspected row) and `REDUCESCATTER` combine (4,096 bytes in the
  inspected row), plus other collectives such as TP all-reduce.

Thus the generated P2D receiver is not the actual Decode scheduler rank. The
small `two_prefill_6_rank_shared_spine.txt` layout also places those shadow
rank endpoints separately from the actual Decode EP ranks, so it cannot be
used as proof that P2D and EP contend at the intended Decode-side NIC/cut.

In the current native Qwen3 trace generator, MoE dispatch/combine are
represented by AG/RS collectives. The code comments describe routing-derived
expert work, but the native ASTRA communication operation is not a literal
variable-sized `ALLTOALL` peer matrix. This is a semantics limit for the new
fine-grained scheduling question, not evidence that a strict A2A experiment
passed.

## Saved 1P2D / EP16 shared-NIC fixture audit

The artifacts generated by
[`generate_minimal_1p2d.py`](../experiments/pd_kv_ep/configs/generate_minimal_1p2d.py)
are **not yet runnable as an authoritative physical serving configuration**.
The generator creates eight TP1 Prefill instances and eight TP2 Decode
instances split across two hosts; all eight Decode instances share
`dp_group="decode_ep"` with `ep_size=16`. Resolving this through the current
worktree gives the following logical layout after the P/D role-axis fix:

| Quantity | Current result |
|---|---:|
| Physical GPU ranks stated by manifest/rank map | 24 (8 P + 16 D) |
| Decode DP-group size | 8 TP2 instances |
| Resolved total EP degree | 16 |
| Resolved local EP per Decode instance | 2 |
| Resolved Decode EP dimension | `[true, true]` |
| Inferred ASTRA dimensions | `[2, 8, 2]`, product 32 |
| Frontend ranks with legacy Prefill shadow receivers | 32 |
| Decode EP dimension | `[true, true, false]` |

The role-axis change is in the uncommitted worktree and is covered by a
targeted builder test. It gives the Prefill/shadow ranks one contiguous role
plane and the Decode DP/EP members the other; the EP collective is scoped over
TP×DP and excludes the role axis. The rank-count guard now passes this fixture
at the *logical ASTRA dimension* level. This has **not** yet been exercised by
ASTRA-Sim's collective runtime or by a serving run, so it is a structural
fix, not proof of collective correctness.

The physical network graph still does not match the logical rank namespace.
It has 24 GPU access endpoints, six NIC
uplinks at 200 Gbps to one ToR, and 7.2-Tbps GPU-to-NIC attachment links. It is
a plausible *network graph* for four GPUs sharing each NIC, but its node IDs
are physical GPU IDs 0–23 plus NIC/switch IDs 24–30. The serving frontend emits
32 logical ranks (including eight P2D shadow ranks); treating those logical IDs
as physical endpoints would alias logical ranks 24–30 with NIC/switch nodes
and leave logical rank 31 outside the declared topology. The saved
`rank_to_nic.csv` has 24 physical rows, not the required 32-entry logical to
physical mapping. The separate `minimal_1p2d_ep16_pairing.json` contains eight
P→D rank pairs, but no code in the current router/graph-generator path loads
it. The pairing is therefore not enforced, and request routing still chooses a
Decode scheduler only after Prefill completion.

The fixture's topology-rate statement also needs careful interpretation: the
200-Gbps capacity is on each NIC-to-ToR uplink; the 7.2-Tbps attachment links
are not NIC uplinks and do not make an individual NIC faster than 200 Gbps.
This is suitable for a shared-NIC resource graph only after the frontend
logical ranks are mapped to physical GPU/NIC endpoints, P/D pairing is fixed
before P2D graph generation, and the selected Decode scheduler matches that
pairing.

## Endpoint and network model limits

The serving frontend addresses ASTRA network endpoints by NPU/rank. The
current cluster builder does not expose a verified mapping of eight GPU ranks
onto two shared physical 200-Gbps NICs, nor a two-rail hashing/striping policy.
Do not interpret a per-rank ASTRA endpoint as a shared server NIC without an
explicit mapping and conservation tests.

The native ns-3 backend is present and selectable, but packet queue/ECN/PFC or
DCQCN results are not established by the analytical smoke. FlowSim fluid
backlog, if used via a standalone replay tool, is not packet-buffer occupancy.

## Minimal run and its limits

Command and checksums are preserved in `01_REPRODUCIBILITY.md`; output is
[`current_head_pd_ep2_smoke_final.csv`](results/current_head_pd_ep2_smoke_final.csv).

| Metric | Value | Interpretation |
|---|---:|---|
| Model / config | Qwen3-30B-A3B-Instruct-2507; 1 Prefill TP1 + 1 Decode TP2/EP2 | Small serving execution check |
| Workload | 1 request; input 8, output 1 | Not a contention sample |
| Backend | ASTRA analytical | Not packet-level |
| Simulation clock | 24.682 ms | Simulated time, not wall time |
| Wall time reported by simulator | 0.482 s | Runtime of this one-request smoke |
| TTFT | 16.767 ms | Valid for this simulator run only; not a model-quality claim |
| TPOT | 0 ms | No post-first-token interval for one output token; not an optimization result |
| Decode capacity wait | 0 ns | Does not validate overloaded admission |
| P2D-ready == Decode admit | 16.767 ms | Control barrier ordering; destination rank is shadow, so data-path validity remains partial |

## P/D role-axis / EP16 analytical smoke

After adding the size-2 role axis, the saved configuration was run once with
one request, input 8/output 1, and the ASTRA analytical backend. The run
completed in 1.274 s reported simulator wall time (29.656 ms simulated clock).
The Decode DP-group batch emitted ET files for all 16 Decode EP ranks (16–31)
and exited without an unresolved collective. The request was admitted to
Decode instance 8 with:

```text
p2d_kv_ready_time_ns = 22,628,004
decode_admit_time_ns  = 22,628,004
TTFT                  = 22.628 ms
```

This is a one-request logical correctness smoke only. Output length 1 gives no
post-first-token TPOT sample. The network was ASTRA's analytical
`FullyConnected × 3` with 50 GB/s (=400 Gbps) per modeled dimension; it did
**not** load the generated 200-Gbps NIC/ToR topology. The P2D receive is still a
shadow-rank graph node, so this is not evidence of a physical Decode receiver,
shared-NIC contention, or a serving optimization opportunity.

## Gate decision at the initial clean-HEAD audit (historical snapshot)

`PARTIALLY_VALIDATED`. Targeted serving execution and Decode-capacity logic are
testable. The P/D role-axis fix makes logical cardinality consistent for the
saved DP/EP fixture, but collective execution has not been verified. The
experiment path needed for the paper question is not recovered: FlowSim is not
integrated at the serving entry point, the physical topology has no consumed
logical-rank map, and model-generated P2D sends do not target the selected
Decode scheduler rank. The mission's theoretical/motivation stages are **not
run** until the physical rank mapping, P2D pairing/receiver, and FlowSim
execution path are wired and regression-tested. Do not use the saved fixture's
prior or manifest-level results as current-HEAD evidence.

## Authoritative current gate decision — corrected worktree

The current worktree now passes focused request lifecycle, Decode capacity,
rank mapping, time-unit conversion, and group-collective barrier checks (28
focused tests at that earlier checkpoint; the final focused suite now has 36
passing tests across ten scripts. A corrected integrated two-request run has actual cross-class
service overlap on three directed FlowSim links, and a matched native ns-3
replay of a complete dispatch+combine MoE-layer pair reproduces a modest
network-side EP CCT / queue increase. The integrated serving effect remains
negligible at this point. The ns-3 replay's callback is a no-op; it cannot
produce serving metrics. A two-independent-EP4-group FlowSim case now shares
directed links and changes CCT by 1.6–6.4%, but changes TPOT/TBT by <1% and
leaves TTFT unchanged; see the EP–EP validation report.

**Current status remains `PARTIALLY_VALIDATED`.** Outstanding limitations
include native EP AG/RS rather than exact GateRouter A2A-P2P, no supported
POST_PREFILL mode, no packet-to-serving completion feedback, only one validated
rectangular independent Decode EP-group layout, a small controlled workload
set without repeated seeds, and no immutable committed source SHA.
The new experiments are bounded mechanism validation, not a policy sweep,
oracle, scheduler, natural-trace result, or motivation PASS. The machine-readable source/config/
workload/backend/output binding is
[`01_baseline_run_manifest.json`](results/01_baseline_run_manifest.json),
generated by [`write_baseline_manifest.py`](scripts/write_baseline_manifest.py).

The old retained two-request ledger from before the unit fix was independently
checked with
[`validate_baseline_barriers.py`](scripts/validate_baseline_barriers.py): each
request has 96 P2D shards (98,304 B), and its last shard finishes 300,029,759
ns before the recorded KV-ready/Decode-admission timestamp. For all 288 EP
collectives, the recorded collective end equals the maximum completion time
of the corresponding 240 peer-flow rows. The validator also reconstructs
five shared directed links and confirms zero half-open KV/EP service-interval
intersection on all five. This is barrier-accounting validation on this small
run; its one-token prompts and zero overlap do not validate a contention
mechanism. This older ledger's timing/overlap result is withdrawn. The
corrected ledger is checked explicitly in the new reproducibility section and
the current manifest.

## Authoritative update — Decode completion wakeup

A second scheduler-control defect was found in addition to the P2D handoff
wakeup bug. After a Decode graph completed and advanced request/token state,
the FlowSim worker could retain a stale `pass <next-arrival>` suppression on
the group's start rank. This delayed the next decode iteration until an
unrelated request arrival. A spurious multi-ms TBT gap also appeared in the
`KV_ISOLATED` control, proving that it was not network contention.

The serving loop now detects scheduler-relevant changes around
`scheduler.add_done()` (token progress, finish, or inflight-count change) and
returns a state-changing response. The FlowSim worker invalidates the stale
future-arrival suppression and polls the Decode group again. The focused
`test_flowsim_decode_completion_wakeup.py` regression suite covers these
transitions. After the fix, the D4-only token cadence matches the earlier
corrected cadence, and the D4+late-8192-token-K run has no spurious 9.13-ms
Decode interval.

The matched post-fix D4+K8192 result is:

| Metric | FAIR | KV-isolated counterfactual | Delta |
|---|---:|---:|---:|
| EP CCT mean | 13.495635 µs | 13.477500 µs | +0.134% |
| EP CCT P99 | 16.273 µs | 16.099 µs | +1.08% |
| Decode TPOT mean | ≈2.339182 ms | 2.339088 ms | <0.01% |
| New request KV-ready | 308.724596 ms | 308.724596 ms | 0 at saved precision |
| New request TTFT | 295.328 ms | 295.328 ms | 0 at saved precision |

There are 672 within-run collective samples, not 672 independent requests.
The D4 Decode traffic and K request have same-directed-link time overlap;
FlowSim's queue field is analytical residual fluid, not physical switch
occupancy. `KV_ISOLATED` gives the KV class independent virtual copies of
directed-link capacity and is a causal counterfactual, not a deployable
policy. The network effect exists, but its serving-barrier exposure is
negligible at this tested point.

**Gate remains `PARTIALLY_VALIDATED`.** This repair removes a false serving
latency artifact. It does not add exact routed A2A, a second independent
Decode EP group, POST_PREFILL, or packet-to-serving completion feedback.
