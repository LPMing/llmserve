# Research audit status

This directory records recovery of the current dirty worktree for the
fine-grained network-scheduling study. Historical experiment tables are not
promoted to new evidence.

## Current decision

`NO_GO` for the current fine-grained scheduling paper line; simulator baseline
is still `PARTIALLY_VALIDATED`. Post-fix FlowSim exposes model-derived KV–KV and
cross-request KV–EP service overlap. KV–KV shard P99 can move by up to 25.35%
in a size-skew pair, but the last required shard/KV-ready/TTFT does not. The
post-fix KV–EP case changes EP CCT P99 by 1.08%, while request TTFT is
unchanged and Decode TPOT changes by <0.01%. Two independent EP4 groups now
share directed links in a bounded integrated FlowSim case: dispatch CCT rises
6.39%, combine CCT 1.58–3.11%, while TTFT is unchanged and TPOT/TBT rises only
0.75–0.80%. A complete ns-3 replay shows about 7% network-only EP CCT
inflation without serving feedback. These results show network interaction,
but not useful serving-level scheduling headroom.

The serving MoE path currently uses its native `ALLGATHER` dispatch plus
`REDUCESCATTER` combine realization with balanced routing. It does not emit a
GateRouter-derived exact A2A peer matrix. The primary P2D path is per-layer;
`POST_PREFILL` is not currently a supported serving mode. Any next-stage work
must be scoped to these actual semantics unless those features are separately
implemented and validated.

All code changes and reports are uncommitted. Results are tied to the dirty
worktree through source/config/workload hashes, not to `HEAD` alone.

## Reports

- [Baseline audit](01_BASELINE_AUDIT.md)
- [Code fixes and tests](01_CODE_FIXES.md)
- [Reproducibility ledger](01_REPRODUCIBILITY.md)
- [Machine-readable run/source manifest](results/01_baseline_run_manifest.json)
- [Manifest generator](scripts/write_baseline_manifest.py)
- [Next baseline actions](10_NEXT_ACTIONS.md)
- [Reproducible ns-3 packet smoke input builder](scripts/build_ns3_baseline_smoke_input.py)
- [Corrected FlowSim request CSV](results/current_baseline_flowsim_handoff_fix.csv)
- [Corrected FlowSim compressed flow ledger](results/current_baseline_flowsim_handoff_fix.jsonl.gz)
- [ns-3 packet smoke results](results/ns3_packet_smoke_minimal_logical_20261011_reproduced/network_run_manifest.json)

The two-independent-EP-group case is representable in the tested rectangular
group-major layout; other arbitrary arrangements remain unsupported and fail
closed. EP–EP contention exists, but the serving-level effect is weak and
does not pass the motivation gate. No large trace, scheduling oracle,
scheduler prototype, or paper result is claimed. The current paper-line
disposition is `NO_GO` for this evidence set.

## Gate artifacts

- [Theory and barrier-exposure model](02_THEORETICAL_CONTENTION_MODEL.md)
- [Minimal cases](02_MINIMAL_MOTIVATION_CASES.md) and [results CSV](02_MOTIVATION_RESULTS.csv)
- [Contention gate decision](02_CONTENTION_GO_NO_GO.md)
- [Full Nuska audit](03_NUSKA_FULL_AUDIT.md) and [novelty difference](03_NOVELTY_DIFFERENCE.md)
- [Related-work matrix](04_RELATED_WORK_MATRIX.md) and [novelty gate](04_NOVELTY_AUDIT.md)
- [Oracle status](05_PRIORITY_ORACLE_RESULTS.md), [scheduler status](06_MINIMAL_SCHEDULER_DESIGN.md)
- [Consolidated experiment results](07_EXPERIMENT_RESULTS.md), [direction decision](08_FINAL_PAPER_DIRECTION.md), [conditional blueprint](09_PAPER_BLUEPRINT.md), [next actions](10_NEXT_ACTIONS.md)
- [Final Q1–Q10 answers and overall disposition](11_FINAL_QA.md)
- [Independent Decode EP-group validation and matched controls](12_EP_EP_GROUP_VALIDATION.md)
