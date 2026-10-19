# Round 14: ordered public-trace screen for the short-output burst

## Decision

**NO_GO for using the four available Qwen-Bailian traces as evidence of a
frequent eight-source, distinct-prefix, short-output burst.** The
Round-13 eight-request cohort remains a valid controlled causal test, but
its frequency and online predictability are not established by this public
trace family. This is a bounded workload result, not proof that other
deployments never show the pattern.

## Data and conservative screen

The four already pinned files come from the
[Qwen-Bailian production-derived anonymous release](https://github.com/alibaba-edu/qwen-bailian-usagetraces-anon).
Its published schema supplies trace-relative arrival timestamps, input and
output lengths, turn index, and salted hashes for 16-token input blocks.
The local manifest pins the source revision and each raw SHA-256. No new
download or SwissAI mining was done.

The [screen](workloads/screen_prefix_bursts.py) scans requests in their
published order. A candidate root request (`turn == 1`) must have output
at most 128 tokens, input length either 1984–2304 (near the profile's
2048-token prompt) or the wider 1984–4096 range, and the exact ordered
first 124 block hashes must have appeared in an **earlier input**. It then
counts **distinct** 1984-token prefixes in fixed 100-ms and 1-s arrival
buckets. Earlier appearance is an optimistic reuse opportunity, not an
observed cache hit; no P/D roles, physical NIC map or destination cache
residency are present. The Qwen models are not the Llama-3.1-8B profile,
so this is a workload-shape screen only. The
[JSON result](workloads/prefix_burst_screen.json) includes source SHA-256
and all counts.

| Input window | Eligible requests across four files | Maximum distinct earlier-seen prefixes in a 100-ms bucket | Buckets with ≥4 in 100 ms | Maximum in a 1-s bucket | Buckets with ≥8 in 1 s |
|---|---:|---:|---:|---:|---:|
| 1984–2304 tokens | 440 | 2 | 0 | 2 | 0 |
| 1984–4096 tokens | 2612 | 2 | 0 | 4 | 0 |

Only one 100-ms bucket in the near-profile window has two distinct
earlier-seen root prefixes; the wider window has 37 such buckets, zero
with four. Even at the looser 1-s width, the wider window has only one
bucket with four and none with eight. These counts use optimistic prior
occurrence and therefore cannot be interpreted as actual simultaneous P
cache hits, let alone D misses. A 1-s bucket is much wider than the
20–172-ms target handoff interval, so it is a deliberately permissive
upper screen for a synchronized eight-source example.

## Implication

This trace screen provides no representative workload support for the
Round-13 8P distinct-prefix burst. The 2P hot-prefix source-cut threshold
is theoretically low, but even its matched near-profile root/short-output
100-ms pattern appears only once in the selected public traces, and its
P/D cache state is unknown. A paper cannot take the Round-13 controlled
87.8% D-residency gap as a production mean/P99 or achieved scheduling
benefit. The current candidate remains a measured **mechanism** with
`NEED_DATA` for an online cache-placement policy and a model/deployment
matched workload. Another random parameter sweep would not change this
evidence limit.
