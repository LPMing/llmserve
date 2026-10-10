# Exposure metric validation (preliminary)

## Scope

This report audits what the retained integrated FlowSim ledgers can and cannot
support before implementing an oracle. All intervals below come from existing
integrated runs under `results/pd_moe_phase_search/`; they are not packet-level
queue data. FlowSim queue values, when present, mean analytical fluid backlog.

## Barrier definitions

For a layerwise P2D request, the immediately observable serving slack is:

```text
P2D admission slack = Prefill completion - last required KV completion
```

A positive value means the last KV shard completed before the Prefill lifecycle
barrier and its network delay was hidden by the remaining Prefill work. A
negative value is a candidate for exposed KV delay, subject to checking the
actual Decode-ready and scheduler-admission timestamps.

For an EP collective, `collectives.jsonl.gz` records the collective-level
`start_ns`, `end_ns`, and `cct_ns = end - start`. This is the correct network
barrier metric, but the retained compact event does not carry Decode batch or
iteration IDs, request membership, per-peer route/path, or the next serving
barrier timestamp. Therefore it cannot by itself yield a valid per-collective
`BarrierSlack` or prove same-link P2D exposure.

## Measured P2D slack from retained natural windows

Reconstructed from `KV_COMPLETED` request IDs in `kv_events.jsonl.gz` and
`prefill_completion_time_ns` in `requests.csv`:

| Run | Requests with matched KV barrier | Last KV after Prefill | Prefill-minus-last-KV slack P50 | P95 | Minimum |
|---|---:|---:|---:|---:|---:|
| Azure Code, window 013818, first 32 | 32/32 | 0 | 1.239 ms | 1.616 ms | 0.709 ms |
| Azure Conversation, window 007421, first 16 | 16/16 | 0 | 1.170 ms | 1.484 ms | 1.074 ms |

These two runs show no last-shard barrier exposure in their retained
LAYERWISE baseline: every request's last observed KV completion precedes
Prefill completion. This does not imply that every KV flow is fast; it says the
measured request barrier has positive slack in these samples.

## Global temporal overlap (screening signal only)

I reconstructed the union of all KV-flow service intervals and all completed
EP-collective intervals in each ledger, then intersected those unions:

| Run | KV/EP global overlap | KV-active union | EP-active union | Overlap / EP-active union | Max active KV flows | Max overlapping EP records |
|---|---:|---:|---:|---:|---:|---:|
| Controlled EP64, 32D+64P2D | 19.011 ms | 70.752 ms | 22.048 ms | 86.2% | 1,152 | 1 |
| Azure Code, first 32 | 74.025 ms | 293.503 ms | 295.516 ms | 25.0% | 10 | 2 |
| Azure Conversation, first 16 | 24.148 ms | 86.626 ms | 334.915 ms | 7.2% | 11 | 2 |

This is only an event-time overlap screen. The retained compact collective
records do not include their exact per-peer directed paths, so global overlap
does **not** prove that KV and EP used the same physical link, nor that a
barrier was delayed because of that overlap. Also, the max-active-KV-flow count
depends on the event aggregation semantics and is not a NIC queue-depth metric.

## Metric verdict and instrumentation gap

- P2D release/completion and request barrier slack are reconstructable and
  source-provenanced using `scripts/export_request_critical_path.py`.
- EP collective CCT is reconstructable, but critical-collective slack to the
  serving iteration barrier is not in the retained compact ledger.
- Per-link shared exposure is not reconstructable from these compact
  collectives alone.
- Consequently, the overlap values above select candidate windows only; they
  cannot be presented as causal exposure or used to claim a joint-scheduling
  benefit.

The source audit confirmed that Chakra nodes are assigned `batch_id`,
`collective_id`, `layer_id`, `event_type`, and request-membership attributes.
The completed 64-request Code replay has empty EP `request_ids`, but its
collective IDs decode exactly to logical Decode batch/layer/event. Cross-check
against `decode_iterations.csv` succeeded for all 22,464/22,464 collective
events, with 96 events per each of 234 logical batches and every collective
interval contained in the batch's iteration interval. The batch membership
ledger has nonempty request IDs on scheduler-member rows; unioning those rows
gives 64/64 request-to-token-step joins and 1,120/1,120 TBT-sample joins.

The Decode scheduler retains completed iteration records in memory. The
default-off `--serving-iteration-telemetry` option exports a compact
`<run>.decode_iterations.csv` with batch ID, request IDs, start/finish,
duration, Decode population, and total sequence length. The request-ID
fallback from `decode_iteration_request_ids` is present in the current source.
The completed run's logical-batch join was independently validated, so this
result does not depend on assuming the converter formula alone.

## 64-request Azure Code route-coactivity screen

The completed integrated replay was analyzed under
`../results/jointcap_azure_code_w13818_n64_profile2048_telemetry1/`:
`COMMUNICATION_EXPOSURE_TRACE.csv`, `REQUEST_DECODE_STEP_ATTRIBUTION.csv`,
`EXPOSURE_WINDOW_RANKING.csv`, and `analysis_summary.json`. KV flows retain
exact request IDs, bytes, start/end, and backend-emitted paths. For each EP
collective, critical peer endpoints were resolved through the same
deterministic shortest-path route model used by FlowSim. This establishes
same-directed-link coactivity in the model, not counterfactual delay or
packet-level queue occupancy.

| Signal | Result | Interpretation |
|---|---:|---|
| KV request barriers | 64/64 exact, all complete before first Decode batch | No KV handoff barrier exposure in this run |
| EP collective to iteration join | 22,464/22,464; exactly 96/batch | Provenance join valid |
| EP CCT | mean 23.067us; P50 21.511us; P95 44.333us; P99 45.644us | Integrated FlowSim collective metric |
| Critical EP-route / active-KV same-directed-link coactivity | 4,855/22,464 = 21.61% | Natural exposure candidate, not delay attribution |
| EP CCT, route-coactive vs not | mean 25.276 vs 22.457us; P50 22.822 vs 21.511us; P95/P99 equal (44.333/45.644us) | Raw association is modest and confounded |
| Within-strata match by layer, event type, bytes, flow count, Decode cohort | weighted mean difference -0.231us; median stratum difference 0us | No consistent CCT increase after limited matching |
| KV handoff slack | P50/P95 1.232/1.609ms; minimum 0.709ms | All 64 KV barriers remain hidden by Prefill |

The highest ex-ante route-coactivity region is 450–475ms simulated time. It
contains 331 collective records from logical batches 81–85; the 1ms bins at
463–466ms have 14/14 critical-route coactivity, Decode cohort 12, and mean
CCT 34.233us (P99 45.644us). The next source request arrives at 494.435ms,
so the first 44 requests include every arrival that can causally affect this
25ms interval; no same-time arrival was introduced.

The full-run link sidecar hit its 8,192-row cap at 10.401809ms and has zero
EP-active samples. It is invalid for the later route-overlap window and cannot
support any link utilization/backlog claim. A bounded, prefix-preserving
44-request replay is therefore selected to retain link telemetry only for
450–475ms and only on the route-derived shared-link set. Link selection is
based on the observed critical-route overlap ledger, not a presumed
bottleneck. This targeted capture is the next mechanism-validation gate.

No causal or 2x2-oracle claim follows from this screen. FlowSim backlog is
analytical residual-fluid backlog, never packet-buffer occupancy, ECN, PFC,
or drops. The existing full-prefix link file must remain marked truncated.

## Targeted link capture result

The selected 44-request capture completed and exactly reproduced the first-64
run's serving iterations, EP collectives, and KV events through 475ms. It
captured the full requested interval, unlike the earlier sidecar that
truncated at 10.402ms. In the 463–466ms candidate, 42/42 collective critical
routes were coactive with KV on at least one identical directed link. In the
broader 450–475ms interval, the route-coactive group had lower raw mean CCT
(29.365us) than the non-coactive group (38.626us), while both had P99
45.644us. Exact-stratum matching previously gave no positive mean delta.
These observations reject the shortcut “same-link overlap implies EP delay”;
they do not establish that KV improves CCT, because cohort phase and other
collective attributes confound the unmatched split.

All captured same-link service sharing is a FlowSim max-min fluid allocation.
Selected Decode NIC-facing links are 200Gbps and saturated during the brief
mixed intervals; leaf/spine aggregate links are represented at 800Gbps for
four physical 200Gbps links. The corresponding outstanding-byte signal is
analytical fluid work, not switch-buffer occupancy. No matched no-KV or
independent-fabric counterfactual exists yet, so `delta_net`, per-object
barrier slack consumption, and exposure ratio remain unavailable.

## Exact iteration-boundary slack distribution from the 44-request replay

The full communication exposure ledger joins every A2A_P2P collective to its
Decode iteration. For each collective, slack is
`iteration_finish_ns - collective_finish_ns`; this is an exact timestamp
difference to the group iteration boundary, but not a claim that independently
delaying every collective adds linearly to TBT.

| Scope / event | n | Slack P01 / P50 / P95 (us) | Slack / own CCT P01 / P50 / P95 | Slack <= 10x CCT |
|---|---:|---:|---:|---:|
| Full run, dispatch | 11,232 | 231 / 1,808 / 5,283 | 10.74 / 96.31 / 363.85 | 4 |
| Full run, combine | 11,232 | 231 / 1,798 / 5,210 | 10.74 / 85.39 / 194.02 | 81 |
| 450–475ms, dispatch | 166 | 305 / 3,609 / 6,912 | 13.36 / 158.12 / 453.49 | 0 |
| 450–475ms, combine | 165 | 231 / 3,535 / 6,839 | 5.06 / 77.44 / 149.83 | 8 |

The selected natural window has some relatively low-slack combine events, but
its smallest iteration-boundary gap is 231us, versus a single-event CCT in the
tens-of-microseconds range. This is a useful near-critical screen, not proof
that cumulative communication delay is hidden or exposed: the event DAG may
contain sequential collectives and compute, so only an integrated matched
counterfactual can measure net iteration/TBT change.

For the same 450–475ms window, the per-token sum of 96 dispatch/combine CCTs
divided by measured TBT has mean/P50/P95/P99 `0.433/0.438/0.461/0.461` across
45 joined Decode steps. This is deliberately an upper-bound accounting proxy,
not additive critical time. It says EP communication is not negligible in the
iteration budget, while the coactivity comparison still fails to show that
P2D raises those CCTs. The missing quantity is a matched, causally attributed
`delta_net` propagated through the full iteration DAG.

## Release-time population and same-route incidence instrumentation

The natural-exposure analyzer now resolves critical EP peer paths once, joins
them to the Decode request active intervals, and samples P2D/EP populations at
barrier release. The generated
`COMMUNICATION_EXPOSURE_TRACE.csv` distinguishes:

- `active_p2d_flows_at_release`: flows whose backend `KV_STARTED`–
  `KV_COMPLETED` interval contains the timestamp;
- `active_p2d_flow_size_sum_at_release`: sum of those flows' declared sizes.
  This is **not** remaining bytes, instantaneous wire rate, or queue occupancy;
- `same_link_active_kv_flow_link_incidence_at_release` and
  `same_link_active_kv_link_byte_incidence_at_release`: active KV flow/link
  incidences over the critical route's directed links. A multi-link flow is
  counted once per shared link, so the byte incidence is not unique KV bytes;
- `active_ep_collectives_at_critical_release` and the corresponding EP/KV
  route-link incidence counts: interval coactivity at the selected barrier
  timestamp, not a delay estimate;
- `critical_flow_fct_or_cct_ns`: observed baseline last-shard FCT for a KV
  request or observed EP collective CCT. In contrast,
  `network_remaining_time_ns` stays blank until a matched network counterfactual
  can estimate exposed delay.

Intervals use half-open `[start,end)` membership. For EP rows, Decode activity
is reconstructed from each request's Decode-admission through request-end
interval. For a KV request barrier, all shards tied at the last completion are
retained in `critical_flow_ids`; the population snapshot timestamp is the
earliest backend-requested start among that co-critical set. In the current
44-request ledger, each request has exactly one co-critical shard. These are
event-ledger-derived populations, not device utilization or NIC queue depth.

On the 44-request Azure Code replay, the 22,464 EP rows have active Decode
population min/P50/P95/max `1/2/10/12`; active P2D flow count
`0/0/3/10`; and active P2D declared-flow-size sum
`0/0/5.344/17.734 MB` (decimal MB). The 44 request-level critical KV
releases see active Decode count `0/5/10/12` and active P2D flows
`1/2/3/5`. In the ex-ante 450–475ms candidate specifically, the 331 EP
collectives see mean/P50/P95/max active Decode count
`11.45/12/12/12`, active P2D flow count `1/1/3/4`, and same-route
active-KV flow/link incidence P50/P95/max `0/6/12`. This validates that
population and route exposure can now be quantified without calling flow-size
incidence a queue or bandwidth measurement. It does not overturn the negative
matched CCT/slack evidence above.
