# Final decision: Network-induced Decode Batch Admission Miss

## Classification

**`MECHANISM_EXISTS_BUT_IMPACT_SMALL`**

The physical cross-request network mechanism is confirmed: model-derived P2D KV flows and Decode EP flows overlap on the same directed 200G cut, and the P2D critical-shard completion changes. The specific serving hypothesis—network delay moves `P2D_READY` across a real Decode batch-selection boundary, causing an amplified TTST/SLO miss—was **not observed** in the theory-selected and bounded integrated workload. The earliest failed causal edge is `network completion → P2D-ready`: Prefill compute hides the network increment.

## Gates

| Gate | Result | Evidence |
|---|---|---|
| G0 theory/legal opportunity | **NO-GO in the tested 1P2D/EP4, four-active-Prefill envelope** | Batch crossing requires ideal N=19 equal 4MiB layer flows against the fixed E3a compute slack/boundary; the actual configuration can co-release at most four full-size streams (one per active Prefill graph/rank) with this batch budget. |
| G1 physical network mechanism | **PASS** | Exact paths, positive interval overlap, cut saturation, FCT and EP CCT changes; E4 removes the additional KV/KV overlap and restores target FCT. |
| G2 actual Batch Miss | **FAIL / not observed** | Same target is eligible before and selected into Batch9 in both matched E3a/E3b runs; `P2D_READY` identical; no capacity wait. |
| G3 serving amplification from a miss | **FAIL** | No miss exists. FAIR TTST rises1.452%, due to EP shifting prior-batch completion; TTFT unchanged. |
| G4 phase robustness | **NOT RUN** | `Delta_ready=0`, so the bounded phase-scan prerequisite is absent. No production probability claim. |

This is a bounded negative result for the tested model, profile, 1P2D/EP4 topology, request sizes, scheduler constraints, and FlowSim semantics—not a claim that every deployment can never experience admission misses.

## Answers to the 12 required questions

### Q1. Required 200G flow count/data for additional KV FCT

For Qwen3's 2,048-token KV layer shard, `B=4MiB`; `C=25GB/s`; one flow serialization is167.772µs. Under synchronized equal-flow max-min sharing, the target's ideal extra FCT over an isolated flow is `(N−1)B/C`:

| Extra target FCT | Minimum synchronized N | Total bytes on cut in that layer |
|---:|---:|---:|
| ≥0.1ms | 2 | 8MiB |
| ≥0.2ms | 3 | 12MiB |
| ≥0.5ms | 4 | 16MiB |
| ≥1.0ms | 7 | 28MiB |

Those are **flow-FCT** thresholds, not serving-ready thresholds. Relative to measured E3a N=4, ideal N=11 first exposes P2D-ready by about8.693µs; N=19 is first to cross the Batch9 decision after compute masking. N=19 is not part of the executed workload and is outside the current four-active-Prefill full-size co-release envelope.

### Q2. Which GPUs/NICs/links share?

Active Prefill physical GPUs0–3 attach to NIC rail endpoint24, then ToR30. Target Decode rank8 attaches via rail26. The R1 path is `0→24→30→26→8`; P2D and Decode EP traffic have verified positive-time overlap on common directed `30→26` / receiver-side route segments. Each NIC rail is200Gbps; a server has two rails /400Gbps aggregate. Four GPUs sharing one 200G rail do **not** each have a hard50G cap.

### Q3. Required active requests/load?

The measured Decode cohort is24 R0 requests, six per Decode rank/lane, with `max_num_seqs=8`; the target admission changes the receiving lane from6/8 to7/8. R0 output length16 drives16 legal recurrent EP4 AG/RS iterations. Four full 2,048-token candidate Prefill requests—R1 plus three R2—are co-released across the four Prefill GPU ranks. This is a controlled concurrency point, not a GPU-utilization measurement. The Token budget is2,048 per Prefill batch, so a full-length candidate consumes one such rank's batch. Four is the maximum synchronized full-size P2D population in this tested serving envelope.

### Q4. Prefill/KV/Decode intervals?

R1's QKV-layer completion and KV release interval is exactly1.542ms for all47 layer gaps; the full release span is72.474ms. Decode R0 six-sequence iteration period is about8.431ms. Target Batch9 graph execution takes9.382712ms. R1's Prefill graph lasts74.468ms from54.349ms to128.817ms. These are measured profile-driven values for this controlled workload, not universal hardware constants.

### Q5. R0/R1/R2 arrival order?

R0 arrive at0ms; their prefill/handoff completes54.349ms, then Decode iterates. R1 and three R2 arrive at30ms and start Prefill when a Prefill lane is free at54.349ms; their first KV release is54.496ms. This timing comes from normal scheduler and graph execution. E4 shifts R2 arrivals to130ms (first KV release130.147ms), after R1's final shard127.149653ms.

### Q6. Isolated slack to boundary?

E3a: R1 ready128.817ms; Batch9 selection130.073992ms; slack1.256992ms. Its last required shard finishes127.651289ms, so compute hides1.165711ms. Consequently, network completion must gain over2.422703ms relative to the E3a shard finish to cross Batch9—not merely1.257ms. FAIR has the same ready timestamp and a later Batch9 decision130.228511ms.

### Q7. Network change and ready delta?

E0 single-request critical-shard FCT177.973µs. Four KV requests produce681.289µs in E3a; physical FAIR with EP gives684.649µs. The added P2D concurrency increases the layer-shard FCT by roughly0.503ms over solo; adding class-shared EP on top of the same four-KV counterfactual adds3.360µs to the target critical FCT (+0.493% relative to E3a). Nevertheless, `P2D_READY` changes by **0ns** because last KV finishes1.162351ms before Prefill graph completion in FAIR. The 400G sensitivity lowers target shard FCT to346.585µs but ready remains unchanged.

### Q8. Was there a Network-Induced Batch Miss?

**No.** Request24 is ready128.817ms, admitted with no capacity wait (6/8 active;7/8 after admission), has ample KV blocks and token budget, and is selected into Batch9 in both E3a and E3b. Batch8 is fixed and running; neither condition joins it. The actual next legal selection is the same batch ID.

### Q9. TTST/SLO change?

E3a TTST10.639704ms; E3b FAIR10.794223ms, +154.519µs /+1.452%. First visible token/TTFT stays at128.817ms /98.817ms. The first-batch graph itself is9.382712ms in both; the TTST delta is exactly the later prior-batch completion/selection time. TPOT changes9.081827→9.103901ms (+22.074µs). Using explicitly labeled relative sensitivity thresholds based on E3a TTST (1.25×13.299630ms,1.5×15.959556ms,2×21.279408ms), all4/4 controlled E3 candidates pass all three in both E3a and E3b. This four-request sample does not support production P95/P99 or calibrated SLO claims.

### Q10. Earliest failed causal link?

F3: cross-request network contention delays the final KV flow, but that flow is not the serving-ready gate. E3b last KV ends127.654649ms; Prefill sampler/graph ends128.817ms. The network increment is hidden behind1.162351ms of remaining compute. Thus `network → P2D-ready` fails before the boundary test; `Delta_ready=0`.

### Q11. Maximum avoidable misses under current experiment?

Zero observed and zero avoidable for this exact request set/phase: even a counterfactual eliminating all network delay cannot change the already-identical Batch9 membership. At the fixed measured compute and batch phase, ideal synchronized equal 4MiB messages would require N=19 total active flows to exceed both Prefill masking and the batch boundary. The one-graph-per-Prefill-rank, 2,048-token batch budget and four active Prefill GPUs bound the tested co-released full-size case at N=4. No deployable-algorithm gain is inferred from the N=19 arithmetic.

### Q12. Is there sufficient frequency/user loss to continue?

Not demonstrated. The controlled phase yields0/4 Batch Misses, `Delta_ready=0`, no sensitivity-SLO misses, and a1.452% TTST difference whose source is recurrent EP iteration timing, not the KV admission barrier. A phase scan is not justified without positive ready delay. Under this tested model/topology and valid serving envelope, the Batch-Miss motivation is not strong enough to proceed to an optimization algorithm. The smaller network mechanism itself is real and may be retained as characterization evidence.

## Artifacts

Required analysis is in `01_SCHEDULER_BOUNDARY_AUDIT.md` through this decision file; exact integrated results are in `06_EXPERIMENT_RESULTS.csv` and candidate/SLO rows under `results/06_CANDIDATE_REQUESTS.csv`. `PHASE_SCAN_STATUS.md` explains the intentionally unrun scan. Reproducibility commands and dirty-worktree caveat are in `RUN_COMMANDS.md` and `PROVENANCE.md`.
