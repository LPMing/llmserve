# PD-MoE Network Motivation Gates

This is the current gate record for the corrected FlowSim topology and the
integrated serving validation.  It is separate from older policy-sweep notes;
the old single-200-Gbps-bundle results are not used here.

## Authoritative setup

- S16: 16 servers / 128 logical GPUs; 64 Prefill and 64 Decode GPUs.
- 32 Prefill and 32 Decode instances, TP2, EP64.
- Qwen3-30B-A3B-Instruct-2507: 128 experts, top-k 8, 48 layers.
- 200-Gbps endpoint links; each leaf-to-spine directed pair is represented by
  16 physical 200-Gbps links as one 3.2-Tbps aggregate fluid resource.
- P2D is model-derived `LAYERWISE`; EP is GateRouter-derived `A2A_P2P`.
- FlowSim queue values are residual analytical fluid backlog.  They are not
  packet-buffer occupancy, ECMP hash behavior, ECN, PFC, drops, or packet
  serialization.

## P1 hypothesis

Concentrating otherwise identical P2D handoffs on a Decode-side cut may
interact with the Decode EP collective barrier:

`P2D destination concentration -> shared Decode cut -> KV/EP barrier tails -> TTFT/TBT`

The fan-in control is an offline characterization map.  It changes only the
Prefill-to-Decode pairing; it is not being presented as a scheduler or a
deployable placement algorithm.

## Network-only evidence

The matched 512-request replay contains 256 active Decode requests and 256
new P2D requests.  The two geometries have the same request set, timing,
model-derived bytes, GateRouter routes, topology, and FAIR policy.

| Geometry | EP CCT P99 | KV handoff FCT P99 |
|---|---:|---:|
| spread | 4.385 ms | 74.511 ms |
| fan-in16 | 13.212 ms | 148.277 ms |
| fan-in16 relative to spread | +201.3% | +99.0% |

The 256-request replay shows the same knee: with 64 Decode + 64 P2D the
network-only increase is only EP P99 +10.4%, while 128 Decode + 128 P2D and
256 Decode + 256 P2D produce large EP and KV tails.  Heterogeneous KV mixes
(small-majority, 50/50, and large-majority) also preserve the concentration
effect, so the result is not caused only by a single uniform request size.

The cut audit localizes the difference without overclaiming endpoint
exclusivity.  Endpoint-facing links and Decode-side leaf/spine resources can
both approach fluid utilization.  The distinctive fan-in effect is that all
P2D bytes are moved onto the same Decode-side logical cut (`132->130` in the
audit), where the maximum residual fluid backlog rises from about 2.499 GB to
9.862 GB while EP traffic continues to use that cut.  This is aggregate fluid
evidence, not packet-switch evidence.

## Integrated serving gate

The following matched runs use the same FlowSim backend, FAIR policy,
LAYERWISE P2D, actual receiver mode, EP64, 200 Gbps, and the same
64-Decode + 64-P2D workload.  P2D requests use 512 input tokens and active
Decode requests use 128 input / 8 output tokens.  Both runs completed with
return code 0 and produced complete request CSVs.

| serving cohort / metric | spread | fan-in16 | relative change |
|---|---:|---:|---:|
| active Decode TTFT mean/P99 | 51.762 ms | 51.938 ms | +0.34% |
| active Decode TPOT | 5.903 ms | 6.055 ms | +2.58% |
| active Decode TBT mean | 6.887 ms | 7.064 ms | +2.57% |
| active Decode TBT P95/P99 | 6.889 ms | 7.065 ms | +2.55% |
| new P2D request TTFT mean/P99 | 85.038 ms | 85.263 ms | +0.26% |
| P2D `p2d_kv_ready_time_ns` | 98.104 ms | 98.104 ms | 0.00% |
| active Decode `decode_admit_time_ns` | 44.873 ms | 44.873 ms | 0.00% |

The completed CSVs are:

- `results/p1_integrated_gate/p1_integrated_overlap_64d64p2d_512_out8_spread_fair.requests.csv`
- `results/p1_integrated_gate/p1_integrated_overlap_64d64p2d_512_out8_fanin16_fair.requests.csv`

The integrated result is a valid negative serving gate, not a missing-data
case.  It shows that the large network-only tail is mostly absorbed by the
serving timeline in this tractable overlap slice.  In particular, the P2D
handoff completion and Decode admission timestamps are unchanged; therefore
the network-only KV FCT difference does not become a TTFT difference here.
The Decode-side network difference is visible in TBT, but only at about 2.5%.

Earlier completed integrated 128-Decode + 128-P2D / output-4 controls showed
the same behavior: P2D ready and handoff timestamps were unchanged and active
Decode TBT did not increase.  The output-16 attempt did not produce a complete
CSV and is not used as evidence.

## Gate decision

**P1 Decode-side cut contention: FAIL for the paper-level serving gate.**

The network mechanism is real in the aggregate fluid model and exceeds 20%,
but the required serving-level ≥20% TTFT/TBT headroom has not been observed.
The result must not be promoted to a CCF-A motivation by substituting network
FCT/CCT for TTFT/TBT.

The failure is informative: in this serving realization, a shared cut can
strongly inflate network completion metrics while the Prefill/Decode timeline
and compute overlap hide most of the delay from TTFT/TBT.  Increasing request
count alone is therefore not a sufficient next step.

## Next gate

The next valid direction is the packet-level optimization gate followed by
P2, using an existing reduced native ns-3 replay rather than another large
FlowSim sweep:

`P2D QP entropy / ECMP hash polarization -> physical packet path/queue -> last-shard barrier`

The packet-level gate must first verify that the replay binary, topology,
packetization, queue telemetry, and completion accounting are correct.  Only
then can P2 test whether packet-level QP/path polarization creates serving
headroom that the aggregate fluid model cannot expose.  Any standalone
packet replay remains network-only until an integrated serving run confirms
TTFT/TBT propagation.

## Evidence boundary

No current result establishes a CCF-A PASS.  The strongest present statement
is:

> High-concurrency P2D destination concentration creates a repeatable
> Decode-side fluid-cut tail, but the tested integrated serving path does not
> expose that tail strongly enough in TTFT/TBT.

This negative serving result is retained as a boundary condition for the next
packet-level candidate and prevents treating the old network-only gap as an
end-to-end claim.

## P2 packet replay update (2026-09-28)

The reduced native ns-3 replay was completed on the corrected S16 topology.
It used 32 Decode + 64 P2D requests, Qwen3 model-derived LAYERWISE P2D, EP64
GateRouter A2A_P2P, 4 KiB payloads, and 200 Gbps endpoint links.  Spread and
fan-in16 completed all 12,240 events.  Fan-in16 increased packet-level KV
request FCT P99 from 134.685 ms to 264.604 ms (+96.5%) and EP CCT P99 from
2.166 ms to 3.342 ms (+54.3%).  The runs exposed real queue, ECN and PFC
counters with zero drops.

A matched FlowSim integrated rerun was also completed after repairing a P/D
lifecycle regression.  The corrected request CSVs satisfy
`prefill_completion <= p2d_kv_ready <= decode_admit <= decode_first_token`.
Active Decode TBT P99 changed from 6.793 ms to 7.134 ms (+5.0%), while active
Decode TTFT changed from 49.844 ms to 50.185 ms (+0.68%); P2D TTFT changed by
+0.28%.  Thus P2 remains a network-mechanism result, not a serving-level
PASS.  The detailed record is in `P2_PACKET_REPLAY_GATE.md`.

The first HTSim S16 topology was made endpoint-consistent (128 hosts, four
leaves, two spines, 16x200-Gbps leaf-spine bundle).  One P2D request passed,
but multi-request interactive HTSim runs did not produce complete serving
CSV output and are excluded from the evidence.

## High-concurrency exposure boundary

A real 256-entry integrated FlowSim attempt (128 active Decode + 128
concurrent 2048-token P2D, Decode output 64) reached the 1,200-second timeout
without a request CSV.  The worker peaked at approximately 2.76 GiB RSS and
was cleaned up.  It is a cost/availability boundary only; no serving metric
is inferred from this timeout and no fan-in counterpart was launched.
