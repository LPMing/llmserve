# C: joint network, D memory and Decode-compute bottlenecks

The initial exact-model state space uses the same Llama-3.1-8B BF16
RTX4090 TP1 profiles, normal3,400-block D pool and100-Gb/s declared cut
as A/B. Those are A model/profile inputs plus C placement; the physical
100-Gb/s server uplink ratio has a published precedent (B). The candidate
asks whether one-resource optimization can worsen modeled request
completion or SLO goodput after preserving GPU/NIC/KV budgets.

For a set of requests S, define `W_N=Σ_i bytes_i/B_cut`,
`W_M=Σ_live ceil((L_i+1)/16)` and `W_D=Σ_t C_decode(batch_t)`.
The network exposure threshold is `W_N > Prefill overlap slack` on the
P2D-ready path; the capacity threshold is `W_M > 3400` while a useful
P GPU or D GPU idles; the Decode-compute threshold is arrival token
work exceeding sustainable batched token service. These are distinct
necessary screens, not an additive latency formula. The exact critical
path is determined by the graph and scheduler event order.

For four12k prompts, profile-backed `W_N/C_P≈0.369`, memory ratio0.884,
and64-token D service/prefill ratio≈1.125. For four14k, corresponding
ratios are≈0.357,1.031 and≈0.977. Thus only the D capacity screen
crosses one between those two cases; no claim of a network bottleneck
is predicted. The two-source hot-prefix case from A instead has a
source-cut/hot-P ratio≈2.048, while D work is short. This provides two
candidate bottleneck regimes with the same GPU/NIC technology but not
the same request distribution.

The minimum negative/threshold tests reuse A/B, with per-request
last-flow→ready→admit→token2→completion audits. A causal multi-resource
ablation must hold four P, one D, the same requests/cut and pool while
changing only a legal admission, routing or cache decision. Strong
comparators are FIFO, SRPT/EDF, cache/load/network-aware routing, tuned
fixed P:D allocation, simple multi-resource scoring and, on≤16 jobs,
small-scale legal enumeration. A change in P:D ratio is a separate
resource-allocation contrast, never a gain of the admission algorithm.

No joint policy Oracle has yet been computed, so `Gain_upper` over these
baselines is unknown. This candidate stays at the theory gate until A/B
experiments show a real boundary crossing and a same-resource decision
whose outcome differs. The current simulator's zero-time control and
client-TTFT limitations apply. Derivation: [derive.py](derive.py).

## Round-19 follow-up: transfer order can change D capacity-release time

The matched B experiment now gives a four14k/64-token TP1/PP1 case
under correct two-stage FIFO with identical full-KV bytes. Three
requests obtain credit at Prefill completion (~1.645 s), using
3×876=2,628 of3,400 D blocks; the fourth876-block request cannot
obtain credit yet. With FAIR fluid sharing, three1.835-GB transfers
complete together after at least `3×1.835 GB/12.5 GB/s =440.402 ms`.
Their Decode work then proceeds as a cohort, and no fourth transfer
may start until one D request frees blocks.

A work-conserving FIFO network queue would finish one transfer after
at least146.801 ms, about293.601 ms earlier than FAIR's first ready
event. This could let Decode begin sooner and release one credit earlier;
the theoretical end-to-end upper bound is **not** simply293.601 ms,
because single-request Decode service and subsequent batching differ.
The falsifier is the full event chain: first-flow finish, P2D-ready,
first D completion, fourth credit, fourth ready and last completion.
Run the same requests, source cut, D pool and two-stage admission with
FAIR versus priority for the earliest-ready request. The existing
`KV_REQUEST_FIRST` FlowSim policy is an offline characterization
control; in this specific simultaneous-equal case choosing request0
corresponds to a lawful FIFO tie-break, but a general policy is not
validated by that one result. Compare simple FIFO/SRPT transfer order
before proposing any joint scheduling mechanism.

## Round-19 source-backed trace screen before another simulation

The committed `sharegpt-llama-3.1-8b-300-sps10.jsonl` has exact token
IDs, lengths and arrivals. The first 50 ordered requests are a
source-backed heterogeneous window, not a modified co-arrival burst.
The trace/model/profile are A inputs; mapping those requests onto the
declared 4P1D 100-Gb/s research topology is C. A replay with this
window must use source-prefix caching, D DELTA and online LFU/cache-aware
comparators, because disabling them would weaken the baseline.

The reproducible [`sharegpt50_screen.py`](sharegpt50_screen.py) reads the
unchanged workload and measured RTX4090 profile. Fifty prompts sum to
46,957 tokens or6,154,747,904 full-KV bytes. Their aggregate source-cut
serialization is0.492380 s **before** any DELTA saving. They arrive from
0.046927 to4.229722 s. The last request has708 outputs. Summing the
minimum measured latency of each canonical layer yields a deliberately
optimistic 16.642176-ms Decode iteration; its final707 Decode steps
alone require at least11.766 s, so the last request cannot complete
before15.996 s even with no waiting or network. The cut-time/last-job
unavoidable-time ratio is3.078%. This is a **fixed-work network-only
screen**, not a global Oracle or proof about policies that alter Decode
batching, memory residency or job order. It makes a network-order-only
claim on this real window weak; joint capacity choices still require a
legal strong-baseline/Oracle comparison before a paper claim.
