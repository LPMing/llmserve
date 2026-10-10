# N5 KV Recovery / Rehydration Storm Audit

## Status

`N5_FINAL_FAIL_NO_FAILURE_OR_REHYDRATION_EVENT_MODEL`

The repository has a tiered prefix-cache and remote-prefix fetch model, but it
does not model a runtime recovery, cache-failure, migration, or rehydration
storm. Reusing the existing remote-prefix path as a failure event would be a
semantic substitution.

## Hypothesis

A cache loss, worker restart, or coordinated KV migration could release many
rehydration transfers at once. Those transfers might share the scale-out
fabric with Decode EP and create a recovery-specific barrier:

`cache loss/restart -> rehydration fan-in or fan-out -> packet queue/ECN/PFC
-> remote-KV barrier and EP barrier -> TTFT/TBT tail`.

## Existing cache semantics

`serving/core/kv_cache_manager.py::TieredKVCacheManager` supports a lower-tier
prefix cache. It can calculate lower-tier hits and charge model-derived recall
bytes through `_charge_recall`; write-through is explicitly accounted as
off-critical-path traffic. The ordinary prefix-cache allocator preserves or
recomputes blocks according to cache state. This is cache lookup/preemption
semantics, not a failure/recovery event.

The trace generator can emit `kv_load` / `kv_evict` rows for memory-tier
accounting. The repository documentation and implementation treat eviction as
non-network/off-critical-path in the current model. No event identifies a
failed provider, lost block set, restarted worker, migration epoch, recovery
barrier, or rehydration wave.

`serving/core/flowsim_worker.py` does support explicit model-derived
`REMOTE_KV_FETCH` plans and replica warm-up flows. Those are remote-cache
placement/replication experiments already audited under P4. They are not
failure-triggered recovery, and warm-up is submitted from a planned provider
state rather than released by a cache-loss event.

## Correctness gate result

There is no current input field, event callback, or state transition that can
express:

- a cache/provider failure time;
- the set of invalidated blocks;
- a worker restart or migration epoch;
- recovery source selection;
- a request-level rehydration barrier;
- recovery traffic competing with the existing EP rounds.

Consequently a minimal N5 case cannot be constructed without inventing the
central mechanism. Increasing remote-fetch concurrency would only repeat the
already tested remote-KV placement direction and would not be a recovery
storm.

## Decision

N5 is closed for the current simulator. A legitimate future study would first
need a runtime-grounded failure/migration model, including invalidation,
recovery source selection, recovery ordering, and serving admission semantics.
Only after that extension could native ns-3 telemetry test packet-level
rehydration behavior.

