# Serving control and completion-feedback audit

## Current control path

| Component | Verified behavior | Relevance |
|---|---|---|
| `serving/core/scheduler.py::add_request` | Inserts requests into a time-sorted waiting queue. The scheduler does choose which ready work enters a batch. | A legal Serving control point exists in principle. No alternate-ready-work choice was exercised in the current four-request packet fixture. |
| `serving/core/trace_generator.py` | Emits model/profile-driven graph rows; LAYERWISE P2D KV amount is attached to per-layer QKV projection rows. | Compute/profile events can define KV release opportunities; this does not by itself create a runtime feedback policy. |
| `serving/__main__.py` + controller | Receives ASTRA iteration completion and simulation cycle, calls scheduler completion accounting, then routes Prefill-complete requests to Decode with `completion_time_ns`. | Serving can observe graph/iteration completion time in the integrated ASTRA path. |
| `scheduler.add_decode(req, completion_time_ns)` | Stores P2D-ready time and Decode eligibility; capacity waiting is tracked separately. | Correct place to distinguish KV-ready from Decode capacity admission. |
| Native ASTRA/ns-3 backend `sim_send` | Calls `send_flow` with an ASTRA completion callback; QP completion is delivered into the ASTRA message/graph path. | Packet completion can affect a graph's simulated completion when using the integrated backend. |
| `KVEPReplay.cc` fixed replay | Schedules every event at its ledger timestamp and calls `send_flow(..., noop_message_handler, ...)`. | This study's packet replays cannot feed completion, ECN, CNP, QP rate, or queue state back to Serving. |
| Integrated FlowSim | Persistent fluid-flow engine has event-driven flow completion and exact fluid completion callbacks; telemetry is analytical residual backlog. | Useful for rapid algorithm experiments, but cannot validate packet ECN/CNP/DCQCN/PFC behavior. |

## Correctness boundary

The integrated `network-backend=ns3` executable is a different path from the
fixed `KVEPReplay` tool. Source inspection shows native `sim_send` → RDMA QP →
`qp_finish` → ASTRA callback, and Python processes ASTRA iteration completion
before calling `scheduler.add_done`. The current task did **not** execute that
integrated path on this custom 4P1D topology, so runtime end-to-end correctness
is **NOT_RUN**, not PASS.

Even in the integrated path, Python does not currently receive a live stream of
switch queue occupancy, ECN marks, CNP timing, or per-QP DCQCN rate history as
scheduler inputs. It can see the resulting graph/iteration completion clock.
No congestion-feedback serving policy or packet telemetry IPC was implemented.

## Why no Serving experiment was launched

The most representative executed release ledger is LAYERWISE and uses actual
profile-domain compute offsets. Under both CC0 and CC1, all required KV shards
complete before the profiled Prefill compute endpoint. The maximum possible
network wait exposed after that endpoint is therefore 0ms for this ledger.
Also, the fixture has exactly one active request per Prefill instance and no
second ready work item to switch to; delaying/reordering the current work has no
identified Serving-side benefit. A fixed network-only pacing baseline already
captures the mean-ready ordering headroom for the simultaneous post-prefill
case.

The explicit end-to-end CSV consequently records TTFT, TBT, TPOT, SLO, and
request completion as blank/NOT_RUN. No network-only number is relabeled as a
Serving metric.
