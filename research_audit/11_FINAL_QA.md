# Final Q1–Q10 answers — bounded baseline and motivation study

This report summarizes only evidence tied to the currently audited dirty
worktree. It is not an immutable release, a production-trace study, or a
completed scheduler evaluation. The current disposition is
`NO_GO` for the proposed fine-grained scheduling paper direction under the
tested envelope. The simulator is still only partially validated, and no
scheduler/oracle or CCF contribution is claimed.

## Q1. What correctness issues were confirmed, and were they fixed?

Confirmed and regression-tested in the current worktree:

- Profiled compute time in nanoseconds was passed to Chakra's
  `duration_micros`, causing a 1000× unit error. The adapter now converts the
  unit; pre-fix serving timing and phase-alignment claims are withdrawn.
- FlowSim worker wakeup after P2D handoff and after scheduler completion could
  leave runnable Decode work asleep behind a future-arrival deadline. Both
  paths were fixed and covered by focused regressions; the pre-fix TBT gap is
  retired as a simulator artifact.
- Decode admission capacity, logical/physical rank mapping checks, collective
  scope/queue ownership, and P/D pairing have targeted checks.

The latest focused run passed 36 tests across ten scripts, plus Python
compilation and `git diff --check`. This is not the repository-wide test suite.
The source fixes are uncommitted, and the complete simulator baseline remains
`PARTIALLY_VALIDATED`: exact GateRouter A2A, POST_PREFILL, integrated packet-
backend feedback, and arbitrary grouped topology remain unvalidated or
unsupported. Two independent EP4 groups are now covered only for one bounded
rectangular FlowSim layout.

## Q2. Should the project move to SimAI or another framework?

Not on current evidence. Keep the present serving frontend for request, KV,
P/D and token-barrier semantics, FlowSim as a fast fluid characterization
backend, and native ns-3 for packet-level checks. Neither backend alone
currently validates every required feature end to end. A framework replacement
would not itself provide integrated packet-completion feedback or establish a
scheduling opportunity. The bounded FlowSim topology now supports two
independent EP groups for one rectangular layout. Reconsider replacement only
if a concrete remaining capability gap cannot be added locally at bounded
cost. FlowSim output must not be described as packet queue, ECN/PFC or DCQCN
evidence.

## Q3. Under what legal conditions can KV–KV, EP–EP and KV–EP contend?

- **KV–KV:** distinct requests' P2D shards are active at the same time and
  share a directed link or sender/receiver NIC resource. This is representable
  and observed; shard FCT changes, but the tested request handoff did not.
- **EP–EP:** two distinct legal Decode collective groups run independent
  rounds concurrently and share a physical cut. This was demonstrated in the
  bounded EP4/2-group case; dispatch CCT rose 6.39%, combine 1.58–3.11%, and
  TPOT/TBT less than 1%. It establishes representability and modest network
  interaction, not a useful scheduling opportunity.
- **KV–EP:** one request's P2D traffic and a different, already-admitted
  request's Decode collective overlap in time and on a shared directed
  resource. A post-fix controlled case satisfies this condition. Same-request
  P2D-before-Decode ordering is not contention.

Current MoE communication is AG dispatch + RS combine, not strict GateRouter
A2A. Qwen3 model-derived KV and implemented AG/RS inputs are documented in
[`02_THEORETICAL_CONTENTION_MODEL.md`](02_THEORETICAL_CONTENTION_MODEL.md).

## Q4. Which network interference actually affected TTFT/TBT?

None of the tested FlowSim cases produced a material serving-barrier change.
KV–KV size skew raised one short request's within-run shard-FCT P99 by
25.35%, but its last required shard, KV-ready and TTFT did not move. In the
post-fix KV–EP case, EP CCT P99 increased 1.08%, request TTFT/KV-ready were
unchanged, and TPOT changed by less than 0.01%. Native ns-3 showed roughly
7.1–7.2% network-only collective-CCT inflation, but packet completion was not
fed into the serving scheduler. EP–EP matched integrated FlowSim changes
dispatch CCT +6.39%, combine CCT +1.58–3.11%, TTFT 0%, and TPOT/TBT +0.75–0.80%.
For EP–EP, the per-layer dispatch+combine CCT deltas sum exactly to the
measured TBT delta over 48 layers; the serving effect is real but small
relative to a 5.5–6.2-ms token interval. Earlier large TBT deltas caused by
the wakeup bug are invalidated.

## Q5. Is differentiation among requests/collectives within one traffic class necessary?

It remains a hypothesis, not a result. Shard-FCT differences show same-class
flows can receive different service, but tested KV-ready/TTFT barriers did
not expose it. EP–EP groups were tested and show only sub-1% serving impact;
no evidence demonstrates that finer per-request/per-collective priority would
improve end-to-end serving performance.

## Q6. Have Nuska/MFS, EDF/LLF or coflow methods already solved the candidate?

Generic request-aware, stage-aware, LLF, finite-queue priority, or collective
barrier scheduling cannot be claimed as novel. The reviewed Nuska v2 preprint
explicitly includes intra- and inter-request stage contention, request/batch
arbitration, dependency-aware flow scheduling and finite DSCP classes, with
TTFT as its main target. Decode-recurrent TBT is a possible scope distinction,
but merely extending a stage DAG over repeated iterations may be direct reuse.
Classic coflow and flow-scheduling work also precludes generic “barrier-aware
priority” novelty. A systematic 2012–2026 survey and executable head-to-head
baselines have **not** been completed; therefore the novelty gate is not
passed. See the [Nuska full-paper audit](03_NUSKA_FULL_AUDIT.md) and
[related-work matrix](04_RELATED_WORK_MATRIX.md).

## Q7. Is there a meaningful implementable unified fine-grained scheduling opportunity?

Not demonstrated. Tested FlowSim has shared-fluid service and a valid bounded
EP–EP topology, but no serving-level benefit large enough to motivate an
oracle. Exact A2A routing is absent, and practical finite-priority or host-
pacing policies were not evaluated. The fine-grained scheduling line is
closed for the tested envelope.

## Q8. What are the oracle and algorithm gains/costs?

No priority oracle or proposed algorithm was run; the motivation and novelty
gates are not passed. There are no valid gain numbers or implementation
overhead measurements to report. The +25.35% KV shard P99 and roughly 7% ns-3
collective network-CCT changes are not oracle gains and do not demonstrate
TTFT/TBT optimization headroom.

## Q9. What is the strongest CCF C/B paper idea and motivation?

There is **no confirmed CCF C/B paper idea in the tested evidence**. Independent
EP groups do contend, but their measured TPOT/TBT response is below 1%. The
remaining Decode-recurrent-barrier distinction is not enough on its own to
claim novelty against Nuska/LLF/coflow. A paper title, contribution list, or
venue claim would overstate evidence.

## Q10. Should the research continue?

`NO_GO` for the present fine-grained network-scheduling candidate. The bounded
independent-group test has been completed and did not expose meaningful TBT
headroom. Do not return to large traces, add an oracle, or escalate load to
manufacture a result. This does not rule out a future, independently motivated
network problem.

## Decision

`NO_GO` for the proposed CCF C/B scheduling paper based on current evidence;
baseline `PARTIALLY_VALIDATED`; `NOVELTY_NOT_ESTABLISHED`; `ORACLE_NOT_RUN`;
no algorithm or paper contribution validated. Detailed EP–EP measurements:
[`12_EP_EP_GROUP_VALIDATION.md`](12_EP_EP_GROUP_VALIDATION.md).
