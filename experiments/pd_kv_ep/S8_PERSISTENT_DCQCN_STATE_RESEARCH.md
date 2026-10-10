# S8 Persistent DCQCN State Research

## Existing natural-ECN baseline

The archived S8 4P4D / EP32 / 16-request `FULL` replay used 200-Gbps scale-out links, 4-KiB packet payloads, and `CC_MODE=1`. Its aggregate FAIR summary records 79,026 physical-link ECN observations, 20,876 CNP events, 10,923 RATE events, 10,353 rate decreases, and a 3,243,620-byte maximum physical-link queue. These values establish historical network-wide congestion-control activity only; they do not identify CNP recipients by QP or traffic class.

Detailed provenance and limitations are in [S8_NATURAL_ECN_BASELINE_AUDIT.md](S8_NATURAL_ECN_BASELINE_AUDIT.md).

## Reproduction gate

**Status: `S8_ECN_BASELINE_REPRO_FAIL` (exact replay inputs unavailable).**

The historical manifest counts 171,507 events but the source request schedule and event ledger are missing. The replay directory also lacks its flow input and detailed outputs. Recreating events from aggregate summaries would not preserve exact event timestamps, paths, bytes, or QP identities, so no substitute replay was run.

The explicitly permitted D64 POST_PREFILL fallback was audited too. Its retained artifacts are FlowSim request/KV/collective/fluid-link summaries. The EP file contains collective aggregates and only a subset of critical-flow IDs—not every peer message with exact issue time, bytes, path, and QP identity—so it cannot be converted into a faithful packet replay without regenerating or fabricating missing EP traffic. That fallback was not run.

This status must not be interpreted as `EP_QP_CNP=0`, `persistent state ineffective`, or a failed historical congestion run. The experiment stopped before the persistent-QP treatment.

## Persistent QP correctness / class attribution

Not tested in this run. No QP identities or per-QP DCQCN trajectories were available to establish:

- whether recurrent EP messages reuse the same source port and QP ID;
- whether QP rate, alpha, and recovery state survive between collectives;
- whether an EP QP receives CNP or a rate-decrease transition;
- whether queue-clear precedes recovery or a later EP message;
- whether a reduced peer is last/near-last in a later collective.

KV-QP freshness and EP-QP persistence were not compared. Fresh-QP, persistent-QP/CC-off, and persistent EP-only controls were not run.

## CNP-by-class and state tables

`S8_CNP_BY_TRAFFIC_CLASS.csv` and `S8_PERSISTENT_DCQCN_STATE.csv` are schema-only files with headers and no data rows. Empty tables mean **unavailable/not measured**, not zero CNPs, zero rate transitions, or zero slowdown. The historical aggregate CNP count must not be copied into the EP row.

## PASS / FAIL

No mechanism PASS or FAIL can be assigned. The required prerequisite—reproducing the exact natural-ECN S8 event stream—could not be met, so the observation question (“does a recurrent EP QP itself receive CNP?”) remains unanswered. Do not advance to queue-clear/recovery, post-queue message, collective-barrier, or serving-level attribution.

## Final research decision

**Stop this attempt at the artifact/reproduction gate.** Restore the original request schedule and communication-event ledger, plus detailed per-QP CC telemetry if available. Then rerun the fresh EP-QP FAIR / `CC_MODE=1` baseline and verify queue > Kmin, ECN > 0, CNP > 0, and RATE transitions > 0 before enabling persistent EP QPs. No TTFT/TBT/SLO claim is made from this packet replay.
