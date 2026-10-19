# SLO and serving-metric analysis

## SLO status

No externally grounded TTFT, TPOT or TBT SLO threshold was set for this
controlled mechanism experiment. Consequently, this report does not invent
normalized SLOs or quote SLO attainment percentages. It reports raw serving
latencies and relative changes only.

## Valid metrics

Eight Decode seed requests have 24 output tokens each. The measured token
interval population is 184 intervals (23 per request), so its mean/P50/P95/
P99 are descriptive. Under B:

| Policy | Mean ITL/TBT (ms) | P50 (ms) | P95 (ms) | P99 (ms) | Request TPOT mean (ms) |
|---|---:|---:|---:|---:|---:|
| FAIR | 6.045367 | 5.938688 | 6.713704 | 8.164016 | 6.045367 |
| EP_FIRST | 6.008587 | 5.875528 | 6.647400 | 8.164016 | 6.008587 |
| KV_FIRST | 8.733147 | 5.875528 | 27.588228 | 46.827701 | 8.733146 |

The reported per-request TPOT is the simulator's output-token latency metric;
TBT/ITL distributions are separately pooled from the token intervals. They
are close in the mean here because each seed has the same output length, but
they are not interchangeable. The eight requests are the independent
request-level units; token samples are correlated within each request.

The 18 candidate KV requests each request exactly one output token. Their
TTFT is valid; their TPOT field is zero/undefined because there is no pair of
generated tokens from which to calculate an inter-token interval. Do not
interpret zero as a zero-latency decode. Candidate TTFT is 74.468 ms for
2048-token prompts and 57.757 ms for 1024-token prompts under every tested
policy. Candidate TTFT P95/P99 and attainment are not promoted as population
tail claims from this small controlled sample.

## Serving-level inference

KV_FIRST produces a large decode-side tail in this selected, high-load
controlled FlowSim point; EP_FIRST nearly removes it. EP_FIRST changes mean
seed TPOT by only -0.61% relative to FAIR and does not change measured
candidate TTFT. This is evidence for the basic utility of protecting
recurrent Decode EP in the model, not evidence of ≥20% benefit over an
already reasonable FAIR policy, nor evidence that a finer-grained method
beats EP_FIRST.
