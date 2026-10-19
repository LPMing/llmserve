# Layerwise receiver fan-in check

**Status: NOT RUN in this work item; existing evidence makes the conditional gate unnecessary.**

The current question is specifically whether complete-request POST_PREFILL handoff plus flow-level FAIR delays the request barrier and whether a simple request-grouped policy can materially recover it. The corrected actual-anchor replay shows only a 3.396% mean handoff-span change and no maximum/P99 change; the integrated four-request run has no active Decode EP during KV movement. These results do not motivate a 10-way layerwise fan-in extension, which would test a separate capacity-saturation condition.

Historical mechanism bounds in `experiments/pd_kv_ep/CAPACITY_CALIBRATED_GATE_BASELINE.md` report 0.654–1.796 ms of layerwise release slack and that P2D_READY was usually Prefill-compute limited. The task's cited 4-MiB layer, 1.542-ms release interval, and 200-Gbps calculation gives a fluid necessary-condition knee above roughly 9.19 simultaneous equivalent senders. That calculation alone is not an experiment, and the prior high-fan-in work already showed why raw network FCT can be hidden by Serving slack.

No claim is made that 8 versus 10 full-size requests was measured here. No additional load, buffer reduction, or artificial alignment was introduced. If revisited, it requires a separate legality audit for active Prefill GPUs, per-rail mapping, Decode KV capacity/admission, and same-capacity negative control before running.
