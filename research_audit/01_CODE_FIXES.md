# 01 — Baseline code fixes

## Current-worktree update — grouped topology and independent Decode groups

`serving/core/config_builder.py::_compute_network_dims()` previously used the
first Decode `dp_group` to infer a single lane and could not represent a
multi-lane Prefill/shadow prefix paired with multiple independent Decode
collectives. The grouped-topology path now handles rectangular group-major
layouts and rejects unsupported/interleaved layouts before simulation. A
follow-up test caught the single-group variant too: two Prefill TP2 instances
plus one EP4 group configure 12 serving/shadow ranks, so their topology must
be `[2, 2, 3]`, not `[2, 2, 2]`. The two-group run is `[2, 2, 6]`.

The new regression is
`test_multiple_prefill_lanes_plus_one_ep_group_keep_all_ranks` in
[`test_config_topology_rank_count.py`](../experiments/pd_kv_ep/scripts/test_config_topology_rank_count.py).
The generated full and A-only configurations passed integrated FlowSim and
kept the Decode groups as separate four-participant collectives. This is a
bounded topology-support fix, not a scheduler feature. Ten focused test
scripts now pass 36 tests; full repository tests were not run. See
[`12_EP_EP_GROUP_VALIDATION.md`](12_EP_EP_GROUP_VALIDATION.md) for the matched
serving results and limitations.

The early sections below preserve the initial clean-HEAD audit and recovery
history. The authoritative current source state is the uncommitted worktree
described by [`01_baseline_run_manifest.json`](results/01_baseline_run_manifest.json).
Refresh that manifest after any code, test, config, workload, or artifact
change; do not associate the audit results with `HEAD` alone.

All changes are currently uncommitted and are limited to audit/correctness
work. They are not a scheduling-policy implementation and do not validate a
contention claim.

## Fix 1 — P/D Decode sequence-capacity enforcement

Files:

- [`scheduler.py`](../serving/core/scheduler.py)
- [`request.py`](../serving/core/request.py)
- [`router.py`](../serving/core/router.py)
- [`__main__.py`](../serving/__main__.py)
- [`test_pd_decode_capacity_admission.py`](../experiments/pd_kv_ep/scripts/test_pd_decode_capacity_admission.py)

`Router.transfer_prefill_request()` now passes the actual frontend completion
clock to `Scheduler.add_decode()`. The scheduler rejects missing/invalid
completion times rather than fabricating KV-ready time from request arrival.
When `len(running) >= max_num_seqs`, it retains the received KV allocation and
places the request in the Decode waiting queue. A freed slot admits it through
the standard scheduling path. Separate request fields record P2D-ready time,
Decode admission, capacity-queue entry/wait, active population at handoff, and
the configured limit; these are appended to the per-request CSV schema.

Verification:

```text
experiments/pd_kv_ep/scripts/test_pd_decode_capacity_admission.py
4 tests: PASS
```

The test covers missing completion time, queueing at a full cap, later
admission and wait accounting, under-capacity fast path, and ready-time order.
The integrated one-request smoke had no capacity wait; no overloaded
end-to-end wait result is claimed.

## Fix 2 — ASTRA topology rank-count fail-fast

Files:

- [`config_builder.py`](../serving/core/config_builder.py)
- [`test_config_topology_rank_count.py`](../experiments/pd_kv_ep/scripts/test_config_topology_rank_count.py)

The builder now checks that the product of its uniform ASTRA topology
dimensions equals the number of ranks that the serving frontend/Chakra will
address (including the legacy extra P/D shadow ranks). A mismatch raises a
descriptive `ValueError` before network config generation and avoids silent
missing/phantom ranks or an opaque backend hang.

Concrete invalid layout found:

```text
small_pd_moe_ep.json
Prefill: 1 rank -> 2 including shadow
Decode: 2 ranks
configured ranks: 4
_compute_network_dims: [1, 3]
topology product: 3
```

The fix deliberately does **not** invent a heterogeneous topology. It rejects
layouts the current topology builder cannot represent faithfully.

The first version of this guard exposed a second issue: P/D clusters with a
Decode DP/EP group need a distinct role dimension so the Prefill/shadow rank
plane is counted without joining Decode collectives. The builder now adds a
final size-2 P/D role axis and scopes Decode TP/EP masks to exclude it. This
is a structural topology fix; ASTRA-Sim's runtime collective membership still
needs an execution test.

Verification:

```text
experiments/pd_kv_ep/scripts/test_config_topology_rank_count.py
4 tests: PASS
```

Tests cover a valid equal-TP P/D layout, the 4-vs-3 mismatch, P/D role-axis
collective scope, and the saved 1P2D/EP16 fixture's 32 logical coordinates.

## Checks run

- Python `py_compile` on modified serving modules and these tests: PASS.
- `git diff --check`: PASS.
- Decode admission unit tests: 4/4 PASS.
- Topology-rank tests: 3/3 PASS.

## Fix 4 — Convert serving trace compute time to Chakra microseconds

Files:

- [`trace_generator.py`](../serving/core/trace_generator.py)
- [`test_trace_time_units.py`](../experiments/pd_kv_ep/scripts/test_trace_time_units.py)

The profiler stores `time_us`; `_read_category_csv()` converts it to internal
`latency_ns`. Trace rows therefore correctly carry compute durations in ns.
The Chakra LLM converter, however, parses the row's `comp_time` directly into
`Node.duration_micros`. Previously `indexed_cols()` forwarded the ns integer
unchanged, making every compute node 1000× too long. `indexed_cols()` now
converts ns to ceil-rounded µs at the adapter boundary and keeps a minimum
duration of 1 µs. Marker rows such as `EXPERT` are unchanged.

Verification:

```text
test_trace_time_units.py: 2/2 PASS
all nine focused regression scripts: 28/28 PASS
```

Corrected integrated reruns:

- One Qwen3-30B-A3B request (`input=1`, `output=3`), TP2/EP16, mapped
  1P2D topology: TTFT 4.266 ms, TPOT 2.339088 ms, ITLs 2.339149/2.339088 ms.
- Controlled cross-request case (`input=1/output=3` Decode background plus
  `input=128/output=1` P2D request at 4.302 ms): same directed-link service
  overlap is present. Against a matched KV-only control, KV-shard mean/P99
  FCT rises 3.88%/3.17%; request handoff and TTFT do not change. Against the
  matched EP-only Decode request, EP CCT P99 rises 1.08%, while TPOT rises
  about 0.0013%.

This unit correction changes simulated release/finish timestamps throughout
the Serving DAG. Integrated latency, overlap, or packet-replay timing results
from runs using the old adapter are invalidated; they must not be rescued by
reinterpreting their seconds/milliseconds. Old bytes and endpoint records can
be reused only after independent semantic validation. The corrected results
are dirty-worktree evidence, not a committed release.

The corrected ns-3 replay additionally checks the network-only manifestation
of this controlled overlap. It uses the full dispatch/combine pair for one
MoE layer and matched FULL/EP_ONLY/KV_ONLY event schedules. The EP network CCT
increases about 7.1–7.2%; KV message FCT mean increases about 0.16% and P99 is
unchanged. The repeated FULL packet run is byte-for-byte deterministic for
the saved communication, link-summary, and FCT files. It remains a packet
replay without serving feedback; no TTFT/TBT is inferred from it.

## Follow-up fixture check (audit only)

The generated `minimal_1p2d_ep16_shared_400g.json` was resolved with the same
`_resolve_dp_groups()` / `_compute_network_dims()` helpers used by the cluster
builder. The new role axis changes its logical dimensions from `[2, 8]` to
`[2, 8, 2]`, matching 32 legacy frontend ranks; the guard and unit test now
pass. The manifest still describes only 24 physical GPUs, and the separate
rank-to-NIC and pairing artifacts remain unconsumed. No performance run was
started. This is a logical topology-shape repair, not physical-path
validation.

## Gaps at the initial audit (some are superseded by the recovery update)

1. `flowsim_worker.py` is not launched by the current serving loop and its
   protocol is not the ASTRA `Controller` protocol.
2. Serving graph generation does not pass the bundled Chakra converter's
   explicit actual-Decode receiver arguments.
3. P/D pairing is selected after Prefill completion, while target-rank
   selection must be available when the Prefill communication graph is built.
4. There is no validated shared-GPU-to-multi-NIC resource model on this path.
5. Current native Qwen3 MoE communication uses AG/RS rather than exact routed
   peer flows.

The shared-NIC fixture still requires a logical-rank→physical-GPU/NIC map and
an enforced P/D pairing. The role-axis change defines a candidate ASTRA group
shape, but ASTRA runtime collective execution and the mapped physical path have
not been demonstrated. It is not safe to infer these mappings from the
manifest alone.

These are architecture/semantics gaps, not small fixes that can safely be
papered over by changing CLI flags. No FlowSim integration or scheduler
algorithm was attempted in this gate.

## Recovery update — 2026-10-11

The previous paragraph is an initial-audit snapshot. The following additional
uncommitted changes were made after it:

1. **FlowSim serving integration and provenance.** The serving CLI now selects
   an interactive FlowSim worker; the worker's completion clock is returned to
   the serving loop. P2D/EP events carry request, batch, layer, collective and
   rank provenance. P2D→Decode pairing is fixed before prefill and the
   FlowSim rank map resolves each P2D shadow receiver to its paired physical
   Decode GPU endpoint.
2. **Group-wide Decode collective assembly.** Collective keys include scope
   and occurrence; all DP×TP member graphs are submitted together. Graph
   ownership is recovered from any local TP rank rather than assuming the
   instance's first rank owns the graph. This was required for recurrent
   Decode collectives to finish.
3. **Physical FlowSim local/scale-out separation.** The old ns-3 topology
   fixture is unchanged. A separate FlowSim topology adds one NVSwitch-like
   local fabric per server and retains six distinct 200-Gbps NIC uplinks.
   Same-server pair routes are tested exhaustively; cross-server paths remain
   ToR-routed. The local fabric is a nonblocking fluid abstraction, not a
   packet-accurate NVSwitch model.
4. **Topology count validation.** The parser now rejects a topology whose
   declared switch or physical-link count disagrees with its records.
5. **ns-3 configuration selection.** The packet backend now consumes the
   experiment's `ns3_topology` and `ns3_config_template`, routes all output
   files to the run directory, and generates logical dimensions from the
   actual cluster rank shape. This fixture selects the explicit DCQCN template
   (`CC_MODE 1`, 4096-byte payload); it does not change the global ns-3
   default. Unit tests pass, but the one-request packet run did not produce a
   completed serving result, so this is configuration repair—not packet
   backend validation.

Current verification: **23 focused tests PASS**. One one-request FlowSim run
completed with valid raw TTFT/TPOT/ITL fields. No multi-request contention run,
packet-level serving completion, POST_PREFILL mode, exact GateRouter A2A, or
SLO distribution is claimed. All changes remain uncommitted.

## Fix 3 — Wake Decode ranks on P2D-ready handoff

Files:

- [`__main__.py`](../serving/__main__.py)
- [`flowsim_worker.py`](../serving/core/flowsim_worker.py)
- [`test_flowsim_decode_handoff_wakeup.py`](../experiments/pd_kv_ep/scripts/test_flowsim_decode_handoff_wakeup.py)

The two-request debug trace showed Decode ranks had accepted `pass
<next-arrival>` while no Decode request was ready. When Prefill later called
`transfer_prefill_request()`, the scheduler became runnable but the FlowSim
worker did not invalidate those future-arrival deadlines. The Decode EP stream
therefore resumed only at the unrelated next request arrival. The first EP
collective shifted by exactly the arrival shift while its CCT remained
unchanged, producing a false TBT difference.

The frontend now prefixes its next FlowSim worker response after a P2D handoff
with `wake-decode`; the worker first invalidates/wakes idle Decode ranks, then
processes the original response unchanged. This supports a Prefill graph, pass,
or done response and avoids requiring an extra frontend round trip. Three
protocol tests cover pass/done, a simultaneous graph submission, and avoiding
a duplicate wake for `pass -1`.

Verification:

- protocol regression: 3/3 PASS;
- all 8 focused test scripts: 26/26 PASS;
- exact two-request integrated FlowSim workload rerun: exit 0, 21.465 s wall;
- corrected request 0 TBTs return to `[1.632175088, 1.632175088]` s;
- full class-filtered ledger: 69,312 rows, compressed and retained;
- same-directed-link KV/EP interval intersection remains zero.

This fix restores the FlowSim event-wakeup path; it does not create evidence of
KV/EP network contention or validate ns-3 packet feedback.

## Bounded packet replay follow-up — 2026-10-11

A separate `KVEPReplay` smoke now completes on the configured ns-3 logical-rank
topology and produces deterministic packet FCT/path/link/queue telemetry.
This is not the serving-integrated ASTRA/ns-3 path: `KVEPReplay` supplies a
no-op completion callback, so its packet completions never advance a serving
scheduler. The run and its limitations are recorded in
[`01_BASELINE_AUDIT.md`](01_BASELINE_AUDIT.md) and
[`01_REPRODUCIBILITY.md`](01_REPRODUCIBILITY.md).

## Fix 5 — Wake a Decode group after graph completion changes runnable state

Files:

- [`__main__.py`](../serving/__main__.py)
- [`test_flowsim_decode_completion_wakeup.py`](../experiments/pd_kv_ep/scripts/test_flowsim_decode_completion_wakeup.py)

The interactive FlowSim worker can suppress a Decode start rank until the
next request-arrival timestamp when the scheduler reports no runnable work.
Previously, a subsequent Decode graph completion could make an existing
request runnable without clearing that suppression. The group then slept
until an unrelated arrival. This is a control-plane event-loop bug that
corrupts TBT even in a `KV_ISOLATED` run.

The frontend now compares scheduler-relevant state immediately before and
after `scheduler.add_done()`. Token progress, newly finished requests, or a
reduced inflight count causes a `pass -1` state-change response. The worker
reopens the Decode ranks and processes the next scheduling iteration.

Verification:

- `test_flowsim_decode_completion_wakeup.py`: 4/4 PASS;
- post-fix D4-only workload matches the prior corrected token cadence;
- matched D4+late-K FAIR / KV-isolated runs no longer contain the false
  9.13-ms interval; their serving metrics agree to below 0.01% for Decode
  TPOT, while the measured EP CCT P99 delta remains only +1.08%.

This fix corrects event-loop behavior; it is not a network optimization and
does not upgrade the baseline gate to PASS.

## Historical verification snapshot before timing-unit correction — 2026-10-11

The eight focused scripts were rerun from the recorded Python 3.10 environment:

| Test | Result |
|---|---:|
| `test_pd_decode_capacity_admission.py` | 4 PASS |
| `test_config_topology_rank_count.py` | 4 PASS |
| `test_flowsim_collective_scope.py` | 4 PASS |
| `test_flowsim_decode_handoff_wakeup.py` | 3 PASS |
| `test_flowsim_group_queue_ownership.py` | 3 PASS |
| `test_flowsim_rank_mapping.py` | 6 PASS |
| `test_ns3_config_topology_selection.py` | 1 PASS |
| `test_pd_request_pairing.py` | 1 PASS |
| **Total** | **26 PASS** |

Command template:

```bash
env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  /home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/test_<name>.py
```

`git diff --check` also passes. These are focused regression tests, not a
complete project test suite or a proof of packet-to-serving integration.
