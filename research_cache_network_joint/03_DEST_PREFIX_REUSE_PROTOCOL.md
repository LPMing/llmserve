# Destination Prefix Reuse Protocol and Correctness

## Implemented mode

The simulator has an opt-in `--destination-prefix-handoff` mode with `DISABLED`, `QUERY`, and `DELTA` choices. Existing behavior remains the default (`DISABLED`). The scheduler obtains the paired Decode cache compatibility key and queries the cache before deciding the P2D amount. In DELTA mode, a matching prefix is reserved/pinned before issuing the transfer; the request sends only missing KV; handoff commits the reservation; failed reservation or stale/evicted cache state falls back to ordinary transfer rather than silently omitting required bytes.

The essential lifecycle is:

```text
destination prefix lookup → validate compatibility → reserve/pin blocks
→ transfer missing model-derived KV → commit/adopt resident blocks
→ KV-ready → Decode admission
```

Decode admission is still gated on the actual handoff completion. This change does not set transfer bytes to zero, skip the handoff barrier, or allocate the same prefix twice. `QUERY` observes the destination but leaves the full payload unchanged.

## Data integrity

The 4096-token block identity is derived through the existing token/block hash chain. The request/session fixture uses the same token sequence and session dependency across warm-up and child. Bytes remain derived from the model formula; in full transfer the child receives the complete 4105-token KV representation, while DELTA sends its nine-token suffix. The existing destination copy supplies the prefix portion.

The Decode cache reservation is keyed by destination instance and cache compatibility. The current compatibility tuple includes model identifier, serialized architecture-config digest, TP/PP, precision, KV dtype, block size, layer count, KV-head count, and head dimension (`serving/core/scheduler.py::_prefix_cache_compatibility_key`). It does **not** hash the loaded checkpoint weights or deployment model-version epoch. In these matched experiments both stages use the same configured model/profile, but a deployed cross-stage protocol must add an explicit checkpoint/version fingerprint before it can claim complete weight-version validation. A reservation on the wrong Decode is rejected. Concurrent hits maintain references; a cache miss, failed reserve, or block eviction takes the full-safe fallback path. Partial hit transfers exactly the absent token/block extent represented by the test fixture.

Implementation landmarks: the CLI option is in `serving/__main__.py`; query/reserve and P2D amount selection are in `serving/core/scheduler.py::_query_or_reserve_destination_prefix`; cache pin/reservation and post-transfer validation are `serving/core/kv_cache_manager.py::reserve_handoff_prefix` and `commit_handoff_reservation`; Decode adopts the committed reservation in `Scheduler.add_decode`.

## Correctness cases

`research_cache_network_joint/test_decode_handoff_cache_accounting.py` verifies that Decode handoff adopts resident prefix blocks without allocating them a second time. `test_destination_prefix_reservation.py` verifies reservation, commit, concurrent sharing/refcounts, partial/miss behavior, capacity failure and eviction fallback. Both were rerun and passed on 2026-10-14.

The integrated runs additionally show:

| Case | Verified outcome |
|---|---|
| A0, destination reuse disabled | Full payload: 403,537,920 B per child |
| A1, query only | Prefix hit observed; payload and event times match A0 |
| A2, query + reserve + DELTA | Prefix hit 4096; payload 884,736 B per child; reservation commits after P2D |
| A3, partial destination hit | 2048-token prefix hit; payload 202,211,328 B |
| A4, destination miss | MISS; full 403,537,920 B fallback |
| A5, post-query eviction | Unit protocol test confirms safe fallback; no serving replay claimed |
| A6, concurrent shared prefix | Unit protocol test confirms shared references/commit/free; no multi-client production guarantee claimed |

## Costs not modeled

Query/reserve/commit host code has no explicit simulated network/control-plane duration. Local Python wall timings observed during diagnostics (query around 0.64–1.08 ms and reservation around 1.34–1.70 ms in these runs) are not a distributed RPC measurement and are not inserted into simulated time. Thus “real control overhead” remains unquantified. A production claim needs the actual metadata lookup, pin lease, invalidation/eviction race handling, and control RPC path profiled or modeled.

## Correctness boundary

This is a simulator-level protocol feasibility result. It does not establish a deployed runtime's cache compatibility protocol, cache coherence, token visibility contract, or zero-copy support. It is evidence that the current simulator can model safe destination-side block reuse without violating byte conservation and Decode readiness.
