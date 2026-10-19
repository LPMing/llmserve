# PP-stage KV coflow

**Scenario/data.** Four Qwen3-30B-A3B TP2/PP2 Prefill workers send
2048-token BF16 KV to one TP2/PP2 Decode through two 200-Gb/s rails in
the retained physical map (A profile/config; C synchronized requests).
One request sends 201,326,592 B aggregate. Each PP stage owns half the
layers, so one source rank emits 2,097,152 B/layer and 50,331,648 B total;
four sources present 8,388,608 B per stage-layer rail, a 335.544-µs cut
floor. Measured Prefill block compute is 1,339.101 µs, so 16 identical
sources would be needed before one layer's serialization exceeds the block
interval on that rail. The relevant critical path is stage dependency →
per-layer KV flow → complete Prefill/P2D-ready barrier → Decode admission.

**Baseline/Oracle/gate.** Layerwise FAIR with topology-aware placement is
the strong baseline; zero P2D service is an optimistic Oracle. The repaired
4P run's last flow finishes at63.555 ms, 1.157 ms before P2D-ready64.712 ms;
`Gain_upper=0` on readiness from changing only these flow schedules. PP
SEND→RECV and EP1/TP2 converter bugs were corrected before this decision.
Token2 is78.723 ms, completion92.734 ms, with no exposed coflow delay.
The observed result matches the theoretical hidden-overlap prediction.
Status `NO_GO` for this profile-valid cut; no forced 16:1 funnel or
unmeasured link reduction is substituted. Full provenance is in
`research_autonomous/experiments/pp_coflow/`.
