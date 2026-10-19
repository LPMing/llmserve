# B: timing of Decode KV capacity credits

## Deployment, requests and provenance

Four RTX4090 TP1/PP1 Prefill GPUs share a 100-Gb/s source NIC and send to
one RTX4090 TP1/PP1 Decode GPU with the normal3,400-block pool. Llama-3.1-8B
BF16 and the 2,048-token chunk/16,384-context profile are measured (A);
the 4P:1D physical placement, four concurrent requests and64-token
outputs are controlled assumptions (C). The 100-Gb/s host uplink has a
published hardware-ratio precedent (B), but this exact P:D allocation
is not a measured deployment. No prefix caching is used. Four prompts
are either12,000 or14,000 tokens and arrive together. A64-token output
is a plausible short completion class, not a claimed production
frequency. The same GPUs/NIC/D pool and output work are used in both
threshold cases.

## Resource model and trigger

Each prompt token produces131,072 B of aggregate KV. A12,000-token
handoff is1.573 GB and needs751 D blocks including the first Decode
slot; four credits need3,004 blocks and fit. A14,000-token handoff is
1.835 GB and needs876 blocks; four credits need3,504, crossing the
3,400-block pool by104. The first impossible prompt length for four
credits is13,600 tokens. Four-request source-cut serialization floors
are503.316/587.203 ms for12k/14k respectively. Profile sums over
legal≤2,048-token chunks give1.364/1.644 s of per-P Prefill compute;
Decode step for three14k-context requests is23.147 ms, so64 tokens
take about1.481 s before batch/graph overhead. The4P:1D ratio is near
compute balance for this output length, rather than obviously
underprovisioning D.

Current opt-in protocol grants D credit **before** a P request computes
and holds the blocks through P compute and D completion. Thus at14k,
three credits fit and the fourth P should stay idle while D has zero
running requests until the first Prefills finish. At12k all four can
begin. The key path is arrival → P admission/credit → Prefill chunks →
last P2D flow → P2D-ready → Decode admission/64 steps → completion.
Measured timestamps must distinguish blocked P time, pre-P2D D-block
hold, D capacity wait and actual Decode queue time. A pure NIC FCT
difference would not establish this issue.

## Falsifier, strong baselines and upper bound

Negative control: four12k prompts, no `HANDOFF_CAPACITY_WAIT`, all P
workers start. Threshold: four14k prompts, the fourth P waits for a D
credit even while D has no running work. The minimum causal ablation is
a correct two-stage protocol that computes and retains P KV before a
just-in-time D credit and only releases P2D bytes after that credit;
it must preserve source KV, allow bounded waiting/cancellation, and
conserve all bytes/blocks. It has not yet been implemented. A zero-time
JIT Oracle may estimate an *upper bound* from measured P and D service,
but cannot be reported as achieved improvement.

The realistic strong set is capacity-aware FIFO, size-aware/SRPT,
EDF/SLO-aware, tuned P:D ratio and a simple two-stage admission. There
is no request deadline in this four-request fixture, so EDF has no
distinct decision; no SLO-goodput claim is possible yet. A mechanism
that only beats early reservation but ties two-stage FIFO is not paper
headroom. `Gain_upper` over the strongest legal baseline is currently
unknown. If the threshold event fails, inspect true pool occupancy,
prefill stage ordering, graph release, and request routing before
changing the scenario.

## Applicability limits

The credit has zero modeled control latency and is a simulator protocol,
not a measured production NIXL admission design. Profiled attention
covers up to16,384 context; neither12k nor14k requires extrapolation.
FlowSim excludes default TP/OTHER service, but TP=PP=EP=1 here. The
synthetic short-output/long-prompt combination needs external validity
checks before a system-paper claim. Reproducible profile arithmetic:
[derive.py](derive.py).

## Registered Round-19 same-work transfer comparison

For credit-timing attribution, compare `EARLY_POST` and
`TWO_STAGE_FIFO` with the same four14k/64-token arrivals, normal D
pool and **post-Prefill full-KV transfer**. In both arms every request
computes14k prompt tokens, sends1,835,008,000 B and decodes64 output
tokens. Early credit waits before P compute; two-stage FIFO computes
on the otherwise idle fourth P, holds its source KV and waits for
receiver credit before emitting any P2D SEND. Both therefore pay the
same transfer granularity. The original Round-18 LAYERWISE run remains
an independent reference, not the treatment baseline for this gate.

For external shape sensitivity, an ordered heterogeneous control uses
four jobs `(prompt, output, arrival_s)` = `(12000,32,0)`,
`(14000,96,0.2)`, `(14000,48,0.4)`, `(16000,64,0.6)`.
The first three credits consume751+876+876=2,503 D blocks; the fourth
needs1,001, taking the set to3,504>3,400. All prompt and Decode KV
lengths stay within the profiled16,384-context axis. The predicted
direction is that early credit delays P4 before compute while two-stage
starts P4 on its idle P GPU. If either arm violates byte, block,
credit-before-flow, source-hold or completion invariants, mark it
`INVALID` before comparing completion. A legal Oracle may move the
fourth P's compute earlier but cannot transfer before credit; if
two-stage FIFO approaches it, incremental B headroom is `NO_GO` in
this fixture.
