# Agentic lower-tier KV prefetch

**Scenario/data.** The bundled50-session/715-child-call agentic trace has
tool gaps, but all765 sub-requests have141 fewer prompt IDs than declared
prompt tokens; every output-ID sidecar is also shorter than its declared
output. Exact block hashes are therefore unavailable (A). The
Qwen3-30B-A3B profile/model gives98,304 B of BF16 KV/token (A). A4096-token
prefix is402,653,184 B; at an assumed60-GB/s lower-tier path (C), a full
read takes at least6.711 ms. That transfer can overlap a tool gap only
if the prefix actually misses GPU KV and a timed lower-tier load exists.

**Causal/data limit.** The previous29,086-block estimate was below the
tested one-instance42,260-block GPU capacity, but its hash construction
assumed complete prompt IDs. The new `audit_ids.py`/`audit_ids.json`
invalidates that assumption, so29,086 is not a rigorous cache-capacity
upper bound. No lower-tier miss has been measured. The simulator now
disables prefix hashing for requests with incomplete prompt IDs to avoid
false hits and future-output leakage. FlowSim CXL `MEM_LOAD` still costs
zero time, so the critical path has no causal remote-load service event.

**Baseline/Oracle/gate.** Strong baselines are on-demand load and
[SYMPHONY](https://www.usenix.org/conference/nsdi26/presentation/agarwal)
advisory prefetch, plus cache-aware placement. An Oracle hides only
*observed* misses inside available tool gaps. Here miss count is unknown
and load service is unmodeled: `Gain_upper` is undefined, not a claimed
conditional6.711-ms benefit. Status `NEED_DATA` and
`SIMULATOR_UNSUPPORTED` for timed lower-tier loads. Reopen after acquiring
complete token IDs, observing real misses and calibrating the lower-tier
physical path. The historical
`research_receiver_matching/02_REMOTE_PREFETCH_SUMMARY.json` remains
conditional analysis, not validated capacity evidence.
