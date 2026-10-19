# Theory and Threshold Recalculation

## Model-derived KV bytes

For BF16 K and V, 48 layers, 4 KV heads, head dimension 128:

```text
bytes/token = 2(K,V) × 48 × 4 × 128 × 2 bytes = 98,304 B
full 4,105-token KV = 4,105 × 98,304 = 403,537,920 B
4096-token prefix KV = 4096 × 98,304 = 402,653,184 B
9-token suffix KV = 9 × 98,304 = 884,736 B
TP2 delta per rank = 442,368 B
```

If the destination already owns all 4096 matching prefix tokens, correctly suppressing their redundant P2D payload reduces the request's P2D payload by `402,653,184 / 403,537,920 = 99.7808%`. Decode still needs both the existing prefix blocks and the transferred suffix; this is not a zero-byte request.

## The originally quoted 15% TTFT bound

The historical report used the logged 4-hit value 32.539480 ms and a 27.068000 ms compute floor:

```text
(32.539480 - 27.068000) / 32.539480 = 16.8149%
32.539480 × 0.85 = 27.658558 ms
27.658558 - 27.068000 = 0.590558 ms
```

The arithmetic is correct, but its premise is not: 32.539480 ms is the delay to the **P2D graph/handoff completion** from child arrival, not a separately measured client TTFT. The sampler compute node completes at 177.175 ms in both A0 and A2. In A0, the last KV flow completes at 182.646480 ms; in A2, the last delta flow completes at 176.419675 ms, 0.755325 ms before sampler completion. Thus A0 has a 5.471480 ms post-sampler handoff tail, but A2's graph is compute-limited at the sampler event. The tail cannot be counted as client TTFT savings without a client-visible token event whose dependency semantics say that the token is withheld until P2D completes.

Therefore the 16.8149% figure is not a valid serving TTFT opportunity for this implementation. The actual external client-delivery time is not represented as a distinct event; the best event-level observable is sampler-ready time. Under that proxy, A0 and A2 are identical: 27.068 ms from child arrival. This does **not** prove all real PD runtimes expose the token before or after handoff; it proves the current logs cannot substantiate the old TTFT claim.

## Request completion and decode intervals

Four-target 4P1D child request:

```text
A0 final token: 211.436480 - 150.107000 = 61.329480 ms
A2 final token: 205.965000 - 150.107000 = 55.858000 ms
child end-to-end reduction = 8.92%
```

Using sampler-ready as the first output token event, A0 intervals are 19.866480 ms and 14.395000 ms; A2 intervals are 14.395000 ms and 14.395000 ms. Thus the three-output mean inter-token interval (`(last_token - first_token)/2`) is 17.130740 ms for A0 and 14.395000 ms for A2, a 15.97% decrease. This is a small-fixture decode-interval result, not TTFT gain and not a production tail statistic. The currently emitted CSV `TTFT`/`ITL` for A0 anchors the first token to P2D graph completion and consequently omits the first sampler-to-second-token interval.

## Fixed-resource P:D candidate

Full root sessions finish at a mean 211.436480 ms in 4P1D and 201.797000 ms in 3P2D:

```text
(211.436480 - 201.797000) / 211.436480 = 4.56%
```

The slowest session changes from 211.436480 ms to 226.790000 ms, a 7.26% regression. The child-only average is 47.768500 ms in B1 versus 61.329480 ms in A0 (22.10% lower), but the child arrival times are correctly allowed to move with each configuration's warm-up completion, one B1 child is substantially slower, and the full-session objective improves only 4.56% on the mean while worsening the maximum. The child-only percentage is not the Gate B decision metric.

The old conditional 22.08% estimate (47.789 ms against the 4P1D child mean) assumes a fixed target-arrival anchor and predicted placements. It is not comparable to full-session replay and is superseded by B1's actual session DAG outcomes.

## Interpretation

- Cache bytes were reduced as intended in DELTA mode.
- A0's network drain tail was after sampler compute; hence it moved P2D-ready but not the sampler-ready proxy.
- B's static resource change affects both warm-up completion and child release/cache placement. Its measured full-session benefit is modest and not uniformly positive.
- No SLO thresholds were predeclared for this four-session fixture, so no SLO attainment is reported.
