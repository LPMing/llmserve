# Final motivation decision — request/collective urgency

Date: 2026-10-12. Scope: existing-ledger audit and profile-derived theoretical gate only. No new serving/network simulation was launched, and no scheduler or simulator implementation was added.

## Decision

**Do not proceed to G2/G3 or algorithm development for the current same-class group/request urgency hypothesis.**

- H1: `EP_GROUP_URGENCY_IMPACT_SMALL` in the tested Qwen3 / RTX PRO 6000 / 200-Gbps / EP4-per-group / AG-RS envelope.
- H2: `KV_NETWORK_EFFECT_MASKED` in the audited layerwise P2D fixtures.
- `NO_INCREMENTAL_HEADROOM_OVER_SIMPLE_BASELINES`: **not demonstrated**. No request/group priority oracle, SRPT, EDF, LLF, or EP_FIRST-vs-group-priority integrated comparison was run. The evidence does not justify doing so at this gate.
- `MODEL_OR_INTEGRATION_INVALID`: not indicated by the specific retained ledgers; however, this is not a blanket validation of every current simulator path. The collective is AG/RS rather than sparse A2A, raw source provenance is partly transient, and historical controls are incomplete.

The key distinction is that network contention itself is real and reaches token timing in the homogeneous EP–EP fixture, while **differentiated same-class urgency with enough avoidable serving headroom is not established**.

## Findings against the requested questions

### 1–3. Which layers/groups are affected; is there a hidden per-group tail?

For the 4-request/group full fixture, the added token interval is accounted for at every one of the 48 layers:

`per layer = dispatch (+0.696 µs) + combine (+0.328 µs) = +1.024 µs`

`48 layers × 1.024 µs = +49.152 µs/token`.

The smaller 2-request/group fixture has `+0.696 µs dispatch +0.164 µs combine = 0.860 µs/layer`, or `+41.280 µs/token`. In the full run both groups' observed collective CCTs are identical; all eight requests have identical deterministic ITL sequences. The pooled P99 does not hide a group difference in this dataset: P50/P95/P99 equal the mean. But only Group A has a matched isolated baseline. Thus we know both groups participate in the full-run contention, not that their respective isolated-to-full penalties were separately measured.

### 4–6. EP headroom, larger legal batches, and actual overlap

For the observed EP4 case, the per-directed-cut work is 17,408 B dispatch and 8,192 B combine at four active requests/group. The measured group-A serving penalty is 49.152 µs/token, about 0.80% of the 6.108400-ms isolated token interval; the two-request/group result is about 0.75%.

For larger legal batches, profile-derived bytes and compute both grow. At group64/context2048 the ideal equal-shape, all-96-phase exclusive-service ceiling is 519.045 µs, or 3.07% of the estimated 16.899-ms compute-plus-isolated-EP token interval. This is an equal-work, perfectly aligned ceiling, not differential-urgency headroom. In the 132 directed heterogeneous batch/context screens, the largest optimistic target-group removal is 53.412 µs, or 0.3161%; this charges an entire serialization interval for every phase that intersects and is therefore generous. It is not a schedule or strict global oracle.

In the retained 4-request/group full run, there are 2,976 paired group/phase rounds across dispatch and combine; all paired releases are identical and all corresponding active intervals intersect on the common cut. These are actual overlapping phases, not an assumption that all 96 phases overlap. In the theory screen, different group work de-aligns the releases and the maximum overlap-limited headroom becomes very small.

### 7–11. Urgency, SLO, priority and classic baselines

There is no externally grounded TBT SLO for these fixtures. No SLO misses, recovery, or attainment rates can be calculated. The symmetric full-run groups have the same modeled interval and no differential urgency. Heterogeneous contexts/batches create different intervals, but the profile/cut bound is sub-0.32% and offers no non-arbitrary SLO result.

FAIR and EP_FIRST were not compared for this EP–EP group case. Since both groups are EP traffic, class-only EP_FIRST has no within-class selection signal; this is a code-level implication, not an observed policy result. No group-priority oracle, SJF/SRPT/EDF/LLF baseline, or fairness/deadline trade-off experiment was run. Therefore the data do not establish either that those methods solve the problem or that a new method beats them.

### 12. Earliest H1 failure condition

The topology and independent collective conditions pass: separate groups share a directed cut, and the measured collective delay propagates to the Decode token interval. H1 first fails at **differential exposed headroom**. Equal aligned groups have a small shared-class effect but equal urgency; when compute work differs enough to create an urgency contrast, release de-alignment leaves at most 53.412 µs (0.3161%) of optimistic target-group cut serialization in the tested matrix, before schedule feedback. A deadline chosen within that tiny margin would be a post-hoc knife-edge, not a grounded motivation.

### 13–15. KV request urgency and TTST

The 128-token victim has a worse shard-FCT distribution under large KV background (mean +10.91%, nearest-rank shard P99 +25.35%), but request readiness is determined by the last required shard, not the sum or percentile of all shard FCTs. Its last shard finishes 1.093557 ms before `p2d_ready`; the other inspected requests have 0.654–1.796 ms masking slack. In the A7 candidates, even an arithmetic +1.5-ms extra delay to the last required KV leaves readiness before the first *recorded baseline* Decode batch decision. This calculation does not simulate how a changed ready time would alter future scheduler wakeups.

No KV request-priority replay exists, so no measured priority-driven TTST change can be claimed. The one-output-token fixtures' second-visible timestamp (`TTST`) is diagnostic only and not a valid steady-state TBT distribution.

### 16. Incremental scheduling space

There is no demonstrated serving-level scheduling opportunity beyond class-level EP_FIRST. More precisely, the comparison was not run because the theoretical gate failed. The honest finding is **no evidenced incremental headroom**, not a proof that all possible request-aware algorithms are useless.

## Gate status

| Gate | Status | Reason |
|---|---|---|
| G0 — existing ledger audit | `PASS_WITH_SCOPE_LIMITS` | Request/group/collective and barrier relations can be reconstructed; AG/RS, missing Group B-alone/policy controls, and transient raw source limit claims. |
| G1 — theory/headroom | `FAIL_FOR_MATERIAL_URGENCY` | Heterogeneous-group optimistic bound max 0.3161%; homogeneous 3.1–3.5% ceiling has equal urgency. KV delay remains masked by recorded slack/admission cadence. |
| G2 — frozen network oracle | `NOT_RUN_G1_FAIL` | Correctly gated; no result has been fabricated. |
| G3 — integrated policy/SLO | `NOT_RUN_G1_FAIL` | No fixed SLO and no justified oracle headroom. |

## Classification

- `EP_GROUP_URGENCY_IMPACT_SMALL`
- `KV_NETWORK_EFFECT_MASKED`
- `NO_INCREMENTAL_HEADROOM_OVER_SIMPLE_BASELINES`: **not established / no positive evidence**
- `EP_GROUP_URGENCY_CONFIRMED`: **not met** (contention is confirmed, differentiated urgency motivation is not)
- `KV_REQUEST_URGENCY_CONFIRMED`: **not met**
- `MODEL_OR_INTEGRATION_INVALID`: **not assigned to these audited fixtures**, with the scope caveats above

## Stop decision and research implication

Stop this bounded request/collective-urgency motivation search here. Do not run the candidate 64-vs-8 network oracle, integrated priority policies, or wider workload sweep under the current evidence. Do not interpret this as a universal impossibility result. Reopen only if an independently specified service contract, a supported collective implementation with materially different effective cut work, or a new physically grounded serving DAG changes the gate inputs—not by tuning an SLO or forcing synchronization to fit the observed bound.

The current evidence is suitable as a careful negative result/capability characterization, not as a CCF-B/A paper motivation for fine-grained request/collective priority scheduling. The reports and ledgers in this directory provide the exact boundary and provenance.
