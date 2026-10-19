# 00 — Source and artifact provenance

## Decision context

This is a source/profile/routing audit, not a new Serving or network performance
run. The attached mission prohibits performance experiments until the router,
profile, physical mapping, and sparse-A2A DAG inputs pass their gates.

## Repository state

| Item | Value |
|---|---|
| Repository | `/home/dell/lpm/LLMServingSim` |
| HEAD | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| Branch | `main` (captured by `audit_inputs.py`; see snapshot) |
| Tracked worktree diff SHA-256 | `089f3d35d5740b889d4906da48d4ccbf88b1b8ba5d5a048ec16f52806584cfa9` |
| Worktree | Dirty before this audit; many pre-existing tracked and untracked changes. They were preserved. The diff digest excludes untracked content. |
| Reproducible historical source binding | **NOT_AVAILABLE** — retained runs do not consistently bind the exact source tree, config, workload, backend, command, and output hash. |

The machine-readable inventory is [`audit_snapshot.json`](audit_snapshot.json),
reproduced by [`audit_inputs.py`](audit_inputs.py). The snapshot is an audit
artifact, not a claim that every historical run used the present worktree.

## Audited artifact hashes

| Artifact | SHA-256 |
|---|---|
| Qwen3 model config `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json` | `0736f3bafb95cc658776c92ab34f5f98f8169634a3a36b84892d71448a1f19d3` |
| RTXPRO6000 Qwen3 `bf16/meta.yaml` | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| RTXPRO6000 Qwen3 `bf16/tp1/moe.csv` | `aa6e29a17412a62234a6610d7a699f72e5938f09386374b635925c5db29045f6` |
| `serving/core/gate_function.py` (after RR/RAND provenance fix) | `dc045da318b7017bf5279dd298d6569086a73c2c93efa2fd130469317f4fa491` |
| `serving/core/trace_generator.py` | `65e54faf30dbc51638aa5f7a0c3b554fe8248060a74576f7dbdb70dc95923aa5` |
| `serving/core/graph_generator.py` | `7ea96c919d9b6198e69a9bf27a12004cd6074711b1556e0233c4de30fcfcac23` |
| Checked-out Chakra `llm_converter.py` | `e65d863eac39da5ffa2c76cf8300a8b3b54b2e5ddd8b270421d805329ccfb76f` |

The S16 cluster/topology hashes and the full source status are in the snapshot.
The topology/config pair is internally inconsistent for a direct rank-to-GPU
interpretation; see [`03_PHYSICAL_MAPPING.md`](03_PHYSICAL_MAPPING.md). It is
therefore not treated as an authoritative sparse-MoE testbed.

## Routing provenance repair

`GateRouter.route_ep()` previously passed token index `0` to its routing function
for every token in the non-BALANCED path. Consequently RR repeated one token's
expert choices; a token-index-aware CUSTOM function would also receive incorrect
input. It now passes a stable rank-concatenated batch token ordinal and validates
that each result contains exactly `top_k` distinct in-range expert IDs. Optional
`capture_routes=True` records simulator-policy provenance, source/destination
owner counts, and a pair matrix for RR/RAND. BALANCED remains aggregate-only and
is explicitly labeled `BALANCED_ANALYTIC_APPROXIMATION`.

This repairs simulator-policy bookkeeping; it does **not** add learned Qwen
router outputs. RR is still synthetic, RAND is seeded synthetic routing, and
BALANCED is an analytic approximation. Existing retained route sidecars all
say `routing_policy=BALANCED`, so the RR bug does not invalidate those sidecars
as RR measurements—they were never RR. It does mean any unprovenanced historical
RR/CUSTOM output must not be reused as exact routing evidence.

## Checks run

Using `/home/lpm/.conda/envs/llmsim-flowsim/bin/python`:

- `research_sparse_foundation/test_gate_router_provenance.py`: **3/3 PASS**.
- `experiments/pd_kv_ep/scripts/test_flowsim_collective_scope.py`: **4/4 PASS**.
- `experiments/pd_kv_ep/scripts/test_pd_decode_capacity_admission.py`: **7/7 PASS**.
- `research_sparse_foundation/theory_reference.py`: **4 abstract invariant cases PASS**; these are not model or performance evidence.
- `nvidia-smi -L`: driver unavailable; RTXPRO6000 MoE profile calibration could not be run here.

Exact rerun commands are listed in [`08_THEORY_GO_NO_GO.md`](08_THEORY_GO_NO_GO.md).

## Baseline status

`PARTIALLY_VALIDATED`. RR/RAND route indexing has a regression test. The
retained profile is real GPU measurement over its stated grid. However, learned
Qwen routing, EP64 profile-domain coverage, the S16 rank map, and end-to-end
sparse-A2A graph integration remain unvalidated. Therefore no new FlowSim or
packet-level performance result is reported in this audit.
