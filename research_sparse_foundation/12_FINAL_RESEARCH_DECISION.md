# 12 — Final research decision

## Decision

```text
INSUFFICIENT_MODEL_PROVENANCE
PROFILE_CALIBRATION_BLOCKED
```

This is a **gate-level stop**, not a finding that sparse MoE network
optimization can never help. No FlowSim or packet-level performance run was
started because actual Qwen router provenance, AE=2/4 calibration, S16 physical
rank mapping, and sparse-A2A Serving integration are not established.

## P0/P1 scorecard

| Criterion | P0: AG/RS vs sparse A2A | P1: critical-cut placement |
|---|---|---|
| Model fidelity | Insufficient: no learned route matrix; EP32/64 profile clamps | Insufficient for same reasons |
| Theoretical headroom | Payload-only analytic expectation exists under uniform top-k assumptions; no execution-time crossover | Cannot compute authentic per-cut load without `M_ij` and path map |
| Physically realizable gain | Not available | Not available; legal expert movement/placement cost not modeled |
| Serving critical-path gain | Not run; sparse path dormant | Not run |
| Baseline incremental gain | Not available; current implementation/backend semantics not bound | Not available; generic source-aware placement overlaps prior work |
| Reproducibility | Partial; source tree dirty and historical run bindings incomplete | Partial |
| Novelty vs prior work | Not established; high FAST/backend-selection overlap | Not established; very high Gimbal/FAST/ELDR overlap |
| Gate result | `NOT_PASSED_INPUT_BLOCKED` | `NOT_PASSED_INPUT_BLOCKED` |

## What is established

1. The checked-in MoE timing table has AE grid 8–128; it does not measure the
   natural two-experts-per-rank EP64 case or four-experts-per-rank EP32 case.
2. Nearly all retained sidecar MoE queries are clamped to AE=8.
3. The retained route sidecars are BALANCED analytic route artifacts, not real
   learned Qwen router outputs.
4. RR/RAND token indexing in `route_ep()` was wrong and is now fixed with
   focused tests. The repair does not create real model routing.
5. The S16 topology manifest models physical shared NIC resources, but the
   serving config's logical rank count and generated EP-rank labels do not
   provide the required unique physical mapping.
6. The ordinary trace emits AG/RS. The checked-out exact P2P converter is not
   wired with route records and EP-global ranks through graph generation.
7. A payload-only uniform-routing formula suggests sparse data volume can be
   smaller at high EP; it is not a timing crossover or Serving result.

## Stop rule and resumption criteria

Do not run motivation sweeps, increase concurrency, or tune bandwidth to force
a positive result. Reopen only after all four evidence prerequisites are
available:

- real Qwen layer-level router output sidecars;
- calibrated EP32/64-relevant MoE profile data;
- a topology test proving a unique rank→GPU→server→NIC mapping and correct
  collective participant set;
- an integrated sparse-A2A DAG regression covering dispatch, compute, combine,
  completion, byte conservation, and serving feedback.

Then begin with one minimum network-only correctness instance. If that passes,
run one profile-backed integrated request; only after those pass should P0/P1
headroom be assessed. A clean commit plus exact run manifest should bind every
future result.

## Result label

The correct end-of-stage label is **not** `P0_P1_NO_GO`, because the decisive
mechanisms were not tested with authoritative inputs. It is
`INSUFFICIENT_MODEL_PROVENANCE` plus `PROFILE_CALIBRATION_BLOCKED`, with the
performance experiment gate intentionally not entered.
