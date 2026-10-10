# Natural exposure-window inventory (not yet capacity calibrated)

## Selection basis

The retained `workloads/real/slices/window_candidates.csv` is an ex-ante
request-count / input-pressure / burstiness catalog. The rows below are
candidate natural windows, not a slowdown-selected result. Source offered
rates are not `rho`; each trace family still needs its own S16 sustainable
capacity denominator. Exposure score remains unset until event-level barrier
slack can be joined to calibrated replay output.

| Trace family / candidate window | Duration | Requests | Source RPS | Input tokens | Output tokens | Peak requests in 1 s | Burst ratio | Why retained |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Azure Code 013818 | 30 s | 3,036 | 101.20 | 7,608,704 | 62,131 | 147 | 1.45 | High arrivals + burstiness; existing 32-request integrated prefix |
| Azure Code 13932 | 30 s | 2,657 | 88.57 | 6,898,700 | 50,004 | 142 | 1.60 | Burstiness alternative |
| Azure Conversation 06210 | 30 s | 1,303 | 43.43 | 2,258,353 | 149,528 | 177 | 4.08 | Strong natural burst candidate |
| Azure Conversation 7421 | 30 s | 2,643 | 88.10 | 4,252,832 | 271,044 | 104 | 1.18 | Existing 16-request integrated prefix; arrival/input pressure |
| BurstGPT 148333 | 30 s | 536 | 17.87 | 23,406 | 4,534 | 91 | 5.09 | Burst candidate with existing network/event-ledger history |
| BurstGPT 148335 | 30 s | 730 | 24.33 | 37,824 | 12,956 | 72 | 2.96 | Higher request and token volume alternative |
| Mooncake Conversation 000098 | 30 s | 132 | 4.40 | 1,766,700 | 43,154 | 19 | 4.32 | Long-context / reuse family candidate |
| Mooncake Conversation 000114 | 30 s | 130 | 4.33 | 1,584,307 | 45,823 | 28 | 6.46 | Higher burstiness alternative |
| Mooncake Tool-Agent 000098 | 30 s | 252 | 8.40 | 2,390,534 | 44,943 | 36 | 4.29 | Agent/session trace candidate |
| Mooncake Tool-Agent 000114 | 30 s | 235 | 7.83 | 2,017,341 | 47,420 | 47 | 6.00 | Higher burstiness alternative |

The inventory deliberately keeps the old Azure Conversation 7421 sample as a
negative-control provenance point while retaining 6210 as the catalog's
burstier next candidate. They are not interchangeable windows.

## First-32 request-shape pilot (trace-only, not simulated capacity)

For bounded planning, I computed the first 32 consecutive source records in
each existing candidate slice. These values preserve source timestamps and
tokens; prefix RPS is only a short-prefix descriptor and is **not** a capacity
or rho measurement.

| Family/window | Arrival span | Prefix RPS | Input tokens | Output tokens | Mean input/output | Max output/request | Rationale for follow-up |
|---|---:|---:|---:|---:|---:|---:|---|
| Azure Code 013818 | 0.282 s | 113.7 | 95,623 | 594 | 2,988 / 18.6 | 175 | Existing finite-prefix repeat; KV-heavy relative to short decode |
| Azure Conversation 06210 | 0.688 s | 46.5 | 71,058 | 4,498 | 2,221 / 140.6 | 783 | Best next balanced candidate: bursty arrival plus sustained decode |
| Azure Conversation 07421 | 0.376 s | 85.2 | 52,965 | 3,779 | 1,655 / 118.1 | 461 | Existing policy negative; useful adjacent window, not a substitute for 06210 |
| BurstGPT 148333 | 2.000 s | 16.0 | 5,090 | 1,024 | 159 / 32.0 | 201 | Low KV demand, burst-shaped arrival; possible decode-dominant control |
| BurstGPT 148335 | 2.000 s | 16.0 | 5,404 | 1,429 | 169 / 44.7 | 344 | Similar control with somewhat higher output demand |
| Mooncake Conversation 000098 | 5.999 s | 5.3 | 349,363 | 8,332 | 10,918 / 260.4 | 859 | Long-context KV + long decode; high-workload cost risk |
| Mooncake Conversation 000114 | 8.999 s | 3.6 | 390,207 | 10,395 | 12,194 / 324.8 | 816 | Long-context/high decode alternative |
| Mooncake Tool-Agent 000098 | 3.000 s | 10.7 | 300,676 | 4,730 | 9,396 / 147.8 | 809 | Long-context agent workload |
| Mooncake Tool-Agent 000114 | 3.000 s | 10.7 | 274,409 | 6,117 | 8,575 / 191.2 | 816 | Agent-window alternative |

Some BurstGPT/Mooncake timestamps are tied at the source's timestamp
resolution. The conversion/replay preserves those ties; no new synchronization
was introduced. The completed Code 32-request retry took 1h22m18s wall time
and exactly reproduced its earlier request-level TTFT/TPOT and all 564
token-level TBT/ITL values. Its peak Decode request population was 11 (mean
3.15) across 32 configured Decode scheduler instances (TP2, 64 GPUs total).
This validates the short-prefix
serving result, not a saturated operating point. Given the measured runtime
and output-length heavy tails above, the next trace candidate should be
selected by exposure evidence and compute cost, not by blindly running every
prefix.

## Current screening evidence

The Azure Code 013818 first-64 integrated ledger now provides EP critical-peer
endpoints, exact KV paths, and a validated collective-to-decode-iteration
join. Of 22,464 EP collectives, 4,855 (21.61%) had at least one critical peer
route sharing the same directed FlowSim link with an active KV flow. The
highest-ranked ex-ante bins are 463–466ms: 14/14 critical-route coactivity in
each 1ms bin, 12 active Decode requests, and mean CCT 34.233us (P99
45.644us). The broader 450–475ms interval has 331 collective records.

This is route coactivity, not demonstrated delay or a queue measurement. EP
CCT P95/P99 are identical for coactive and non-coactive populations, and
limited exact-stratum matching shows no positive average delta. Moreover, all
64 KV barriers complete before Prefill/Decode admission. The 64-run link
sidecar truncates before EP begins. A bounded first-44-request replay with
targeted 450–475ms link telemetry has now completed and is summarized below;
the 45th arrival is at 494.435ms, so cannot affect that interval.

## Completed targeted FlowSim link capture: Azure Code 013818, requests 0–43

Run `jointexp_azure_code_w13818_n44_alpha1_links450_475ms_diag3` completed
normally (`44/44` valid requests; 0.996075321s simulated; 1h18m15.128s
wall). It uses the same request IDs, arrivals, tokens, model-derived bytes,
topology, placement, EP64/A2A_P2P, LAYERWISE/ACTUAL P2D, and FAIR policy as
the first-64 run. A direct prefix comparison confirms that through 475ms the
44-request replay exactly matches the first-64 run in all 2,752 Decode
iteration rows, all 8,177 collective events, and all 30,162 KV events. The
link sidecar covers the complete requested interval: 21,615 records over the
selected 18 directed links, with no truncation.

The topology generator maps GPU ranks 0–127 to NICs 128–159 over 7200-Gbps
local-fabric edges. Scale-out NIC ports are 200 Gbps; each directed
leaf–spine pair is four parallel 200-Gbps links, represented by 800 Gbps
aggregate FlowSim capacity. Therefore the 7200-Gbps rows are not scale-out
NIC rates. Link outstanding below means **analytical fluid outstanding**, not
packet queue occupancy.

| Directed resource | Capacity | KV+EP simultaneous allocation | Share window | Fluid outstanding while mixed |
|---|---:|---:|---:|---:|
| Decode NIC-facing `162->146` | 200 Gbps | 176.36 us; all mixed intervals at link capacity; time-weighted KV/EP allocation 67.51/132.49 Gbps | 0.705% of 25 ms | max 3.826 MB |
| Decode NIC-facing `162->147` | 200 Gbps | 166.19 us; all mixed intervals at link capacity; 62.78/137.22 Gbps | 0.665% | max 4.111 MB |
| Decode NIC-facing `162->149` | 200 Gbps | 127.55 us; all mixed intervals at link capacity; 102.06/97.94 Gbps | 0.510% | max 2.654 MB |
| Spine→leaf `164->162` | 800 Gbps aggregate | 569.72 us mixed; 67.31 us at capacity | 2.279% mixed | max 4.386 MB |

This verifies same-directed-resource sharing **inside the FlowSim fluid
model**: both classes receive nonzero allocations simultaneously on those
links, and some 200-Gbps NIC-facing links are fully allocated during the
coactivity. It is not a counterfactual slowdown measurement or packet-level
queue evidence.

The narrower ex-ante high-coactivity subwindow 463–466ms contains 42/42
collectives with critical-route/KV route coactivity and Decode cohort 12. Its
EP CCT mean/P99 is 34.233/45.644us. In the broader 450–475ms slice, 182/331
collectives are route-coactive; their CCT mean is 29.365us versus 38.626us
for non-coactive collectives, while both groups have 45.644us P99. This
unmatched association is confounded and, importantly, does not show higher
CCT during coactivity.

All 44 request KV handoffs still precede their first Decode iteration. The
Prefill-minus-last-KV slack has minimum/P50/P95 0.709/1.232/1.612ms; the one
request whose last shard completes in 450–475ms has 1.271ms slack. The
collective-to-Decode-iteration join is exact (22,464/22,464); within
450–475ms, the minimum gap from collective completion to the logical
iteration finish is 0.228ms, P50 3.535ms. This is an iteration-level bound,
not exact per-collective dependency-DAG slack. No baseline barrier crossing
is observed, and no isolated/oracle counterfactual has been run.

Whole-run serving metrics (44 requests; not window-only attribution) are TTFT
P50/P95/P99 119.056/296.945/299.076ms, TPOT 4.498/6.224/6.469ms, and token
TBT P50/P95/P99 6.043/7.511/11.334ms. These are baseline measurements, not
gains.

### Current decision

Classification: `NATURAL_SAME_LINK_SHARING_VERIFIED; SERVING_EXPOSURE_NOT_YET_DEMONSTRATED`.
The 463–466ms region remains the best bounded candidate, but is not a
capacity-calibrated `rho` point. Do not call full link allocation a 20%
network-headroom result. Next: calibrate this trace mix's sustainable serving
rate with queue/drain evidence; then replay this same natural request set at
a legal calibrated load or close it as a screened-but-unexposed candidate.
No 2×2 oracle is justified yet.

## Next lawful narrowing

1. Do not assign `rho` from source RPS or this finite-window throughput alone.
   The 64-request run's 99.35 source req/s and 53.90 finite-prefix completion
   req/s are not sustainable capacity. Its Decode cohort peaks at 12 across
   32 Decode scheduler instances.
2. Validate the 450–475ms natural route-coactivity candidate using filtered
   link telemetry and verify that the 44-request prefix reproduces the
   original serving/collective events through 475ms.
3. Once a valid exposure join and calibrated load point exist, screen at most the top two windows per
   family from this ex-ante catalog, at no more than three calibrated load
   points (0.70/0.85/0.95, or a smaller bracket around the observed knee).
4. Integrate only the strongest natural exposure candidate. If no candidate
   exposes a serving barrier, record the negative and move to the next family;
   do not increase model bytes or force arrival synchronization.

## Follow-up: same Azure Code prefix with 1.5× interval compression

`jointcap_azure_code_w13818_n44_alpha1p5_compact` preserves the first 44
request IDs/order/tokens and uniformly divides their inter-arrival intervals
by 1.5. It is a trace-shape-preserving offered-load diagnostic, not a measured
capacity ratio. The run completed all 44 requests with the same model-derived
KV total (12,115,378,176 bytes) and 20,544 EP collectives.

Compared with the matched alpha=1 prefix, active populations rise only
modestly (time-weighted Prefill 3.56→4.41, peak 8→13; Decode 3.88→4.44,
peak 12→14). EP CCT P99 is unchanged; the critical-route same-link coactivity
fraction falls 16.96%→15.89%. All KV handoffs remain before Decode. Paired
TTFT P99 changes +0.22%, TPOT P99 +1.95%, and TBT P99 +5.05%; KV handoff slack
median/P95 is unchanged. This is not evidence of an exposed barrier or
joint-scheduling opportunity.

The flow and collective ledgers are complete, but the whole-run link-sidecar
capture is truncated at 5.874ms by its 4,096-row cap. Accordingly this run
cannot establish complete-interval utilization, fluid-backlog persistence,
or a drain rate. `rho` remains `UNSET`; the finite-prefix completion rate is
not a sustainable-capacity estimate. This is a negative pressure diagnostic,
not a replacement for the natural alpha=1.0 window and not grounds for a
2×2 oracle.

### Decision after this diagnostic

Arrival compression of this short prefix alone did not move the request or
collective barriers. Do not continue increasing alpha on this prefix to force
an effect. The next search step should use an independently selected trace
family/window with a higher ex-ante active-decode/exposure score, while
capacity calibration remains explicitly unresolved. If no same-mix stable
capacity procedure can be made tractable, report that limitation rather than
assigning a guessed `rho`.

## Additional ex-ante burst candidate: Azure Conversation 06210, first 16

The completed integrated FlowSim replay
`jointcap_azure_conversation_w06210_n16_alpha1_naturalcompact` selected the
first 16 records from catalog window 06210 (source burst ratio 4.08). It kept
natural arrival spacing and model-derived bytes; it is not a synchronized
cohort or an arrival-scaled load point. All 16 requests completed, and all
73,632 EP collectives joined to 767 Decode batches (96 collectives/batch).
The batch-active Decode population was mean 3.08 and peak 9.

Only 1,313 collectives (1.783%) had a critical peer sharing a directed
FlowSim link with active KV. Their CCT mean/P99 was 15.883/44.333 us versus
13.181/45.644 us across all collectives. This comparison is descriptive and
does not establish causal delay. All 16 last-KV completions preceded their
first Decode batch; Prefill-minus-last-KV slack was min/P50/P95
0.709/1.175/1.517 ms. The request-level KV barrier therefore remained hidden
behind Prefill in this candidate.

Serving metrics are whole-prefix baselines, not gains: TTFT P50/P95/P99
72.332/143.424/276.375 ms; TPOT P50/P95/P99 3.505/6.676/6.676 ms; token
TBT P50/P95/P99 2.787/6.796/6.796 ms. The run took 4 h 24 min for 767 Decode
batches and retained a 1.37-GiB flow ledger. It is recorded as a completed
natural-window negative screen, not a sustainable-capacity measurement or
capacity-calibrated `rho`. No policy/oracle cells were run because the
measured route-coactivity and barrier slack do not pass the exposure gate.
