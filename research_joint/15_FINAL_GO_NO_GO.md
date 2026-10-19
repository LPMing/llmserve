# Final decision

## Decision: `NO_JOINT_MAINLINE_FOUND`

Within the currently supported model/profile/topology and the bounded experiments performed, no candidate demonstrates a robust, fixed-resource, network–serving joint optimization that both beats single-sided alternatives and is materially distinct from prior work.

### Strongest bounded positive mechanism: B

Two independent EP4 groups share the same directed 200-Gbps cut. In the synchronized 8-request run, all 2,976 logically matched dispatch/combine round pairs overlap in time and on common directed links. With a one-time 20-µs hold before `ep_b`'s first Decode batch, the same 2,976 rounds have no temporal common-path overlap. Per-group dispatch/combine CCT returns from 11.593/10.856 µs to 10.897/10.528 µs. Model-derived KV/dispatch/combine bytes are identical.

But the serving effect is small: across all per-request ITL samples, mean falls from 6.157552 to 6.108723 ms (~0.793%); makespan falls from 235.757112 to 234.253400 ms (~0.638%). Group B pays 20 µs in its first Decode interval (6.1284 ms vs 6.1084 ms for A), then benefits on subsequent repeated intervals. TTFT remains 44.873 ms because the first output token is produced by Prefill before the Decode phase gate. With only eight deterministic requests and no external SLO, there is no credible population P99 or SLO claim.

This is a controlled all-at-zero AG/RS FlowSim characterization, not a natural-load frequency statement, not packet-level evidence, and not proof of sparse A2A behavior. It demonstrates phase sensitivity, not a publishable scheduler advantage.

### A and C

- A's joint readiness/compute selection is already close to NetKV's direct network-aware Decode-instance selection. The repository's narrow older slot-boundary test improves one request, but global pair makespan only ~0.014%; topology-oracle CCT deltas were at most 7.1% in selected windows. No fixed-resource three-candidate S0–S3 result establishes incremental headroom. Stop rather than build a larger fixture around a known policy.
- C cannot currently be tested faithfully: BALANCED routing does not retain an exact token→expert-owner matrix and the serving collective is AG/RS. FAST, Semantic Parallelism and Gimbal overlap with the broad batching/routing idea. No synthetic route matrix is substituted.

### Correctness and implementation limits

The focused regression passed 49 tests across 11 scripts. The narrow new phase-gate scheduler hook is disabled by default; an initial run without a scheduler deadline produced an invalid delayed-retry result and was excluded. The wakeup path was fixed and tested before the valid B3 run. TTFT semantics were inspected and are consistent with Prefill's first token output; the phase delay is therefore reported in second-token/ITL metrics, not TTFT. Overall simulator baseline remains **PARTIALLY_VALIDATED** because the worktree is dirty, historical run-to-commit binding is incomplete, exact sparse A2A is absent in this experiment, and native packet-level serving feedback is not validated.

## Joint-side test requirement

The required comparison is `J(S3) < min(J(S1), J(S2))`. It was **not demonstrated**. For B, only S0 (synchronized FAIR) and a Serving-side one-time phase offset (B3) were measured; there is no independent network-only optimizer S1 or distinct joint S3. For A/C, S0–S3 were not run because the novelty/theory/capability gate did not justify them. Do not turn B3's improvement over S0 into a “joint gain.”

## Reproducibility status

- B0 ep_a-only, B1 ep_b-only, B2 synchronized, and B3 20-µs phase runs produced compact request CSVs in `research_joint/outputs/`.
- Raw FlowSim telemetry is in `/tmp/research_joint_ep4_{a_only,b_only,sync,phase20us_fixed}_telemetry.jsonl`; it is not copied into the repository. The invalid pre-fix phase diagnostic is `/tmp/research_joint_ep4_phase20us_telemetry.jsonl` and must not be used as a result.
- The B-only config and rank map are retained under `research_joint/configs/`.
- Git HEAD remains `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`; all pre-existing and new worktree edits remain uncommitted. The tracked diff SHA-256 at final artifact QA is `0f31dfcc88b2ca027a93275f03d14587f10cb10e9c3b8dd9a2abb09c7866f1d9` (also in `PROVENANCE.md`).

## What would change the decision

Do not continue sweeping offsets, increasing EP scale, or inventing exact routes. Reopen only with a new, independently justified mechanism that (1) is not captured by network-aware placement or collective coordination baselines, (2) survives a matched fixed-resource integrated comparison, and (3) provides a meaningful SLO/goodput objective. Otherwise close this A/B/C candidate set.

**Final status: `NO_JOINT_MAINLINE_FOUND`.** This is not a claim that all joint optimization is impossible; it is a no-go for the present candidate set and validated envelope.
