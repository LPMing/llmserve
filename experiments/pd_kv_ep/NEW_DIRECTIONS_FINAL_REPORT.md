# New Packet-Level Directions — Final Bounded Search Report

## Scope

This report covers the post-P4/P4B negative-bound search requested for the
current PD-disaggregated MoE simulator. It is separate from the earlier P4
ordinary provider-placement result, which was later downgraded to NO-GO, and
from the P4B split-source architecture result, which was also NO-GO.

The evidence rule was deliberately strict: no synthetic bytes, artificial
delay, forced synchronization, unsupported topology resource, or inferred
TTFT/TBT from network-only proxy metrics.

## Results

| direction | strongest valid evidence | decision |
|---|---|---|
| P5 layerwise burst shaping | no validated NIXL/UCX/WQE/rendezvous or pacing semantics | FINAL FAIL: unsupported transport granularity |
| N1 Decode batch-boundary amplification | natural 32D+32P2D point: 6.568 ms wait, about 6.5% TTFT; neighboring 32D+64P2D point: 1.418 ms, about 1.2% TTFT | FINAL FAIL: insufficient serving headroom |
| N2 P2D-handoff phase synchronization | real Mooncake windows had at most 2 completions per 5/10 ms in Conversation and at most 2 per 5/10 ms in Tool/Agent; no narrow handoff wave | FINAL FAIL: no natural clustering |
| N3 multi-NIC/rail mismatch | S16 has no NIC/rail resource or assignment semantics | FINAL FAIL: unsupported topology/runtime semantics |
| N4 cross-request KV batching/HOL | KV remains request/layer/shard scoped; only EP memory coalescing exists | FINAL FAIL: unsupported batching/HOL semantics |
| N5 recovery/rehydration storm | no failure, invalidation, restart, migration, or recovery-triggered event | FINAL FAIL: unsupported recovery semantics |

## N1 serving evidence

The integrated FlowSim runs were real scheduler runs, not network-only
proxies. The added telemetry records P2D-ready time, Decode scheduler
admission, in-flight batch IDs, blocking batch interval, missed iterations,
TTFT, and TBT.

- 8 Decode + 8 P2D, output 4: no boundary wait or missed iteration.
- 16 Decode + 16 P2D, output 4: no boundary wait or missed iteration.
- 32 Decode + 32 P2D, output 16: all P2D requests crossed one in-flight
  Decode batch; wait was 6.568 ms and approximately 6.5% of their 101.586-ms
  TTFT.
- 32 Decode + 64 P2D, output 16: one missed batch remained, but wait fell to
  1.418 ms and approximately 1.2% of their 116.232-ms TTFT.

This is a genuine scheduler-boundary mechanism. It does not satisfy the
paper-level criterion because the low/medium operating points are zero and the
larger neighboring point is smaller rather than stronger.

## Why the search stopped

The remaining directions cannot be made meaningful by changing workload size:

1. N3 needs a real endpoint-to-NIC/rail mapping and a rail resource.
2. N4 needs batching eligibility, flush, ordering, and per-request completion
   demultiplexing.
3. N5 needs failure/invalidation/recovery state and a recovery barrier.
4. P5 needs transport-level release/pacing semantics.

Adding only an event field or a delay would change the mechanism under study.

## Current paper conclusion

The current packet-level repository does not yet contain a new, defensible
CCF-B/CCF-A motivation beyond the earlier packet-level hot-prefix/provider
barrier candidate, which itself still requires integrated serving validation.
The new search therefore ends with a bounded negative result rather than a
fabricated positive result.

## What would legitimately reopen the search

The next productive step is not another parameter sweep. It is to obtain one
runtime-grounded semantic source for one missing mechanism:

- actual multi-rail NIC assignment and endpoint resource sharing;
- an actual KV batching/rendezvous policy;
- a real cache-failure or migration trace;
- or an actual NIXL/UCX transfer-granularity trace.

Only then should the corresponding packet-level extension and matched serving
validation be implemented. Until such evidence exists, the current negative
results are the scientifically valid stopping point.

