# Cross-layer evidence map

## Executive answer

The historical results are not contradictory. A network slowdown becomes a serving slowdown only when it delays the communication object that currently controls a serving barrier, by more than the overlap/slack available at baseline. Most measured KV shards are released long before the request's last-shard handoff; their flow tails can change without moving Decode admission. EP traffic is closer to a recurrent Decode iteration barrier, so controlled simultaneous cohorts and KV_FIRST can expose EP delay in TBT. Natural Azure windows show little policy-sensitive shared-link pressure, and the measured Prefill/admission slack absorbs most changes.

The best-supported cross-layer statement is presently an explanatory hypothesis, not a paper result:

> Serving dependencies determine exposure; network service determines the raw completion perturbation.

This organizing model explains many positive/negative pairs. It does not prove a non-separable joint scheduling gain, a natural >=10% serving opportunity, or novelty over stage-aware/laxity/coflow scheduling.

## Audit method and scope

We searched the retained experiment tree, reports and ledgers, source/configuration files, and available git metadata. The worktree contains extensive uncommitted changes. Local experiment history is not represented by commits in the checked git history; reports/manifests and surviving raw artifacts are the provenance basis. Some older high-volume raw ledgers have been removed, while reports or compact summaries remain. Summary-only evidence is not upgraded to independently reproducible evidence.

Primary retained sources:

- [RESEARCH_HISTORY_AND_RESULTS.md](RESEARCH_HISTORY_AND_RESULTS.md), [FAILED_RESEARCH_ATTEMPTS.md](FAILED_RESEARCH_ATTEMPTS.md)
- [PD_MOE_NETWORK_PROBLEM_DISCOVERY.md](PD_MOE_NETWORK_PROBLEM_DISCOVERY.md), [PD_MOE_NETWORK_PAPER_PROBLEM_FINAL_NO_GO.md](PD_MOE_NETWORK_PAPER_PROBLEM_FINAL_NO_GO.md)
- [AUTONOMOUS_PD_KV_NETWORK_PROBLEM_SEARCH.md](AUTONOMOUS_PD_KV_NETWORK_PROBLEM_SEARCH.md), [MINIMAL_IDEAL_KV_EP_FINAL_FAIL.md](MINIMAL_IDEAL_KV_EP_FINAL_FAIL.md)
- [CHARACTERIZATION_REPORT.md](CHARACTERIZATION_REPORT.md), [N1_DECODE_BATCH_BOUNDARY_AUDIT.md](N1_DECODE_BATCH_BOUNDARY_AUDIT.md)
- [DCQCN_MODE1_MATCHED_REPLAY_REPORT.md](DCQCN_MODE1_MATCHED_REPLAY_REPORT.md), [S8_NATURAL_ECN_BASELINE_AUDIT.md](S8_NATURAL_ECN_BASELINE_AUDIT.md)
- [P4_GO_NO_GO.md](P4_GO_NO_GO.md), [P4B_FINAL_NO_GO.md](P4B_FINAL_NO_GO.md), [PROGRESSIVE_PUSH_RESEARCH.md](PROGRESSIVE_PUSH_RESEARCH.md)
- [P2_PACKET_REPLAY_GATE.md](P2_PACKET_REPLAY_GATE.md), [PACKET_LEVEL_AUTONOMOUS_RESEARCH.md](PACKET_LEVEL_AUTONOMOUS_RESEARCH.md)

The master experiment index is [CROSS_LAYER_EVIDENCE_LEDGER.csv](CROSS_LAYER_EVIDENCE_LEDGER.csv); reconstructed paired cross-layer quantities are in [EXPOSURE_ANALYSIS.csv](EXPOSURE_ANALYSIS.csv).

Repository snapshot for provenance: branch main, HEAD a4053bc1161872420e1e0607cb3409ef659b828e (2026-08-28). The checked git history contains no commits under experiments/pd_kv_ep; this directory and the simulator worktree are locally modified/untracked, so experiment reports/manifests—not commit ancestry—identify run provenance.

## Validity labels

- AUTHORITATIVE: matched identities and corrected semantics are documented; use only for the bounded claim stated.
- HISTORICAL_ONLY: useful mechanism/trend, but obsolete topology, incomplete serving/network coupling, summary-only provenance, or diagnostic workload prevents a current quantitative claim.
- INVALIDATED: known topology/configuration/semantic defect directly invalidates the number.
- NOT_RUN / NOT_MEASURED: no result exists; never interpret missing as zero.

Key corrections:
1. Old parallel leaf-spine parsing collapsed multiple physical links into one. Old S16/S64/S256 quantitative results, including old +23.44% KV slowdown, are invalidated for corrected-topology claims.
2. Corrected S16 represents 16 physical 200-Gbps links per leaf-spine pair as 3.2-Tbps aggregate directional fluid capacity; each endpoint NIC remains 200 Gbps. This is not a 3.2-Tbps endpoint.
3. Old q0 data-priority runs that could starve ACK/control are invalidated. Correct q0 is control/ACK/CNP/PFC; q1 is selected data priority; q3 is ordinary data. q1/q3 still pass MMU/ECN/PFC accounting.
4. Native packet replay fixes issue times and does not feed packet completions back to the serving scheduler. It can validate packet behavior and offline barriers, but cannot produce packet-integrated TTFT/TBT.
5. FlowSim queue is fluid backlog, not packet-buffer occupancy, ECN, PFC, loss, ECMP hashing, or DCQCN.
6. CC_MODE=1 is the implemented DCQCN mode. CC_MODE=12 is unsupported/undocumented and cannot be a valid DCQCN-off comparison.

## Experiment families and last meaningful evidence

| Family | Last informative configuration | Strongest finding | Status |
|---|---|---|---|
| Basic cross-class KV/EP | S8; Qwen3-30B-A3B; EP32; 8 Decode warmup + 2 8192-token P2D; LAYERWISE; ns-3 200G, 4KiB, CC_MODE=1 | EP collective P99 +0.0015%; handoff <0.13%, while individual KV shard tails grew | AUTHORITATIVE bounded negative |
| KV self-contention/DCQCN | Same immutable 499,776-event ledger; K8/K9 isolation vs K2; CC_MODE=1 and 0 ablation | Shard P99 roughly doubled under K-vs-K and 5–8x under CC1-vs-CC0; request handoff moved at most 0.045% | AUTHORITATIVE network/barrier; no serving feedback |
| Final-shard exposure | Same layerwise release structure; final required shard attribution | Residual drain +23.568%, handoff +0.0115%; final shard still finished 2.367ms before Prefill completion | AUTHORITATIVE bounded negative |
| EP64 controlled priority | Corrected S16, 8P8D, shared dual-NIC/server 2x200G, EP64; 32 Decode at t0 and 64 P2D at 20ms | EP CCT P99 -50.54%, TBT P99 -21.72%, TPOT -17.26%; KV-ready unchanged | AUTHORITATIVE controlled mechanism, not natural motivation |
| EP64 natural Azure | Corrected S16/Qwen3/EP64/A2A_P2P/LAYERWISE; Conversation 16 and Code 32, original timestamps/tokens; FAIR vs EP_FIRST | EP CCT/TTFT/TBT/TPOT changes effectively zero; KV completion before Prefill completion | AUTHORITATIVE replicated negative for these two windows |
| EP64 high-pressure integrated | 8P8D/EP64/200G, 32 Decode +64 P2D, 4-output and 1-output | EP_FIRST strongly improves EP/TBT in controlled workload; KV handoff/TTFT <1%; topology comparability predates correction | HISTORICAL_ONLY / controlled |
| EP4 integrated policy | 3 Decode+1 P2D, 100G, 8192 input, LAYERWISE | KV_FIRST raises EP CCT P99 11.860 to 148.982us, TBT P99 +8.3%; TTFT unchanged | AUTHORITATIVE for this case; below serving gate |
| POST_PREFILL sensitivity | D64+K1, 8192-token, matched controls; neighboring D32 | Residual drain +19.51% / +10.47%; TTFT +4.62% / +3.30%; TBT P99 <1% | HISTORICAL/mechanism sensitivity; not primary semantics |
| Decode batch boundary | Integrated 8D+8P2D, 16D+16P2D, 32D+32P2D and adjacent 32D+64P2D | Only high point misses one iteration: 6.568ms = 6.5% TTFT; adjacent 1.418ms =1.2% | AUTHORITATIVE bounded negative |
| 512-request fan-in | Corrected S16 FlowSim; 256 Decode +256 P2D; spread vs fan-in16 | EP CCT P99 +201%, KV FCT +99%; no integrated serving result; synchronized equal-size KVs make request samples equal | AUTHORITATIVE network-only |
| Packet fan-in corrected | S16 native ns-3, 32D+64P2D, 4KiB; spread vs fan-in16 | Flow FCT P99 +34.9%, EP CCT P99 +29.1%, request handoff +0.39%; separate 96-request FlowSim TBT P99 +5.01% | AUTHORITATIVE per backend, not same-run causal coupling |
| Old packet fan-in | Earlier S16 route table omitted parallel paths | Claimed KV +96.5%, EP +54.3% | INVALIDATED |
| EP32 packet policy | S8 4P4D/EP32, 16 Azure requests, native ns-3 4KiB, q0 control/q1 priority/q3 ordinary | EP_FIRST EP CCT P99 -0.52%, handoff unchanged; KV_FIRST EP P99 +852.9%; separate FlowSim TBT +95.9% | HISTORICAL_ONLY as cross-backend linkage |
| Same-byte EP route geometry | EP_ONLY/FULL GateRouter exact vs uniform-peer counterfactual, 64-request BurstGPT | ~78% geometry gap already exists in EP_ONLY; P2D does not amplify it | AUTHORITATIVE counterfactual; generic EP geometry |
| Placement/path oracle | Corrected S16, same bytes/load, alternate P/D placements | CCT gains 0–7.1%; KV stable | AUTHORITATIVE bounded negative |
| Critical-only EP oracle | EP_FIRST vs top-5% offline critical-flow protection | Top5 worsens EP P99 39.9–57.7%; negligible KV gain | HISTORICAL_ONLY oracle |
| Minimal ideal shared ToR gate | 1P2D, EP16, 2x200G/server, D16+K8, model-derived 8192-token LAYERWISE, FAIR | EP CCT P99 +5.11%, KV residual +3.66%, TTFT +1.60%, TBT +0.47% | AUTHORITATIVE bounded FlowSim FINAL_FAIL |
| Remote prefix/provider P4 | Mooncake high-reuse windows, provider placement oracle | Remote barrier improves but TTFT/TBT do not; replica warm-up is non-free | AUTHORITATIVE semantic/network; ordinary-placement NO-GO |
| Split-source P4B | Legal dual-destination only; cached prefix still needed at Prefill | TTFT worsens 22.9–61.1%; direct-to-Decode-only is semantically invalid | AUTHORITATIVE P4B NO-GO |
| Progressive Push | Whole KV vs progressive layer push; model-derived bytes | TTFT gain at 200G 6.07%, TBT unchanged; 50G larger but not robust primary | HISTORICAL_ONLY old endpoint topology; sensitivity |
| S16/S64/S256 trace matrix | Large replay / requested 10k–25k serving matrices | Some network-only and small slices; full integrated matrix not completed | NOT_RUN for full matrix |
| P1–P5/N1–N5 broad search | Placement, last-shard, incast, multipath, routing, critical-only, QP, backpressure, remote KV, burst shaping | No candidate meets joint network+serving threshold; some mechanisms lack validated runtime model | Mixed; see family reports |

## Source-grounded system/network boundary

In scheduler.py add_done, Prefill completion and P2D completion are distinct. The Prefill graph completes only after emitted KV SEND QPs report completion at the actual Decode receiver; p2d_kv_ready_time then gates router.transfer_prefill_request() and Decode admission. User-visible TTFT ends at first Decode token, not KV completion.

The request ledger exporter separates arrival→Prefill completion, Prefill completion→P2D-ready, P2D-ready→Decode scheduler admission, and scheduler admission→first Decode token. These segments close to observed TTFT on retained natural rows. KV flow activity overlaps Prefill compute/release; adding a separate KV FCT to the full prefill interval double-counts.

For Decode, EP peer traffic is within an iteration/collective barrier. Peer-flow FCT is not collective CCT; CCT is last required peer completion minus collective start. CCT is not TBT: compute or other batch work can overlap communication, and only delay that holds the Decode iteration/token boundary reaches TBT.

## Invariant and limits

For a fixed max barrier with baseline completion B0=max_i(F_i), changing only object i by delta_net gives slack_i=B0-F_i and exposed barrier delay=max(0, delta_net-slack_i). This exact identity explains early-shard masking. It is not a universal serving predictor: admission epochs, batch barriers, concurrent compute, active-set changes, and repeated Decode iterations require integrated replay.

Detailed comparisons: [03_POSITIVE_NEGATIVE_PAIR_ANALYSIS.md](03_POSITIVE_NEGATIVE_PAIR_ANALYSIS.md). Definitions: [04_EXPOSURE_MODEL.md](04_EXPOSURE_MODEL.md).

## Decision

The strongest current insight is an organizing principle: measure delay at the dependency barrier after accounting for slack; do not equate congestion with serving bottleneck. The bounded KV×EP line has authoritative negative gates, including the favorable minimal legal 1P2D/EP16 case. The controlled EP64 run proves mechanism capability only.

A joint system+network paper direction remains UNVALIDATED. The exact baseline/network-only/system-only/joint factorial on identical natural requests and bytes does not exist. Do not claim synergy or >=10% integrated headroom by combining different workloads or simulators.
