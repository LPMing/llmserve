# Capacity-calibrated Decode × P2D characterization

This is a separate, bounded follow-up to the archived
`MINIMAL_IDEAL_KV_EP_FINAL_FAIL`. That earlier conclusion remains valid for
its tested D/K envelope; this report does not revise or rerun those points.

## Fixed configuration and measurement semantics

- Qwen3-30B-A3B-Instruct-2507, 48 layers, 128 experts, top-k 8, BF16 KV.
- 1 Prefill server + 2 Decode servers, 8 GPUs/server, 2 x 200-Gbps NIC/server,
  single ToR; EP16; actual Decode receivers; `LAYERWISE`; GateRouter-derived
  `A2A_P2P`; FlowSim; `FAIR`.
- The 8 Decode schedulers each use the existing default limit of 128 active
  sequences, so the configured aggregate ceiling is D=1,024. No runtime limit,
  topology, rate, routing, model-derived byte, or buffer is changed by this
  phase.
- FlowSim has no externally capped source rate. `rho` is unavailable. Its
  residual-fluid bytes are not switch queue occupancy and imply no packet
  queue, ECN, PFC, drop, or DCQCN result.
- For each point, the Decode-only cohort run derives the K injection timestamp
  from the actual events (all D admitted and at least four Decode token
  boundaries completed). A matched KV-only run and a FULL/FAIR run use the same
  K request. EP comparisons end at the first K Decode admission so K's own EP
  does not enter the measured cross-request P2D window.

## D32K1 round 1

Point: `d32_k1_i8192`; 32 D requests (`input=128`, `output=128`) and one K
request (`input=8192`, `output=2`). The event-derived K injection is
75,986,593 ns. D32 uses four D requests per Decode scheduler. The K request's
model-derived KV is 805,306,368 B; measured Decode EP bytes for the point are
5,349,703,680 B. No synthetic byte override is used.

Matched results from
[`results/capacity_calibrated_kv_ep/CAPACITY_CALIBRATED_KV_EP_EXPERIMENTS.csv`](results/capacity_calibrated_kv_ep/CAPACITY_CALIBRATED_KV_EP_EXPERIMENTS.csv)
and the per-point [`summary.json`](results/capacity_calibrated_kv_ep/points/d32_k1_i8192/summary.json):

| Metric | Isolated control | FULL/FAIR | Change |
|---|---:|---:|---:|
| EP CCT mean | 22.5095 us | 22.5560 us | +0.206% |
| EP CCT P99 | 29.576 us | 30.231 us | +2.215% |
| KV final-shard residual drain | 177.973 us | 196.324 us | +10.311% |
| KV request network handoff span | 366.067973 ms | 366.086324 ms | +0.005% |
| K TTFT | 371.129936 ms | 377.658361 ms | +1.759% |
| D TBT mean | 6.502648 ms | 6.505609 ms | +0.0455% |
| D TBT P99 | 6.502648 ms | 6.506824 ms | +0.0642% |

The K population is one request, so its reported P99 equals that single
request; it is not a multi-request tail distribution. EP CCT has 5,442 FULL
collectives versus 5,444 in the matched Decode-only control. The TBT
comparison contains 1,824 token intervals in each run. The request handoff
span barely changes because it is dominated by the 48-layer release span;
the final-shard residual drain changes more, but remains a sub-millisecond
component. FULL TTFT additionally includes the Decode admission/first-token
path, so it is reported directly rather than inferred from residual drain.

## Shared-cut diagnosis

The actual shared directed resource remains a 200-Gbps D0 ingress uplink
(e.g. `30->26`): P0→D0 KV and D1→D0 EP routes use that same link. During the
matched 368.624-ms measurement window:

- D-only time at link capacity: 9.680%; FULL time at capacity: 11.850%.
- D-only longest ≥90%-utilization interval: 5.243 us; FULL: 188.746 us.
- FULL max analytical fluid outstanding volume on the Decode ingress cut:
  4,318,076 B. This is not a packet queue measurement.
- FULL releases 3,566,469,120 EP bytes and 805,306,368 KV bytes in the cut
  window, corresponding to window-average release-rate proxies of 77.40 and
  17.48 Gbps respectively. They are not exogenous offered rates.
- KV/EP same-directed-link overlap sums to 3.620274 ms of link-time across
  the four Decode ingress links (0.2455% of aggregate link-time). Global
  temporal activity overlap is longer; the smaller number specifically
  measures shared directed-link exposure.

Diagnosis: D32 creates recurring full-utilization EP bursts on the shared
cut, and P2D overlaps some of them. But the shared-link overlap is sparse
relative to the measurement window; the request's layerwise release span
absorbs almost all of the added network service time. This is a real
cross-request shared-link interaction in the fluid model, but not yet a
serving-visible barrier knee.

## D64K1 round 2 and last-shard attribution

Point: `d64_k1_i8192`, same request shapes, model bytes, topology, routing,
and policy as D32. The K injection is event-derived at 87,850,193 ns. The
request again contains 384 model-generated 2-MiB KV shard flows (805,306,368
B total). EP bytes recorded for the point are 9,246,474,240 B.

| Metric | Isolated control | FULL/FAIR | Change |
|---|---:|---:|---:|
| EP CCT mean | 29.7185 us | 29.8176 us | +0.333% |
| EP CCT P99 | 38.751 us | 40.062 us | +3.383% |
| KV final-shard residual drain | 177.973 us | 219.918 us | +23.568% |
| KV request network handoff span | 366.067973 ms | 366.109918 ms | +0.0115% |
| Arrival-to-P2D-ready | 368.624 ms | 368.624 ms | unchanged |
| K TTFT | 371.129936 ms | 376.898707 ms | +1.555% |
| D TBT mean | 7.522048 ms | 7.528544 ms | +0.0866% |
| D TBT P99 | 7.522048 ms | 7.531225 ms | +0.1220% |

The 23.568% residual-drain result is a network-level last-shard service
effect, not a request-handoff or TTFT result. The KV event ledger identifies
the last flow in both matched runs as layer 472, 2,097,152 B, destination
rank 8, on `0->24 -> 24->30 -> 30->26 -> 26->8`:

- FULL requested the last-layer shard at 453,887,193 ns and completed at
  454,107,111 ns (219,918 ns residual).
- KV_ONLY completed the same last-layer shard at 454,065,166 ns (177,973 ns
  residual), a 41,945-ns delay in FULL.
- In FULL, the prefill-completion / P2D-ready barrier is 456,474,193 ns,
  2,367,082 ns after the last network shard. The same prefill completion
  timestamp is present in KV_ONLY. The extra 41.945 us therefore consumes
  only a small part of the layerwise release/compute slack and does not move
  KV readiness.

At the critical link during the final-shard interval, two KV flows remain
active for 209.718 us; EP is simultaneously active for 45.222 us. During the
24-EP-flow overlap, max-min allocation gives the KV class 1.923 GB/s and EP
23.077 GB/s on the 25-GB/s link. During the 32-EP-flow overlap the KV class
gets 1.471 GB/s. These are allocated fluid rates, not packet service samples.
This directly explains the increased final-shard drain. It does **not** make
that shard the Decode-admission critical event because prefill completion
occurs later.

At the full matched window, D-only cut time at capacity is 16.727% and FULL
is 18.886%; longest ≥90% interval is 10.486 us versus 209.718 us. FULL
analytical fluid outstanding volume peaks at 4,431,548 B. The same-link
KV/EP overlap is 6.883816 ms of aggregate four-link time (0.4669%); the
window-average released-byte proxies are 133.77 Gbps EP and 17.48 Gbps KV.
Exact offered `rho` remains unavailable.

The K TTFT increase is also not evidence that the extra KV residual reached
TTFT: `p2d_kv_ready_time_ns` is identical. FULL has 274,659 ns Decode
admission wait and an 8.000-ms post-scheduler first-token interval, versus
zero admission wait and 2.506 ms in KV_ONLY. This is a real integrated
FULL-vs-KV_ONLY difference under a loaded Decode service, but it is not
attributable to a changed KV-ready barrier from these data. The D TBT P99
change is only 0.122%. (The time-window TBT samples are 3,136 FULL versus
3,200 D-only; the fixed stop is the first K admission, so the sample counts
are not identical and both are reported rather than concealed.)

**Round-2 interpretation:** the shared link has real class overlap, and the
final shard suffers >20% residual-drain inflation. However, layerwise release
slack prevents that inflation from changing request handoff/KV-ready, so it
does not establish a ≥20% serving barrier. This is exactly the condition for
one `POST_PREFILL` mechanism-sensitivity control; it is not permission to
replace the main `LAYERWISE` workload or to continue increasing D before
checking whether removing release slack exposes the existing service delay.

## D64K1 POST_PREFILL granularity sensitivity — completed

Point: `post_prefill_matched_d64_k1_i8192`. This is an explicit sensitivity
case, not the primary serving mode and not numerically paired against the
LAYERWISE point at the same injection timestamp. It uses its own POST_PREFILL
D-only warmup and event-derived K injection (`103,966,521 ns`). Configuration,
model-derived bytes, routing, topology, and `FAIR` policy otherwise remain
fixed: 64 D requests (`128/128` tokens), one K request (`8192/2` tokens),
EP16, 1P2D, 2 x 200-Gbps NICs/server, and one ToR. The K request carries
805,306,368 B of model-derived KV; the EP collective flow-byte sum in the
comparison window is 10,209,853,440 B. This is the collective-flow metric,
not bytes on one cut: 6,806,306,816 B of EP and 805,306,368 B of KV were
released onto the four shared Decode-ingress links in that same window. No
synthetic byte override is used.

### Correctness and mode matching

The first attempted POST_PREFILL FULL replay reused the cached LAYERWISE
warmup. `_assert_full_prefix` detected that the D cohort's pre-handoff serving
events diverged, so that attempt is invalid and excluded from every metric,
summary row, and conclusion. Its partial artifacts are preserved separately
under `results/capacity_calibrated_kv_ep/points/post_prefill_d64_k1_i8192/`.

The runner now keys warmup caches and phases by transfer mode. The corrected
POST_PREFILL run generated its own warmup and passed the matched-prefix
assertion. It produced one valid K row in each KV_ONLY/FULL run and 64 valid D
rows in FULL. The complete `summary.json` and the appended experiment CSV row
are the authoritative artifacts. There is one K request, so every K P50/P95/P99
is that single observation, not a tail distribution.

Important semantic detail: in this implementation `POST_PREFILL` emits a KV
transfer after each scheduled prefill chunk, not one monolithic transfer only
after the entire 8,192-token prompt. With a 2,048-token prefill chunk budget,
the event ledger shows four 201,326,592-B releases, each split across D0/D1
(two 100,663,296-B flows). A chunk's SEND completion is part of that prefill
graph's completion; the next prefill chunk therefore starts after the prior
chunk's transfer has completed. This mode intentionally removes layerwise
release slack but adds a chunk-level compute/transfer dependency. Do not treat
it as a drop-in model of the normal LAYERWISE runtime.

### Matched network and serving results

| Metric | KV_ONLY | FULL/FAIR | Change |
|---|---:|---:|---:|
| EP CCT mean | 29.7168 us | 29.8077 us | +0.306% |
| EP CCT P99 | 38.751 us | 40.062 us | +3.383% |
| K final-release residual drain | 8.063264 ms | 9.636213 ms | +19.508% |
| K request network handoff span | 326.409056 ms | 332.716582 ms | +1.932% |
| K arrival-to-P2D-ready / prefill-TTFT | 400.877056 ms | 407.184582 ms | +1.573% |
| K TTFT (arrival to first Decode token) | 403.382992 ms | 422.027982 ms | +4.622% |
| D TBT mean (3,520 intervals each) | 7.522048 ms | 7.527781 ms | +0.076% |
| D TBT P99 | 7.522048 ms | 7.584976 ms | +0.837% |
| D TPOT mean (64 requests each) | 7.482472 ms | 7.488719 ms | +0.084% |

`K request network handoff span` is last required KV flow completion minus
first required KV flow issue; it is not the sum of per-flow FCTs. The
`final-release residual drain` is last flow completion minus the last KV
release. Both are request-level values here (`n=1`).

The per-chunk event times expose the mechanism. For the four KV releases,
FULL's final flow completion is later than KV_ONLY by 1.562, 3.177, 4.735,
and 6.308 ms respectively. The next release shifts by the preceding transfer
completion delta, while the inter-chunk prefill interval remains the same.
Thus the shared-fabric service penalty on each chunk propagates through the
chunk-level barrier and accumulates at the final KV-ready event. For the last
chunk specifically:

| Last chunk event | KV_ONLY | FULL/FAIR | FULL delta |
|---|---:|---:|---:|
| Release/request | 496.780313 ms | 501.514890 ms | +4.734577 ms |
| Completion | 504.843577 ms | 511.151103 ms | +6.307526 ms |
| Release-to-completion | 8.063264 ms | 9.636213 ms | +1.572949 ms |

So the 6.308-ms P2D-ready shift is not all extra serialization of the final
flow: 4.735 ms has already accumulated in later chunk release times, and the
last network service contributes a further 1.573 ms. The ready-time delta is
1.57% of the isolated arrival-to-ready time. K TTFT increases by 18.645 ms in
total, but the interval from Decode admission/P2D-ready to first token grows
from 2.506 ms to 14.843 ms (+12.337 ms). That post-admission interval is a
loaded Decode first-iteration/service effect; it must not be attributed to
KV handoff. No SLO profile was defined for this one-request sensitivity case,
so no SLO attainment claim is made.

During the matched observation window, the shared Decode-side 200-Gbps ToR
uplink cut is at capacity for 16.73% of D-only time and 18.68% of FULL time;
the longest >=90%-utilization interval is 10.486 us versus 9.668 ms. Peak
analytical fluid outstanding volume is 261,219 B in D-only and 201,301,142 B
in FULL. Same-directed-link KV/EP overlap sums to 6.781 ms across the four
Decode ingress links. These are FlowSim fluid-model observations, not packet
switch queue occupancy, ECN, PFC, or drops. The backend has no exogenous source
rate cap, so offered rho remains unavailable.

### Interpretation and stopping decision

This sensitivity confirms a small, real simulator-level cross-request effect:
Decode EP traffic increases per-chunk P2D service time, and POST_PREFILL's
chunk barrier propagates that delay into later KV releases and request
readiness. It does **not** meet the motivation target: residual drain is
19.51% (below 20%), request network handoff span is +1.93%, P2D-ready delay is
+1.57%, EP CCT P99 is +3.38%, and Decode TBT P99 is +0.84%. The larger +4.62%
whole-K-TTFT difference includes +12.337 ms after Decode admission and is
therefore not a KV-network-only gain/penalty.

Together with the primary LAYERWISE D64 result—+23.568% final-shard residual
but unchanged P2D-ready time—this shows that granularity/dependency semantics
decide how much network delay is exposed. It does not justify increasing D,
changing link rate/buffers, or launching a priority sweep. The calibrated
1P2D characterization ends here: LAYERWISE remains the serving baseline;
POST_PREFILL is only evidence that a synchronous chunk-level handoff can
expose some otherwise-hidden drain delay. No claim of a >=20% serving-level
KV/EP opportunity is supported.

Warmup, KV_ONLY, and FULL wall times were 1,629.34 s, 4.44 s, and 1,638.98 s
(about 54.5 minutes total). The corrected run completed normally. The
mode-specific runner change is limited to the optional `--pd-kv-transfer-mode`
argument and warmup-cache namespacing; the default remains LAYERWISE.

No scheduler, policy, routing, topology, byte, or packet-network changes are
part of this characterization.
