# Final GO / NO-GO

## Decision

```text
INCAST_NETWORK_MOTIVATION_CONFIRMED
NETWORK_ONLY_SUFFICIENT (for the tested fixed-release mean-ready objective only)
INSUFFICIENT_SERVING_HEADROOM
NO_VALID_PAPER_MAINLINE (for congestion-feedback-guided Serving scheduling on the tested workload)
```

`CC_RECOVERY_HEADROOM_CONFIRMED` and
`FEEDBACK_DRIVEN_SERVING_GAIN_CONFIRMED` are **not** established. The CC0/CC1
pair quantifies packet behavior, but CC0 disables DCQCN response and is not a
deployable optimization baseline; no runtime scheduler action consumed CNP or
rate feedback.

This is a scoped decision for the calibrated 4P1D/200G topology and the tested
model-derived 4-request workload, not a universal claim that receiver incast
never affects PD Serving.

## Answers to the mission questions

1. **Can non-ECMP congestion occur?** Yes. Four independent source-spine paths
   feed one shared Decode 200G receiver NIC and build a real switch-egress
   queue. ECMP collision is not needed.
2. **Does receiver incast affect packet completion?** Yes. N2 CC0 mean flow
   FCT is 32.481310ms versus the 8.053064ms one-shard serialization bound and
   32.212255ms four-way equal-share payload bound. N3 spreading over two NICs
   cuts FCT to ~16.261ms; N4 spreading over four receiver NICs gives ~8.151ms.
3. **Does DCQCN act?** Yes. With `CC_MODE=1`, local CE leads to CNP and QP
   rate-change telemetry. In the simultaneous FULL4 sample, mean request
   max-shard readiness is +2.41% vs CC0. CC0 is a diagnostic with rate
   response disabled, not a proposed deployment.
4. **Does PFC/HOL occur?** No. The largest queue is 3,148,584 B versus a
   32MiB buffer; PFC pauses and packet drops are zero. HOL was not isolated.
5. **Does layerwise KV leave network queues?** It creates recurring bursts and
   local ECN. With CC1, all 768 QPs react, but all wave flows complete before
   the next layer/chunk release (minimum gap 55.255µs).
6. **Do those packet delays become a Serving barrier here?** The last P2D
   shard completes at 134.059112ms (CC0) / 134.963180ms (CC1), before profiled
   Prefill compute ends at 135.319248ms. The exposed P2D wait upper bound is
   zero for this frozen profile release schedule. TTFT/TBT/TPOT/SLO were not
   measured.
7. **How much can network-only ordering do?** On the fixed post-prefill cohort,
   an 8.2ms bundle pacing schedule reduces mean absolute P2D-ready by 37.04%
   but increases the last-request/makespan by 0.83%. This is a network-only,
   offline result, not a Serving feedback gain.
8. **Does the scheduler receive live congestion signals?** No validated direct
   queue/ECN/CNP/QP-rate path to Python was found. Integrated ASTRA/ns-3 has
   network-completion callbacks into graph progress, but the custom topology's
   integrated runtime is NOT_RUN. The fixed replay has no-op callbacks and
   cannot be used as serving evidence.
9. **Is there ≥15% joint headroom?** Not demonstrated. The LAYERWISE exposed
   wait bound is 0ms, and the workload has no alternative ready Prefill task
   for a feedback-based Serving action. The post-prefill mean gain is already
   available from network-only pacing.

## What should happen next

Do **not** implement a congestion-feedback Serving scheduler or expand this
same workload to more requests/less bandwidth. Reopen only if a new, physically
and profile-legal workload first demonstrates both:

- positive network-exposed P2D/compute or Decode-admission slack after all
  required shards; and
- independent ready Prefill work whose order can change without adding GPU,
  NIC, byte, or arrival assumptions.

Before any packet run, calculate an exposed-wait upper bound and compare the
best network-only and Serving-local baselines. If that bound is below the
15% screening threshold, stop. If it passes, implement and validate a
timestamped online signal channel before reporting TTFT/TBT.

## Limitations retained

- No integrated Serving run, no TTFT/TBT/TPOT/SLO, no closed-loop network
  feedback controller.
- No persistent KV-QP reuse; each KV message event uses a fresh QP in this
  replay path.
- No PFC/drop/HOL, sender-NIC incast, external tenant load, packet-level
  KV–EP, or packet-level EP–EP experiment.
- Four-request tail quantiles are not production P95/P99 claims.
- ECMP all-path balancing was not demonstrated; the multipath audit actually
  selected one common spine for the four flows. Main receiver-incast tests use
  unique physical source paths.
