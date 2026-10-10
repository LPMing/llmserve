# P4B Final No-Go: Split-Source KV Assembly

Date: 2026-09-29

## Decision

**`P4B_FAIL_LOW_SERVING_HEADROOM` / FINAL NO-GO.**

The current corrected remote-prefix baseline is semantically valid. The only
next architecture compatible with its explicit dependency is V1 dual
 destination:

```text
R -> P prefix, R -> D prefix, P -> D suffix
```

The two existing high-reuse Mooncake windows do not show an improvement over
`R -> P -> D`:

| Window | Remote-hit TTFT change | EP side effect |
|---|---:|---:|
| Simultaneous high reuse | +61.1% for two representative remote-hit requests | EP CCT unchanged |
| Staggered high reuse | +22.9% to +32.0% for three remote-hit requests | EP CCT mean +25.0%, P99 +62.5% |

The result is caused by a real critical-path interaction:

```text
R->D extra copy
 -> shared provider/fabric contention
 -> R->P completion later
 -> suffix compute later
 -> suffix P2D barrier later
 -> TTFT later
```

The V1 implementation reduced the P2D suffix bytes and preserved exact
model-derived logical KV receipt. It did not obtain a serving gain because the
R-to-P dependency remains necessary in the current semantics and the R-to-D
copy is not free.

## What is proven

- Current B1 `REMOTE_PREFIX_PD_BASELINE` remains regression-equivalent after
  adding V1 support.
- M0/M1/M2 split-source accounting and role separation pass.
- Remote prefix reuse can change Prefill compute and TTFT.
- The current simulator's suffix Prefill path requires remote prefix
  materialization at Prefill.
- A legal dual-destination characterization can move bytes from P2D to R2D,
  but can worsen the serving barrier.

## What is not proven

- A pure R-to-Decode-only V2 architecture; it is not supported by the current
  dependency model.
- A positive split-source TTFT opportunity.
- A provider-placement, replica-selection, or remote-KV/EP scheduling gain.

No further P4 stress search is justified without a new runtime-supported
primitive. Do not increase provider fan-in, reduce bandwidth, synchronize
requests, or enlarge remote KV merely to reverse this result.
