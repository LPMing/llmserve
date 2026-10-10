# P2 Reduced Packet Replay Gate

This file records the reduced native ns-3 packet replay and the matched
integrated FlowSim check. It does not promote the result to a serving-level
paper PASS.

## Setup

- S16: 16 servers / 128 GPU endpoints, 64 Prefill and 64 Decode GPUs.
- Qwen3-30B-A3B-Instruct-2507, 48 layers, EP64, GateRouter A2A_P2P.
- 32 Decode + 64 P2D requests; model-derived layerwise KV; 4 KiB packet
  payload; 200 Gbps endpoint links.
- The packet replay contains 12,240 communication events, 9,216 P2D layer
  events and 3,024 EP events. Total P2D and EP bytes are identical between
  geometries.
- `spread` is the normal pairing. `fan-in16` is an offline matched control
  that concentrates P2D destinations on Decode instances 32--47. It is not a
  deployable scheduler.

## Native ns-3 network result

Both runs completed all 12,240 events. Wall-clock time was 484.3 s for
spread and 510.5 s for fan-in16. The packet backend emitted real link queue,
ECN, PFC and drop fields.

| metric | spread | fan-in16 | fan-in16 relative |
|---|---:|---:|---:|
| KV request FCT mean | 89.908 ms | 175.748 ms | +95.5% |
| KV request FCT P99 | 134.685 ms | 264.604 ms | +96.5% |
| EP collective CCT mean | 1.167 ms | 1.930 ms | +65.3% |
| EP collective CCT P99 | 2.166 ms | 3.342 ms | +54.3% |
| maximum link queue | 10.85 MB | 11.41 MB | — |
| total ECN marks | 5,800,607 | 5,860,464 | — |
| total PFC pauses | 39,372 | 52,882 | — |
| drops | 0 | 0 | — |

This is genuine packet-level network evidence for a Decode-side cut/path
interaction. It is not evidence for TTFT/TBT because the replay is detached
from the serving scheduler.

## Integrated serving result after lifecycle repair

The first FlowSim integrated runs were discarded. Their CSVs had
`decode_admit_time_ns < prefill_completion_time_ns`, which violated the P/D
barrier. The cause was a scheduler state regression: `req.is_init = False`
was missing in the Prefill completion path. It has been restored, and the
minimal cross-request regression now satisfies:

`prefill_completion <= p2d_kv_ready <= decode_admit <= decode_first_token`.

The matched 96-request FlowSim runs were then repeated and passed this
lifecycle check. FlowSim values below are analytical fluid results, not
packet-buffer occupancy.

| serving cohort / metric | spread | fan-in16 | relative |
|---|---:|---:|---:|
| active Decode TTFT mean/P99 | 49.844 ms | 50.185 ms | +0.68% |
| active Decode TPOT mean | 4.529 ms | 4.755 ms | +5.01% |
| active Decode TBT mean | 6.793 ms | 7.133 ms | +5.01% |
| active Decode TBT P99 | 6.793 ms | 7.134 ms | +5.01% |
| new P2D TTFT mean/P99 | 114.275 ms | 114.596 ms | +0.28% |
| P2D KV-ready mean/P99 | 127.197 ms | 127.197 ms | 0.00% |

There are 32 active Decode and 64 P2D rows in each serving CSV. All rows have
monotonic lifecycle timestamps. The integrated result therefore remains a
negative serving gate: the packet-level network gap is not yet a >=20%
TTFT/TBT gap in this FlowSim serving realization.

## HTSim status

An S16 HTSim FatTree with 128 endpoints, four 32-port leaves, two spines and
16 parallel 200-Gbps links per leaf-spine pair was added. One P2D request
completed and produced a valid serving row. Multi-request interactive runs
(2, 36 and 96 requests) exited before the ASTRA handshake or hit an existing
interactive scheduler/backend failure, so they are not used as serving
evidence. The topology file is retained for later backend debugging.

## Gate decision

**P2 packet replay: network-mechanism PASS, serving-level FAIL so far.**

The reduced packet run proves that the fan-in geometry creates physical queue
and collective-tail changes. The integrated FlowSim run shows only about 5%
TBT and less than 1% TTFT change. A CCF-A motivation claim requires another
serving-visible mechanism or a valid packet-level integrated run; the
standalone +54% EP CCT / +96% KV FCT numbers must not be substituted for it.

## High-concurrency exposure attempt

A real 256-entry replay (128 active Decode + 128 concurrent 2048-token P2D,
Decode output 64) was attempted with the same S16/EP64/200-Gbps/LAYERWISE
configuration.  It reached the 1,200-second wall-clock limit without a
complete request CSV.  The FlowSim worker peaked at approximately 2.76 GiB
RSS; the wrapper cleaned up the child processes.  No TTFT/TBT values were
inferred from this timeout, and the matched fan-in run was not started.

## Corrected parallel-link topology gate (2026-09-28)

The initial packet numbers above are superseded for any claim about ECMP or
parallel leaf-spine use. A source audit found that the old topology builder
stored parallel interfaces in `nbr2if[(src,dst)]`, so later links overwrote the
same pair key. The route table consequently exposed only one physical link of
a parallel bundle. Those old packet-level spread/fan-in values remain useful as
historical debugging output only, not as valid multilink evidence.

The topology representation was corrected in the native ns-3 backend:
`nbr2ifs[(src,dst)]` retains every physical interface, and route-table setup
adds all interfaces as ECMP next hops. The endpoint route key was also aligned
with the address used by `send_flow()`. Every physical Qbb device is now
registered for link telemetry.

A single unchanged 96-request spread replay was rerun with the corrected
binary, S16/EP64/200 Gbps/4-KB packets and the original event ledger. It
completed 12,240 events in 409.88 s wall time with 344,160 KB maximum RSS.
There were 512 physical directed link rows, all at 200 Gbps. For the
representative leaf-to-spine pair 128 -> 132, all 16 physical links carried
traffic:

| quantity | corrected replay | old replay |
|---|---:|---:|
| physical links in pair | 16 | 16 rows, but 15 idle |
| non-zero links | 16 | 1 |
| aggregate TX bytes | 3,273,601,792 | 3,255,619,328 |
| minimum / mean / maximum per-link TX | 187.5 / 204.6 / 260.2 MB | 0 / 203.5 / 3,255.6 MB |
| maximum per-link queue | 4.05 MB | 9.97 MB |
| ECN marks on pair | 19,689 | 76,683 |
| PFC pauses on pair | 1,693 | 37 |

The corrected packet FCT distribution was mean 0.233 ms and P99 0.591 ms,
versus 43.299 ms and 108.019 ms under the old single-link route. This large
change is expected: the old result serialized the pair through one 200-Gbps
link, while the corrected route exposes 16 independent 200-Gbps links. A
single flow still uses one selected physical path/interface; 3.2 Tbps is only
the aggregate capacity of the 16-link pair.

This gate validates the physical-link representation and telemetry. It also
invalidates the old packet-level +54% EP / +96% KV fan-in comparison as a
corrected ECMP/multilink result. No new serving-level claim is inferred from
this replay. The existing FlowSim serving result remains the only valid
integrated evidence in this gate, and its approximately +5% TBT / <1% TTFT
fan-in gap is below the motivation threshold.

### Corrected fan-in16 replay

The matched fan-in16 event ledger was also rerun with the corrected parallel-link
backend. It completed all 12,240 events in 432.20 s wall time with 342,100 KB
maximum RSS. Unlike the old run, every parallel leaf-spine pair retained all
16 physical links. Relative to corrected spread, the packet-level distribution
was:

| metric | corrected spread | corrected fan-in16 | fan-in16 relative |
|---|---:|---:|---:|
| flow FCT mean | 0.233 ms | 0.304 ms | +30.7% |
| flow FCT P99 | 0.591 ms | 0.797 ms | +34.9% |
| request KV handoff mean | 32.753 ms | 32.881 ms | +0.39% |
| request KV handoff P99 | 46.493 ms | 46.673 ms | +0.39% |
| EP collective CCT mean | 0.203 ms | 0.222 ms | +9.6% |
| EP collective CCT P99 | 0.366 ms | 0.473 ms | +29.1% |

The fan-in run increased traffic on the busiest corrected directed cuts (for
example 133 -> 130 and 132 -> 130), where all 16 physical links were still
used. This is valid packet-level evidence that destination concentration can
amplify EP collective tails without materially changing the request-level KV
barrier in this reduced workload. It is not integrated serving evidence: the
corresponding corrected FlowSim integrated gate remains approximately +5% TBT
and <1% TTFT for the tractable 96-request serving run.
