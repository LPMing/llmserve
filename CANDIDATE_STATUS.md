# Candidate status — Round 19 (2026-10-15)

Round 17's ten-line closure remains a historical screen of that evidence
pool. The new Round 18 gate separates validated motivation from paper
headroom. The leading controlled mechanism is documented in
`research_autonomous/MOTIVATION_REPORT.md`; no solution gain is claimed.

Round 19 preserves that motivation result and rejects the current A/B
paper cases after implementable strong baselines. A's history/varied-cost
fixture is solved on its modeled completion path by ordinary LFU. B's
matched early-credit contrast is solved to within 0.000252% by ordinary
two-stage FIFO under its explicitly scoped admission-only Oracle. C's
first network-order control yields 6.76% over FAIR, and the control is
itself a simple FIFO tie-break. `PAPER_HEADROOM_VALIDATED` remains open.

| New rank | Candidate | Motivation status | Strong-baseline and Oracle status | Next discriminator |
|---:|---|---|---|---|
| 1 | P/D KV residency inversion after ordinary D eviction | **`MOTIVATION_VALIDATED`** remains frozen. | Current A fixture `NO_GO` for additional paper headroom: under legal two-access history and 50%-varied filler sizes, LRU misses, but simple LFU reaches the ideal modeled target completion of 56.971 ms. Cost-aware retention has no separate target-completion room; one D and distinct keys make routing and single-flight inert. | Seek a source-backed workload with a lawful signal and residual gain after LFU, cost-aware placement, DELTA, single-flight and cache/load/network-aware routing. |
| 2 | Decode credit timing and source-KV ownership | Early-credit resource idling remains observed; opt-in two-stage source retention, late D credit and internal cancellation semantics now pass tests. | Current B fixture `NO_GO`: matched POST credit-only ablation gives two-stage FIFO 25.35%/22.56% over early; stronger early layerwise overlap still finishes 17.92%/18.07% later; two-stage's scoped FAIR/FIFO admission Oracle gaps are 0.000252% and zero. | Treat two-stage FIFO and early layerwise as strong protocol baselines; do not claim the simple two-stage gain as novel. |
| 3 | Joint network, D memory and Decode compute | Correct two-stage FIFO supplies a valid capacity/transfer baseline. | Uniform FAIR→simple FIFO-tie-break network order gains 6.76%, below the 10% screen. An unchanged first-50 Llama ShareGPT window has 0.492-s full-KV cut work versus at least 11.766-s last-request Decode work after arrival; its 3.078% fixed-work screen is not a global joint-policy bound. | Identify a legal joint memory/Decode-order decision that escapes FIFO/SRPT/LFU/DELTA/routing on observed workload state; do not infer it from the cut-only screen. |

## Earlier Round-17 candidate pool

The pool is ordered by remaining *credible* evidence, not by a weak-baseline
or zero-network Oracle difference. `A` is local measured/model-derived input,
`B` is published hardware/workload evidence, and `C` is an explicit scenario
assumption. A conditional upper bound is not a measured benefit.

| Rank | Candidate | Current gate | Strong comparator | Next discriminator |
|---:|---|---|---|---|
| 1 | Network-staged dual-memory handoff/backpressure | Cold and uniform30-request capacity-stress network stage `NO_GO`; opt-in modeled D credit repaired and validated, real transport timing still `NEED_DATA` | Capacity-aware FIFO/SRPT/EDF, tuned P:D ratio, [DMRS](https://arxiv.org/abs/2610.15579) | Seek stable source-backed long-context demand with a strong-baseline ≥10% theoretical margin before another policy run |
| 2 | Shared-source-NIC prefix placement | Fixed-byte scheduler `NO_GO`; ordered ShareGPT ideal prior-prefix bytes only7.59–7.90%, online policy `NEED_DATA` | D cache-aware selection, DELTA, single-flight, LFU/PrefixPlace | Source-backed recurring-prefix demand with an online signal and no D-resident alternative |
| 3 | P2D versus active Decode EP on one physical cut | **`NO_GO`** in 24-request matched case: exact same-direction overlap, but new P2D ready unchanged and old completion interference ≤0.279% | FAIR, EP_FIRST/KV_FIRST, topology-aware P/D placement, phase staggering | No scale-up without a different physical cut/workload and >10% bound; this fixture is exhausted |
| 4 | PP-stage KV coflow | `NO_GO` in profile-valid 4P1D TP2/PP2 case; flow finishes before ready | Layerwise FAIR, topology greedy | Reopen only on a physical cut whose *strong-baseline* critical path exceeds 10% |
| 5 | Fork-group replication degree | `NO_GO` for symmetric N=4; strong simple envelope leaves ≤3.45% | One D, equal four D, marginal-cost group greedy | Heterogeneous real branches plus source-backed group semantics |
| 6 | Heterogeneous P/D TP and NIC shape | **`NO_GO`** for Qwen3-32B 2048/600: two optimistic TP1 D workers reach only51.6% of one TP2 D on same GPUs | Best fixed same-TP2 role ratio and topology-aware pairing | Reopen only on a model-matched profile showing actual TP1 per-GPU advantage |
| 7 | Network-induced Decode KV-length skew and rebatching (new) | **`NO_GO`** for serial split: all249 memory-feasible measured shapes slow down, best by29.6% | Mixed batch, length bucketing, vLLM HPC-Ops | Multi-D routing only with ordered demand and an increment over length-aware routing/kernel |
| 8 | Agentic lower-tier KV prefetch | `NEED_DATA`/`SIMULATOR_UNSUPPORTED`: all765 SWE sub-requests have incomplete prompt IDs, no verified miss, and FlowSim CXL load is zero | On-demand load, SYMPHONY advisory prefetch | Exact token IDs, observed misses and a calibrated timed lower-tier load |
| 9 | FreeInference irregular agent fork (retained older candidate) | `NEED_DATA`: 277 shared-prefix sibling groups are observed, but provider models/tokenizer do not match local profiles, join is ambiguous and the simulator has no fork DAG | One-D/equal-D/marginal-cost group greedy, child-ready and parent-resume baselines | Exact-model prompt IDs, explicit join and provider-matched long-context profile |
| 10 | Chutes Qwen3-32B production arrivals (retained older candidate) | `NEED_DATA`: production arrivals/cache counts exist, but physical P/D roles, GPU/NIC topology and reusable prefix IDs are unreleased | NetKV-like cache/load/topology scorer, layerwise transfer, local Prefill deflection | Physical P/D placement and token-identical Decode cache state for a network-critical Serving claim |

Detailed theory cards and any experiment/iteration records live in
`research_autonomous/candidates/<name>/`. The ten earlier candidates
were gated by a measured sub-10% strong-baseline margin, missing
source-backed state, or a documented simulator boundary. Their old
conclusion does not invalidate the distinct Round-18 controlled
motivation gate; a `NEED_DATA` row is not a hidden positive result.
