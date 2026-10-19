# Round 12: prefix acceleration exposes a shared source NIC

## Decision

**MECHANISM_VALIDATED, PAPER_GAIN_UNPROVEN.** On a topology anchored to
[UBELIX's 8×RTX4090/one-100-Gb/s node](https://hpc-unibe-ch.github.io/hardware/gpu/),
measured Llama-3.1-8B TP1 kernels and a causal FlowSim Serving run agree:
Prefill prefix hits shrink the layer compute interval while a Decode miss
still requires the full KV. The 100-Gb/s source cut becomes the P2D-ready
critical path. The result is a controlled mechanism, not evidence that a
new policy beats an existing cache-aware Decode selector. In these fixtures
the destination-resident copy is idle and immediately selectable.

## Setup and registered prediction

The [theory input](theory/round12_prefix_inversion.json) covers 2,048-token
BF16 Llama-3.1-8B requests on the checked-in RTX4090 TP1 profile. One
request has 268,435,456 B of KV, 8,388,608 B per layer. The one-layer
100-Gb/s serialization floor is 671.089 µs. The profiled cold block takes
5,995.177 µs; a 1,984-token prefix hit plus 64 fresh tokens takes
614.049 µs. The synchronous source-cut screen is

`A(m,h) = m × 671.089 µs / C_layer(2048 × (1-h))`.

It is a capacity/overlap screen, not an exact lower bound on request-ready
time. At 8 sources it moves from `A=0.896` cold to `A=8.743` hot. The
simple hot two-source excess is `32×(2×0.671089−0.614049)=23.300 ms`;
the analogous eight-source value is 152.15 ms. These numbers were registered
before the sweep, with no timing calibration to the FlowSim output.

The [runner](experiments/prefix_inversion/run.py) places 1, 2, 4, or 8
Prefill GPUs on one 100-Gb/s source node. It distributes one Decode GPU per
Prefill GPU over two separate 100-Gb/s destination nodes. Every GPU has a
200-Gb/s local endpoint link; P2D flows share only the documented 100-Gb/s
source uplink. No requests are forced to one Decode GPU. A first request
warms a real 16-token-block prefix on each P and one D. At 350 ms the
target is routed either to its warm D or an otherwise idle cold D. The
same physical resources are present in both cases. All warmups complete
before 350 ms. Cache lookups and D admission are event checked. Prefix hit
sizes are 0, 1024, 1536, 1792, 1920, and 1984 tokens. The 24 full-KV
D-miss cases plus four 1984-token D-resident controls are archived with
inputs, manifests, requests, events and per-flow telemetry. FlowSim FAIR
and layerwise P2D are held fixed.

## Observations

Target metrics below are elapsed from the 350-ms arrival, not simulator
absolute time. Each target has three output tokens, so token 2 and complete
timestamps exist. No target waits for Decode sequence capacity. Values in
one cohort are equal, and these are controlled cohorts, not production P99s.

| P GPUs sharing source NIC | Cold D-miss P2D-ready | 1984-hit D-miss P2D-ready | 1984-hit D-resident P2D-ready | D-miss minus D-resident |
|---:|---:|---:|---:|---:|
| 1 | 193.161 ms | 21.552 ms | 20.969 ms | 0.583 ms |
| 2 | 193.161 ms | 43.027 ms | 20.969 ms | 22.058 ms |
| 4 | 193.161 ms | 85.977 ms | 20.969 ms | 65.008 ms |
| 8 | 193.161 ms | 171.876 ms | 20.969 ms | 150.907 ms |

Every D-miss target carries exactly 268,435,456 B in 32 layer flows.
Every D-resident target carries exactly 8,388,608 B, the 64-token delta,
also in 32 layer flows. In the eight-source hot D-miss case, 2,147,483,648 B
cross the source node's `24→27` 100-Gb/s link. Its 171.799-ms serialization
floor nearly equals the 171.876-ms measured ready time. The last required KV
flow ends at the ready/admission time, then token 2 occurs at 189.004 ms and
completion at 206.132 ms after target arrival. Decode capacity queue wait is
zero. In the eight-source cold case, the last flow finishes 1.110 ms before
the 193.161-ms ready barrier, proving network work remains hidden. In the
eight-source D-resident control the last delta flow finishes 1.504 ms before
the 20.969-ms barrier. Both D nodes receive targets and have independent
uplinks, so the critical cut is on the source node.

Across the full hit sweep, the 8P D-miss ready time falls from 193.161 ms
at zero hit to 172.152 ms at 50% hit, then plateaus near the 171.8-ms NIC
floor. At 2P, it follows compute through a 75% hit, then plateaus near
43 ms. This is a **bottleneck inversion and diminishing cache benefit**.
Higher hit does not increase absolute latency in this experiment. The
[figure](experiments/prefix_inversion/prefix_inversion.pdf),
[summary and hashes](experiments/prefix_inversion/summary.json), and
[analysis script](experiments/prefix_inversion/analyze.py) retain the full
theory/measurement comparison and conservation checks.

## Strong-baseline and novelty audit

The 150.907-ms eight-source difference is a **conditional cache-state
comparison**. It is neither an achieved new-scheduler gain nor an oracle
subtracted from network FCT. Given the idle warm D in this fixture, ordinary
cache-aware Decode choice plus existing delta handoff selects the 20.969-ms
path. Thus the incremental gain available to the proposed joint scheduler
over that baseline is **zero in this fixture**. The D-miss branch is valid
as a causal control but is a deliberately suboptimal placement choice when
the warm D is free. No paper GO is asserted.

Recent work narrows novelty considerably. [HMA-Serve](https://arxiv.org/abs/2606.29986)
already pipelines per-layer KV with Prefill computation.
[NetKV](https://arxiv.org/abs/2606.03910) explicitly combines Decode cache,
load and network cost in Decode selection.
[SGLang's 2026 Q4 roadmap](https://github.com/sgl-project/sglang/issues/43699)
says Decode-side radix/HiCache delta transfer has shipped, while cache-aware
Decode steering and proactive movement are current engineering gaps.
[PrefixPlace](https://arxiv.org/abs/2608.01655) already optimizes
memory-constrained, source-dependent prefix placement, though its planning
objective uses static transfer costs and routing is outside its optimizer.
[CacheRoute](https://arxiv.org/abs/2608.19677) plans warm-prefix affinity.
[TraCT](https://arxiv.org/abs/2512.18194) attacks a NIC KV-transfer bottleneck
with a CXL substrate. A paper cannot claim layerwise overlap, Decode delta,
cache-aware routing, or generic prefix placement as its own mechanism.

The distinctive remaining question is narrower: when P retains a hot
prefix but all feasible D replicas have naturally evicted it, can an online
placement/replication policy justify its memory and network cost and beat a
strong composite of Decode cache-aware selection, source-group routing,
local recompute and static prefix placement on end-to-end request metrics?
The present simulator does not time prefix control-plane queries, NIXL
transport, packet congestion or client egress. `first_token_visible_ns` is
the P/D graph-completion proxy, so these results are called P2D-ready and
modeled token 2, not hardware TTFT. FlowSim uses fluid max-min sharing.

## Next discriminating loop

Produce **natural D eviction** under the normal RTX4090 24-GB, 0.9 memory
budget while P retains its prefix, with ordinary distinct requests and no
forced cache clearing. Use 8 P GPUs on the one-NIC node and two D GPUs on
separate 100-Gb/s nodes; route four P GPUs to each D and keep outputs short
enough that D compute/capacity is not the target bottleneck. Verify P hit,
all-D miss, KV block eviction and no live D alternative before testing a
policy. If this fails, the current mechanism remains valid but the paper
setting lacks an evidenced operating point. The full SwissAI file remains
archived and unmined until a stronger-baseline solution exists.
