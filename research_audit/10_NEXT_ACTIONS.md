# 10 — Next actions and stop gates

## Current disposition (2026-10-11)

The bounded EP–EP representability and serving check is complete. Do not run
more request/trace sweeps, Case D, packet replay, or scheduler/oracle work for
this candidate. The measured network effect is real but the serving delta is
under 1%; the fine-grained scheduling paper line is `NO_GO` in the tested
envelope.

## Disposition and handoff

1. Preserve the topology fix, focused tests, generator, configs, workloads and compact results. Current evidence binds to the dirty worktree, not `HEAD` alone; commit or archive the worktree before any future paper-grade comparison.
2. The validated topology is limited to rectangular group-major layouts. No claim is made for arbitrary group arrangements.
3. The matched EP–EP case produced shared-link contention and a modest barrier effect, but only +0.75–0.80% TPOT/TBT. That is not sufficient motivation for an oracle or practical scheduler.
4. Do not interpret the FlowSim fluid backlog as a packet queue. Native ns-3 fixed-time replay still lacks serving completion feedback.
5. If the project continues under a new hypothesis, first state the new physical mechanism and derive its maximum serving-visible gain before adding load or coding a policy.

## Current tests

The ten focused regression scripts cover topology rank count, collective scope, Decode completion and handoff wakeups, group queue ownership, rank mapping, ns-3 config selection, Decode capacity, P/D pairing and trace time units. The final focused run passed 36 tests. This is not the full repository suite.

## Stop condition

The tested independent-group EP–EP case has a small serving consequence, not a paper-level optimization opportunity. Close the current fine-grained arbitration direction for this evidence set. Do not fall back to extreme trace scaling, synthetic bytes, reduced link rate, artificial delays, or invented per-request EP flows.
