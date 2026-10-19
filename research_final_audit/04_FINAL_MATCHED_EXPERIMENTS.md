# 04 — Final matched experiments and unrun comparisons

## What is matched evidence

Historical rows below belong to different experiment families and must not be
combined into one synthetic table. A matched comparison means identical request
set, arrivals, model-derived bytes, topology, route realization and serving
semantics, except for the named intervention.

| Question | Comparison that exists | Measured result | Limit |
|---|---|---|---|
| Can class priority protect active Decode EP? | Controlled S16 / EP64 / 8P8D / 200G, 32 active Decode + 64 P2D; FAIR vs EP_FIRST | EP CCT P99 92.279→45.644 µs (−50.54%); TBT P99 8.862→6.937 ms (−21.72%); TPOT −17.26%; KV-ready unchanged | Controlled alignment; it establishes a mechanism, not natural incidence or policy novelty. |
| Does KV-only route pressure move a request handoff? | KV–KV shard-level controls with request last-shard joins | Small-victim shard FCT P99 up to +25.35% | Request P2D-ready/TTFT generally unchanged because layerwise release slack absorbs the shard tail. |
| Is natural KV/EP coactivity serving-critical? | Azure Code `013818` first 44 and Conversation `06210` first 16; retained integrated event joins | Same-link coactivity exists; all sampled KV last completions precede Prefill completion, with ≥0.709 ms slack; no positive matched barrier delta demonstrated | No final isolated-network or service-order matched causal counterfactual for these windows. |
| Is EP–EP collective scheduling visibly important? | Two independent EP4 groups; same fixture with/without the second group | Dispatch CCT +6.39%; combine +1.58–3.11%; TBT/TPOT +0.75–0.80% | Original realization was AG/RS, not sparse routed A2A; serving effect is small. |
| Does Decode-opportunity ordering help a particular request? | Frozen two-request controlled FlowSim fixture; FAIR vs request-first intervention | Target P2D-ready advances ~4.038 ms; arrival-to-second advances ~3.381 ms in one seed; pair mean ~0.85%; neighboring 13-token seed ~43 µs | Narrow phase/lane boundary; second-token event is not a validated client TTST; not a request-tail result. |
| Does new sparse-A2A geometry produce a PD-specific effect? | BurstGPT first16, exact route surrogate vs same-source-byte counterfactual; EP_ONLY, FULL, KV_ONLY | Route realization changes approximate CCT, but nearly the same gap is already present in EP_ONLY; P2D adds 0–3.787 µs to only one of 336 phases | Counterfactual changes destination assignments and layers are coalesced; invalid as serving or deployable evidence. |

## Final old-line policy matrix: intentionally not run

The requested final natural-window comparisons against EDF/LLF/SRPT/coflow/Nuska
surrogates and a serving-aware offline oracle were **NOT_RUN**. The natural
exposure and global-headroom gates did not pass, and the available event records
do not define a trustworthy counterfactual for those schedulers. This is not a
zero-gain result and is not evidence that those methods fail. It is a deliberate
stop: running an algorithm matrix after the causal opportunity gate failed
would produce a large, weakly interpretable result set.

## Reproduction boundary

The new sparse-A2A screen used five FlowSim runs: exact EP_ONLY, exact FULL,
exact KV_ONLY, counterfactual EP_ONLY and counterfactual FULL. It did not run
native ns-3, HTSim, or a network-completion-driven serving scheduler. The run
artifacts are under [`sparse_a2a_minimal/`](sparse_a2a_minimal/); exact commands
and hashes are in [`12_REPRODUCIBILITY_AND_HASHES.md`](12_REPRODUCIBILITY_AND_HASHES.md).

