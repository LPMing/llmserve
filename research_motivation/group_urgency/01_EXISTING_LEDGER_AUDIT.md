# Existing EP–EP / KV–KV ledger audit

Date: 2026-10-12. Scope: inspect and compact existing results only; no serving or network simulation was launched for this audit.

## EP–EP experiment reconstructed

The retained case is the 8-request full run: Qwen3-30B-A3B-Instruct-2507, input 128/output 32, two independent EP4 Decode groups on the existing two-Decode-server, one-ToR FlowSim topology. Each server has 8 GPU endpoints and two 200-Gbps NIC-facing rails; this run's routed flows use a common 200-Gbps directed ToR-facing resource. The rank map keeps the groups' GPU ranks separate while sharing the physical D0/D1 cut. The exact artifacts are `experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_full.json`, `two_ep4_groups_full_logical_to_physical.json`, `experiments/pd_kv_ep/configs/large_scale/flowsim/minimal_1p2d_ep16_single_tor_nvlink.txt`, and `experiments/pd_kv_ep/workloads/two_ep4_groups_full_8req.jsonl`.

The realized Decode collective is **ALLGATHER dispatch + REDUCESCATTER combine**, with BALANCED routing. It is a legal group collective, not strict GateRouter sparse A2A and not one collective per request. Each EP4 collective has four participants and twelve directed peer flows; the two groups have separate collective barriers.

The compact per-group ledger has 5,952 phase/group observations for the 8-request run: 1,488 dispatch and 1,488 combine collective observations for each group, i.e. 31 Decode ITLs × 48 layers × 2 phases. The retained raw FlowSim source contained 71,424 EP peer-flow records (12 per group-phase) plus 384 P2D records. All 2,976 paired group/phase rounds have identical release timestamps; dispatch and combine active intervals overlap in all 1,488 corresponding rounds. Each group therefore really did share the same directed links at the same time; this was not inferred from request count alone.

On a directed cross-server link, a group-4-request dispatch carries 17,408 B and combine carries 8,192 B. Both groups together present twice that cut work. The full-run CCTs are identical between A and B: dispatch 11.593 µs, combine 10.856 µs. The matched A-only control is 10.897 µs dispatch and 10.528 µs combine. The group-A delta per layer is therefore 0.696 + 0.328 = 1.024 µs, and over 48 layers equals 49.152 µs/token. In the smaller 2-request/group point, 0.696 + 0.164 = 0.860 µs/layer, or 41.280 µs/token.

All eight requests in the 4-request/group FULL run have exactly the same 31 recorded ITLs: 6.157552 ms. Both groups are affected in the FULL run, not only A. However, the matched isolated baseline was retained only for Group A; B-alone was not measured. Do not present B's isolated delta as measured. The pooled ITL distribution is deterministic here: P50/P95/P99 equal the mean and cannot establish a stochastic tail. TTFT is 44.873 ms in both the matched A-only and FULL runs. No SLO threshold was specified. No EP_FIRST result was saved for this EP–EP case.

The 4-request/group run's 49.152-µs token delta is exact across the 48 per-layer barriers. The effect is real in FlowSim and reaches TBT, but is only 0.80% of 6.108400 ms isolated TBT. The 2-request/group result is +0.75%. The residual-fluid queue peaks around 33.9 KiB; that is **analytical fluid backlog**, not packet buffer occupancy, ECN, PFC, or drops.

## EP flow, request and KV records

- [`01_EP_PER_GROUP.csv`](01_EP_PER_GROUP.csv) has one row per group/collective/phase, including phase type, bytes, shared-link overlap, barrier completion and the last peer. `sum_link_byte_hops_on_shared_directed_links` intentionally counts payload once per traversed shared directed link; it is not unique payload and must not be read as bytes on one link.
- [`01_EP_FLOW_LEDGER.csv`](01_EP_FLOW_LEDGER.csv) is the compact 71,424-row per-flow ledger derived from the transient raw flow file. It retains flow/request-set/collective/layer/src/dst/bytes/timestamps/path.
- [`01_EP_GROUP_REQUESTS.csv`](01_EP_GROUP_REQUESTS.csv) retains all 12 requests from the 2- and 4-request/group FULL runs. Group A has matched A-only ITLs; Group B's standalone control remains `NOT_MEASURED`.
- [`01_KV_PER_REQUEST.csv`](01_KV_PER_REQUEST.csv) and [`01_KV_LAYER_EVENTS.csv`](01_KV_LAYER_EVENTS.csv) retain request-level last-shard/readiness data and individual model-derived layer transfers from historical KV–KV and recent A7/B policy cases. The per-request handoff is `max(required KV finish)`, never the sum of shard FCTs.

The original 54-MiB flow JSONL was transient under `/tmp`; its SHA-256 and the compacted-output provenance are in [`00_PROVENANCE.md`](00_PROVENANCE.md). This report does not claim the raw file is a durable original artifact. The compact per-flow CSV is now durable in this research directory.

## KV–KV evidence relevant to urgency

In the 128-token victim + 2,048/8,192-token background cases, victim shard-FCT mean is +10.91% and nearest-rank shard P99 is +25.35% versus the victim-only control. But the victim's last required KV still completes at 41.957443 ms, 1.093557 ms before `p2d_ready` at 43.051 ms; TTFT/readiness are unchanged. The 2,048-token background has 1.418913 ms slack and the 8,192-token background 1.795913 ms. This is a shard distribution difference, not evidence that request-level KV urgency changed.

In the recent A7 candidate set, the retained FAIR candidates have 0.653791 ms slack for 2,048-token prompts and 0.793964 ms for 1,024-token prompts; all required KV completes before the prefill-completion readiness point. `TTFT` is 74.468 ms and 57.757 ms, respectively. The run records a second-visible-token delta (`TTST`) even though `output_tokens_field=1`; retain that raw timestamp delta only with the fixture caveat. It is not a robust ITL/TBT sample. No SLO was defined.

## Correctness and evidence status

**G0 ledger status: PASS WITH SCOPE LIMITS.** Physical routes, directed shared link, legal independent groups, collective multiplicity, request sets, and max-barrier timestamps can be reconstructed from the retained records. The collective realization is AG/RS, not exact sparse A2A. The old EP policy comparison is absent. Group B isolated control is absent. The 8-request raw source came from the dirty worktree and scratch path; the model/config/profile/source hashes are recorded in `00_PROVENANCE.md`. These limits prevent retroactively upgrading the historical results into a complete policy experiment.

No new simulation is justified by ledger auditing alone. The next gate is the profile-derived H1/H2 headroom calculation in `02_EP_THEORETICAL_HEADROOM.md` and `07_KV_REQUEST_THEORY.md`.
