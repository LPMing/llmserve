# Research log: network and Serving paper gate

Date: 2026-10-14 (Asia/Shanghai). Source HEAD:
`0c0839aff54ec0abb1810dc09cf3d66f06b1b078`. The repository already had
substantial uncommitted work before this audit. This round adds only
`research_receiver_matching/` and this log; it did not alter simulator source
or overwrite earlier research results. Rounds 5–6 later repaired the PP
dependency and EP1/TP2 converter paths and retained separate rerun artifacts.
Exact Round-1 input and source hashes are in
[`00_PROVENANCE.json`](research_receiver_matching/00_PROVENANCE.json).

## Round 1: causal and metric audit

**Hypothesis.** The document's 4→1 versus 4→2 packet result might imply a
large client-visible gain from joint P2D placement.

**Source audit.** `Router.route_arrived_requests()` pins a Decode instance
from `pd_pairing` before Prefill execution; the P2D graph uses that fixed
destination. `Router.transfer_prefill_request()` then admits the same request
to the pinned Decode. This preserves KV correctness, but there is no online
cohort matching point or per-request destination choice within a multi-request
Prefill graph. The small experiment below assigns one request to each Prefill
instance, allowing all legal fixed-resource assignments to be enumerated.

`Scheduler.add_done()` records `TTFT` and `first_token_visible_ns` when the
Prefill graph completes. That graph can remain live after the sampler because
P2D sends still need to finish. There is no independent client output callback
or external frontend network in the simulator. Thus the current `TTFT` field is
a modeled graph-completion proxy for P/D and cannot certify client TTFT. The
Decode `second_token_visible_ns` is recorded at Decode batch completion, and
`end_time` at request completion; these are valid scheduler boundary metrics
within this model, with no frontend delivery latency. This study uses those
two values and reports P2D ready separately. No event was relabeled as a real
client emission to manufacture a TTFT result.

FlowSim performs fluid/max-min network service with callbacks into graph
completion. It is suitable for a paired Serving causal comparison, but does
not reproduce DCQCN, ECN, packet queues, or software transport overhead.
Its default `FLOWSIM_NETWORK_CLASSES=KV_MOVEMENT,EP` also completes TP
collectives classified as `OTHER` at DAG readiness, without an intra-node
communication time. The absolute token latencies here are therefore not
calibrated TP2 hardware predictions. This omission applies to every matched
assignment; a positive paper claim would require a measured TP/NVLink model.
`POST_PREFILL` is a model-derived synchronous handoff mode, without NIXL
registration, WQE, polling or GPU memory-copy overhead.
The saved ns-3 packet runs were independently recomputed from raw
`comm_events.csv` by [`recheck_packet.py`](research_receiver_matching/recheck_packet.py)
into [`03_PACKET_RECHECK.csv`](research_receiver_matching/03_PACKET_RECHECK.csv):

| Packet case | Mean shard FCT | Maximum request ready | Status |
|---|---:|---:|---|
| 4→1, CC0 | 32.481310 ms | 32.481557 ms | network only; CC0 diagnostic |
| 4→2, CC0 | 16.261314 ms | 16.261397 ms | network only |
| 4→4, CC0 | 8.151317 ms | 8.151317 ms | network only |
| 4→1, CC1 | 32.781754 ms | 34.315681 ms | packet congestion control active |
| 4→2, CC1 | 17.091878 ms | 17.207700 ms | packet congestion control active |

These numbers verify receiver fan-in as a *network* mechanism. They do not
measure Serving latency. The document's 21.94–27.24% expressions add an
unoverlapped packet transfer to a Prefill floor taken from a different run;
the same-dataset critical path and Decode batching must be measured instead.

**Next action:** run a fixed-resource integrated exhaustive placement gate
using the profile-valid prompt length.

## Round 2: exact small-cohort placement gate

**Theory before simulation.** Qwen3-30B-A3B BF16 has 48 layers, four KV
heads and head dimension 128: `2 × 4 × 128 × 48 × 2 = 98,304` KV bytes/token.
At 2,048 input tokens, each request transfers 201,326,592 B total and
100,663,296 B per TP2 rail. A 200-Gbps rail serializes one shard in
4.026532 ms. A simultaneous three-request one-receiver cohort has a
12.079595-ms per-rail serialization floor; assigning two and one to two
receivers gives an 8.053064-ms worst-receiver floor. These are network
floors, not Serving savings. The proposed 4,096-token `POST_PREFILL` experiment
failed its legality check: this mode requires the whole prompt in one graph,
whereas the measured profile and token budget stop at 2,048. We therefore
used 2,048 without extending a profile outside its measured domain. The
EP1 MoE lookup can use up to 128 local activated experts, which is present
at the 2,048-token row of the measured `tp1/moe.csv` grid.

**Matched experiment.** Qwen3/RTX PRO 6000 BF16, TP2, EP1, three Prefill
instances and two Decode instances on the existing five-server/ten-active-rank
200-Gbps topology; three identical prompt-2,048/output-3 requests at time 0;
same routing, cache disabled, model profile, hardware and NIC mapping in all
16 runs. For each of `POST_PREFILL` and `LAYERWISE`, all eight assignments of
P0/P1/P2 to D0/D1 were executed with FlowSim FAIR. The sequence `010` is one
assignment made by sequential least-assigned-rail-work selection with a fixed
tie break, updating assigned work after each request. It is replayed as a
static pairing because the current router does not implement this online
policy. All six balanced assignments produce almost identical results; the
exhaustive optimum is the best of all eight assignments under the measured
Serving objective. Full per-request results,
event logs, exact commands and config hashes are in
[`run_exhaustive_gate.py`](research_receiver_matching/run_exhaustive_gate.py)
and [`01_EXHAUSTIVE_ASSIGNMENT_RESULTS.csv`](research_receiver_matching/01_EXHAUSTIVE_ASSIGNMENT_RESULTS.csv).
The independent [`audit_flow_paths.py`](research_receiver_matching/audit_flow_paths.py)
check passed for all 2,352 P2D shard flows: each request sends exactly
201,326,592 model-derived bytes and its physical destinations are D0 rails
24/28 or D1 rails 32/36 as assigned. Paths and completion times are in
[`06_FLOW_PATH_AUDIT.csv`](research_receiver_matching/06_FLOW_PATH_AUDIT.csv).

| Release mode | Metric | All to D0 | Greedy `010` | Exhaustive best | Best over greedy |
|---|---|---:|---:|---:|---:|
| POST_PREFILL | mean arrival→token 2 | 88.336796 ms | 78.979420 ms | 78.976087 ms | 0.00422% |
| POST_PREFILL | mean request completion | 99.850796 ms | 86.508087 ms | 86.504753 ms | 0.00385% |
| POST_PREFILL | max arrival→token 2 | 88.336796 ms | 81.812264 ms | 81.802264 ms | 0.01222% |
| LAYERWISE | mean arrival→token 2 | 76.226000 ms | 72.240667 ms | 72.240667 ms | 0% |
| LAYERWISE | mean request completion | 87.740000 ms | 79.769333 ms | 79.769333 ms | 0% |

**Causal interpretation.** In `POST_PREFILL`, the 10.60% token-2 and 13.37%
completion gains of the best placement over forced incast are real within the
integrated FlowSim run, but they are nearly all available to a simple
sequential greedy. The optimum's 3.333-µs mean advantage is below 0.005%.
No request's maximum token-2 or completion latency is sacrificed by the
optimum. In `LAYERWISE`, P2D ready is 64.712 ms for every assignment;
Prefill compute hides the transfer. The token-2 gain from 1→2 Decode
distribution is Decode batch-size reduction (11.514-ms versus 9.016/4.554-ms
iterations), not reduced P2D waiting. It cannot motivate a network algorithm.
The flow→scheduler boundary closes numerically: `POST_PREFILL 000` has its
last P2D flow, P2D ready and Decode admission at 76.822796 ms, followed by
token 2 at 88.336796 ms. For balanced `010`, the last P2D flow/ready moves
to 72.796264 ms. In `LAYERWISE 000`, the last flow finishes at 63.480859 ms,
before the 64.712-ms Prefill graph barrier; balancing moves that last flow
to 63.396973 ms but leaves P2D ready unchanged.

This falsifies the proposed paper claim for this tested symmetric cohort:
**receiver incast exists, but global matching adds effectively nothing over a
balanced, work-updating per-request baseline.** The eight-assignment optimum is
an offline comparison, not an implemented online scheduler. No ns-3 packet
placement run was made after this Serving gate failed.

**Natural workload check.** Six one-request FlowSim runs measured Prefill
ready from 44.875 ms (256 tokens) to 64.712 ms (2,048 tokens). Every
calibration's final P2D flow finished 1.101–1.399 ms before graph ready, so
the values screen compute-side completion in this range. Interpolating these
profile-valid points and preserving ShareGPT arrivals and output lengths
for a theory screen of 300 Qwen requests at 10 sessions/s gave 290 in-domain
requests. There were zero predicted three-request Prefill-completion cohorts
inside 4.037 ms (one max-size shard service) and one inside 8.053 ms; its
inputs were 974/881/410 tokens, whose individual service times are much less
than the permissive 8.053-ms window. Ten prompts above 2,048 tokens were
excluded, and the projection uses FCFS per Prefill rather than full Serving
feedback. This is an **analytical screening result**, not a measured natural
Serving speedup or a proof that no other workload can form cohorts. See
[`screen_natural_cohorts.py`](research_receiver_matching/screen_natural_cohorts.py),
[`04_PROFILE_PREFILL_CALIBRATION.csv`](research_receiver_matching/04_PROFILE_PREFILL_CALIBRATION.csv)
and [`05_NATURAL_COHORT_SCREEN.csv`](research_receiver_matching/05_NATURAL_COHORT_SCREEN.csv).

**Next action:** audit whether the bundled multi-turn trace actually requires
remote KV retrieval before designing prefetch.

## Round 3: agentic remote-KV prefetch prerequisite gate

**Theory.** A 4,096-token Qwen prefix is 402,653,184 B. At an assumed shared
60-GB/s CXL bandwidth it has a 6.711-ms serialization floor. Hiding that
transfer during a tool gap can be valuable *only if the prefix is actually in
the lower tier and the fetch is timed and competes for its real path*. Current
FlowSim treats the ordinary CXL `MEM_LOAD` duration as zero, so an integrated
CXL TTFT gain is not measurable with the present model.

**Trace audit.** The bundled 50-session SWE-bench trace has 715 child turns,
611 positive tool gaps, median 109.266 ms. Under the *conditional* assumption
that every child's common-prefix KV must be fetched at 60 GB/s, 85.45% of
gaps could cover the ideal transfer and the mean hideable duration is
7.841 ms. This is not an observed performance opportunity. The actual
token-ID hash chain has 25,338 distinct full blocks across all sessions;
counting the same hashes separately per session and charging every one of
50 simultaneously active sessions its maximum missing-ID/partial tail gives
29,086 blocks. One Qwen/TP2 RTX PRO 6000 instance has 42,260 KV blocks in
the tested config; `MemoryModel` derives the same block count with prefix
caching enabled because that flag changes indexing, not capacity. Thus this
dataset does not force a single-instance NPU
cache eviction, even under the conservative all-session bound. No remote
fetch was measured. The sidecar token IDs are shorter than the declared
request shapes by as much as 1,140 tokens, so the bound explicitly charges
those live tail blocks. Results are in
[`audit_remote_prefetch.py`](research_receiver_matching/audit_remote_prefetch.py)
and [`02_REMOTE_PREFETCH_SUMMARY.json`](research_receiver_matching/02_REMOTE_PREFETCH_SUMMARY.json).

**Decision.** The real tool gaps alone cannot support a remote-prefetch
paper result. There is no evidenced remote-cache miss for this trace and no
timed FlowSim lower-tier load to move off the critical path. Do not implement
EDF/network-aware prefetch against zero-duration loads or count a conditional
oracle as measured gain.

## Prior work and current selection

[NetKV](https://arxiv.org/html/2606.03910v1) already makes network-aware
Decode selection per request, tracks its own in-flight transfers, and compares
against tuned cache+load routing. Explicit receiver-rail capacity and joint
cohort matching could be distinct, but this run found no incremental Serving
headroom. [SYMPHONY](https://www.usenix.org/conference/nsdi26/presentation/agarwal)
already uses advisory prefetch for multi-turn KV state;
[HyMCache](https://arxiv.org/abs/2607.18141) adds request-level prefetch in
CXL hybrid memory; [DualPath](https://arxiv.org/abs/2602.21548) adds a second
storage-to-Decode load path. A deadline-and-congestion variant needs actual
remote misses and measured transport/memory service to be distinct.

MoE replica routing remains a data prerequisite, not a tested third algorithm:
the current Qwen EP32/64 activated-expert lookup is outside the measured
profile domain, and the simulator lacks real token→expert IDs and replica
candidate traces. Synthesizing routes or clamping the profile would create an
unreliable speedup.

**Current paper decision: NO VALID MAINLINE on the available, matched data.**
This does not reject receiver placement or remote prefetch universally. The
next credible input is a same-source trace/profile bundle with natural
near-simultaneous P2D-ready requests and legal alternative Decode receivers,
or a multi-turn run with observed lower-tier KV misses, measured remote-load
latency and a real client-token callback. Until one of those prerequisites
exists, inventing congestion, changing bandwidth or extrapolating the profile
would not meet the research objective.

## Reproduction

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_receiver_matching/recheck_packet.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_receiver_matching/run_exhaustive_gate.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_receiver_matching/audit_flow_paths.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_receiver_matching/screen_natural_cohorts.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_receiver_matching/audit_remote_prefetch.py
```

All newly generated run CSVs and logs are under
`research_receiver_matching/runs/` and `research_receiver_matching/calibration/`.

## Round 4: branch-group fanout theory gate (2026-10-14)

**Hypothesis from the supplied candidate memo.** One Prefill computes a shared
prompt once, then places four independent decode branches on one, two or four
Decode instances. Each selected Decode gets one complete copy of the shared KV;
TP ranks within it receive disjoint shards. The proposed paper gain is from
choosing the replication degree and branch assignment jointly. This is a new
workload shape: the current router sends an ordinary request to exactly one
Decode instance and has no branch-group object or shared-fork transfer path.
EP expert distribution does not itself require KV fanout. The MoE collective
exchanges current-token hidden activations/router information, while attention
KV stays with the owning Decode instance.

**Metric/model audit.** The memo's `T(k) = T_P + kS/B + O t_D(4/k)` is a useful
screen, not an integrated result. It serializes all replicas at the source,
omits overlap and queues, assumes four branches have identical output length,
and uses `t_D(1,2,4) = (4.698,9.256,14.395) ms` from independent-request
simulator runs. The 27.068-ms prefix-hit and 162.780-ms full-prefill anchors
also came from independent requests, not one actual forked Prefill. They are
common-term proxies, not validated fork timings. The current `TTFT` field is
not an independently observed client-token emission time. A credible future
experiment must report per-branch token timestamps and group completion, and
must implement shared-prefix block ownership and one P2D copy per selected D.

**Exact theory calculation under the memo's own assumptions.** For Qwen3's
4105-token BF16 KV, `S = 403,537,920 B`; two 200-Gbps source rails give the
*conditional* `B = 50 GB/s`, hence `S/B = 8.0707584 ms`. The memo compares
`k=4` with `k=1`; at eight decode steps after a full prefill this yields
286.011 -> 232.647 ms, or 18.658%. But the explicitly required equal-split
baseline already chooses `k=4` and achieves that same 232.647-ms value.
Enumerating all `O=1..64` and `k in {1,2,4}`, the oracle's largest incremental
gain over the best of one-D and equal-four-D is **3.452658%** with the
27.068-ms common term (`O=2`) or **1.179744%** with the 162.780-ms common term
(`O=3`). At `O>=4`, equal-four-D is optimal among these three choices, so the
incremental gain is zero. See
[`research_branch_group/theory_gate.py`](research_branch_group/theory_gate.py)
and [`theory_gate.csv`](research_branch_group/theory_gate.csv); reproduce with
`python3 research_branch_group/theory_gate.py`.

**Decision.** The candidate memo's N=4 symmetric example does **not** clear
the >=10% strong-baseline gate. Its 18.66%-45.30% full-prefill numbers are
real comparisons to one-D within the formula, but not incremental benefit of
the proposed joint decision. Do not implement a branch-aware scheduler from
that example or present the theory oracle as a measured Serving gain. This is
a NO-GO for the specified homogeneous, known-length cohort, not for all fork
workloads. An empirical fork trace with varying branch lengths, constrained
Decode capacity, or measured heterogeneous links could reopen it only after
showing >10% headroom over cache-aware equal-split and simple marginal-cost
group greedy on the same trace. No such trace/profile is available here.

**Closest mechanisms.** [vLLM's PagedAttention paper](https://www.cs.princeton.edu/~ravian/COS597_F24/papers/vllm.pdf)
already shares physical prefix blocks among parallel samples and uses
copy-on-write when their output blocks diverge. [NetKV](https://arxiv.org/html/2606.03910v1)
chooses one Decode endpoint per request using cache, load and network cost;
[TokenDance](https://arxiv.org/abs/2604.03143) addresses collective KV sharing
for grouped agents. A fork-group replication-degree/placement decision is a
distinct formulation, but this theory gate shows the tested symmetric
instance offers too little incremental value over simple strong choices.

**Next step.** Screen PP-stage coflow placement using actual source/destination
rank paths and a NetKV-like network-aware endpoint baseline before creating
any 25/50/200-Gbps synthetic topology. A slow-cut-versus-fast-path comparison
alone cannot prove an advantage over a topology-aware router that selects the
fast Decode pipeline.

## Round 5: PP2 P2D coflow fidelity gate (2026-10-14)

**Pre-registered candidate and theory.** Four independent 2048-token Qwen3-30B-A3B
Prefills (TP2/PP2/EP1) send to one Decode (TP2/PP2) on the existing five-server,
two-200-Gbps-NIC topology. The model-derived BF16 KV is 201,326,592 B per
request, 96 P2D flows per request, half from each PP stage. A four-source
same-rail layer wave is 8,388,608 B; its 200-Gbps fluid serialization floor
is 0.335544 ms. The profiled 2048-token block cost is 1.339101 ms. Thus this
profile-valid point predicts that each layer's KV traffic clears before the
next wave and that the P2D network is mostly hidden. Pass/fail and provenance
are frozen in `research_autonomous/theory/pp_coflow/`.

**Initial run failed a causality check.** Four requests completed, and all
384 expected P2D flows conserved exactly 201,326,592 B per request. However,
the first PP-stage-1 KV flow was released at 0.072 ms, before stage 0 had
finished producing its output. Reported P2D ready/token 2/completion were
32.474/39.593/46.712 ms. Source inspection found that FlowSim's default
excluded OTHER traffic completed PP SEND and RECV nodes independently at their
local DAG ready times. The receiving stage therefore computed before its
sender produced the activation. This was a simulator error, not a network
optimization.

**Repair and same-input rerun.** `serving/core/flowsim_worker.py` now keeps a
job-local FIFO rendezvous keyed by the PP send/recv communication identity for
excluded P2P traffic: the receiver completes only after its matching sender
is ready, at zero transfer duration. Excluding cross-graph P2D now fails
loudly. The two PP ordering tests in
`research_autonomous/simulator_tests/test_flowsim_pp_local_sync.py` failed
before and pass after the repair; a third test checks P2D exclusion. The
existing FlowSim test suite passed
23/23. Preserved pre-fix files are in `raw_before_fix/`; the same command's
post-fix files are in `raw/`. Stage-1 first KV release moved to 31.243 ms
after stage-0 release ended at 30.967 ms. P2D ready/token 2/completion became
64.712/78.723/92.734 ms. The first wave FCT was 0.355745 ms, only 20.201 us
over the 0.335544-ms network floor; last KV finished at 63.554745 ms,
1.157255 ms before P2D ready. This is a NO-GO for a large network-placement
gain at the chosen four-source 200-Gbps point. These timings are **not**
client-observed TTFT or TBT.

**Second fidelity issue and repair.** Node-level debug showed the
EP1 expert compute node on TP rank 0 but absent on TP rank 1, so stage-1 TP
rank 1 starts about 1 ms earlier. The converter assigns expert marker 0 only
to `npu_offset == 0` even when EP1 experts should execute on each replicated
TP rank. `llm_converter.py` now identifies a sole zero-dispatch expert block
and emits its compute on every TP rank; multi-expert EP blocks retain rank
assignment. A two-mode COLOCATED/PREFILL regression failed before and passes
after; an EP2 sharding control passes too. The original corrected-PP run is
preserved in `raw_after_pp_fix_before_moe_fix/`. With the MoE fix, the first
stage-1 KV release moved from 31.243 to 32.310 ms as the formerly skipped
rank catches up. The rank-0 critical path and modeled P2D-ready/token-2/
completion remain 64.712/78.723/92.734 ms. All 384 P2D flows still conserve
their bytes and finish before P2D ready. The 49 existing P/D script tests
and five new simulator tests pass; one pre-existing router test stub was
updated to return its created Request, matching `Scheduler.add_request`.

**Decision.** NO-GO for a network placement paper based on this 4P1D PP2
200-Gbps point: the network transfer is hidden under profiled compute, so
there is no >=10% Serving opportunity even against an unrealistically perfect
zero-transfer network. The result is a deterministic mechanism gate, not a
claim about all arrivals or hardware. Future work should require an observed
profile-valid workload where P2D traffic is on the end-to-end critical path;
theoretical congestion from adding more sources than this topology supports
is insufficient. Next: complete the cross-candidate evidence audit and stop
honestly if no other currently verifiable setting clears the strong-baseline
gate.

## Round 6: post-repair receiver baseline and cross-candidate stop (2026-10-14)

**Question.** Did the EP1 converter repair change the earlier 3P2D
receiver-matching result enough to reopen that direction? The old study used
the same Qwen/TP2/EP1 graph semantics, so its exact 0.00422% gate needed a
matched rerun rather than an assumption that the bug was harmless.

**Experiment.** `research_autonomous/experiments/receiver_recheck/scripts/recheck.py`
reuses the frozen 3P2D TP2 config, 2048-token three-request trace, eight
assignments and both P2D modes. It saves 16 fresh raw request CSVs, logs,
events, flow telemetry, a result CSV and source hashes in an independent
directory. The old raw runs were not overwritten. Post-fix metrics were
compared field-by-field against the historical summary.

**Observation.** All 16 assignments have exactly identical recorded
P2D-ready, mean/max token-2 and mean/max completion values before and after
the converter repair. POST_PREFILL's greedy `010` mean token 2 is
78.979420 ms and the best is 78.976087 ms: 0.0042205% additional gain.
LAYERWISE greedy and best both give 72.240667 ms. The EP1 rank error was real
in the graph, but rank 0 already controlled the previous PP1 timings; this
explains why the Serving outputs were unchanged. The repaired PP2 case in
Round 5 did move rank-1 layer releases, verifying that the graph fix is active.

**Novelty and decision.** This confirms the receiver-matching NO-GO for the
tested strong greedy baseline. The broader candidate review is recorded in
`research_autonomous/CANDIDATE_DIRECTIONS.md`: PP coflow, homogeneous fork
degree, destination DELTA, and EP phase staggering do not clear the
strong-baseline Serving threshold in the available scenarios; agentic remote
prefetch, sparse MoE A2A and SLO goodput need missing route/profile/load or
client-event data. No `MOTIVATION_VALIDATED` direction remains within the
current profile-valid, causally audited envelope. The task ends as a bounded
negative research result, not as a claim that future hardware or traces have
no >10% opportunity.

## Round 7: full real agent-fork trace and KV placement theory gate (2026-10-14)

**Hypothesis.** Children spawned from one parent request can share a long
prefix but execute on different Decode replicas. A group-aware decision might
trade extra shared-prefix KV copies against parallel child service and shorten
parent resume time. The prior homogeneous four-child formula did not establish
incremental value, so this round asks whether real irregular forks reopen it.

**Data and reproducibility.** Downloaded all 119 daily JSONL.zst files of
[FreeInference](https://huggingface.co/datasets/harvardMadsys/freeinference_agentic_trace)
at revision `16d3c04dae6ccaa0c48a9064e204e3a8f1eb9ade`; the SHA256 of
every raw file is in `research_autonomous/workloads/freeinference_manifest.json`.
`research_autonomous/workloads/mine_freeinference.py` recursively parses root
and nested sessions, checks duplicate root IDs, and writes
`freeinference_analysis/{fork_groups,overlap_components}.csv` plus `summary.json`.
It found 12,002 root sessions and 1,222,199 recursively counted LLM requests;
the release card reports 1,186,582 requests. The count difference is not yet
reconciled, so only the local recursive count is used as its denominator.
There are 288 groups with at least two children attached to the *same parent
request*, 280 with overlapping child intervals, and 277 with both overlap and
at least 256 shared 16-token blocks' worth of prefix. These groups occur in
191 root sessions. The median group width is 3, median common prefix at least
7,864 trace-token units, median release skew 1.961 s, and median first-child
to last-child span 349.004 s. Another 43 cross-request overlapping components
are reported separately; their shared join is not ground truth.

**Theory before simulation.** For the available Qwen3-30B-A3B-Instruct-2507
BF16 model, 48 layers, four KV heads and 128-dim heads imply
`48 × 2(K,V) × 4 × 128 × 2 B = 98,304 B/token` of aggregate KV. Charging all
`width − 1` redundant shared-prefix copies to a *single* 200-Gbps (25-GB/s)
source cut gives a median serial-copy budget of 52.16 ms, p95 344.35 ms, and
maximum 824.62 ms. The median one-copy example with 7,864 shared units is
about 30.9 ms. Dividing each budget by its observed provider-side group span
gives p50/p95/max 0.0158%/0.2024%/0.7665%; zero of 288 reach 1%. Script and
per-group values are in `research_autonomous/theory/agent_fork_screen.py` and
`agent_fork_screen/`. This is a *cross-model screening diagnostic*, **not** a
Qwen Serving bound or measured gain: FreeInference block IDs use
`o200k_base`, provider token counts use provider tokenizers, and the actual
GLM/Minimax/DeepSeek etc. models lack local profiles. The source cut also
ignores possible overlap, dual rails, cache hits, queueing, and transfer
backpressure. No oracle was treated as an implemented policy.

**Causality and novelty gate.** The exact parent-child link is real, but the
trace does not explicitly mark a join. Of 263 groups with a later parent
request, 76 start that request before the last child ends. Therefore a claimed
parent JCT improvement cannot be computed by simply moving the next request.
Only two groups have all first-child *provider* prompts at most 2,048 tokens;
219 are at most 16,384, the attention-profile context ceiling, but tokenizer
mismatch and later child turns prevent treating 219 as verified profile-valid
replays. [NetKV](https://arxiv.org/html/2606.03910v1) already uses per-request
cache/load/network destination scoring; [TokenDance](https://arxiv.org/html/2604.03143v1)
and [ForkKV](https://arxiv.org/html/2604.06370v1) already share group prefixes;
[Agentix](https://www.usenix.org/conference/nsdi26/presentation/luo) and
[TOPAS](https://arxiv.org/abs/2608.25523) already schedule agent critical
paths. A new mechanism would need to improve over their corresponding group,
cache and network decisions, not merely create KV sharing.

**Decision.** The released trace proves irregular, concurrent siblings exist,
but does not validate a network-critical parent JCT mechanism in the available
simulator. No fork-placement prototype or claimed >=10% gain is justified yet.
Status: `NEED_DATA` for a child-TTFT-specific hypothesis; `NO_GO` for claiming
parent JCT from the current trace. Next: screen each group's first-child TTFT
against the deliberately pessimistic copy budget; if a nontrivial subset
survives, identify a model-matched profile and explicit join/metric path.

**Child-TTFT follow-up.** The completed per-group screen finds 54/288 cases in
which the serial-copy proxy exceeds 10% of the *fastest* child's observed
provider TTFT. Thirty-five have every first-child provider prompt at most
16,384 tokens; eleven also have overlapping children released within 1 s.
None has the exact locally profiled model. Some ratios exceed 100% because
the `o200k_base` token units and Qwen KV shape are being compared to another
provider's measured TTFT; that contradiction is direct evidence against
interpreting the ratios as causal benefits. The proxy also charges every
extra copy to one child's latency even when copies overlap or go to other
receivers. This retains `NEED_DATA` for a *narrow child-TTFT* question, while
rejecting any measured-speedup claim from these 54 theoretical flags. The
output is reproducible with `python3 research_autonomous/theory/agent_fork_screen.py`.

## Round 8: public trace alternatives and nearest mechanisms (2026-10-14)

**Hypothesis.** An independent public trace might supply the missing arrival,
prefix and dependency observations without selecting synthetic congestion or
reconstructing unobserved joins. The compared artifacts were pinned and mined
with scripts/manifests in `research_autonomous/workloads/`.

**Observations.** TraceLab v0.0.2 has 665,453 coding-agent rounds and median
prompt 132,092 tokens, but its release lacks ground-truth content block IDs
and reliable parent-child joins; replay tools synthesize those fields. ServeGen
releases 1,616 selected conversations and 5,720 turns, with median prompt
7,745 tokens, but is not a full-fleet arrival trace and its `input_tokens`
list does not yet have verified exact KV-block semantics. Mooncake FAST'25
releases 12,031 conversation and 23,608 tool/agent requests with 512-token
prefix hashes; each trace has exactly 1,180 distinct arrival timestamps over
one hour, with positive gaps almost entirely 3,000 ms. The ten or twenty
requests per timestamp therefore cannot be labeled same-millisecond incast.
Provider model/hardware/NIC mapping is missing in all three sources. Exact
counts and source revisions are in `SOURCE_MATRIX.md` and analysis summaries.

**Theory, baselines and decision.** The minimum 3-second release quantum alone
exceeds the Qwen 200-Gbps one-prefix transfer budget by two orders of
magnitude, so replaying each Mooncake bucket as a synchronized burst would
manufacture the relevant congestion. There is no meaningful strong-baseline
or oracle Serving comparison before arrival ordering and model latency are
observed. The closest designs are Mooncake's distributed KV store, NetKV's
network-aware destination scorer, and the prefix-aware group works listed in
the fork matrix. `NO_GO` for using any of these artifacts *alone* as proof of
fork-induced P2D incast or parent JCT gain. Next: mine the Chutes production
trace for an exact locally profiled model and reassess a different mechanism.

## Round 9: exact-model Chutes arrivals versus a layerwise P2D cut (2026-10-14)

**Hypothesis and source audit.** A high-traffic, model-matched production
window might expose KV transport even though the previous four-source Qwen3
MoE cohort did not. We pinned the
[Chutes one-year trace](https://huggingface.co/datasets/harvardMadsys/chutes_metadata)
to revision `85722e694bf7bb8a5a5ccdf70424fa5998372467` (CC-BY-4.0).
`chute_models.parquet` maps `0d7184a2-32a3-53e0-9607-058c37edaab5` to
`Qwen/Qwen3-32B`; `pro_6000` appears in its supported-GPU list, and the repo
has RTXPRO6000 TP1/TP2 profiles plus a vLLM bench example. Supported hardware
is not the GPU used by each production instance. The model registry's
`invocation_count` does **not** agree with counts in the trace shards, so it
is not used as a released-request total. An ID-column-only sparse Parquet scan
locates 1,542,078 model requests in shard 20, 1,782,882 in shard 30, and
40,267,133 in shard 40; shard 44 has none. The 1,542,078 ID-only count for
shard 20 matches its fully downloaded source exactly. Source hashes and
commands are in `research_autonomous/workloads/chutes_raw/` and
`SOURCE_MATRIX.md`.

**Profiled theory and strong baseline.** For Qwen3-32B BF16 TP2, one
2048-token first-chunk transformer block takes 2.875951 ms from measured
layer CSVs, excluding collectives. Its aggregate K+V is 8,388,608 B per
layer, needing 0.335544 ms over a single 200-Gbps source cut. Thus at least
nine perfectly synchronized Prefill sources would be required for one wave's
bytes to exceed the block compute interval on that idealized shared cut.
Collectives and less-than-perfect synchrony increase the needed pressure.
This is a necessary screen, not a TTFT prediction. The code and JSON result
are `research_autonomous/theory/chutes_qwen32b_network_gate.py` and its JSON.
The relevant baseline is **layerwise** transfer as in
[HMA-Serve](https://arxiv.org/html/2606.29986), followed by
[NetKV](https://arxiv.org/html/2606.03910v1)-style cache/load/network receiver
selection and [Kairos](https://arxiv.org/html/2607.02043) deflection where
feasible; a post-prefill bulk-transfer baseline is too weak. The local
Qwen3-32B *colocation* bench summary reports roughly +1% simulation error
for its saturated workload, but it is not a P/D or Chutes-hardware validation.

**First real window.** The full shard-20 filter writes 1,542,078 rows
(`qwen3_32b_shard20.parquet`, SHA256 in `qwen3_32b_extract_manifest.json`).
It spans 5.50 normalized days, 3.245 requests/s for this model, and 1,191
distinct serving instance IDs over the whole span. Median/p95 input lengths
are 7,440/12,545 and median output is 250 tokens; 97.2% of all rows have
input <=16,384 provider tokens. The observed streaming TTFT median is 1.798 s
over 1,070,055 rows, and completed-request duration median is 15.326 s.
These production latencies cannot calibrate RTXPRO6000 P/D transport because
the trace omits actual GPU types and whether production was disaggregated.
`ct` is null throughout this older shard, so it offers no cache-hit test.

**Arrival pressure check.** In aligned 200-ms bins across the **entire model
fleet**, only 100 bins have >=9 distinct instance IDs, containing 1,824
requests (0.118% of this model's requests); the half-bin-shifted check gives
101 bins/1,854 requests. At 1 s, 3,936 bins/45,757 requests (2.97%) pass
that same deliberately loose test. Peak 200-ms volume is 47 requests from
32 distinct instance IDs, while the median/p95/p99 *nonempty* 200-ms bin has
1/3/4 requests. These counts are arrivals, not simultaneous P2D layer waves.
They pool all 1,191 historical instances and cannot establish that nine
sources share a receiver NIC. Even the optimistic necessary cohort is rare
at the first-chunk timescale; the prior four-source 200-Gbps simulator result
also finished all P2D flows before Decode readiness.

**Decision and next action.** `NO_GO` for claiming a representative cold-KV
200-Gbps coflow bottleneck from shard 20 or from post-prefill transfer alone.
A distinct high-Prefill-cache-hit/cold-Decode case remains `NEED_DATA`: if
Prefill reuses most of the prompt, compute slack shrinks while a cold Decode
could still require full KV. A linear fresh-token approximation gives a
conditional 88.3% Prefill cache-hit threshold for wire time to match compute,
but it ignores long-context attention, Decode cache affinity and actual
placement. Next: complete the late shard-40 extraction, measure `ct` and
instance-level arrivals, and stop if the condition is rare or unidentifiable.

**Late-window cross-check.** Full shard 40 validates the sparse scan exactly:
40,267,133 Qwen3-32B requests over 10.15 normalized days (45.892 rps), 771
distinct serving-instance IDs and 1,429 `(user_id, rehash_round)` pairs.
The exact-model extracted Parquet is 827,687,189 B with SHA256 recorded in
`qwen3_32b_extract_manifest.json`; aggregate results are in
`chutes_qwen3_32b_analysis/summary_shard40.json`. Of 36,525,702 rows with
observed `ct`, 11,016,037 (30.2%) have `ct/it >= 0.8833`. But one anonymous
user contributes **38,345,218 of 40,267,133** requests (95.2%) and
10,705,259 of the 11,016,037 high-hit rows (97.2%); all that user's calls
are nonstreaming and have no observed TTFT. The high-volume surge is therefore
one tenant's workload, not independent fleet-wide demand. The trace does not
reveal what this tenant does or whether its prefixes are shared across calls.

Only 1,319,046 of the 40.27M requests record TTFT. Among high-hit requests
within the 16,384-token profile-length screen, 250,829 have TTFT; 72,687
would exceed a 10%-of-observed-TTFT *proxy* if one assumes a cold Decode,
full-prefix retransmission over one 200-Gbps cut, and fresh-token compute
linearized from the first-chunk profile. That proxy uses
`max(0, 0.01048576*it - 0.08987347*(it-ct))` milliseconds and is not a
simulation or a measured benefit. One other anonymous user contributes 65,342
of those 72,687 flags (89.9%); the next contributes 6,570 (9.0%). For the
11,006,441 high-hit profile-length requests with observed completion, the
proxy is only 0.16%/0.77%/1.26% of completion duration at p50/p95/p99;
1,794 requests exceed 10%. High-hit requests from the two leading streaming
users occur on 651 and 587 distinct serving instances, respectively, but the
trace does not disclose whether those hits refer to the same exact prefix.

**Final decision for this candidate.** Neither a cold Decode nor a shared
physical NIC cut can be observed in Chutes. A cache-aware router could choose
a resident Decode, and the dataset has no exact block IDs to replay that
strong baseline or test whether `ct` on the Prefill side implies a miss at the
Decode side. The high-hit TTFT proxy is concentrated in two tenants and has
no validated P/D causal path. `NO_GO` for an honest >=10% network/Serving
paper claim from Chutes alone; retain `NEED_DATA` only for the narrow
cache-hit/cold-Decode mechanism. Next: inspect a public Qwen single-cluster
trace that releases real arrival times, session links and 16-token hashes.

## Round 10: Qwen-Bailian prefix and arrival gate (2026-10-14)

**Source and semantic audit.** Downloaded all four LFS files in the
[Qwen-Bailian public trace](https://github.com/alibaba-edu/qwen-bailian-usagetraces-anon)
at commit `5f7439c51ec248a0c585f7d90a41a6f57773b912` (Apache-2.0), verified
each byte count and SHA256 against its Git LFS pointer, and retained the
manifest in `research_autonomous/workloads/qwen_bailian_raw/manifest.json`.
The release says these are *sampled* two-hour excerpts from a single Qwen
serving cluster per file. It has millisecond-resolution, trace-relative
arrival times, per-request input/output lengths, parent chat IDs and 16-token
content hashes of model-tokenized input after the chat template. The original
model identity, selection fraction, physical worker count, P/D roles, network
topology, per-worker cache content, completion/TTFT and output hashes are not
released. To-B B is labelled December 2024, so its original model cannot be
Qwen3-32B, which was released later. The ATC'25 paper analyzed richer internal
traces, including user IDs and input/output hashes at a different stated
granularity; those fields should not be silently imputed to the public files.

**Exact released-input prefix audit.** `mine_qwen_bailian.py` uses a compressed
radix trie over the ordered block-content IDs and was checked against brute
force on 10,000 random requests. All 269,681 rows across the four files have
`len(hash_ids)=ceil(input_length/16)`; no timestamp inversions or missing
parents occur. The observed windows are approximately 7,200 s. The table is
*longest block-aligned prefix shared with an earlier-arriving input*, not
realized GPU cache hits: the earlier request may not have finished computing,
an evicted block may be absent, and generated-output KV that can later be
reused is missing from the release.

| Trace | Requests / mean rps | Input p50 / p95 | Earlier-input prefix p50 | Input tokens in earlier-input prefixes | Requests with >=88.33% earlier-input prefix | 200-ms peak arrivals / requests in >=4 same-256-token-prefix groups |
|---|---:|---:|---:|---:|---:|---:|
| To-C A | 43,058 / 5.981 | 1,046 / 8,809 | 720 | 58.0% | 11,121 (25.8%) | 10 / 236 |
| To-B B | 172,800 / 24.000 | 574 / 2,491 | 272 | 53.8% | 38,331 (22.2%) | 19 / 4,470 |
| Thinking | 10,812 / 1.503 | 3,680 / 16,229 | 672 | 46.2% | 5,047 (46.7%) | 20 / 50 |
| Coder | 43,011 / 5.975 | 4,540 / 13,407 | 1,072 | 66.5% | 12,474 (29.0%) | 9 / 8 |

The high-prefix counts include only full 16-token blocks. To-B B has no
parent-linked rows; Coder has 16,605 parent-linked rows. The released
`hash_ids` are **one content hash per 16-token block**, not the per-token IDs
expected by the simulator's `input_tok_ids`; feeding them directly would
shrink the simulated prompt 16-fold and create false cache matches. A faithful
input-prefix adapter must preserve only proven full-block equality, treat
partial terminal blocks conservatively, and label output-derived session reuse
unknown. No P/D replay has been claimed on these files.

**Capacity and overlap screen.** `qwen_bailian_cut_screen.py` substitutes the
locally profiled Qwen3-32B BF16 TP2 *only as a model sizing proxy*: 64 layers,
8 KV heads and 128-dim heads give 262,144 aggregate KV B/prompt token. If
every full prompt is transferred across **one shared cut** to a cold Decode,
mean offered loads are 29.24 (A), 46.03 (B), 15.02 (Thinking) and 72.02
(Coder) Gbps. At 200 Gbps, 1-s arrival bins whose full-KV bytes exceed one
cut's one-second capacity contain 30 (A), 0 (B), 0 (Thinking) and 274 (Coder)
requests: 0.07%, 0%, 0% and 0.64% of each trace. At 200 ms the fractions are
2.90%, 0.98%, 8.02% and 22.26%, respectively. This deliberately extreme
single-cut/cold-Decode estimate ignores cache-aware routing, reused blocks,
layerwise overlap and distributed NICs. Bin bytes are not a packet trace and
cannot establish exposed transfer time or client TTFT. Coder's short-window
pressure is a conditional scenario worth retaining, not a demonstrated
bottleneck. The earlier 2048-token Qwen3-32B layer screen requires nine
synchronized cold Prefill producers on one 200-Gbps cut for per-layer bytes to
exceed profiled compute; the Coder file's *fleet-wide* 200-ms peak has nine
arrivals, not nine verified Prefill layer waves on the same receiver.

**Nearest work and decision.**
[KVCache in the Wild](https://arxiv.org/html/2506.02634) already studies
workload-aware prefix eviction on the richer original trace;
[LMetric](https://arxiv.org/abs/2603.15202) uses these workload families and
multiplies new-prefill tokens by load for cache-aware routing;
[py-kvcache](https://arxiv.org/html/2609.11744) explicitly replays the
public Bailian files and finds model/hardware-dependent break-even for external
KV reads. For P/D, a credible comparator also includes
[PPD](https://arxiv.org/abs/2603.13358) local append-prefill,
[vLLM bidirectional transfer](https://github.com/vllm-project/vllm-project.github.io/blob/main/_posts/2026-09-29-disaggregated-serving-guide.md),
NetKV receiver scoring and HMA-Serve layerwise sends. A generic cache-aware
router or multi-turn return transfer would duplicate those mechanisms.
There is no public P/D cache state, exact original model profile or P/D bench
validation to quantify an incremental >=10% end-to-end gain over them.
`NO_GO` for a Bailian-only P/D network paper claim. Retain the Coder short-window
screen as `NEED_DATA` only if an independently calibrated deployment and
cache/receiver mapping can be obtained. Next: search a model-matched trace or
mechanism where source fidelity and serving events close the gap, without
merging unrelated production traces into synthetic evidence.

## Round 11: theory-first exact-model layerwise gate and admission audit (2026-10-15)

**Mission revision.** The latest user brief requires a deployment scenario bank,
3–5 quantitative theory screens and small causal motivation tests before any
full production-trace mining or replay. The [SwissAI trace](https://huggingface.co/datasets/eth-easl/swissai-serving-trace)
had already been downloaded before this revised ordering arrived. Its pinned
`qwen3-32b-buckets.jsonl` file is 4,617,817,342 B and 3,994,435 lines. The
local SHA256 is `58b2265b98a10ec3bb2a0b455c520731c1296967906c7adc7b6d3710a013e402`;
three independent 4096-byte HTTP Range samples at offsets 0, 2,310,000,000
and 4,617,813,246 matched. The Hugging Face response ETag
`a00c42af3365e2cb93e6448bd2672faad715e1e6f10d4214204dd3005e3426ed`
is **not** the local file SHA256; `download_swissai.py` and the manifest now
separate those fields. The file is retained raw and gitignored. Its full miner
and replay were *not run* under the new evidence ordering. The
[OpenTela OSDI'26 paper](https://www.usenix.org/system/files/osdi26-yao.pdf)
describes a colocated system without P/D disaggregation or global prefix
caching, so its observed completion times cannot validate a hypothetical P/D
policy. The release has no per-request GPU/NIC path.

**Candidate and falsifiable prediction.** In an exact-model 2,048-token
Qwen3-32B BF16 TP2/PP1 case, one Prefill sends 536,870,912 B of KV to one
Decode. At 200 Gbps on each TP rail, one 4,194,304-B layer shard has a
167.772-µs serialization floor. The measured RTX PRO 6000 TP2 Prefill block
compute is 2,875.951 µs excluding collectives. Four synchronized Prefill
sources sharing one Decode pair of rails require 671.089 µs of layer service,
still below one block. The simple fluid threshold is **18** equal sources on
one receiver rail before layer service exceeds one block interval. Prediction:
1P1D and 4P1D layerwise P2D-ready times will be equal even though flow FCT
increases. If last flow completion crossed the P2D-ready barrier or P2D-ready
grew, revisit per-layer release, bottleneck mapping and hidden-overlap theory.
This is a timing prediction, not a claim that network traffic is zero.

**Small diagnostic experiment.** `research_autonomous/experiments/qwen32b_layerwise_gate/run.py`
reuses the checked-in four-source/one-receiver two-rail topology and replaces
the model with the exact measured Qwen3-32B bundle. It runs 1 and 4
simultaneous 2048/3-token requests, deterministic RR routing, FlowSim FAIR,
LAYERWISE transfer and no prefix cache. The 4P1D cohort is a controlled
short-output diagnostic, not a natural arrival-frequency assertion. Every
request sends exactly 536,870,912 B; the 4P1D case has 512 P2D flows,
2,147,483,648 B total and equal 1,073,741,824-B receiver-rail totals.
Maximum individual FCT rises 0.188→0.691 ms. Last flow completion is
181.951→182.454 ms, while both cohorts have **184.907-ms P2D-ready**.
The 4P1D last flow is still 2.453 ms before the barrier. Modeled token 2 is
210.039→210.545 ms; this +0.506 ms follows a larger Decode batch, not
exposed P2D network waiting. `analyze.py` asserts byte conservation and
flow-finish-before-ready; `summary.json`, raw CSV/telemetry/logs and the
profile/source/config-hash manifest retain the evidence.

**Theory-vs-observation and decision.** The predicted zero change in P2D
ready was observed. There is no ≥10% end-to-end network headroom for a
receiver-cut scheduler in this tested 1–4-source, two-rail, 200-Gbps envelope.
`NO_GO` for this bounded layerwise Qwen3-32B candidate. An 18-to-one
forced receiver would be a weak/unrealistic baseline without independent
deployment evidence, so the threshold is not promoted as a paper motivation.
The previous Qwen3-30B-A3B PP2 gate independently found hidden network work.
An independent repeat of both small cases produced the same readiness and
token-2 values; the runner clears its own generated telemetry before replay.

| Iteration field | Round-11 record |
|---|---|
| ID / current hypothesis | 11 / four independent 2048-token cold P/D transfers may expose the receiver cut |
| Prediction / observation | 671.089-µs four-source layer service < 2875.951-µs compute; P2D-ready should not rise / both cases 184.907 ms |
| Mismatch / root cause | None in the tested envelope; longer per-flow FCT remains hidden behind Prefill compute |
| Theory or simulator modification | No performance-model tuning or simulator source change; only a deterministic analysis runner and provenance repair for the downloaded file |
| Next discriminating experiment | None for this bounded cut; another candidate needs >10% incremental strong-baseline headroom before a new run |
| Outcome | `NO_GO` for S01/S02; no claimed client TTFT gain |

**Other screens and simulator boundary.** The 15-scenario deployment bank and
four quantitative gates are in `research_autonomous/ROUND11_SCENARIOS_AND_THEORY.md`.
For a 600-output-token assumption, one TP2 Decode's profiled compute-only
batch-128 throughput is an optimistic 2,391 tokens/s or 3.986 requests/s;
one Prefill's compute-only limit is 5.416 requests/s. A 1P1D steady arrival
rate can therefore build a Decode queue, whereas 1P2D is a necessary
provisioning comparator. The simulator's per-rank TP2 KV capacity is an
**upper bound** of 457,824 tokens, or 128 active 2048+600-token sequences
plus about 58 waiting 2048-token handoffs. At saturation,
`Scheduler.add_decode` immediately allocates Decode KV and raises when full,
while `Scheduler.add_done` already freed the Prefill source. No source
retention, receiver rejection or backpressure event closes this path.
`SIMULATOR_UNSUPPORTED` for a memory-saturated P/D gain claim; no such
integrated experiment was run. Strong existing admission mechanisms include
[Dynamo request rejection](https://docs.dynamo.nvidia.com/dynamo/dev/knowledge-base/concepts/fault-tolerance/request-rejection-architecture)
and [dual-memory request scheduling](https://arxiv.org/abs/2610.15579).
Cross-node Decode TP has a conditional 6.711-ms 200-Gbps cut floor per
batch-128 step and an 11.14% serial toy-model removal fraction, but local TP
placement is the stronger normal baseline. It is `NEED_DEPLOYMENT_EVIDENCE`,
not a validated network opportunity.

A secondary fifth gate uses the documented
[UBELIX eight-RTX-4090/one-100-Gbps-NIC node](https://hpc-unibe-ch.github.io/hardware/gpu/)
and this repository's measured RTX 4090/Llama-3.1-8B TP1 profile. A cold
2048-token prompt has a 5.995-ms Prefill block versus 0.671-ms/layer NIC
service, so up to eight synchronous source GPUs still have no per-layer
serialization excess. With an **assumed** 1984-token Prefill prefix hit and
64 new tokens, the measured block falls to 0.614 ms while a full P/D layer
still needs 0.671 ms; two senders on the shared NIC yield a conditional
0.728-ms/layer excess. One Decode GPU at batch 16 has only an optimistic
11.16 requests/s capacity for 64-token outputs, so 2P1D at a sustained
high-hit Prefill rate would be unfairly underprovisioned. This is
`THEORY_READY / NEED_DATA`, not a Serving
result: a Prefill hit does not prove a Decode miss, the inventory does not
claim P/D service, and strong cache-aware/DELTA/local-pairing baselines may
remove the full-prefix transfer. `round11_rtx4090_100g.py` and JSON retain
the arithmetic. The previous prefix-hit study already observed a related
barrier but failed the final >10% full-session strong-baseline gate, so this
hardware ratio alone cannot reopen that paper claim.

**Next discriminating step.** Do not run the archived full SwissAI miner yet.
Prioritize a candidate with a >10% *incremental* bound over local TP,
layerwise transfer, balanced receiver choice and capacity-aware admission.
If such a bound depends on Decode saturation, first implement and validate
the P/D retention/backpressure causal chain; if it depends on cross-node TP,
obtain a deployment constraint that rules out local packing. No Round-11
candidate reaches `MOTIVATION_VALIDATED`.

Reproduce this round from the repository root:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/theory/round11_qwen32b.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/theory/round11_rtx4090_100g.py
python3 research_autonomous/experiments/qwen32b_layerwise_gate/run.py
python3 research_autonomous/experiments/qwen32b_layerwise_gate/analyze.py
python3 research_autonomous/workloads/download_swissai.py
```

## Round 12 — 2026-10-15: prefix-hit shared-source-NIC inversion

**Hypothesis and theory.** Revisited the Round-11 secondary screen using the
documented UBELIX eight-RTX4090/one-100-Gb/s hardware ratio and the existing
Llama-3.1-8B BF16 TP1 profile. Full 2048-token KV is 268,435,456 B/request
and 671.089 µs/layer on the 100-Gb/s cut. Cold layer compute is 5,995.177
µs; with 1984 cached prefix tokens and 64 fresh tokens it is 614.049 µs.
Thus eight cold sources have source-cut/compute ratio 0.896, while two hot
sources have 2.186 and eight hot sources 8.743. The 23.300-ms two-source
and 152.15-ms eight-source residuals were recorded as screening predictions,
not exact request-ready bounds or measured gains.

**Causal repair and small prototype.** Added an optional per-request Decode
instance ID to flat/agentic workload routing and made the destination-prefix
query use the actual target D. This repaired a previously fixed-peer query
that would mislabel D cache state under per-request target choice. The
28-case FlowSim fixture places 1/2/4/8 P GPUs behind one 100-Gb/s source
uplink, splits D targets over two independent 100-Gb/s nodes, uses real
prefix warmups and actual block-hash lookup, and compares D miss with pinned
D-resident delta handoff. All warmups finish before target arrival. No D
sequence-capacity wait occurs. `run.py`, `analyze.py`, raw request/event/flow
ledgers and manifests are in
`research_autonomous/experiments/prefix_inversion/`.

**Results and failure audit.** The full 24-case D-miss sweep conserves exactly
268,435,456 B/request; D-resident controls send exactly 8,388,608 B/request.
Cold P2D-ready stays 193.161 ms at 1/2/4/8 sources. Hot D-miss ready grows
21.552→43.027→85.977→171.876 ms; matched D-resident ready is 20.969 ms
at every source count. The 8P hot last flow is exactly on the Decode-ready
barrier; token 2 follows at 189.004 ms after target arrival. The 8P cold
last flow ends 1.110 ms before ready. The hot eight-source 2.147-GB source
cut needs 171.799 ms to serialize and FlowSim reports 171.876-ms ready.
The full hit sweep displays a latency plateau at that source-NIC floor.
The cache hit never worsens absolute ready time relative to cold; it moves
the bottleneck and caps further cache benefit.

**Strong-baseline decision.** This is `MECHANISM_VALIDATED` but **not** a
publishable algorithm result. Every D-miss fixture has an idle D-resident
alternative, so existing cache-aware Decode selection plus delta transfer
already obtains the 20.969-ms control. The large conditional difference
must not be called our policy gain. NetKV, SGLang's shipped Decode radix
delta, PrefixPlace and CacheRoute narrow novelty. A natural all-D-miss
operating point and >10% *incremental* modeled Serving improvement over a
composite strong baseline are still missing. No client egress or packet/NIXL
latency is modeled. Detailed theory, figure, URLs and reproduction are in
`research_autonomous/ROUND12_PREFIX_INVERSION.md`.

| Iteration field | Round-12 record |
|---|---|
| ID / hypothesis | 12 / Prefill cache acceleration removes overlap slack while D miss keeps full KV bytes on a shared source NIC |
| Prediction / observation | Cold 8P ratio <1, hot 2P ratio >1; observed cold ready invariant and hot ready plateaus at physical source-cut service |
| Mismatch / root cause | Two-source measured excess 22.058 ms versus 23.300-ms toy residual because the screen omits prologue, layer release timing and path latency; order and scale agree |
| Theory or simulator modification | Per-request Decode target and matching pre-transfer D cache query; no performance model tuning |
| Next discriminating experiment | Normal-capacity D cache churn with P prefix retained and no resident D alternative; then a strong placement/replication baseline |
| Outcome | `MECHANISM_VALIDATED / PAPER_GAIN_UNPROVEN`; do not present conditional D-miss-versus-D-hit difference as an achieved new-policy improvement |

## Round 13 — 2026-10-15: natural Decode eviction and fixed-byte bound

**Hypothesis and theoretical gate.** Under the normal 24-GB RTX4090,
0.9-utilization pool, a Decode worker paired with four Prefill GPUs should
evict old reusable prefixes after 32 distinct 2048-token fillers, while
each Prefill GPU sees only eight fillers and retains its own 1984-token
prefix. With eight simultaneous *distinct* hot-prefix targets, no
single-flight deduplication is possible. If both D workers miss, the
2,147,483,648-B source cut has a 171.799-ms lower bound at 100 Gb/s.
This bound was computed before inspecting the new target run.

**Small integrated experiment.** `churn.py` built matched no-churn and
eight-wave cases on 8P:2D RTX4090 GPUs. D0 and D1 sit on independent
100-Gb/s nodes; all eight P GPUs share one source 100-Gb/s uplink. Eight
distinct warm prefixes, 64 unique filler requests in 300-ms waves and eight
distinct-prefix targets use real token hashes and the unchanged D KV
capacity of 3,400 16-token blocks. Every filler completes before the 2.7-s
target arrival. `analyze_churn.py` verifies all pre-transfer D queries,
P hits, target prefix distinctness, byte/path conservation and admission
ordering; raw events, flows, CSV and SHA-256 manifests are archived.

**Results.** No-churn targets have P hit 1984, D HIT 1984, delta bytes
8,388,608 B/request and 20.969-ms P2D-ready. After ordinary cache churn,
all eight P hits remain 1984 but D0/D1 return four MISS each, so each
target sends 268,435,456 B; ready is 171.876 ms. Modeled token 2 moves
39.487→190.394 ms and completion 58.005→208.912 ms. Decode capacity
queue wait remains zero. The full-byte run is only 0.077 ms or 0.045%
above the source NIC serialization floor. **Any scheduling-only method
that keeps the bytes and physical cut fixed has effectively no 10%
headroom.** Cache residency, prepositioning, byte reduction or a different
physical cut would be required.

**Failure and novelty audit.** The same-prefix diagnostic had later
post-P2D D hits within the target cohort, which could be removed by the
single-flight prompt admission already discussed in SGLang. The distinct
prefix control removes that overlap. The remaining 87.8% conditional
D-residency difference is still not a new-policy gain: no online signal in
this constructed stream distinguishes the eight soon-to-repeat keys from
64 one-off fillers after one observation each. LFU, PrefixPlace, NetKV,
Decode delta and single-flight form necessary strong baselines. The result
is `NATURAL_ASYMMETRY_VALIDATED / NETWORK_SCHEDULING_NO_GO /
ONLINE_CACHE_POLICY_NEED_DATA`, not a paper GO. Details and citations:
`research_autonomous/ROUND13_NATURAL_CACHE_ASYMMETRY.md`.

| Iteration field | Round-13 record |
|---|---|
| ID / hypothesis | 13 / normal Decode churn makes P-hit/D-miss natural without a warm D alternative |
| Prediction / observation | D capacity 3,400 blocks; 32 fillers per D exceed it, eight fillers per P fit; observed eight P hits and eight D misses |
| Mismatch / root cause | None in cache-state prediction; full-byte ready is already at the source-cut lower bound |
| Theory or simulator modification | No simulator performance-model change; new controlled churn workloads and causal analysis |
| Next discriminating experiment | Demand predictability and a matched LFU/recency/PrefixPlace-style retention baseline on an ordered repeated-prefix workload |
| Outcome | `NATURAL_ASYMMETRY_VALIDATED`, fixed-byte network scheduling `NO_GO`, online retention `NEED_DATA` |

## Round 14 — 2026-10-15: ordered public-trace demand screen

**Hypothesis.** Before developing a D-prefix retention policy, check whether
the four existing Qwen-Bailian production-derived traces contain repeated,
*distinct* ~2048-token root prefixes with short output arriving close enough
to activate the 8P source cut. This is only workload-shape evidence because
these are Qwen traces and contain no P/D layout or actual cache-hit state.

**Method and result.** `workloads/screen_prefix_bursts.py` scans the pinned
16-token hash sequences in timestamp order. It counts `turn=1`, output≤128,
exact first-1984-token prior-input reuse and distinct prefix keys in 100-ms
and 1-s buckets. Across all four traces, 440 requests fit the near-profile
1984–2304-token input window; its largest 100-ms and 1-s buckets have only
two distinct prior-seen prefixes. A wider 1984–4096-token window yields
2612 requests and at most two distinct prefixes in 100 ms or four in1 s.
There are **zero** 8-prefix buckets even in the one-second upper screen.
Prior occurrence is not a GPU cache hit, so this is already optimistic.
The raw source is pinned in `qwen_bailian_raw/manifest.json`; exact screen
output and SHA-256 are in `workloads/prefix_burst_screen.json`.

**Decision and next step.** `NO_GO` for using these traces to justify a
frequent eight-source Llama-8B short-output burst. The Round-13 mechanism
remains valid, but no online retention policy can be credited with its
conditional D-residency difference, and a fixed-byte scheduler is bounded
by the source cut. Demand predictability and strong LFU/PrefixPlace-style
cache admission remain `NEED_DATA` in another model/deployment matched
workload. The full SwissAI miner remains deferred. See
`research_autonomous/ROUND14_PREFIX_BURST_SCREEN.md`.

| Iteration field | Round-14 record |
|---|---|
| ID / hypothesis | 14 / prior-seen distinct short-output prefixes often burst at the 8P cut width |
| Prediction / observation | An 8-key cohort needed for current 8P controlled scale; maximum observed is two in100 ms, four in a looser1 s / wider input window |
| Mismatch / root cause | Public aggregate does not contain the required matched short-output burst in the selected windows; no P/D/cache state or model match |
| Theory or simulator modification | None; read-only pinned workload screen and reproducible JSON |
| Next discriminating experiment | Seek a model/deployment matched demand stream or formulate a different mechanism with strong-baseline headroom; do not extrapolate this fixture |
| Outcome | `NO_GO` for Qwen-Bailian support of this burst; overall paper claim still unvalidated |

## Round 15 — 2026-10-15: directed P2D/Decode EP overlap, TP shape and skew screen

**Capability re-audit.** Re-read the source path from `_pd_kv_send_bytes` to
the converter's TP/PP shard mapping, FlowSim physical paths and scheduler
handoff. The independent 2,352-flow byte/path audit, Round-13 8P prefix
audit, all49 P/D tests and five simulator regression tests pass. The audit
still marks memory-full P/D handoff unsupported: Prefill frees source KV
before Decode allocates and a full D pool raises. TP/OTHER service is zero
by default FlowSim, although PP SEND→RECV ordering survives. ns-3 packet
FCT is not a Serving TTFT validation. Exact code/evidence/limitations are
in `research_autonomous/SIMULATOR_CAPABILITY_AUDIT.md`.

**Pre-run theory and candidate pool.** `CANDIDATE_STATUS.md` ranks eight
directions, including the six required families and the new
network-induced Decode KV-length skew idea. For a Qwen3-30B-A3B TP2/EP4
2048-token new request, KV is201,326,592 B; four new requests on one
200-Gb/s rail require16.106 ms of serialized service. Layerwise Prefill
compute takes1.339 ms/block versus0.336 ms/layer for four flows, so new
P2D can still be hidden. A prior EP-only two-group run showed at most0.798%
ITL cross-group interference, but did **not** bound a later KV wave. The
falsifier was whether new P2D and active D EP overlap on the *same directed
link* and then move token2/ITL/Serving completion by ≥10% beyond EP_FIRST.
The separate cold Qwen3-32B network-staged theory gives zero P2D-ready
headroom for1–4P; its saturated case remains unsupported. Both top
cards have executable `derive.py` and a fixed-resource experiment plan.

**24-request controlled overlap experiment.** The retained 4P:4D TP2,
two-EP4-group 200-Gb/s topology receives eight128/32 requests at0 and
four2048/3 requests at each of100/180/260/340 ms. This is a controlled
mechanism diagnostic, not a claimed production arrival distribution.
The 8-request no-new-wave control and three identical-workload policies
(FAIR, EP_FIRST, KV_FIRST) preserve all model/GPU/NIC resources. Each of
16 new requests sends exactly201,326,592 B; total 24-request P2D is
3,321,888,768 B. `experiments/analyze.py` writes per-flow rank/byte/time/
directed-rail ledgers, per-request arrival→completion timelines and
checks every byte. Commands, seed, config, profile and source hashes are in
the run manifests. FAIR has40,160 directed P2D/EP interval pairs; the
physical overlap is real in FlowSim, not an inferred queue. Yet every
new last KV flow finishes at least1.161 ms *before* P2D-ready, and all
policies have the same64.712-ms new-request arrival→P2D-ready. All D
capacity stalls are zero.

| Condition | Old mean TPOT (ms) | Old completion (ms) | New mean completion from arrival (ms) | All-request makespan (ms) |
|---|---:|---:|---:|---:|
| Eight-old-only FAIR control | 6.157552 | 235.757112 | — | 235.757112 |
| 24-request FAIR | 6.178858 | 236.417623 | 77.180152 | 415.943616 |
| 24-request EP_FIRST | 6.171083 | 236.176600 | 77.147370 | 415.943616 |
| 24-request KV_FIRST | 7.118469 | 265.545544 | 78.240206 | 415.943616 |

Deleting *all* later arrivals is an intentionally generous interference
Oracle for the old cohort and only saves0.279% of its completion or0.345%
of its TPOT. FAIR→EP_FIRST saves0.102% old completion and0.0425% new
mean completion. KV_FIRST changes Decode batch composition and EP bytes,
so it is a policy control, not an equal-EP-byte isolated priority effect.
The old cohort's first token2 is51.030552 ms in every run, before the
later wave arrives. **P2D/EP competition is `NO_GO` in this concrete
profile-valid cut:** physical overlap is present, but new P2D remains
hidden and D penalty is far below10%. No EP64 scale-up or weaker FAIR-only
claim is warranted. FlowSim is fluid; no packet/client-SLO conclusion.

**Two further theory gates.** Exact Qwen3-32B TP1/TP2 profiles and the
96-GB memory model show TP1 holds at most39 concurrent2048+600-token
sequences, versus TP2's scheduler-bound128. Even a favorable but
memory-infeasible TP1 batch40 gives two TP1 Decode workers only51.6% of
one TP2 worker's tokens/s on the same two GPUs; concentrating KV on one
TP1 source rail also doubles its 200-Gb/s serialization floor to21.475 ms.
Heterogeneous TP is `NO_GO` for this measured shape. For the new Decode
skew idea, the old skew profiler was found to **sum** three attention
timings whereas the uniform profiler averages. Among330 exact pure
endpoints, the median raw ratio is3.004. The profiler now averages future
shots; two regression tests pass. Historical skew CSV remains unchanged
and only its dimensionless alpha is used with uniform measured costs.
After filtering by actual TP2 GPU KV capacity, all249 feasible pure skew
shapes make serial length bucketing slower; the best is29.6% slower.
An ideal cost-free zero-skew kernel could save at most11.31% at a rare
feasible profile point, but that is neither an achievable rebatching
policy nor an observed workload. Serial skew rebatching is `NO_GO`.

| Iteration field | Round-15 record |
|---|---|
| Hypothesis | A later P2D wave competes with active D EP enough to move end-to-end modeled Serving metrics; TP reshape/skew could offer alternate headroom |
| Theory/falsifiable prediction | 16.106-ms four-request rail work may overlap EP; require same directed path and token-event effect beyond EP_FIRST; TP1 memory limits batching; skew split must overcome duplicated dense work |
| Observation | 40,160 same-link interval pairs, but new P2D-ready invariant64.712 ms; old interference ≤0.279% completion; hetero TP1 throughput ratio≤0.516; serial skew split always slower |
| Mismatch/root cause | Network overlap did not cross the new-request ready barrier; EP delay small. Raw skew endpoint scale was a profiler aggregation bug, not a real 3× attention cost |
| Modification | Fixed future skew `_measure` averaging and added two tests; no simulator performance tuning, no historical data deletion |
| Next | Repair memory-full P/D handoff before a saturated candidate, or acquire a source-backed ordered workload with a distinct >10% strong-baseline mechanism |
| Outcome | `NO_GO` for this EP cut, this heterogeneous TP shape and serial skew rebatching; no `MOTIVATION_VALIDATED` claim |

## Round 16 (2026-10-15): D capacity-credit repair, finite stress test, ordered-prefix bound

**Hypothesis/theory.** Existing P/D handoff freed Prefill KV before the D
pool allocated the received prompt. A full D pool therefore raised after
network bytes had already been sent; saturated-handoff Serving claims were
causally invalid. The minimal repair is a D block credit acquired before
Prefill emits KV. For Llama-3.1-8B TP1, a2048-token prompt is268,435,456 B
(8,388,608 B/layer) and one request needs129 D blocks including its first
Decode slot. The100-Gb/s per-request serialization floor is21.475 ms. A
3,400-block RTX4090 D pool can hold26 such prompt reservations, so a30
request synchronous fixture should make late requests wait before sending.
This burst is deliberately a correctness stress case and is not a paper
workload or a policy gain measurement.

**Implementation/verification.** Added opt-in
`--pd-handoff-capacity-reservation`, D block reservation before P graph
submission, retry on insufficient D blocks and commit at D handoff.
A tiny two-request real-block-pool regression checks reserve→wait→commit→free→retry.
The earlier under-capacity 2P control is unchanged with the flag:
target P2D-ready43,026,875 ns, second token60,154,875 ns,
completion77,282,875 ns and total P2D1,056,964,608 B, with zero waits.
The valid30-request2P1D run uses normal24-GB RTX4090 pools, 3,400 D blocks,
chunked prefill and one declared100-Gb/s physical cut. The analyzer checks
960 P2D flows, 8,053,063,680 B total, exactly268,435,456 B per request,
correct source/destination ranks and cut paths, flow start after D credit,
flow end before ready and ready≤Decode admit≤token2≤completion. All30
requests complete. Capacity waits involve requests27–29 only, with378
retry events and4.025/3.429/0.211-s first-to-credit delays. Every last
flow finishes5.137–5.808 ms before P2D-ready. Raw flows/events,
request timeline, per-flow rail ledger, config, seed/command and all
source/profile hashes are under
`research_autonomous/candidates/network_staged_handoff/experiments/normal_capacity_30req_chunked/`.

**Failure diagnosis.** The first capacity run disabled chunked prefill.
After a D preemption, a resumed context exceeded the2,048-token
per-iteration budget, permanently blocking the FCFS waiting queue. That
run was interrupted, retained with `INVALID_INTERRUPTED` and excluded
from conclusions. `_schedule_waiting` now raises a precise error for a
request that cannot fit even the *full* budget when splitting is disabled;
the valid rerun uses chunked recomputation. A fail-fast regression passes.
The source of the discrepancy was an infeasible scheduler configuration,
not a measured network or capacity-policy benefit.

**Independent candidate screen.** A new ordered-token-ID derivation scans
all three committed300-request ShareGPT traces. An ideal D retaining
*every* earlier16-token prompt block can reuse only7.588% of the Llama
prompt tokens and7.904% in each Qwen trace; exactly32/300 requests have
any prior block reuse. This is an optimistic *byte* ceiling, not a latency
ceiling under queueing. The online prefix-placement candidate remains
`NEED_DATA` for an observed recurring-prefix sequence; the fixed-byte
network-scheduling variant remains `NO_GO` because the earlier source cut
already ran within0.045% of the serialization floor.

| Iteration field | Round-16 record |
|---|---|
| Falsifiable prediction | With D credit, late requests wait before KV send; all completed requests conserve bytes and event order; if final flow precedes ready, pure network-stage scheduling has no gate gain in this fixture |
| Observation | Requests27–29 wait; all30 complete;960 flows conserve8.05 GB; every final flow precedes ready by at least5.137 ms |
| Theory versus simulation | D pool threshold and byte count match; an overload burst exposed a scheduler no-chunk deadlock, repaired by fail-fast plus valid chunked run |
| Strong baseline/Oracle | Identical-size t=0 requests provide no credible SRPT/EDF advantage over FIFO; the single D is underprovisioned against2P, so ratio adjustment dominates a network policy. No Oracle gain or TTFT improvement is claimed |
| Status | Handoff correctness improved; `NO_GO` for this fixture's network-stage motivation. Stable observed saturated demand and hardware credit timing remain `NEED_DATA` |
| Next | Screen source-backed workloads for a stable long-context capacity regime, or exhaust remaining candidate mechanisms without manufacturing a load spike |

**Executive summary:** The repaired simulator now refuses to transmit
P2D KV without D capacity credit, and a normal-pool stress run completed
all requests with exact byte and temporal conservation. It did not reveal
a ≥10% network-stage opportunity. The provided ShareGPT traces also lack
the repeated-prefix volume assumed by the earlier synthetic inversion.

## Round 17 (2026-10-15): agentic KV sidecar causality audit

The remote-prefetch candidate needs exact KV identity and an observed
lower-tier miss. An independent scan of the committed50-session/765-call
SWE-bench-like trace found **every** `input_tok_ids` sidecar is exactly141
IDs shorter than `input_toks`; every `output_tok_ids` sidecar is also short
by20–999 IDs (median41). The old `request_block_hashes()` concatenated
known input and output IDs. With a missing prompt segment, output hashes
could be indexed before the declared prompt ended, defeating the
`num_computed_tokens` causal gate. This is a genuine falsifiable bug, not
an optimization effect. The minimal safe repair returns no prefix hashes
when prompt sidecar length and declared prompt length disagree; those
requests still allocate and execute normally. A targeted regression,
52 P/D tests and the KV manager self-test pass.

The previous29,086-block historical agentic estimate used the
misaligned hashes, so it is not accepted as a strict proof that the
42,260-block D pool cannot miss. We retain its raw file with this
correction. The dataset contains no observed lower-tier miss, and
FlowSim CXL `MEM_LOAD` still has zero service time. A conditional
6.711-ms read floor at an assumed60-GB/s path is therefore not a
validated TTFT/token-2 saving. Status: `NEED_DATA` for exact token IDs
and miss measurements, `SIMULATOR_UNSUPPORTED` for a timed remote load.
Evidence and source hash: `research_autonomous/candidates/agentic_remote_kv/theory/audit_ids.json`;
repair: `serving/core/kv_cache_manager.py`.

| Candidate | Scenario | Theory upper bound | Measured phenomenon | Discrepancy | Status | Next step |
|---|---|---|---|---|---|---|
| Agentic remote KV prefetch | 50-session SWE-bench-like trace | Undefined without real misses; conditional6.711-ms full4096-token read floor | 765/765 incomplete prompt sidecars; no timed CXL service or verified miss | Historical capacity/hash calculation used misaligned IDs | `NEED_DATA`/`SIMULATOR_UNSUPPORTED` | Exact IDs, measured miss and calibrated CXL load before policy evaluation |

**Executive summary:** A trace-format gap invalidated an apparent agentic
KV-cache opportunity. The simulator now prevents false prefix hits from
unknown prompt IDs. No new paper motivation was validated.

### Current-pool closure after Round 17

The ten candidates represented in `CANDIDATE_STATUS.md` and
`research_autonomous/EXHAUSTION_REPORT.md` have now been screened against
the available profiles, traces, physical maps and repaired simulator
boundaries. Seven concrete envelopes fail their ≥10% strong-baseline
or critical-path gates; the three external-data-dependent lines (agentic
remote KV, irregular provider-model fork, Chutes P/D topology) cannot be
promoted to motivation evidence. The online prefix-placement and stable
saturated-handoff variants also remain conditional on missing observed
state and load, despite their concrete fixture variants being negative.
No `MOTIVATION_VALIDATED` condition has been met, so no scheme or
large-scale trace victory is claimed and no motivation report is created.
This is exhaustion of the current candidate/evidence pool, not a general
impossibility theorem. The next independent work requires one of the
specific data sets or measured transport mechanisms listed in the
exhaustion report.

**中文 Executive Summary：**本轮把 P/D 内存满交接从“传完后失败”修成“先取得 D 容量 credit 再传输”，30 请求正常内存池压力测试全部完成且 KV 字节、物理路径、事件顺序守恒。网络尾流始终早于 P2D-ready，因此未发现网络阶段优化收益。随后发现 agentic trace 的 765 个 prompt token-ID 侧载全部缺 141 个 ID，修复了可能把未来 output 错位计入前缀哈希的问题。现有 10 个候选在可用数据和可信仿真边界内已完成筛查，没有达到 `MOTIVATION_VALIDATED`。

| 候选 | 场景 | 理论上界 | 实测现象 | 偏差 | 状态 | 下一步 |
|---|---|---|---|---|---|---|
| 网络阶段交接 | 2P1D、30 个同到达 Llama 请求，100 Gb/s cut | 冷启动网络阶段上界 0；本压力场景末流仍藏在计算内 | 960 flow / 8.05 GB 守恒，3 个请求先等容量，30 个完成 | 关闭分块重算会使抢占请求无法调度，已显式报错并重跑 | 当前场景 `NO_GO`；真实控制时延 `NEED_DATA` | 仅在稳定、可溯源长上下文负载出现理论 ≥10% 空间时重开 |
| 共享源 NIC 前缀 | 三个 300 请求 ShareGPT trace | 理想历史前缀复用仅 7.59–7.90% prompt 字节；不等同延迟上界 | 每 trace 仅 32 个请求有任何历史 block 复用 | 人工 8 前缀突发不代表这些 trace | 固定字节调度 `NO_GO`；在线放置 `NEED_DATA` | 需要真实重复前缀与 D 状态 |
| Agentic 远端 KV 预取 | 50 session、765 次 LLM 调用 | 未观察 miss，端到端上界未定义 | 所有 prompt ID 缺 141，输出 ID 也不全 | 旧哈希/容量估计不能作为严格证据 | `NEED_DATA`/`SIMULATOR_UNSUPPORTED` | 完整 ID、实际 miss、计时的下层读取 |

## Round 18 (2026-10-15): new motivation gate and online-headroom screen

The Round-17 closure applied to its old ten candidate/evidence pool.
This round adopts four distinct gates: `MOTIVATION_VALIDATED`,
`PAPER_HEADROOM_VALIDATED`, `SOLUTION_VALIDATED`, `PAPER_READY`. It
revisited the causal Round-12/13 P-hit/D-miss result and the Round-16
early D-credit implementation. New profile/model-backed theory cards,
derivation scripts, falsifiers and experiment plans cover A (P/D KV
residency inversion), B (D credit timing), and C (network/memory/Decode
compute bottleneck switching). All five actual Serving runs used the
Llama-3.1-8B BF16 RTX4090 TP1 profile, normal3,400-block D pool,
declared100-Gb/s shared source cut and exact manifests; the specific
arrival streams are controlled mechanism fixtures, not production
frequency estimates.

**A theory and observed event chain.** KV is131,072 B/token, so a
2,048-token full transfer is268,435,456 B and a64-token delta is
8,388,608 B. Two distinct1,984-token warm prefixes plus24 distinct
2,048-token fillers use3,320 completed prompt blocks in D;28 fillers
would use3,832 >3,400, while each P uses at most1,916. The theory
predicted target P hit in both cases, D hit at24 and miss at28, with
two full transfers requiring42.949673 ms on the source cut after D
eviction. The24-filler negative run sent8,388,608 B/target and finished
each target56.971 ms after arrival. The28-filler threshold sent
268,435,456 B/target; P2D-ready43.026875 ms, token2 61.027875 ms,
completion79.028875 ms. The final flow has zero slack to ready and
the source-cut floor is only0.077202 ms smaller. Two ordinary
refresh requests at4.5 s restored D hits before the same4.8-s targets;
their bytes and times returned to the24-filler values. Every flow,
physical rail, event order, prior completion and request count passed
the independent analyzer. The raw and plotted evidence is frozen in
`research_autonomous/MOTIVATION_REPORT.md`. **A has reached
`MOTIVATION_VALIDATED` only.** The22.058-ms D-state completion gap is
not a new algorithm gain.

**A strong-baseline decision screen.** A separate exact-block-capacity
replay of the frozen prefix identities gives LRU/LFU/cost-LFU target
hits0/2 when every key has one prior appearance. A future-knowing
Oracle retains2/2; it cannot be used by an online scheduler. In a
clearly labeled analytic counterfactual adding one earlier access to
each warm prefix, ordinary LFU and cost-LFU retain2/2 while LRU
retains0/2. This is *not* a Serving simulation or evidence of a policy
gain. It exposes why the original synthetic sequence lacks a lawful
predictive signal, and why a simple LFU baseline may erase an apparent
new-policy opportunity as soon as history exists. `PAPER_HEADROOM_VALIDATED`
remains open.

**B theory and observed event chain.** Four12k requests need3,004 D
blocks and all four P workers start at0; four14k requests need3,504
blocks, so the fourth cannot obtain early credit in the3,400-block
pool. The exact profile predicts per-P Prefill1.364/1.644 s and
source-cut floors503.316/587.203 ms for the four-request sets. Both
runs passed all flow/credit/block/event checks. At14k the fourth P
waits3.113511 s for receiver credit; D has no ready request until
1.644666 s. Its completion is5.899737 s, versus2.882268-s final
completion for the12k negative. The changed prompt length changes
compute and KV work too, so that difference is **not** a treatment
effect. A separate optimistic two-stage FIFO bound starts P4 at0,
holds its source KV, waits for D credit, then charges only the
100-Gb/s full-KV floor and measured isolated Decode service. It yields
4.401872 s, a conditional25.39% gap versus early credit. This is not
an implemented or measured JIT result, and ordinary two-stage FIFO
may capture the entire gap. B's observed mechanism is limited to the
current early-credit protocol; production prevalence and paper
headroom are unverified.

**C boundary.** A is source-cut-critical when P is hot; B crosses D
capacity with NIC transfer hidden under long Prefill. This supports a
multi-resource problem *hypothesis*, not a joint-policy advantage.
No legal same-resource C Oracle has been run.

| 候选 | 场景与理论上界 | 实测现象 | 理论/实验偏差与强基线 | 状态 | 下一步 |
|---|---|---|---|---|---|
| A：P/D KV 驻留不对称 | 2P1D、正常3,400块、100 Gb/s；两条全量流的 cut 下界42.950 ms；D-hit 状态理想差22.058 ms | 24 filler D 命中、28 filler D 失配；普通刷新恢复命中；目标完成56.971→79.029→56.971 ms，字节/路径/事件全通过 | 触发条件符合预测；原流无在线区分信号，加入历史后简单 LFU 已保住热前缀；Oracle 差不是策略收益 | **`MOTIVATION_VALIDATED`**；论文空间未验证 | 冻结动机数据；有合法历史信号、不同重传代价的固定资源缓存/路由强基线比较 |
| B：D 容量 credit 时序 | 4P1D、12k→14k 越过3,400块阈值；乐观两阶段下界4.402 s，相对 early credit 条件差25.39% | 14k 第四 P 等3.113511 s，首个 D-ready 在1.644666 s；所有4请求及7.34 GB流守恒 | 机制符合预测；下界假设 source KV 保留与零额外开销，简单两阶段 FIFO 可能已达到；不同 prompt 长度不能直接当处理效应 | 当前协议机制已观察；论文空间未验证 | 实现正确的 source retention/late credit，并先比两阶段 FIFO |
| C：网络/容量/Decode 计算联合决策 | A 网络临界，B 容量跨阈值；相同技术但不同请求分布 | 只观察到两个独立瓶颈边界 | 无同资源联合决策、强基线或 Oracle | 理论筛查 | 固定异构流和资源后比较简单多资源基线与合法 Oracle |

**中文 Executive Summary：**第18轮在真实模型 profile、正常 D 缓存容量和显式物理链路下，用负对照、阈值实验和普通请求刷新消融验证了 P/D KV 驻留不对称：D 淘汰后，两条目标请求虽在 P 命中前缀，仍须全量传输，模型完成时间各增加22.058 ms。该结果达到研究动机门槛，不是策略收益。另一个实验发现当前提前获取 D 容量 credit 的协议会让第四个 P 长时间空闲；但其25.39%只是乐观解析上界，合理两阶段 FIFO 可能获得同样结果。A/B 的强基线后论文空间均未验证，C 尚为理论假设。所有原始数据、分析和下一步保存在 `research_autonomous/`。

## Round 19 (2026-10-15): strong-baseline closure before proposing a policy

**假设与理论。**沿用第18轮 Llama-3.1-8B BF16/RTX4090 TP1 profile、正常
3,400-block D 池和声明的100-Gb/s共享源 cut。B 的14k 请求每条 KV 是
`14,000×131,072=1,835,008,000 B`，四条共7,340,032,000 B；每条
预留`ceil((14,000+1)/16)=876`块，四条3,504块超过 D 池。提前取得
credit 会让第四个 P 等待；正确的两阶段 FIFO 应在 P 计算完成后保留源
KV，再按 FIFO 取得 D credit、传输并提交。A 先注册两条有第二次已完成
访问的 warm prefix，再加入14条2048-token、14条3072-token的不同
fillers；历史只来自已到达请求，D 总缓存需求4,728>3,400块，各 P
分别最多1,916/2,812块，故 LRU 与 LFU 有可证伪差异。C 预判三个同
时 transfer 的 FAIR 共享会推迟首个 D 完成，简单 FIFO 网络顺序应提前
放出一条，但整体收益需包含后续 Decode 与第四条的关键路径。

**实现和修复。**加入 opt-in `TWO_STAGE_FIFO`：Prefill compute-only、
P 源块保持、D credit 后 transfer-only、图结束后释放 P，并有 held 与
in-flight 内部取消语义。第一次 `r19a` 把16-bit `fp` 当成16字节，
每请求发14.680064 GB而非1.835008 GB；原始数据保留并标记
`INVALID_BYTE_OVERCOUNT`，用`fp//8`修复后重新生成全新 case。加入
D-only LFU 普通在线基线；默认 LRU 不变。审计每 flow 的源/目的 rank、
bytes、开始/结束、源/目的 rail，逐请求核对 D credit、P 块释放、
P2D-ready、D admit、token2 与完成。52 个 P/D 测试、13 个聚焦测试及
`git diff --check`通过。FlowSim 的 control/query 仍零模拟耗时；
取消只在内部状态机测试，尚无外部 abort workload。

**B 匹配实验。**同样4P1D、全量 POST_PREFILL 流量、配置和请求：
四条14k/64在t=0，early-credit FIFO 最末完成6.486961960 s，
two-stage FIFO 4.842297960 s，即简单基线改善25.3534%。异构序列
`(12k,32,0)→(14k,96,.2s)→(14k,48,.4s)→(16k,64,.6s)`分别
为5.310646680/4.112784320 s，改善22.5559%。两组每 arm 都传
7.340032 GB、4条请求全完成，容量和事件顺序通过。固定 FAIR 网络、
FIFO Decode，只优化 admission 时序的**条件 Oracle**下界分别是
4.842285760/4.112784320 s，two-stage FIFO 仅差12.2 µs/0。
这否定 B 在这两组场景下的新增 admission 策略空间；25%是简单
two-stage 相对旧 early-credit 协议的收益，不是论文算法收益。

**A 在线历史实验。**34请求同配置对照全部完成；LRU 两目标 D hit
均0，分别全传268,435,456 B，目标到达至模型完成79.028875 ms。
LFU 两目标 D hit 均1,968/1,984 token，分别传10,485,760 B，
完成56.971 ms。理论预测的1,984个 token全命中高估了最后1块的
计数：该块未获得第二次已计入的 block access。剩余2.097 MB/目标
在 Prefill 完成前传完，故理想 D-hit 状态的目标完成时间也不能再降低。
这是 LRU 与简单 LFU 的差距；没有新方案收益。单 D 没有 routing
决策，两条 target key 不同排除 single-flight，DELTA 两 arm 都开。
成本感知策略在本 fixture 没有超越 LFU 的目标完成空间。第18轮
D-hit/D-miss 动机保持冻结，不被这个 NO_GO 推翻。

**C 初步转向。**保持正确 two-stage FIFO，仅将均匀同到达流改成
`KV_REQUEST_FIRST id0` 离线网络顺序对照；在此例 id0 是合法 FIFO
并列顺序。7.340032 GB、容量/路径/事件通过，末完成4.515045840 s，
相对 FAIR 的4.842297960 s 改善6.76%。首流提前完成后 D 更早
运行并释放第四条 credit，符合理论因果；但收益小于10%，而且简单
FIFO 已得到，故本均匀 C fixture `NO_GO`。此 control 不是通用在线
网络调度实现或全资源 Oracle。

**文献差异与门槛。**[P/D-Serve](https://arxiv.org/abs/2408.08147)
已描述 Prefill 等待 KV transfer 时占用源 slot，以及 Prefill 后
选择空闲 Decode 的路径；不能把两阶段保留包装成新机制。
[PrefixPlace](https://arxiv.org/abs/2608.01655)已处理异构前缀
计算/传输成本，[NetKV](https://arxiv.org/abs/2606.03910)已处理
网络拓扑/拥塞与 cache/load 的 Decode 选择；
[DMRS](https://arxiv.org/abs/2610.15579)已形式化 Prefill/Decode
双内存占用及请求完成时间调度。未来的新机制必须在
同资源下胜过这些方向及简单 LFU/FIFO/DELTA/single-flight 组合。
当前 **`MOTIVATION_VALIDATED` 保持，`PAPER_HEADROOM_VALIDATED` 未达到**。
下一步只接受有来源的异构共同负载，并先推导强基线后的≥10%合法
空间；不通过就记录 NO_GO/NEED_DATA，不回头调整已完成 fixture。

| 候选 | 场景与理论上界 | 实测现象 | 偏差及强基线结论 | 状态 | 下一步 |
|---|---|---|---|---|---|
| A：P/D 前缀保留 | 2P1D、两条二次历史、28条异构 filler；D需求4,728/3,400块，理想 D-hit 目标56.971 ms | LRU 79.029 ms、全量；LFU 56.971 ms、每条10.486 MB | LFU仅命中1,968/1,984，但尾块传输被 P 计算掩盖；强基线后模型完成上界0 | 当前 fixture `NO_GO`；冻结动机仍有效 | 有来源的在线预测信号和多 D 候选；先比 LFU/成本/路由/DELTA/single-flight |
| B：credit 时序 | 4P1D、14k/64、3,504块需求>3,400；固定 FAIR/FIFO admission Oracle 4.842286 s | 匹配 early 6.486962 s、two-stage 4.842298 s；异构组也从5.310647→4.112784 s | 第一次8倍字节 bug 已排除；两阶段 FIFO 对条件 Oracle 几乎无差 | admission 论文空间 `NO_GO` | 把 two-stage FIFO 当后续强基线 |
| C：联合网络/容量/Decode | 同4P1D满 credit，理论首条 FIFO 比 FAIR 早 ready 约294 ms；端到端上界须重算 | 简单 FIFO 并列优先末完成4.515046 s，较 FAIR 快6.76% | 小于10%，且差距被简单网络顺序获得；无全资源 Oracle | 当前均匀 fixture `NO_GO` | 只对有来源异构共同负载做强基线后的理论筛查 |

完整分轮记录、理论、原始配置/日志及每次 run 的 SHA-256 在
`research_autonomous/candidates/r18_*/iterations/round19.md`、
`research_autonomous/EXPERIMENT_REGISTRY.jsonl` 和相应 case 目录。

**第19轮追加来源负载筛查。**读取仓库原始
`sharegpt-llama-3.1-8b-300-sps10.jsonl` 的前50条有 token ID、
长度和到达时间的请求，未经改写。它们合计46,957 prompt tokens，
全量 P2D 在同一100-Gb/s cut 上仅需0.492380 s 序列化；开启
DELTA 后只会减少传输字节。最后一条在4.229722 s到达、需708个
output token。逐层取实测 profile 的最小耗时，Decode 每步至少
16.642176 ms，该请求余下707步至少11.766 s，即无排队和无网络
时也不早于15.996 s完成；cut 时间/这个不可避免时间为3.078%。
这是**固定后续计算工作量时的网络单资源必要筛查**，不是允许改变
batching、缓存、完成顺序时的全局收益上界。没有≥10%的强基线后
理论空间，因此未为这个真实窗口盲目跑新的网络调度仿真。脚本、
profile/trace SHA-256和结果在
`r18_joint_bottleneck/theory/sharegpt50_screen.{py,json}`。为了以后
能用强基线跑含真实前缀的负载，两阶段 FIFO 又加入了 late-credit
DELTA：只减去当前 D credit 实际 pin 住的前缀字节，新增块池和字节
单测通过；该组合尚无端到端结果，不计入任何收益。

**更强 early-credit 基线复查。**为避免只用 POST_PREFILL 弱化旧协议，
又用当前修复后的代码、同配置和两组请求重跑早期逐层发送
`EARLY_LAYERWISE`。每组896条 flow 共7.340032 GB，全部请求、
路径、credit 和 Serving 事件通过；均匀/异构末完成分别
5.899737/5.020136 s。普通 two-stage FIFO 分别快17.9235%/
18.0742%。这是含不同传输 DAG 的**完整协议对照**；前述
EARLY_POST 才是只改 credit 时序的严格消融。两组都说明收益已由
简单两阶段基线获得，B 的新策略论文空间仍 `NO_GO`。
