# Experiment disposition

The 28-case hit/sender sweep and the 8P:2D natural-eviction controls are
already archived in `research_autonomous/experiments/prefix_inversion/`.
Do not rerun with a weaker D router or fabricate a burst. A future policy
test requires a model-matched ordered prefix stream, per-D cache state,
identical GPUs/NICs, LFU/PrefixPlace and cache-aware DELTA baselines,
an online-only admission rule, and request-level flow/Serving timelines.
