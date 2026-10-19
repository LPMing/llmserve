# Packet-level causal telemetry

## Receiver-incast path

The authoritative fan-in uses four distinct Prefill source servers and four
source-specific physical spine paths. On each rail, those paths converge at a
single Decode leaf→NIC 200G egress (link 113 or 123). The selected receiver
egress—not a 200G aggregate across parallel spines—is the bottleneck. N0 has
one flow and no local ECN. N1/N2 add two/four simultaneously active senders to
the same receiver; N3 divides four senders over two receiver NICs; N4 gives
each sender a separate receiver NIC. The reduced FCT when the fan-in is spread
is consistent with the receiver resource being causal.

For N2, four 192-MiB app shards share one 200G receiver egress. The egress
queue peaks at 3,148,584 B; local first-CE marking begins at 31.435µs and
continues through 32.429845ms. The configured `KMIN=600` and `KMAX=2400` are
converted by the MMU code to 600,000 B and 2,400,000 B. The configured switch
buffer is 32 MiB. No PFC pause or drop occurs. This is queueing plus ECN, not
buffer overflow or loss.

The topology's rank attachment is capped at 200G for this calibrated QP-rate
test. An earlier uncalibrated fixture allowed a rank attachment at 7.2 Tbps;
DCQCN then began at that incorrect rate and fell to 3.64 Tbps. Those runs are
rejected and are not in the authoritative comparison. The calibrated N0 QP
starts at 200G and has no ECN/CNP/rate event.

## ECN and DCQCN semantics

The experiment uses `CC_MODE=0` and `CC_MODE=1`; mode 1 is the DCQCN response
path. With mode 0, the switch can locally mark and the telemetry can observe
CNP generation, but the sender rate is not adjusted. Therefore “CC_MODE=0 has
CNP rows” does not mean DCQCN is active. With mode 1, local CE is followed by
CNP and RATE events, and QP rates drop from 200G; in N2 each QP has CNP and
rate-change events. The resulting mean flow FCT rises from 32.481310ms to
32.781754ms (+0.93%); for FULL4, mean request max-shard readiness rises from
32.481310ms to 33.263584ms (+2.41%). The four-request sample is too small for a
production-tail claim.

`link_summary.ecn_marks` observes CE-carrying packets at downstream hops as
well as local marks. Those values must not be summed as independent ECN
events. `local_ecn_marks.csv` records first local mark transitions; for the
profiled layerwise CC0 run, the two receiver ports record 127,926 and 127,789
local first marks. For CC1 they record 43,587 and 43,610. The large CC0
telemetry count is not a count of distinct congestion episodes.

The data queues are groups 1/3, which traverse ordinary MMU/ECN/PFC accounting;
queue 0 is reserved for ACK/CNP/PFC control with `ACK_HIGH_PRIO=1`. No evidence
here supports a claim that control packets were blocked behind data.

## Profile-derived LAYERWISE timeline

Each of 96 QKV release epochs creates eight 2MiB messages (four requests × two
rails). Each epoch uses model-derived KV payload, not a byte override. The
four request instances are synchronized by construction as a controlled
mechanism test; this is not a natural-arrival frequency claim.

| Measurement | CC_MODE=0 | CC_MODE=1 |
|---|---:|---:|
| Shard-flow FCT mean / max | 0.378910 / 0.379157ms | 1.261535 / 1.288550ms |
| Local first ECN marks, both rails | 255,715 | 87,197 |
| QPs / QPs with CNP / QPs with rate change | 768 / 768 / 0 | 768 / 768 / 768 |
| CNP / RATE telemetry events | 255,715 / 0 | 87,197 / 13,006 |
| Latest request P2D-ready | 134.059112ms | 134.963180ms |
| Profiled Prefill compute end | 135.319248ms | 135.319248ms |
| Compute slack remaining after latest P2D-ready | 1.260136ms | 0.356068ms |
| Queue max on either receiver egress | 3,148,584 B | 3,148,584 B |
| PFC pauses / drops | 0 / 0 | 0 / 0 |

The CC1 critical shard is request 0's final event on layer 47 (release
133.679955ms, finish 134.963180ms); the other request barriers finish at
134.956250–134.962190ms. The actual last-release-to-ready drain is about
1.28ms, not the ~134.9ms elapsed from the first layer release. Those quantities
must not be conflated.

Across the 96 release waves, the minimum time from the prior wave's latest
packet completion to the next release is 959.943µs in CC0 and 55.255µs in CC1;
all 95 inter-wave gaps are positive in both runs. Thus each wave's flows finish
before the next layer/chunk wave is released. The burst queue and DCQCN response
are real, but there is no cross-wave active-flow carry in this fixed ledger.

The replay creates a QP per message event: there are 768 QP starts for 768 KV
events, each starts at 200G. A RATE reduction inside one layer's transfer is
therefore not proof that a later layer inherits a persistent QP's reduced rate.
QP reuse across KV layers/requests remains unmodeled by this replay.

## What the evidence does and does not establish

Established: receiver-side packet queue, local ECN, CNP, DCQCN rate changes,
and increased packet FCT under the calibrated line-rate model.

Not established: PFC/HOL, persistent-QP rate inheritance, KV–EP shared-cut
effects, Decode EP collective delay, TTFT/TBT/SLO impact, or serving feedback
benefit. The packet event ledger is fixed before ns-3 starts; callbacks in this
replay are no-ops.
