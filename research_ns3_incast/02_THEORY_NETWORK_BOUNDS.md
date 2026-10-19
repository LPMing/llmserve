# Independent network and barrier bounds

## Model-derived bytes

For this Qwen3 configuration, the simulator's BF16 KV accounting is
98,304 B/token across all layers. At 4,096 prompt tokens:

```text
one request total KV = 98,304 × 4,096 = 402,653,184 B = 384 MiB
TP2 shard per rank   = 201,326,592 B = 192 MiB
```

Each request has two required shards, one on each independent Decode NIC rail.
Four requests therefore inject 1,610,612,736 application bytes. Per receiver
rail, four shards total 805,306,368 B.

## One-cut lower bound

One receiver NIC is 200 Gbit/s = 25,000,000,000 B/s. Ignoring all packet and
transport overhead, one TP2 shard requires:

```text
201,326,592 / 25,000,000,000 = 8.05306368 ms
```

For four equal shards released at time zero onto the same receiver cut, an
event-driven equal-share max-min fluid calculation gives all four completion
times at 32.21225472 ms. A one-request-at-a-time network oracle gives
8.053064, 16.106127, 24.159191, and 32.212255 ms; mean completion improves
37.5%, while the makespan is unchanged. The independent implementation is
`theory_network_bounds.py`; it does not call FlowSim code.

The two NIC rails are independent. The same calculation applies to each rail;
the request barrier is the max of that request's rail-0 and rail-1 shard
completions. Do not add the two shard bytes onto one rail.

## Packet-level observations against the bound

| Case | App bytes on cut | CC0 packet result | Interpretation |
|---|---:|---:|---|
| N0 one shard | 201,326,592 B | FCT 8.151317ms | 98.253µs above the app-payload-only lower bound; packet headers, startup/RTT and protocol behavior are present. |
| N1 two shards / one receiver | 402,653,184 B | mean FCT 16.261314ms | Near 2× the payload-only serialization bound, with receiver queue and local ECN. |
| N2 four shards / one receiver | 805,306,368 B | mean FCT 32.481310ms | 269.055µs above the 32.212255ms ideal fair bound (≈0.84%). The measured link is still 200G; no multi-spine aggregate is granted to one receiver. |
| N3 four shards / two receivers | two shards per receiver | mean FCT 16.261314ms | Splitting the fan-in over two independent 200G NICs approximately halves the barrier time. |
| N4 four shards / four receivers | one shard per receiver | FCT 8.151317ms each | Capacity control: no shared receiver queue or local CE. |

These are exact small-case observations, not large-sample latency distributions.
The packet completion result is close to, but is not required to equal, the
fluid lower bound.

## Network-only serialization bound

The packet fixed-release experiment offsets each two-shard request bundle by
8.2ms. Its mean absolute P2D-ready time is 20.451317ms (37.04% below the
simultaneous FAIR replay's 32.481310ms); makespan is 32.751317ms (+0.83%).
This is a fixed network-only release/pacing schedule, not a Serving policy or
feedback loop. Its gains are mean-objective redistribution; it does not improve
the completion time of the last request.

## Profiled LAYERWISE exposed-wait upper bound

The trace generator, in the `RTXPRO6000` BF16 TP2 profile domain, emits two
2,048-token chunks. The 96 distinct QKV release epochs span to 133.679955ms;
profiled Prefill compute ends at 135.319248ms. Four synchronized requests
produce a 2MiB/rank shard at every layer/chunk release.

| CC setting | Latest packet P2D-ready | Prefill compute end | Remaining compute slack | Maximum exposed Decode-admission wait in this fixed release projection |
|---|---:|---:|---:|---:|
| CC_MODE=0 | 134.059112ms | 135.319248ms | 1.260136ms | 0ms |
| CC_MODE=1 | 134.963180ms | 135.319248ms | 0.356068ms | 0ms |

The strict upper bound on saving *P2D-ready-to-Prefill-end* waiting for this
profile/release schedule is zero: both network completions precede the compute
endpoint. This is not a measured TTFT or TBT result. It is a barrier-exposure
bound for the frozen, profile-derived event ledger.

## Conditions that would be necessary for a Serving benefit

At minimum, network completion or a feedback response must extend beyond a
Serving-critical compute/admission boundary, or an online Serving choice must
avoid delaying a different critical request by scheduling independent ready
work. Neither condition appears in the current four-worker, one-request-per-
Prefill-instance workload. The next stage therefore does not have a justified
15% Serving-headroom hypothesis for this workload.
