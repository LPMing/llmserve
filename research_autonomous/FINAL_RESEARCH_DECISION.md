# Autonomous research decision (2026-10-15)

**2026-10-15 Round 14 update:** A targeted ordered scan of the four pinned
Qwen-Bailian production-derived traces found no eight-distinct-prefix
short-output root bursts even in a permissive 1-s window. The near-2048
input window has only 440 optimistic prior-prefix candidates across the
four files, with at most two distinct in 100 ms or 1 s. These Qwen traces
cannot support a frequency claim for the Llama-8B eight-source fixture,
and contain no observed P/D cache state. This is a bounded workload
negative, not a denial of the measured cache/network inversion. The paper
mainline remains unvalidated. See `ROUND14_PREFIX_BURST_SCREEN.md`.

**2026-10-15 Round 12–13 update:** Prefix-hit acceleration on the documented
8×4090/one-100-Gb/s source-node ratio produces a measured source-NIC
bottleneck. With a 1984-token P hit, 8P D-miss P2D-ready is 171.876 ms
versus 20.969 ms when each D holds its prefix; cold 8P ready is 193.161 ms.
The first controlled D-miss fixture had an idle D-resident alternative, so
cache-aware routing already obtains the 20.969-ms path. A subsequent
normal-capacity 8P:2D run with 64 distinct filler requests produced all
eight P hits and all eight D misses for eight *distinct* target prefixes,
without a warm D alternative or capacity queueing. But its full-KV source
cut is within 0.045% of the 100-Gb/s byte floor, ruling out a meaningful
fixed-byte network scheduler gain. Prefix-retention/prepositioning remains
`NEED_DATA` until it beats LFU, PrefixPlace, NetKV, shipped delta and
single-flight semantics on an ordered workload with an online demand signal.
`ROUND12_PREFIX_INVERSION.md` and `ROUND13_NATURAL_CACHE_ASYMMETRY.md`
retain exact evidence. There is still no validated publishable policy gain.

**2026-10-15 update:** Round 11 added an exact-model Qwen3-32B TP2,
1P1D/4P1D two-rail layerwise test. The 4P1D last KV flow finished 2.453 ms
before an unchanged 184.907-ms P2D-ready barrier, so the bounded receiver-cut
candidate is also `NO_GO`. The 15-scenario theory bank and current
Decode-memory handoff limitation are in
`ROUND11_SCENARIOS_AND_THEORY.md`. A documented 8×RTX-4090/one-100-Gbps-NIC
hardware ratio yields a conditional prefix-hit network threshold, but lacks
observed Decode misses and an incremental mechanism over cache-aware/DELTA
baselines. The pinned SwissAI exact-model file was
archived before the revised theory-first instruction; its full analysis is
deferred. No `MOTIVATION_VALIDATED` paper candidate has emerged.

## Result

**NO_VALID_PAPER_MAINLINE in the currently profile-valid and causally audited
envelope.** This is a bounded negative result. None of the tested directions
has both a credible >=10% Serving gain over a strong matched baseline and a
clear incremental mechanism over recent work. Directions requiring missing
route, cache-miss or client-token data are `NEED_DATA`, not performance
failures. The complete screen is in `CANDIDATE_DIRECTIONS.md`.

## Most decisive new loop

The retained Qwen3-30B-A3B TP2/PP2, four-Prefill/one-Decode, dual-200-Gbps
topology gives 201,326,592 B of P2D KV per 2048-token request. Theory from
the checked-in profile predicts a 0.335544-ms four-source wave against a
1.339101-ms block interval. The same-input FlowSim test initially reported
an impossible PP stage-1 release at 0.072 ms, before stage 0 produced its
output. We repaired the excluded-class PP SEND/RECV dependency and found a
second EP1/TP2 expert graph omission. Raw files before both repairs, after
the PP repair and after both repairs are retained separately.

After both repairs, the first stage-1 KV flow releases at 32.310 ms. All
384 P2D flows conserve exactly 201,326,592 B/request; the last finishes at
63.554745 ms, before the 64.712-ms Prefill/P2D-ready barrier. Modeled token
2 and request completion occur at 78.723 and 92.734 ms. A network placement
policy cannot remove >=10% from this fixed-resource critical path because
there is no exposed receiver-cut tail to remove at this point. The measured
first wave FCT is 0.355745 ms, consistent with the 0.335544-ms fluid
serialization floor plus path latency. This is a model-based mechanism gate,
not a hardware latency validation or natural-load frequency estimate.

The earlier 3P2D receiver-placement experiment was rerun after the MoE fix
in an independent directory. Every one of its 16 assignment/mode metric
rows is identical to the historical result. POST_PREFILL optimal assignment
adds only 0.0042205% mean token-2 improvement over sequential load-updating
greedy; LAYERWISE adds 0%. This removes the strongest remaining concern that
the converter bug invalidated that NO-GO gate.

## Code and audit changes

- `serving/core/flowsim_worker.py`: excluded local/OTHER PP P2P uses a
  job-scoped FIFO sender/receiver rendezvous; P2D exclusion fails loudly.
- `astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py`:
  a sole EP1 expert block executes on every TP replica. EP2 expert sharding
  remains unchanged in the control test.
- `experiments/pd_kv_ep/scripts/test_pd_request_pairing.py`: the test's
  scheduler stub returns its Request, matching the real scheduler API.
- `SIMULATOR_CAPABILITY_AUDIT.md`: records remaining model/metric limits.

These changes repair causal semantics; they are not proposed paper
optimizations. Five new focused tests and 49 existing P/D script tests pass.
Full `serving/validate.sh` and hardware bench validation were not rerun, so
global simulator accuracy remains unproven. Existing output `TTFT` is a
Prefill graph-completion proxy in P/D mode, and no client egress event is
available. TP/PP OTHER communication has zero transfer duration by default;
FlowSim is fluid and does not model packet queues or NIXL transport overhead.
These limits prevent a client-TTFT/SLO claim from this artifact.

## Reproduction and files

From the repository root, with the existing simulator environment:

```bash
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=.:astra-sim/extern/graph_frontend /home/lpm/.conda/envs/llmsim-flowsim/bin/python -m unittest discover -s research_autonomous/simulator_tests -p 'test_*.py' -q
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=.:astra-sim/extern/graph_frontend /home/lpm/.conda/envs/llmsim-flowsim/bin/python -m unittest discover -s experiments/pd_kv_ep/scripts -p 'test_*.py' -q
python3 research_autonomous/theory/pp_coflow/derive.py
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=.:astra-sim/extern/graph_frontend /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/experiments/pp_coflow/scripts/run_gate.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/experiments/pp_coflow/scripts/analyze_gate.py
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=.:astra-sim/extern/graph_frontend /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/experiments/receiver_recheck/scripts/recheck.py
```

`experiments/pp_coflow/raw_before_fix/`,
`raw_after_pp_fix_before_moe_fix/` and `raw/` hold the three causal states.
`processed/theory_sim_comparison.csv` compares them. Each current run has a
manifest with source/config/profile hashes. `experiments/receiver_recheck/`
holds the post-repair 16-case raw and summary; its manifest binds the reused
historical runner and relevant source files. The repository has substantial
pre-existing uncommitted work, so these manifests are the reproducibility
identity rather than a clean commit alone.

## What would reopen research

1. **Natural P/D congestion:** a model-matched trace with several P2D-ready
   requests within one receiver-rail service window, legal alternative
   Decodes, measured link/NIC sharing and a tuned NetKV-like comparator.
   Profile the actual longer or mixed prompts before making latency claims.
2. **Remote agentic KV:** a trace with observed lower-tier misses, a measured
   CXL/RDMA load latency and contention model, and an independently recorded
   client-token event. Compare against on-demand load and advisory prefetch.
3. **Sparse MoE:** genuine per-layer token→expert routes, EP32/64 relevant
   expert-shape profiles, physical rank→GPU→NIC mapping and an integrated
   sparse A2A DAG with dispatch/combine feedback. Compare against strong
   backend and overlap systems.

The newly available public FreeInference agentic trace is a promising
arrival/dependency source, but its provider/model mix and some long prompts
do not match the current Qwen 2048-token latency profile. Adapting its shapes
requires explicit cross-model assumptions or new hardware profiling. No
further artificial fan-in, bandwidth reduction or oracle-only gain is counted
as evidence.
