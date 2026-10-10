# Controlled positive versus natural Azure windows

## Purpose and limits

This is a projection of prior results into the first exposure features now
available. The controlled timing case demonstrates that the current model can
produce EP network and serving effects; it is not evidence that the same
alignment occurs at production frequency. Azure windows are retained natural
trace prefixes, but are small samples and are not capacity-calibrated. None of
these comparisons is the required network/system/joint 2x2 oracle.

## Matched policy results

| Workload | Policy comparison | EP CCT P99 | Token TBT P99 | TTFT P99 | KV-ready P99 |
|---|---|---:|---:|---:|---:|
| Controlled EP64: 32 Decode + 64 P2D | FAIR → EP_FIRST | 92.279 → 45.644 us (-50.54%) | 8.862 → 6.937 ms (-21.72%) | Decode TTFT 50.684 ms; P2D TTFT 159.508 → 159.507 ms | 152.475 → 152.475 ms |
| Azure Code, window 013818, first 32 | FAIR → EP_FIRST | 45.644 → 45.644 us (0%) | 11.185 → 11.154 ms (-0.28%) | 297.325 → 297.302 ms (-0.008%) | 286.062 → 286.062 ms |
| Azure Conversation, window 007421, first 16 | FAIR → EP_FIRST | 45.644 → 45.644 us (0%) | 6.731 → 6.731 ms (0%) | 144.849 → 144.846 ms (-0.002%) | 132.399 → 132.399 ms |

Sources: `results/pd_moe_phase_search/ep64_shared_2nic/summary.json`,
`real_azure_code_w13818_first32/summary.json`, and
`real_azure_conversation_w7421_first16/summary.json`. The controlled P2D TTFT
and Decode TTFT populations are distinct request cohorts; they are not
collapsed into one statistic.

## What differs in the available exposure features

The controlled event ledger has about 19.0 ms global KV/EP interval overlap
over 22.0 ms of EP-active union, versus 74.0/295.5 ms in the Azure Code prefix
and 24.1/334.9 ms in the Azure Conversation prefix. The corresponding
last-KV-to-Prefill slack remains positive for every request in all three
datasets. In the natural runs the maximum number of concurrently active KV
flow records is 10–11; in the controlled case it is 1,152. This indicates a
large difference in P2D activity concentration/alignment, but active-flow
counts are not physical queue occupancy and global overlap is not same-link
overlap.

The controlled positive has a deliberately synchronized request mix, not an
open-loop production arrival pattern: `workloads/autonomous/ep64_integrated_high_32d64p2d_decode4.jsonl`
places 32 short Decode requests at `t=0` and all 64 2,048-token P2D requests
at `t=20ms` (each P2D request asks for one output token). The Decode group is
therefore already active when a large P2D wave is released. This is a useful
mechanism-positive bound, but not a capacity-calibrated natural window. By
contrast, the Azure prefixes preserve source arrivals and spread requests
across 32 Decode scheduler instances; their active Decode populations peak at
11–12 globally and their maximum simultaneous KV-flow counts are 10–11.
Those differences in population and release concentration must be included
when projecting the controlled positive into the natural exposure feature
space.

From each natural request's Decode-admission-to-completion interval, the Code
prefix has a global active-Decode peak of 11 (time mean 3.15), and the
Conversation prefix peaks at 12 (time mean 4.97). Each sampled request was
assigned to a distinct Decode instance, so the sample itself never tests
multiple simultaneously active requests in one such instance. This is an
important limitation of a 16/32-request prefix on the 32-Decode-instance
cluster; it must not be described as a high-concurrency capacity-calibrated
cluster run.

As a further screening statistic, I split each collective interval by whether
it intersects the **global** union of KV-flow service intervals. EP CCT P95
for global-overlap / no-global-overlap collectives is 88.898 / 45.644 us in
the controlled case, 43.022 / 23.477 us in Azure Code, and 45.644 / 43.022 us
in Azure Conversation. The p99 is 92.830 us in the controlled case and
45.644 us in both natural cases. This association is not a causal estimate:
it does not require the KV flow and EP peer to share a directed link, and
collective size, routing, batch state, and phase may differ between groups.

Natural Code and Conversation samples therefore remain negative controls for
class-priority benefit: EP_FIRST barely changes either network tail or serving
tail. The controlled run says the mechanism can be activated when the serving
state maintains a Decode collective population while a concentrated P2D
release is present. The remaining causal questions are whether any naturally
capacity-calibrated window creates barrier exposure, whether exact route/link
overlap is present, and whether changing legal system scheduling can change
that exposure enough to make a network oracle more useful.

## Interpretation

The evidence is consistent with, but does not yet prove, the organizing
hypothesis that serving dependencies determine exposure while network service
determines raw completion perturbation. Positive P2D slack explains why
request-level KV readiness is unchanged in these examples. The natural-window
policy results do not establish that a system oracle would help: that requires
the same trace/request set under default, network-only, system-only, and joint
oracle runs.

## Azure Code 64-request route-aware screen (completed)

The natural first-64 replay adds exact KV flow paths and a validated join of
all 22,464 EP collectives to their decode iterations. 4,855 collectives
(21.61%) had a critical peer route coactive with KV on at least one identical
directed FlowSim link. The raw coactive CCT mean was 25.276us versus 22.457us
without that route coactivity; however, P95/P99 were unchanged, and matching
on layer, event type, bytes, flow count, and Decode cohort yielded a weighted
within-stratum mean difference of -0.231us. This is evidence of naturally
occurring route coactivity, not yet evidence of an EP delay caused by KV.

All 64 KV request barriers remained hidden behind Prefill (minimum observed
slack 0.709ms). The high-overlap bins at 463–466ms had a 12-request Decode
cohort, but the full-run link sampler stopped at 10.402ms and observed no EP.
The first 44 requests are a causal prefix for a 450–475ms link-capture window:
the 44th normalized arrival is 399.852ms and the 45th is 494.435ms. A bounded
same-prefix replay is in progress to capture analytical per-link backlog and
class allocations on only route-derived shared links. No system/network
oracle or policy gain has been run or inferred yet.

## Same-trace pressure diagnostic: Azure Code n44 at 1.5× arrivals

The same first 44 requests were replayed with every inter-arrival interval
scaled uniformly by 1/1.5. Request IDs, order, token counts, model-derived
traffic, and serving/network semantics remain matched. Active Prefill rises
from mean/peak 3.56/8 to 4.41/13 and active Decode from 3.88/12 to 4.44/14.
This is a finite-prefix pressure diagnostic, not a capacity-calibrated `rho`.

EP CCT mean rises 3.00%, but CCT P50/P95/P99 are unchanged. KV handoff slack
median/P95 is unchanged; TTFT P99 rises 0.22%, TPOT P99 1.95%, and token TBT
P99 5.05%. The same-link critical-route coactivity fraction falls from 16.96%
to 15.89%. All 44 handoffs remain before Decode. The full-run link sidecar is
truncated at 5.874ms, so this diagnostic does not establish whole-run
utilization, queue persistence, or a network-caused serving effect.
