# A: P/D prefix asymmetry under ordinary D eviction

## Deployment, requests and provenance

Two RTX4090 TP1/PP1 Prefill GPUs share a documented-style 100-Gb/s source
NIC; one RTX4090 TP1/PP1 Decode GPU has its normal 24-GB, 0.9-utilization
3,400-block KV pool. The model is Llama-3.1-8B BF16 with measured RTX4090
profile (A); the physical rail map and ordered 2-key demand are controlled
assumptions (C), based on the 8-GPU/100-Gb/s server ratio published by
[UBELIX](https://hpc-unibe-ch.github.io/hardware/gpu/) (B). Every request
has one D target; no expert-distributed KV copies. Two distinct1,984-token
prefixes are warmed at P0/P1 and D. Fresh2,048-token random fillers each
arrive after the previous wave; two distinct 2,048-token targets with64
fresh suffix tokens arrive at4.8 s. Each output is3 tokens, allowing
token-2 and completion checks. The sequence is a **mechanism fixture**,
not a production workload or SLO distribution.

## Resource threshold and critical path

The model produces131,072 B of KV per prompt token, hence full
2,048-token P2D sends268,435,456 B/request and a64-token delta sends
8,388,608 B/request. Two full copies need42.950 ms on the source100-Gb/s
cut; two deltas need1.342 ms. The measured hot-P block costs about
20.969 ms/request, whereas a cold Prefill costs193.161 ms. The relevant
path is target arrival → hot-P Prefill/flow release → final KV flow →
P2D-ready → D admission → token 2 → completion. Hot-P full-KV wire time
can exceed the Prefill barrier; D-hit delta service is hidden.

Each warm key uses124 blocks; a distinct filler uses128. With two warm
keys,24 fillers occupy at most3,320 of3,400 D blocks and should leave
both prefixes resident. The25th filler first exceeds the pool;28 fillers
exceed it by432 blocks, enough to evict both old124-block prefixes under
the actual free-list LRU order. Each P sees at most14 fillers, so its own
maximum1,916-block footprint remains below3,400. The predicted
crossing is therefore D-miss while both P prefixes remain hits. If
fillers overlap targets, a source cut or D queue confounds this test and
the run is invalid for this inference.

## Falsifier, baselines and Oracle

Negative control:24 fillers, both D prefix queries hit and each target
sends only its64-token delta. Positive threshold:28 otherwise identical
fillers, both D queries miss and each target sends full2,048-token KV.
Causal ablation: restore the original D prefix state without changing
target arrival, ranks, cut, P cache or model; P2D-ready and token 2 should
return to the delta path. The predicted event is a jump in last-flow and
P2D-ready, not merely network FCT. All output timestamps and flow bytes
must be conserved. A partial hit at25/26 fillers would locate the
threshold more precisely rather than count as a failed theory.

For motivation, the conditional miss-vs-hit cost can be observed without
an algorithm. For **paper headroom**, the strong comparator combines
LRU/LFU, cost-aware retention, cache-aware D routing, single-flight and
DELTA. The ideal all-prefix-resident state is only an Oracle; its
conditional42.95-vs20.97-ms difference is not an achieved gain over the
composite baseline. The currently registered incremental headroom is
**unknown**: all prefixes have one prior access, so no lawful online
rule can know which will recur without a stronger history signal. A
new online cost signal and small legal cache-placement enumeration are
required before `PAPER_HEADROOM_VALIDATED`.

## Known model limits

FlowSim is fluid and lacks NIXL startup/control timing. Destination
prefix query and D credit are zero simulated ns. Simulated first token
is a graph-completion proxy; only P2D-ready, token 2 and completion are
used here. The profiler covers the requested chunk/context range and
the physical rank map is explicitly checked. Full derivation:
[derive.py](derive.py).
