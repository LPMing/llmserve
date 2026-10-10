# Trace Workloads and Accounting

This document consolidates trace conversion, Mooncake hash semantics, native
traffic accounting, and time-varying workload notes.

## Conversion invariants

All converters under `experiments/pd_kv_ep/scripts/`:

- preserve source order and request identity;
- normalize the first valid timestamp to `arrival_time_ns = 0`;
- convert timestamps to integer nanoseconds;
- retain source file, source record index, and provenance;
- write invalid records instead of silently dropping them;
- never fabricate `input_tok_ids` when a source only has lengths or hashes.

## Converted datasets

| source | requests | duration | input P50/P95/max | output P50/P95/max | identity/reuse |
|---|---:|---:|---:|---:|---|
| Azure code | 16,803,695 | 604,799.920 s | 1,924 / 7,674 / 7,691 | 8 / 79 / 5,000 | no token IDs or sessions |
| Azure conversation | 27,303,999 | 604,799.994 s | 933 / 4,936 / 7,999 | 41 / 451 / 1,200 | no token IDs or sessions |
| BurstGPT | 1,429,737 | 5,269,968 s | 251 / 2,461 / 29,665 | 34 / 460 / 7,315 | flat open-loop; no reliable session |
| Mooncake conversation | 12,031 | 3,537.000 s | 6,909 / 39,549 / 126,195 | 350 / 698 / 2,000 | block reuse 0.366 |
| Mooncake tool-agent | 23,608 | 3,537.000 s | 6,346 / 26,114 / 126,195 | 30 / 600 / 2,000 | block reuse 0.553 |

Azure uses `TIMESTAMP,ContextTokens,GeneratedTokens`; BurstGPT uses the
inspected `Timestamp`, request-token, and response-token fields. The main
BurstGPT replay is flat/open-loop and preserves zero-output rows. No session is
invented when the source does not provide a reliable one.

The full Azure and BurstGPT releases are intentionally not packet-replayed.
Every large-scale run is capped at 25,000 requests; candidate windows are
selected before expensive native validation. Mooncake is small enough for a
full converted trace, but bounded windows remain preferred for packet-level
experiments.

## Mooncake block identity

Mooncake `hash_ids` are opaque prefix-block identities, not token IDs. The
adapter stores them in `input_block_hashes` / `prefix_block_hashes` with a
512-token block size. Equal identities may represent cross-request reuse, but
hash similarity is never used to infer session ownership. Source-level reuse
and simulated cache hit ratio are reported separately.

The supported remote-cache path is modular:

```text
LOCAL_MISS       -> normal prefill computation
REMOTE_HIT       -> model-derived fetch of matched blocks
P2D              -> Prefill-to-Decode handoff
```

Remote bytes are computed from matched blocks, model layers, KV heads, head
dimension, precision, and TP/partition. They are never supplied as a
`REMOTE_KV_SIZE_MB` override. Both serving/Prefill-worker placement and a
dedicated cache endpoint per leaf are represented in the experiment artifacts.

## Native byte accounting

For Qwen3-30B-A3B BF16 at TP=1 Prefill, P2D KV is 98,304 bytes per input token.
At TP=2, the rank-shard accounting is preserved by the model/partition logic.
MoE dispatch and combine are generated from active tokens, hidden size, top-k,
precision, EP degree, and the route matrix. The study does not turn old
synthetic `1 GiB KV` or periodic EP flows into LLMServingSim workload values.

The current simple motivation output labels its large and small points as
model/request-derived replay parameters; see the canonical report rather than
reconstructing bytes from a prose approximation.

## Time-varying workload

The native eight-request characterization has:

| phase | arrival | requests | input/output | intended state |
|---|---:|---:|---:|---|
| 1 | 0--1 ms | 2 | 8 / 32 | establish Decode population |
| 2 | 80--83 ms | 4 | 64 / 4 | P2D burst while Decode is active |
| 3 | 160--161 ms | 2 | 8 / 32 | later Decode-rich phase |

It uses deliberate prefix identities and observes a 50% total prefix-hit ratio.
This is demand characterization only; multi-request prefill batching can carry
batch-level rather than exact per-request P2D metadata.

## Accounting boundaries

- Trace distributions are not silently resampled into synthetic arrivals.
- Hashes are not token IDs.
- Source identity reuse is not the same as a cache hit.
- Offered demand in a time bucket is not packet overlap on a directed link.
- A request count of 25,000 is a safety cap, not a requirement to replay a
  full production week.

The scale, SLO, and cost policy is consolidated in
[`LARGE_SCALE_PLAN.md`](LARGE_SCALE_PLAN.md).
