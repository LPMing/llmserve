# N1 Decode Batch-Boundary Audit

Status: in progress. This audit records the scheduler semantics before any
N1 claim is made.

## Control-plane path

1. `serving/core/scheduler.py::_build_batch()` creates a Decode batch at the
   controller's current simulation time and records its request set.
2. `serving/core/scheduler.py::add_done()` retires the batch only after the
   FlowSim group barrier has reported completion.
3. `serving/core/router.py::transfer_prefill_request()` writes the native
   `p2d_kv_ready_time_ns` and calls `DecodeScheduler.add_decode()`.
4. `DecodeScheduler.add_decode()` places the request in the Decode running set.
   If a Decode batch is already in flight, the audit telemetry records that
   batch but does not change admission or network behavior.
5. For FlowSim, `serving/core/scheduler.py::schedule()` refuses to open a new
   Decode batch while the current group batch is in flight. This is a modelled
   group barrier, not an artificial delay added by the N1 experiment.

## Telemetry added for this audit

Per request CSV fields:

- `decode_scheduler_admit_time_ns`
- `decode_iteration_id`
- `decode_iteration_start_time_ns`
- `decode_iteration_finish_time_ns`
- `decode_admission_wait_ns`
- `decode_handoff_inflight_batch_ids`
- `decode_handoff_blocking_batch_id`
- `decode_handoff_blocking_batch_start_ns`
- `decode_handoff_blocking_batch_finish_ns`
- `decode_missed_iteration_count`

The fields distinguish the network/control-plane handoff time from the first
Decode batch that actually contains the request. Existing TTFT/TBT accounting
is unchanged.

## Preliminary natural-workload results

The low point (8 Decode + 8 P2D, 16 requests) and medium point (16 Decode +
16 P2D, 32 requests) both completed with valid serving CSVs. In both runs,
all requests had `decode_admission_wait_ns=0` and
`decode_missed_iteration_count=0`; they are negative boundary controls, not
contention evidence.

The first 64 rows of the existing 32 Decode + 64 P2D, output-16 workload
(32 Decode + 32 P2D) produced a positive natural boundary case: all 32 P2D
requests became ready at 107.763 ms while Decode batch 9 was in flight from
107.205 to 114.331 ms. Each incurred 6.568 ms of scheduler-boundary wait and
missed one Decode iteration; TTFT was 101.586 ms, so the boundary component
was about 6.5% of TTFT.

The full 32 Decode + 64 P2D neighboring point also missed one iteration, but
its wait was only 1.418 ms against 116.232 ms TTFT (about 1.2%). Low and
medium points had zero wait. The mechanism is real, but the tested natural
points do not provide paper-level serving headroom; N1 is FINAL_FAIL.

## Interpretation rule

Only a naturally observed positive `decode_admission_wait_ns`, together with
the corresponding P2D/EP packet or flow timeline, can support N1. A network
metric alone cannot be called Decode batch-boundary amplification, and
network-only delay cannot be reported as TTFT/TBT.
