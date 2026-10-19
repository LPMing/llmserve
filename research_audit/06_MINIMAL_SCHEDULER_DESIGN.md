# 06 — Minimal scheduler design status

**No scheduler design or implementation is approved by the evidence so far.** The project remains before the motivation and novelty gates.

The prior-art screen already covers the obvious candidate components: flow size/deadline priority (pFabric/PDQ/PIAS), coflow/barrier scheduling (Varys/Aalo), and stage-/request-aware LLM communication scheduling (Nuska). A new formula built from request slack or collective IDs would be incremental unless a minimal counterexample shows these methods choosing the wrong action and a realizable mechanism fixes it.

If reopened after valid motivation, the first design question is not “what score?” but the scheduling granularity: physical message/QP, entire collective, or host submission batch. The implementation must preserve real batch aggregation and collective barriers, map to finite queues or host-side pacing, protect ACK/CNP, enforce minimum service, and avoid starvation. These are requirements for a future design, not implemented functionality.
