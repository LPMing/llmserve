# Capacity calibration — Joint system/network exposure study

## Scope and validity

Target cluster is the corrected S16 Qwen3-30B-A3B-Instruct-2507 configuration:
8 Prefill servers + 8 Decode servers, 8 GPUs/server, two 200-Gbps scale-out
NICs/server, EP64, model-derived BF16 KV, GateRouter A2A_P2P, ACTUAL P2D
receivers, and LAYERWISE transfer. Topology/profile provenance is the existing
`configs/large_scale/s16_8p8d_ep64_shared_2nic_qwen.json` plus its referenced
200-Gbps Clos file.

Trace windows were selected from the retained, trace-derived 30-second window
catalog, not selected by a later slowdown. For reference, the candidate catalog
reports Azure Code window 013818 at 101.2 req/s (7,608,704 input tokens and
62,131 output tokens per 30 seconds), Azure Conversation window 06210 at
43.43 req/s, BurstGPT window 148333 at 17.87 req/s with a 91-request peak
second, Mooncake Conversation window 000098 at 4.40 req/s, and Mooncake
Tool-Agent window 000098 at 8.40 req/s. These are source offered rates, not
cluster-normalized rho.

## Capacity definition

`rho` will be assigned only after measuring the same S16 cluster's sustainable
completion rate for the corresponding trace mix. A request-rate-only ratio is
not sufficient when input/output composition differs. Runs must preserve
request order, token counts, and all relative inter-arrival intervals; only a
single scale factor on those intervals may change. Queue stability and serving
completion behavior must be checked in addition to aggregate throughput.

The historical Azure Code 32-request run reports `Max batched tokens = 2048`
in its retained `run.log`, so the earlier claim that this run used 4096 and was
profile-invalid was incorrect and is withdrawn. Its `33.49 req/s` is
`32 / 0.956 s` over a finite completion window, not a measured sustainable
capacity: the selected prefix spans only 281.5 ms and maps roughly one request
per Decode scheduler across the 32 Decode instances. It does not demonstrate a
stable saturated service regime or bound queue growth. It is retained as a
finite-burst throughput observation only.

Reconstructing request occupancy from that run (Prefill interval approximated
as first scheduled time `arrival + queuing_delay` through Prefill completion;
Decode interval from admission through request end) gives peak/mean concurrent
population 8 / 3.23 for Prefill and 11 / 3.15 for Decode over their observed
intervals. There are 32 distinct scheduler-instance assignments in the
prefix; the per-host interval peaks are only 2–3. These are serving request
occupancy estimates, not GPU utilization. They confirm the prefix does not
populate the full configured active capacity and cannot be treated as a
saturated service-capacity measurement.

## Current probe

Two 256-request probes were stopped before producing a request CSV: the
4096-budget attempt was invalid for profile-range reasons, while the
2048-budget attempts were operationally too costly and had no completed serving
result. They are marked ABORTED and are not scientific negatives. The 32-request
retry below has completed; it is retained as a finite-prefix repeatability
observation, not a sustainable-capacity measurement.

The retry `jointcap_azure_code_w13818_n32_profile2048_compact_retry1` completed
successfully (`returncode=0`) from 2026-10-09 22:48:39 to 2026-10-10 00:10:57
EDT. Runner elapsed time was 1h22m18.5s. It produced all 32 request rows and
564 generated-token timing samples. The compact simulator log reports
`Total simulation time: 1h22m08.376s`; simulated time was 954,457,192 ns.
Route-audit artifacts continued advancing until completion;
the quiet compact log was not a stall. The request prefix has a 175-token
maximum output (18.6 mean), explaining why a 32-request run still had a long
decode tail.

### Repeatability and limits of this probe

The completed retry was compared by request ID with the retained
`real_azure_code_w13818_first32/fair` integrated run. All 32 input/output
lengths match; arrivals match exactly after subtracting the single 1,115,904 ns
first-timestamp normalization offset. TTFT and TPOT match exactly for every
request, and all 564 per-token ITL/TBT values match exactly. This validates
repeatability of this serving path for the selected finite prefix.

| Metric | Mean | P50 | P95 | P99 |
|---|---:|---:|---:|---:|
| TTFT (ms/request) | 132.282 | 122.468 | 294.421 | 297.325 |
| TPOT (ms/request, nonempty samples) | 3.756 | 4.498 | 6.238 | 6.402 |
| TBT/ITL (ms/token, 564 tokens) | 5.020 | 3.987 | 7.129 | 11.185 |

The observed `32 / 0.954 s = 33.53 req/s` is still only finite-prefix
completion throughput. Integrated interval reconstruction gives Decode
request population peak/mean 11 / 3.15 across 32 distinct Decode scheduler
instances (32 configured instances, each with TP2); Prefill peak/mean is 8 /
3.23 across 32 distinct scheduler instances. This is not a saturated active
set, a stable queue/drain
measurement, or a capacity denominator. Network telemetry was `none`, so this
retry also cannot establish link exposure, queue stability, or a `rho` value.
Its only new conclusion is exact serving-result repeatability on this prefix.

## Calibration decision

No `rho` values are authoritative yet. A finite-prefix requests/s number alone
will not be used as a sustainable-capacity denominator. Calibration must show
the per-instance active population, queue/drain trend, and serving completion
rate for the same trace mix. Other trace families require their own baseline
or capacity estimate and will never inherit Azure's denominator. The completed
retry confirms that the current 32-request Code prefix is too small to serve as
that denominator; the next run must add useful capacity/exposure telemetry
and target an adequately populated active set rather than repeat this prefix.

For that next run, `--omit-a2a-route-audit` is now available for capacity-only
replays. It skips writing the observational per-batch route JSON sidecars (the
retry produced about 1.1 GB of them) while leaving the in-memory GateRouter
matrix, generated communication graph, FlowSim routing, and completion
semantics unchanged. It is opt-in; mechanism-validation runs retain route
audits by default.

### Completed bounded arrival-compression diagnostic (not a rho point)

Run `jointcap_azure_code_w13818_n44_alpha1p5_compact` replays the first 44
Azure Code requests with identical IDs/order/input/output tokens and scales
every inter-arrival interval by `1/1.5` (arrival span 0.399852s → 0.266568s).
It completed normally (`44/44 VALID`, exit 0) in 1h18m23s wall time, with a
925.912ms simulated horizon. It is a bounded offered-load diagnostic:
`alpha=1.5` is **not** `rho=1.5`, and this finite prefix does not establish a
sustainable-capacity denominator.

Against the matched alpha=1.0 first-44 replay, integrated whole-run TTFT
P99 changed 299.076→299.743ms (+0.22%), TPOT P99 6.469→6.596ms (+1.95%), and
token TBT P99 11.334→11.907ms (+5.05%). EP CCT mean rose 3.00%, but CCT P50,
P95, and P99 were unchanged (P99 45.644us). All 44 KV handoffs still preceded
Decode; paired Prefill-minus-last-KV slack was identical for 28/44 requests,
with mean delta only +0.744us and median/P95 unchanged. Thus this point does
not meet the network or serving exposure gate.

The load did increase time-weighted global active Prefill population from
3.56 (peak 8) to 4.41 (peak 13), and active Decode from 3.88 (peak 12) to
4.44 (peak 14). These are small global populations relative to 32 scheduler
instances per stage; first-batch per-instance Decode occupancy remained at
most 2, and the arrival-to-first-schedule queue-delay distribution was
unchanged. The finite-prefix completion throughput rose from 44.18 to
47.52req/s, but is not a stationary service-rate measurement.

Link telemetry is incomplete: the default 4,096-row cap truncated the sidecar
at 5.874ms, so it cannot support full-run utilization, queue, or drain claims.
Flow/collective ledgers remain complete, but they show no EP CCT P99 increase;
same-link route-coactivity fraction moved 16.96%→15.89%. The ledger therefore
records this as `COMPLETED_FINITE_PREFIX_PRESSURE_DIAGNOSTIC`, with `rho=UNSET`
and no capacity claim. Any later link-telemetry replay must filter to
route-derived directed links before raising the row cap; do not infer the
missing full-run queue history from this truncated file.

### Completed 64-request natural-prefix exposure screen

`jointcap_azure_code_w13818_n64_profile2048_telemetry1` completed with
`returncode=0` on 2026-10-10 00:15:46–01:53:27 EDT (1h37m31.1s wall time).
It replayed the first 64 Azure Code requests at their original normalized
timestamps, with 164,896 input tokens and 1,174 requested output tokens. The
simulated horizon was 1.187486551s. The result is a finite natural prefix, not
a sustainable-capacity measurement and not a `rho` point.

All 64 request rows are `VALID`. Request-level KV attribution is exact and
single-request: 11,232 P2D flows carried 16,209,936,384 model-derived bytes.
Every request's last KV shard completed before its first Decode iteration;
the Decode admission was also after Prefill completion. The
`p2d_kv_ready_time - last_kv_completion` slack has min/P50/P95/P99/max of
0.709/1.232/1.609/1.618/1.618ms. Thus the observed natural prefix does not
expose the KV request barrier.

The 7,482 Decode-iteration rows form 234 logical Decode batches. The active
request-ID union has mean/P50/P95/max 4.79/4/10/12 requests per logical batch.
All 22,464 EP collectives join exactly to one Decode iteration by the encoded
logical batch ID, and every batch has 96 A2A_P2P collective events. This
validates collective provenance; it does not by itself establish a causal
network penalty.

Integrated serving metrics for this finite prefix are:

| Metric | Mean | P50 | P95 | P99 |
|---|---:|---:|---:|---:|
| TTFT (ms/request) | 119.529 | 117.375 | 295.705 | 299.092 |
| TPOT (ms/request) | 3.812 | 4.834 | 6.295 | 6.618 |
| TBT/ITL (ms/token, 1,120 samples) | 5.693 | 6.582 | 7.351 | 11.875 |
| Request latency (ms) | 210.449 | 136.211 | 554.468 | 938.581 |

The trace-derived source offered rate over this short 0.644156s prefix is
99.35 req/s; completed-prefix throughput is 53.90 req/s over the 1.187s
simulated horizon. Neither number establishes steady-state capacity. The
first-prefill-schedule delay has mean/P50/P95 of 56.10/64.71/212.52ms, but
there is no full-run link/utilization history in this telemetry capture and no
demonstrated stationary queue/drain window. The largest observed Decode
cohort is 12 across 32 Decode scheduler instances; this is insufficient to
call the cluster saturated or assign `rho`.

The link sidecar is explicitly incomplete: its 8,192-row cap was reached at
10.401809ms, before any EP-active sample. Those rows only describe the initial
P2D phase. They must not be used to claim absence of KV/EP link overlap,
utilization, or queueing. A second bounded replay will capture an ex-ante
selected natural 450–475ms route-overlap window on only the shared directed
links, with all other serving/network semantics held fixed.

This screen therefore advances exposure discovery but not capacity
calibration: natural route coactivity exists in the full event ledgers, the KV
handoff remains hidden behind Prefill, and the finite-prefix `rho` remains
`UNSET`. Capacity calibration still requires a stable trace-mix completion
rate and queue/drain check rather than prefix request/s extrapolation.

## Completed natural Azure Conversation candidate (not a rho point)

`jointcap_azure_conversation_w06210_n16_alpha1_naturalcompact` completed all
16 source requests with valid request rows. It preserves the first 16 records
of ex-ante burstier Conversation window 06210, original relative arrival
times, token counts, S16 topology, EP64/A2A_P2P, actual P2D receivers,
LAYERWISE KV, and FAIR service. It contains 32,021 input tokens and 2,377
requested output tokens; the longest output is 732 tokens. The simulator
executed 767 Decode batches (IDs 0–766), 73,632 EP collectives, and 2,400 KV
flows. Simulated horizon was 2.5873 s; wall time was 4 h 24 min 22 s.

The completed serving result is a finite-prefix observation only: TTFT
P50/P95/P99 = 72.332/143.424/276.375 ms; request TPOT
P50/P95/P99 = 3.505/6.676/6.676 ms; token TBT P50/P95/P99 =
2.787/6.796/6.796 ms. Decode-batch active population was mean 3.08, peak 9;
the 16 requests used 16 distinct Decode schedulers. This does not establish
a populated or sustainable-capacity regime.

The complete event-ledger join found 1,313/73,632 EP collectives (1.783%)
whose critical-peer route shared a directed FlowSim link with active KV.
Their CCT mean/P99 was 15.883/44.333 us; across all collectives it was
13.181/45.644 us. This is route coactivity, not a matched causal slowdown.
All 16 KV handoffs finished before the first Decode batch; Prefill-minus-last-
KV slack was min/P50/P95 0.709/1.175/1.517 ms. The natural candidate does not
pass the exposure gate, so no 2x2 oracle is justified.

The run retained a 1.37-GiB per-flow JSONL ledger. Subsequent discovery runs
must not preserve per-flow telemetry unless a window is selected for detailed
validation. Even with route-audit sidecars disabled, this finite 16-request
replay took over four hours because its decode tail required hundreds of
EP64 serving batches. Do not extrapolate sustainable rate from its
16/2.5873s completion ratio or relabel its arrival scale as `rho`.

## Targeted natural-window follow-up: 44-request prefix

The bounded FlowSim run `jointexp_azure_code_w13818_n44_alpha1_links450_475ms_diag3`
completed normally. It preserves the first-44 source requests, original
arrival offsets, token counts, model-derived communication, S16 placement,
EP64/A2A_P2P, ACTUAL P2D receivers, LAYERWISE release, and FAIR network
service. The first 44 requests are a valid causal prefix through 475ms because
request 45 arrives at 494.435ms. Direct ledger comparison against the retained
64-request run matched all 2,752 Decode-iteration rows, 8,177 collective
events, and 30,162 KV events through 475ms. The targeted link sidecar covered
the full 450–475ms interval on 18 route-derived directed links (21,615 rows),
without truncation.

This follow-up improves exposure observability, not capacity calibration. In
the 463–466ms subwindow, all 42/42 collectives had critical-route/KV same-link
coactivity, but route-coactive CCT did not rise in the broader interval and
there is no matched isolated-network counterfactual. Every request still
completed KV handoff before Decode; the request whose last KV shard fell in
the captured window had 1.271ms before Prefill completion. Thus `rho` remains
`UNSET`, and the run is not a serving-exposure pass.

## Capacity-probe status

The 1.5x arrival-compression probe of this same 44-request prefix is a separate
calibration-only run. Its scale factor is an offered-load perturbation, not a
measured `rho`; capacity will remain unassigned unless active-set/queue-drain
and completion behavior support a stable service-rate estimate. Do not mix
this probe into the natural alpha=1.0 exposure result.
