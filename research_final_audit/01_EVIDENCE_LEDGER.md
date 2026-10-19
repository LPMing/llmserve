# 01 — Evidence ledger and provenance freeze

## Decision scope

This is the final review of `KV/EP Flow-Level Priority Scheduling` for the tested
Qwen3-30B-A3B serving/model envelope. Historical percentages below are kept in
their own experiment families; they are not pooled as if they were one matched
matrix. `NOT_RUN` means no evidence, not zero gain.

## Repository and evidence snapshot

| Item | Frozen value |
|---|---|
| Repository | `/home/dell/lpm/LLMServingSim` |
| Git HEAD | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| Pre-existing tracked diff SHA-256 | `bffce36e4015d9fbcf484dc78ebed4c658f7365297a672230127331cba0986db` |
| Worktree | Dirty before this audit; many modified/untracked simulator and research files were preserved. No reset or cleanup was performed. |
| Qwen model config SHA-256 | `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3` |
| RTXPRO6000/Qwen3 BF16 profile `meta.yaml` SHA-256 | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| S16 EP64 manifest SHA-256 | `507a0ae4bc6fd04e63e8b5d4d829aed10fd2aaae9301b68701441084b8b982e0` |
| S16 EP64 200G Clos topology SHA-256 | `cc105c3b3aa6452d31ea6df586e221f20d568eec54d17f5628cffa77017d1ba7` |
| New replay source BurstGPT slice SHA-256 | `ed609a5edcec5b06fa89985b601b008e426e8885c3aef2c9f7e75af7be2bb7a1` |
| New replay builder SHA-256 at run | `029b4d975854c24a7f64dc94039bb511a7aa7aa8e5c31f59c6c2da93acd0ecbb` |
| New replay runner SHA-256 at run | `d81907c86d84a9bd82d4c36729d4b5d1ef728f0067b8d37eb05b2169741797da` |

The dirty-tree snapshot binds this audit’s new run to the current checked-out
scripts/configuration, but it does **not** retroactively bind every old output
to an immutable historical commit. Historical results without surviving raw
ledger/provenance remain historical evidence, not newly reproduced evidence.

## Frozen experiment ledger

| Direction / experiment | Executed evidence | Level | Result and validity boundary |
|---|---|---|---|
| KV–KV, 128-token victim with long KV backgrounds | Per-shard FCT mean/P99 and request barrier analysis in `experiments/pd_kv_ep/RESEARCH_HISTORY_AND_RESULTS.md`, `03_POSITIVE_NEGATIVE_PAIR_ANALYSIS.md` | Network + serving-integrated FlowSim | Shard FCT P99 increased up to 25.35%; request last-required-shard/P2D-ready/TTFT generally did not move. A shard tail is not the request max barrier. |
| KV–EP, EP4 native ns-3/cohort | Small matched model-derived flow replays in historical reports | Packet/network only | Examples include EP P99 6.545→13.270µs for two 2048-token P2D requests in one corrected case; other EP4 cohort EP protection opportunity 43.54%. These are not whole-run TTFT/TBT gains. |
| KV–EP, controlled EP64 policy | 8P8D, EP64, 200G, 32 active Decode + 64 P2D at a controlled phase; model-derived LAYERWISE; FlowSim integrated | Controlled serving-integrated | FAIR→EP_FIRST: EP CCT P99 92.279→45.644µs (−50.54%), TBT P99 8.862→6.937ms (−21.72%), TPOT −17.26%; KV-ready unchanged. Valid mechanism demonstration, not natural-incidence or global policy evidence. |
| KV–EP, natural Azure windows | Azure Code 013818 first 44 and Azure Conversation 06210 first 16, natural arrivals, FlowSim FAIR | Natural serving baseline + event/link attribution | Same-directed-link coactivity exists, but KV handoffs precede Prefill completion; no positive matched CCT attribution was shown. Whole-window serving metrics are baselines only. |
| KV–EP, smallest ideal shared ToR gate | 1P2D, EP16, D16+K8, LAYERWISE 8192-token P2D, FAIR, FlowSim | Controlled integrated | EP CCT P99 +5.11%, KV residual P99 +3.66%, TTFT +1.60%, TBT +0.47%; queue episodes were far shorter than recurrent EP periods. Bounded negative gate, not packet evidence. |
| EP–EP, two independent EP4 groups | Legal independent groups, common directed cuts; Qwen3 TP2; original implementation used AG/RS semantics | Integrated FlowSim | Dispatch CCT +6.39%, combine +1.58–3.11%, resulting TPOT/TBT +0.75–0.80%. Do not call this exact sparse A2A. |
| Shared NIC and static class priority | 4 GPU ranks share one modeled 200G NIC rail; FAIR/EP_FIRST/KV_FIRST | FlowSim integrated/network | FAIR→EP_FIRST mean TPOT about −0.61%, ITL P99 unchanged; KV_FIRST can badly stall EP. Strict EP protection already captures most measured class-level headroom in that fixture. |
| Layerwise KV / progressive push | Historical progressive release and post-prefill comparisons | Integrated sensitivity; some old topology files invalid | Progressive push showed up to ~20.22% TTFT P99 on old 50G small files, but old endpoint/rank IDs were invalid; corrected 200G sensitivity was ~−6.07%, TBT unchanged. Not authoritative packet/serving motivation. |
| Decode opportunity | `research_motivation/decode_opportunity/06_SERVING_INTEGRATED_RESULTS.csv` | Controlled integrated FlowSim | One target’s P2D-ready advanced ~4.038ms; arrival-to-second improved ~3.381ms in the primary seed. Pair mean improved ~0.85%; a neighboring 13-token seed reduced the target delta to ~43µs. The reported TTST anchor is not a validated client-visible event. |
| Batch admission miss | `research_motivation/batch_miss/10_FINAL_MOTIVATION_DECISION.md` | Controlled integrated FlowSim | Packet/network mechanism did not change P2D-ready or admission decision; FAIR TTST diagnostic +1.452% in a prior fixture. No Batch Miss demonstrated. |
| Group urgency / EP collective urgency | Profile-derived bounds and two EP4-group experiments | Theory + FlowSim integrated | Heterogeneous-context optimistic bound 53.412µs = 0.3161% of target token interval; homogeneous upper bound ≤3.46% assumes equal-urgency synchronized groups. No serving-aware oracle run. |
| DCQCN / ECN | CC_MODE=1 packet-level tests in prior experiment folders | Packet network only | ECN/CNP/rate changes were observed; packet completion did not feed the serving scheduler. Therefore no TTFT/TBT causal claim. |
| New sparse-A2A minimal replay in this audit | BurstGPT window 148333, first 16 original requests, S16 EP64, 200G, 1µs bin, exact GateRouter surrogate vs same-source-byte “uniform” counterfactual; FlowSim | Network-only approximation | CCT geometry difference exists, but it exists in EP_ONLY, P2D adds essentially nothing, the counterfactual creates receiver concentration, and 48 layers are coalesced. Classified `SPARSE_A2A_MODEL_NOT_VALIDATED`, not a motivation PASS. |

## Simulator-validity labels used here

- **Integrated**: serving scheduler receives network-completion feedback for the
  represented flows and records the relevant serving event. It still does not
  automatically mean a client-wire TTFT callback is modeled.
- **Network-only**: event issue times are fixed independently of network
  completion; no serving feedback is claimed.
- **FlowSim**: event-driven fluid/max-min model. Its outstanding bytes are
  analytical fluid backlog, not packet-buffer occupancy, ECN, PFC, drops, or
  DCQCN.
- **ns-3**: packet-level evidence only for the exact packet replay/configuration
  that was run. A fixed-timestamp replay is not integrated TTFT/TBT.
- **Counterfactual/oracle**: an upper bound or mechanism isolation, not a
  deployable policy unless separately implemented and validated.

## Test record

The targeted FlowSim/P2D/capacity regression suite ran on the current tree:
31 tests passed in 0.017s. Exact command and scope are in
[`12_REPRODUCIBILITY_AND_HASHES.md`](12_REPRODUCIBILITY_AND_HASHES.md).

