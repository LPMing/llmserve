# Existing evidence and audit provenance

Audit date: 2026-10-12. Scope: strict-theory screening of owner-level MoE dispatch/compute/combine overlap. No new Serving or FlowSim performance run was started. Existing experiment artifacts were read only; nothing in historical result directories was modified or removed.

## Repository provenance

- Git HEAD: `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`.
- Worktree was already dirty before this audit. Tracked diff SHA-256 at audit start: `0f31dfcc88b2ca027a93275f03d14587f10cb10e9c3b8dd9a2abb09c7866f1d9`. Numerous pre-existing untracked research files/directories were also present; preserved.
- Model config SHA-256: `0736f3bafb95cc658776c92ab34f5f98f8169634a3a36b84892d71448a1f19d3`.
- RTX PRO 6000 profile meta SHA-256: `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96`.
- `tp1/moe.csv` SHA-256: `aa6e29a17412a62234a6610d7a699f72e5938f09386374b635925c5db29045f6`.
- Relevant source hashes are recorded in `05_THEORY_GATE_DECISION.md`.

The provenance binds current source and profile, **not** every historical result. Old reports that say standard serving used exact A2A_P2P conflict with the current `trace_generator.py`/`graph_generator.py` path and must not be silently treated as current-version integrated evidence.

## Relevant retained historical evidence

1. `research_motivation/group_urgency/02_EP_THEORETICAL_HEADROOM.md` reports a profile-backed EP4-per-group AG/RS screen. Its largest heterogeneous-group optimistic screen is 53.412 µs, 0.3161% of the target token interval; the equal-shape 64-request/group all-phase ceiling is 3.07% and has no differentiated urgency. These numbers concern inter-group collective urgency, **not** owner-level dispatch/compute streaming, so they are context only.
2. `research_motivation/group_urgency/10_FINAL_MOTIVATION_DECISION.md` reports a retained EP4 AG/RS contention fixture with 49.152 µs/token or about 0.80% of the 6.1084 ms isolated interval. It is not owner-level streaming evidence.
3. There are 2,040 `.a2a_routes.json` sidecars in the audited `natural_ecn_baseline_v1/.../s8_d8_k2_i8192_gap5ms` run tree (2,016 EP32 route records). A sampled record is `BALANCED`, has source tokens `[1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,...]`, 2 tokens and 2 activated experts per owner, and is repeated over 48 layers. This is a simulator-balanced route approximation, not learned checkpoint gate output. The profile has no `(tokens=2, activated_experts=2)` sample; its smallest activated-expert axis value is 8. These sidecars therefore do not provide profile-supported owner compute durations.
4. `experiments/pd_kv_ep/CRITICAL_EP_PROTECTION_VALIDATION.md` is a historical offline critical-flow test, not proof for this different DAG. It cautions that protecting a formerly critical flow can migrate the straggler.

## Focused regression checks

Passed with the repository's `llmsim-flowsim` environment and `PYTHONPATH=.`:

- `test_flowsim_collective_scope.py`: 4/4.
- `test_flowsim_decode_completion_wakeup.py`: 4/4.
- `test_pd_decode_capacity_admission.py`: 7/7.

These are focused semantic tests, not a full simulator correctness certification. The independent toy scheduler in this directory is a mathematical checker; it is not a serving experiment.

## Current audit conclusion

The current serving-generated MoE trace uses AG/RS and does not provide a source→owner route matrix. A separate exact-P2P converter extension exists and includes rank-local joins, but it is not wired through the standard graph-generator arguments. Its join also waits both local sends and receives. The repository therefore contains a partial dormant capability, not a validated integrated owner-readiness implementation.

