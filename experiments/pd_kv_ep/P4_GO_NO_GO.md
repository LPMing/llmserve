# P4 Remote-KV Barrier: GO/NO-GO Decision

Date: 2026-09-28

## Decision

**GO for the corrected remote-KV semantic baseline; NO-GO for promoting the current provider-egress/source-selection comparison to the primary paper motivation.**

The corrected experiment establishes that a real remote-prefix reuse path can be represented as:

```text
remote provider -> Prefill prefix materialization
                  -> suffix-only Prefill compute
                  -> complete P2D KV handoff
                  -> Decode admission
```

It does **not** establish that provider placement or existing-holder selection produces a stable >=20% serving-level opportunity on the two tested Mooncake windows.

The distinction matters: the old result attached remote fetches as sibling waiters to a native P2D graph and left Prefill compute unchanged. The new `REMOTE_PREFIX_PD_BASELINE` mode changes compute accounting and dependency ordering, so its serving output is valid for the narrower semantic question.

## Correctness checks

- `REMOTE_KV_FETCH` is submitted before the first Prefill compute node for the affected graph.
- In the retained high-reuse run, the last remote fetch completed at 59.657557 ms; the first affected P2D layer was requested at 59.683557 ms. This is the expected remote-fetch -> suffix-compute ordering.
- B1 charges complete prefix + suffix KV to P2D. The pure scheduler check produced 6,168 P2D tokens for a 6,144-token remote prefix plus a 24-token suffix.
- Decode admission still waits for the request's P2D handoff barrier.
- The request CSV, rather than a sum of flow FCTs, is the authority for `p2d_kv_ready_time_ns` and request-relative `kv_handoff_fct_ns`.
- FlowSim queue values are residual fluid backlog only; they are not packet-buffer occupancy, ECN, PFC, or drop telemetry.

## P4A policy comparison

Policies:

- `NO_REMOTE`: matched control; all prompt KV is produced locally and sent by native P2D.
- `FIRST_PRODUCER`: fetches each matched block from the first trace-local producer.
- `LEAST_LOADED_EXISTING_HOLDER`: chooses among existing holders only. With no created replica in these windows, it correctly degenerates to `FIRST_PRODUCER`.
- `BALANCED_REPLICA_ORACLE`: creates model-derived same-fabric warm-up copies, waits for warm-up completion, and then fetches from selected holders. This is an offline oracle, not a final source-selection algorithm.

All policy runs use the same four request rows, token lengths, block identities, EP realization, LAYERWISE P2D, FlowSim topology, and 200-Gbps link profile. The complete P2D logical bytes remain approximately 2.27--2.29 GiB in every run. The comparison is therefore not based on arbitrary byte overrides.

### High-reuse simultaneous window

- `FIRST_PRODUCER` actual remote-fetch traffic: 1.125 GiB; peak residual fluid backlog: 1.142 GiB.
- `BALANCED_REPLICA_ORACLE` actual remote-fetch traffic: 0.844 GiB; replica warm-up: 0.563 GiB; peak residual fluid backlog: 0.299 GiB.
- EP CCT mean/P99 stayed approximately 3.6/5.0 microseconds for both policies.
- `FIRST_PRODUCER` TTFT P99: 238.698 ms.
- `BALANCED_REPLICA_ORACLE` TTFT P99: 274.939 ms.
- The oracle was **15.2% worse than FIRST_PRODUCER** on TTFT P99 because its replication traffic was charged to the same fabric. It was also worse than `NO_REMOTE` (214.177 ms) for this small simultaneous gate.

### High-reuse staggered window

- `FIRST_PRODUCER` and `LEAST_LOADED_EXISTING_HOLDER` are identical in network and serving output, as expected from a single-holder cache state.
- `BALANCED_REPLICA_ORACLE` reduces actual remote-fetch bytes but adds 0.563 GiB of warm-up traffic.
- TTFT P99 is about 129.9 ms for FIRST_PRODUCER and 130.2 ms for the replica oracle; the provider ordering difference is not material.
- The large TBT outlier in the NO_REMOTE staggered control is not used as provider-placement evidence: both remote policies remove it through the corrected prefix-hit/suffix-compute semantics, so it is a reuse-compute effect rather than a source-selection effect.

## PASS/FAIL assessment

| Gate | Result | Reason |
|---|---|---|
| Correct R->P->D remote-prefix lifecycle | **PASS** | Dependency and byte-accounting checks passed; remote fetch precedes suffix P2D release. |
| Integrated TTFT visibility of remote prefix reuse | **PASS** | The corrected mode changes Prefill completion and TTFT for hit requests. |
| Provider egress / holder selection as P4 paper opportunity | **NO-GO** | Existing-holder policy is identical to first producer; replica oracle changes fluid backlog but not EP CCT and does not provide stable >=20% TTFT/FCT headroom. |
| Deployable replication policy | **NOT TESTED** | The oracle charges warm-up traffic but no online replication/admission policy was implemented. |

Therefore P4 should not currently be written as “hot-prefix provider placement yields a >=20% PD-MoE serving gain.” The defensible result is narrower:

> Correct remote-prefix semantics expose a real R->P->D barrier, but in the tested small Mooncake windows the dominant serving effect is prefix-compute avoidance and request scheduling; changing the provider does not reliably move the Decode admission barrier once replication cost is charged.

## Required artifacts

- Semantics audit: [`P4_REMOTE_KV_SEMANTICS_AUDIT.md`](P4_REMOTE_KV_SEMANTICS_AUDIT.md)
- Request/barrier ledger: [`P4_REQUEST_CRITICAL_PATH.csv`](P4_REQUEST_CRITICAL_PATH.csv)
- Network accounting: [`P4_NETWORK_ACCOUNTING.csv`](P4_NETWORK_ACCOUNTING.csv)
- Human-readable critical-path summary: [`P4_REQUEST_CRITICAL_PATH.md`](P4_REQUEST_CRITICAL_PATH.md)

## Research implication

The corrected P4 baseline is still useful as infrastructure for a future remote-KV paper, but a CCF-A-level claim would require a stronger mechanism than “choose a less loaded provider.” The next credible extensions would need trace-backed evidence of either:

1. remote-fetch completion becoming the last required handoff event under realistic provider/Decode overlap; or
2. a direct-to-Decode assembly path in which remote fetches and P2D shards form one explicit request-level coflow, with warm-up/replication cost and a stable barrier-tail gap.

Neither extension is implemented or claimed here.
