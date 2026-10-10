# S8 Artifact Recovery Audit

## Outcome

**`ARTIFACT_RECOVERY_FAIL` for the original S8 event stream.** No complete original schedule plus 171,507-row communication ledger was found. A new baseline was subsequently generated from a legal integrated serving execution and replayed; it must not be described as an exact recreation of historical Azure16.

## Inventory

| Artifact | Expected path | Exists now? | Recoverable from Git? | What remains | Exact replay sufficient? |
|---|---|---:|---:|---|---:|
| Original request schedule | `experiments/pd_kv_ep/results/shared_nic_4p4d_ep32_azure16/flowsim_fair_ledger/requests.csv` | No | No path history found | Only manifests/reports cite it | No |
| Original FlowSim event ledger | `astra-sim/inputs/runs/shared-nic-4p4d-ep32-azure16-flowsim-fair-ledger/flowsim/flow_telemetry.jsonl` | No | No path history found | Aggregate event counts/bytes only | No |
| Original packet replay input | `.../ns3_issue_events/events.csv` (also referenced as `flow.txt`) | No | No | `replay_manifest.json`, `network_run_manifest.json`, `replay.conf` | No |
| Original packet output | `.../ns3_cc1_fair/flow.txt`, `comm_events.csv`, `fct.txt`, queue/link outputs | No | No | `network_run_manifest.json`, `replay.conf` | No |
| Original per-QP CC telemetry | `.../ns3_cc1_fair/cc_events.csv` | No | No | Historical aggregate summary only | No class/QP attribution |
| Historical aggregate summary | `.../ns3_cc1_analysis/dcqcn_policy_summary.json` | Yes | N/A | ECN/CNP/RATE and aggregate queue/latency metrics | Historical reference only |
| Similar strings / metadata | `experiments/`, `results/`, `log/`, `logout.dat` | Yes | N/A | Historical reports, manifests, config | No event reconstruction |
| Main-repository Git history | S8 result paths | No matching commit | `git log --all -- <S8 result path>` returned no commit; `git fsck --full --no-reflogs --unreachable` returned no recoverable objects | None | No |
| ASTRA-Sim submodule Git history | Original run input path | No matching commit/object | Path history and unreachable-object audit returned no recovery | None | No |
| `/tmp` candidate | `/tmp/llmservingsim_minimal_z0327199/inputs/flowsim/` | Yes, unrelated | N/A | 2×12 ranks, 50-Gbps FlowSim inputs; not S8 and not the historical ledger | No |

The S8 packet directories currently contain only manifests/configuration. Earlier reports state that detailed files were produced at the time, but those references do not make the files recoverable now. The aggregate CNP total cannot be used to infer CNP recipients or reconstruct per-flow events.

## Historical identity retained for comparison

The archived S8 manifest records 16 requests, EP32, 1,536 P2D events / 4,904,386,560 KV bytes, 169,971 EP events / 696,201,216 EP bytes, 4,096-byte packet payload, and the 200-Gbps S8 shared-NIC Clos topology. Historical FAIR/`CC_MODE=1` aggregate values are recorded in [S8_NATURAL_ECN_BASELINE_AUDIT.md](S8_NATURAL_ECN_BASELINE_AUDIT.md). These are not new-run results.

## Regenerated candidate and next action

A new D8+K2 candidate is preserved at `results/natural_ecn_baseline_v1/attempts/s8_d8_k2_i8192_do64_gap5ms/`. Its K arrival was derived from the D-only serving warmup; its complete model-derived flow ledger was replayed with the corrected S8 topology and unchanged 200-Gbps/ECN/DCQCN settings. The exact class attribution found 5,134 CNPs and 2,420 rate decreases on KV QPs, and zero CNP/rate-decrease events on EP QPs. See [NATURAL_ECN_REPRODUCTION_RESEARCH.md](NATURAL_ECN_REPRODUCTION_RESEARCH.md) and the immutable [baseline manifest](results/natural_ecn_baseline_v1/BASELINE_MANIFEST.json).

The new candidate passes the natural-congestion/packet-replay gate but fails the prerequisite for the persistent-**EP**-QP branch. Per the protocol, do not run fresh/persistent EP-QP comparisons or escalate the load to seek an EP CNP. The historical artifact recovery status remains a failure; the new D8+K2 result is a separately labeled regenerated baseline, not a recovered historical run.
