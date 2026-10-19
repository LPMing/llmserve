# P2D KV versus active Decode EP on a shared physical cut

## Scenario and provenance

Four TP2 Prefill instances feed four TP2 Decode instances in two independent
EP4 groups on the retained five-node, 200-Gb/s topology. A running Decode
cohort receives a later 2048-token Prefill wave. The hardware/model/profile
and existing rank map are A (checked-in profile and prior integrated run);
the staggered arrival wave is C until a matched workload establishes its
frequency. Qwen3-30B-A3B has 48 layers, four KV heads and 128-dimensional
heads; 2048-token BF16 KV is 201,326,592 B/request, 100,663,296 B/TP rank.

## Cut, overlap and objective

Four new requests sending across one 200-Gb/s directed rail present
402,653,184 B, a 16.106-ms serialization floor in aggregate, or
335.544 µs/layer. The measured 2048-token Prefill block is 1,339.101 µs,
so layerwise P2D can be hidden from the producer barrier while still sharing
links with an active Decode EP round. The prior Decode-only EP4 iteration is
6.1084 ms; two synchronized EP groups increased it to 6.157552 ms, and
one-time phase separation reached 6.108723 ms. Removing *all prior EP-only
cross-group interference* has at most 0.798% ITL headroom. That number does
not bound a new overlapping KV wave.

The new wave's possible gain needs the actual directed flow intervals and
Serving DAG: the critical path is `P layer → KV flow → P2D-ready` for new
requests and `D EP barrier → token 2 / ITL` for incumbents. Aggregate KV
serialization alone cannot be counted as either delay. At four sources the
mean P2D offered rate across one 1.339-ms block is below the 200-Gb/s rail;
the contention question is burst alignment with EP barriers, not assumed
steady saturation. A source/destination rail mapping check is mandatory.

## Strong baselines, Oracle and gate

Compare FAIR with `EP_FIRST`, `KV_FIRST`, existing phase staggering and
topology-aware P/D placement on identical resources/bytes. An optimistic
Oracle eliminates only the **extra** EP wait attributable to the new P2D
wave; it retains both EP and KV work. Its gain upper is unknown until the
overlap event is measured. `gain_upper < 10%` on modeled token-2, mean ITL
and completion over the matched cohort is `NO_GO`; any benefit available to
`EP_FIRST` or topology greedy is not a new joint-policy gain. Related work:
network-aware D choice in [NetKV](https://arxiv.org/abs/2606.03910), class
priority/collective orchestration in Nuska and Symphony/Harmonics.

## Falsifiable prediction

With the new P wave released while D is active, at least one P2D KV flow
and one Decode EP flow must overlap on the **same directed link**. FAIR must
then delay a D collective and a modeled D token event; `EP_FIRST` should
recover most of that effect. If paths do not intersect, if the EP barrier
has slack, or if the strong baseline removes the change, this candidate
fails. Derivation: [derive.py](derive.py).
