# Recovery checkpoint after Round 19

## Current claims

`MOTIVATION_VALIDATED` remains frozen for the P-hit/D-miss causal
mechanism in `MOTIVATION_REPORT.md`. `PAPER_HEADROOM_VALIDATED` is not
reached. The current A history/cost case is solved on modeled completion
by plain online LFU; the current B admission-timing case is solved by
ordinary two-stage FIFO; the current C uniform transfer-order case gives
only 6.76% over FAIR and is solved by simple FIFO order. No new policy
gain or paper result is claimed.

## Reproduction and exact evidence

Every Round-19 case and status, including the invalid first byte-overcount
run, is indexed in `EXPERIMENT_REGISTRY.jsonl`. Case manifests record
commands, source/profile/input/output SHA-256, seed and dependencies.
The source diff is intentionally dirty and contains earlier research
changes; do not treat `git HEAD` alone as code provenance. The full
52-script P/D suite, 13 focused simulator tests and `git diff --check`
passed after the Round-19 implementation. Run again after any code edit:

```bash
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=.:astra-sim/extern/graph_frontend /home/lpm/.conda/envs/llmsim-flowsim/bin/python -m unittest discover -s experiments/pd_kv_ep/scripts -p 'test_*.py' -q
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=.:astra-sim/extern/graph_frontend /home/lpm/.conda/envs/llmsim-flowsim/bin/python -m unittest discover -s research_autonomous/simulator_tests -p 'test_*.py' -q
```

The B source-control path is in `serving/core/scheduler.py`:
`source_held`, `_schedule_held_handoff`, `cancel_held_handoff` and the
handoff-only `add_done` branch. The exact transfer graph is
`serving/core/trace_generator.py::generate_handoff_trace`. The first
attempt used `fp` bits as bytes and is `INVALID_BYTE_OVERCOUNT`; the
corrected run uses `fp//8` and passed exact flow conservation.
Matched early POST and two-stage cases isolate credit timing. Separate
early LAYERWISE reruns in the registry preserve the stronger overlap
protocol; its different transfer DAG makes that a whole-protocol
comparison rather than an admission-only treatment effect.

## Next independent discriminator

Start from a source-backed heterogeneous request stream, not a parameter
sweep of the completed fixtures. Form a joint-resource theory card with
observed/declared P/D GPU, NIC, KV capacity, prefix identities and arrival
order. Compare **two-stage FIFO, FIFO/SRPT network order, LFU or
cost-aware retention, DELTA, single-flight and cache/load/network-aware
D routing** under the same resources. Compute a legal small Oracle or a
tighter bound before implementation. Proceed to a new policy only if a
specific failure of that combined simple baseline leaves at least 10%
modeled completion or SLO-goodput headroom and a plausible online signal.
If no such case exists, record a bounded NO_GO/NEED_DATA rather than
manufacturing congestion or claiming Oracle gains.

The unchanged first-50 Llama ShareGPT window already has a reproducible
theory screen in `candidates/r18_joint_bottleneck/theory/sharegpt50_screen.json`:
0.492-s full-KV cut service versus at least11.766-s last-request
Decode work after arrival. Its3.078% ratio is only for fixed downstream
work; a new joint problem must explicitly name a memory/batching/order
interaction that escapes that screen and the combined simple baseline.

Relevant nearby work: [P/D-Serve](https://arxiv.org/abs/2408.08147)
already describes retaining a Prefill prompt while awaiting transfer;
[DMRS](https://arxiv.org/abs/2610.15579) formalizes coupled Prefill/
Decode memory scheduling and completion-time minimization;
[PrefixPlace](https://arxiv.org/abs/2608.01655) handles heterogeneous
prefix compute/transfer costs; [NetKV](https://arxiv.org/abs/2606.03910)
addresses topology/congestion/cache/load-aware Decode choice. These
strengthen the comparator requirement.

## Remaining model boundaries

- FlowSim is fluid, with zero-time receiver credit/query control; packet
  transport, NIXL startup and real cancel handshakes are not calibrated.
- Two-stage FIFO currently supports TP1/PP1, POST_PREFILL P/D,
  one target Decode per request and no DP group. An optional DELTA late
  reservation has unit coverage but no end-to-end run yet. Internal
  cancel state tests exist; the workload format has no external abort event.
- `TTFT` is a Prefill graph-completion proxy whose position differs in
  early POST and compute-only two-stage traces. Compare P2D-ready,
  token 2 and modeled completion, never call flow FCT client TTFT/TBT.
- The A synthetic frequency and churn sequence has no measured
  production prevalence; committed ShareGPT traces have limited reuse.
