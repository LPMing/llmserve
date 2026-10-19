# Runtime signal observability

| Signal | ns-3 source | Current packet replay | Integrated ns-3 Serving path | Available to Python scheduler now? |
|---|---|---|---|---|
| QP completion | RDMA QP `qp_finish`/ASTRA message callback | Callback is `noop_message_handler`; all release times are pre-scheduled | `sim_send` registers callback and graph/network completion propagates into ASTRA | Only indirectly through subsequent ASTRA iteration/batch completion time; custom topology runtime not exercised here |
| ACK | RDMA transport | Simulated inside ns-3 | Simulated inside ns-3 | No direct event feed shown |
| ECN/local CE | Switch MMU queue marking and local-mark telemetry | Written to CSV after/during replay; not connected to Serving event loop | Switch can mark packets; no scheduler IPC for marks was audited | No |
| CNP | RDMA congestion-control feedback | Recorded in `cc_events.csv`; no-op replay callback | DCQCN changes sender QP state inside ns-3 | No direct CNP timestamp/state feed |
| Current QP rate | DCQCN QP rate history | Recorded in CSV | Maintained in ns-3 QP | No direct scheduler feed |
| Queue occupancy | Switch per-port MMU telemetry | Sampled/written by replay | Available to ns-3 telemetry code | No direct scheduler feed |
| P2D-ready | Required shard/message completion barrier | Reconstructed offline as max of END times | ASTRA graph/Scheduler can receive completion timing through integrated completion path | Potentially via graph completion; not validated on this fixture |
| Serving choice | Scheduler waiting/running queues | None; event ledger frozen | Python chooses next batch after ASTRA iteration response | Yes, but no network-state feature/policy is implemented |

## Signal timing and causal validity

In fixed replay, issue timestamps are all known before the ns-3 event loop
starts. `comm_events.csv`, `cc_events.csv`, and switch telemetry are outputs,
not online observations. An offline controller that sorts by the eventual FCT
or CNP timeline would be clairvoyant and is not tested.

In integrated ns-3, packet message completion can affect ASTRA graph progress.
That is distinct from exposing early ECN/CNP/queue signals to the Serving
scheduler. The current code path has no validated packet-telemetry-to-Python
control channel. Implementing that channel is deferred because this workload's
profiled P2D completion has no exposed downstream compute wait and no alternate
ready Prefill work item.
