# Strongest matched baselines and interpretation

## Fixed post-prefill 4-request cohort

| Network condition | Mean request-ready | Last request / makespan | Mean objective result | Serving interpretation |
|---|---:|---:|---|---|
| Simultaneous FAIR, CC0 | 32.481310ms | 32.481557ms | Baseline | Network-only P2D-ready, not TTFT. |
| Simultaneous FAIR, CC1 | 33.263584ms | 33.888367ms | DCQCN adds ~2.41% mean readiness and ~4.33% max readiness over CC0 in this 4-request sample | No PFC/drop; not serving-visible evidence. |
| Fixed bundle pacing, 8.2ms spacing, CC0/CC1 | 20.451317ms | 32.751317ms | Mean improves 37.04%; makespan worsens 0.83% vs FAIR CC0 | Network-only, offline release schedule; no scheduler feedback. |
| Ideal one-at-a-time network order | 20.132659ms | 32.212255ms | Mean upper bound improves 37.5%; makespan unchanged | Fluid oracle only; not a deployable scheduling result. |

The order schedule nearly attains the mean-completion upper bound. Its benefit
does not establish joint network–Serving optimization: all release timestamps
are fixed before the network run, and no Serving computation was reordered.
There is no distinct SRPT advantage because all request bundles have equal
bytes; a coflow-aware order is simply one legal tie order.

## Profile-derived LAYERWISE cohort

| Metric | CC0 | CC1 | Serving implication |
|---|---:|---:|---|
| Per-shard FCT mean | 0.378910ms | 1.261535ms | Packet-level service changed materially for a 2MiB burst. |
| Latest P2D-ready | 134.059112ms | 134.963180ms | CC1 adds 0.904068ms to the latest completion. |
| Prefill compute end | 135.319248ms | 135.319248ms | The latest shard still arrives 1.260136ms (CC0) / 0.356068ms (CC1) before this boundary. |
| Exposed P2D wait after compute | 0ms | 0ms | The observed packet-level difference is hidden under this profile timeline. |
| TTFT/TBT/TPOT/SLO | NOT_RUN | NOT_RUN | No integrated-serving claim. |

This is the strongest current evidence for why network telemetry does not
automatically imply a useful scheduler signal: ECN/CNP/rate changes can be
large at the QP level yet occur within slack before the request's downstream
handoff boundary. A future candidate must first show a nonzero exposed-wait
upper bound using a legal model/profile/workload before implementing feedback.

## Research decision from these controls

Receiver incast is a real packet mechanism. A network-only mean-completion
baseline exists. Neither finding proves that network feedback can improve
Serving beyond the strongest network-only and Serving-local choices. On this
tested LAYERWISE profile point, the measured exposed wait is zero and the
current fixture provides no alternate ready Prefill work, so there is no
evidence for a ≥15% incremental feedback-scheduling opportunity.
