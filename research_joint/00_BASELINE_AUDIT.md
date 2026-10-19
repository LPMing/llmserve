# Baseline, code-path and provenance audit

Audit date: 2026-10-12. Scope: the current dirty worktree and a short, controlled, integrated FlowSim experiment. **Overall simulator status remains `PARTIALLY_VALIDATED`; it is not a clean release or a blanket validation of all backends.**

## Source identity and preservation

| Item | Value |
|---|---|
| Repository / branch | `/home/dell/lpm/LLMServingSim`, `main` |
| Git HEAD | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| Worktree at mission start | Dirty; pre-existing tracked-diff SHA-256 `bffce36e4015d9fbcf484dc78ebed4c658f7365297a672230127331cba0986db` |
| State at this audit | Still dirty; all existing work was preserved. Current diff hash is captured in `15_FINAL_GO_NO_GO.md` after the artifacts are complete. |
| Python | `/home/lpm/.conda/envs/llmsim-flowsim/bin/python` (Python 3.10 environment) |
| Integrated FlowSim identity | `serving/core/flowsim_backend.py` + `flowsim_worker.py`; no independent package release/version string is exposed. Source hashes are below. |
| Current mission changes | Research-only first-Decode phase gate, scheduler wakeup deadline, focused regression additions, analysis script, isolated ep_b fixture and compact outputs. The phase feature defaults to zero/off. |

No reset, deletion, historical CSV overwrite, or old-result directory reuse was performed. The pre-existing `research_audit/`, `research_motivation/`, and experiment ledgers are retained.

## Relevant corrected semantics already present in the worktree

- The audited Chakra boundary converts profile nanoseconds to Chakra microseconds with rounding; older FlowSim timing outputs made before that correction are not timing evidence.
- Decode admission receives the actual P2D-ready time and enforces `max_num_seqs`; capacity wait is represented rather than fabricated as immediate admission.
- FlowSim completion feeds back through the integrated scheduler. A flow replay with fixed issue timestamps is not equivalent to this path.
- A request's first output token is produced in the Prefill graph (`lm_head`/sampler). `TTFT` therefore ends at Prefill completion; a later Decode-start phase gate cannot alter TTFT. The first Decode token interval is measured from that Prefill-produced token to the second visible token.
- Independent EP groups are separate group-wide barriers; a batched physical collective keeps the set of request IDs and is not split into imaginary per-request flows.
- The B fixture uses the simulator's actual ALLGATHER dispatch + REDUCESCATTER combine with BALANCED routing. It is **not** sparse GateRouter-derived exact A2A_P2P. The result cannot support a claim about exact sparse peer matrices.
- FlowSim models directed fluid links and event completion. It does not model packet queues, ECN/CNP, PFC, RDMA QP control, or packet loss.

## B fixture identity

| Input | SHA-256 |
|---|---|
| Qwen3-30B-A3B model subset | `0736f3bafb95cc658776c92ab34f5f98f8169634a3a36b84892d71448a1f19d3` |
| RTXPRO6000 BF16 Qwen profile `meta.yaml` | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| Full two-group EP4 cluster config | `2a91e26179b8e2bace307bde4f8a118d32f984531426e7b120173f679fb3c1fa` |
| Full fixture rank map | `d5c18ecd573480f2dc28e1c7f95e09a88f6f70e88197ea9ce3e9d0c9e3e62f54` |
| Single-ToR / local-fabric topology | `3fa000e6ff3b26fb77f00645a0ddac82f993ca0e831e4abd5cd208baa14995ca` |
| 8-request workload (`128 in, 32 out`, arrival 0) | `8e6280ae241494e412553dbf6f3dd57221d6a799bb38f1914e0338e09f6ad4f8` |
| B-only ep_b config | `cf733829fb66c7ab5d36bcca5cd2669e3978f0d65b361a42c968015f72c852ad` |
| B-only rank map | `74e68e4e7a504cce195245921a5edef449a3cc674df68f9f2f8c57ea2d59f4ec` |

The full fixture has four TP2 Prefill instances and four TP2 Decode instances arranged as two separate EP4 DP groups. Each EP4 group spans D0/D1; both groups share the same modeled D0↔ToR↔D1 directed links. The physical topology has 200-Gbps leaf/ToR links (25 GB/s per direction); endpoint access is represented by the topology's high-capacity GPU-to-leaf links, while the shared directed cut is the 200-Gbps bottleneck. This is a deterministic single-ToR characterization, not a production topology frequency claim.

The new ep_b-only config uses the same GPU endpoints, network, request shape and group placement as the full fixture, with only one group active. It is a matched isolation control, not added capacity.

## Focused correctness regression

All 11 `experiments/pd_kv_ep/scripts/test_*.py` focused scripts passed: **49 tests total**. This includes topology rank count, FlowSim collective scope, Decode completion and handoff wakeups, group queue ownership, rank mapping, ns-3 topology selection, Decode capacity/admission, actual receiver mapping, P/D pairing and trace time units. The B-only integrated request run also completed with four requests and all 31 Decode ITLs/request recorded.

This does not establish native ns-3 serving feedback, exact GateRouter A2A integration, or general arbitrary topology support. It does establish that the narrow exercised FlowSim case was runnable with a Decode phase eligibility deadline and did not suppress the scheduler wakeup.

## Current relevant source hashes

| Source | SHA-256 |
|---|---|
| `serving/core/flowsim_backend.py` | `89028c7c75d1eb8fa181647f3de82dc01fa55be4ff3f108e79676fa251fc35aa` |
| `serving/core/flowsim_worker.py` | `36435f5ac8f8e0a78b153f941f08816fde3683017cd7a39a9a3469c9afa77feb` |
| `serving/core/scheduler.py` (after phase-gate change) | `123e1e47ef3af49a35d9498cb1a88eadc0b513ceef6284f2fdf8b884c808f10a` |
| `serving/__main__.py` (after phase gate and wakeup deadline) | `93171b2a0f1486e554544a048dd93e13c32e9301271e081ae3afc07d7ad47ac9` |
| `experiments/pd_kv_ep/scripts/test_pd_decode_capacity_admission.py` | `f4bd3be55b75342fae23e0b781c5a753aaf427a9bbdb4b9f3a3f9c58f6ac9820` |

The repository HEAD plus dirty-worktree hash, all compact request-output hashes, scratch telemetry hashes, and B run IDs/wall times are recorded in [`PROVENANCE.md`](PROVENANCE.md). The phase hook code is uncommitted. Because the whole worktree is dirty and historical runs are not all bound to immutable source commits, these results are a reproducible local characterization, not immutable paper-grade provenance.
