# Run and artifact provenance

Audit date: 2026-10-12. All paths are relative to the repository root unless absolute.

## Source identity

- Git HEAD: `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` (`main`).
- Tracked `git diff --binary | sha256sum` at final artifact QA: `0f31dfcc88b2ca027a93275f03d14587f10cb10e9c3b8dd9a2abb09c7866f1d9`.
- Worktree is dirty (56 `git status --short` entries); it was already dirty before this mission. Initial tracked-diff SHA: `bffce36e4015d9fbcf484dc78ebed4c658f7365297a672230127331cba0986db`.
- Interpreter: Python 3.10.21, `/home/lpm/.conda/envs/llmsim-flowsim/bin/python`.
- No FlowSim package version is surfaced; relevant backend source hashes are in `00_BASELINE_AUDIT.md`.

## Inputs and source hashes

| Artifact | SHA-256 |
|---|---|
| model subset `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json` | `0736f3bafb95cc658776c92ab34f5f98f8169634a3a36b84892d71448a1f19d3` |
| RTXPRO6000 BF16 profile `.../bf16/meta.yaml` | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| full config `two_ep4_groups_full.json` | `2a91e26179b8e2bace307bde4f8a118d32f984531426e7b120173f679fb3c1fa` |
| full rank map | `d5c18ecd573480f2dc28e1c7f95e09a88f6f70e88197ea9ce3e9d0c9e3e62f54` |
| topology `minimal_1p2d_ep16_single_tor_nvlink.txt` | `3fa000e6ff3b26fb77f00645a0ddac82f993ca0e831e4abd5cd208baa14995ca` |
| 8-request workload | `8e6280ae241494e412553dbf6f3dd57221d6a799bb38f1914e0338e09f6ad4f8` |
| B-only config | `cf733829fb66c7ab5d36bcca5cd2669e3978f0d65b361a42c968015f72c852ad` |
| B-only rank map | `74e68e4e7a504cce195245921a5edef449a3cc674df68f9f2f8c57ea2d59f4ec` |
| analyzer `scripts/analyze_b_phase_runs.py` | `1df48618153551ae6474dc56ea0927e8d9d72c040f6d433d20e8504b36f23ef9` |

The B-only control workload `experiments/pd_kv_ep/workloads/two_ep4_groups_a_only_4req.jsonl` (input128/output32, arrival0) has SHA-256 `336f0fea76be5b8839439f1906a170cbf49176aabb95e21ad7b350b64a92122e`.

## B run records

| Condition | Run ID | Request output / SHA-256 | Telemetry path / SHA-256 | Simulated makespan | Wall runtime |
|---|---|---|---|---:|---:|
| B0 ep_a only, 4 requests/group | `research_joint_ep4_a_only_20261012` | `outputs/b_ep4_a_only_requests.csv` / `ad0ee5696b839e1725b69a11263aa8c0f5f40603fc8cc70f460077133436e32b` | `/tmp/research_joint_ep4_a_only_telemetry.jsonl` / `ec44861a0d8170c1a97db6326350e1d4a3f8a26686e5c004f1ce0d852c42ad67` | 234.233400 ms | 31.379 s |
| B1 ep_b only, 4 requests/group | `research_joint_ep4_b_only_20261012` | `outputs/b_ep4_b_only_requests.csv` / `ad0ee5696b839e1725b69a11263aa8c0f5f40603fc8cc70f460077133436e32b` | `/tmp/research_joint_ep4_b_only_telemetry.jsonl` / `d1763db052b184800a919bafda100cc989ddf31856f267ec1505abaf6d0c1d14` | 234.233400 ms | 31.439 s |
| B2 two groups synchronized, FAIR | `research_joint_ep4_sync_20261012` | `outputs/b_ep4_sync_requests.csv` / `aedb6d9b9f66b7849a10731e1c3fa4666cb1f29dd5ddfa6ace33cdfdac070df9` | `/tmp/research_joint_ep4_sync_telemetry.jsonl` / `a985716008c5cd5ce1a7e8aaea0c80c15f565f8f85bcf30f44c5e97bb760ea79` | 235.757112 ms | 61.761 s |
| B3 two groups, one-time ep_b phase +20µs, FAIR | `research_joint_ep4_phase20us_fixed_20261012` | `outputs/b_ep4_phase20us_requests.csv` / `1e7d22fc6175518b0400ea7bdc5cc4dd1641f52977dcc8a3e004c56cfce1a783` | `/tmp/research_joint_ep4_phase20us_fixed_telemetry.jsonl` / `c9e8d803f81c6ee0dcc94d0b06d48b14f218f4979cbd4c2c2f1056118e9901aa` | 234.253400 ms | 56.914 s |
| Invalid diagnostic; **exclude from all result tables** | `research_joint_ep4_phase20us_20261012` | superseded/overwritten by valid B3 request CSV | `/tmp/research_joint_ep4_phase20us_telemetry.jsonl` / `f64b7a2d83c4421adad7eab8fa5d24a142ded5379e32a39293b7463e1e8c57a8` | invalid retry timing | 56-MiB scratch |

The exact transient ASTRA input directories were cleaned by the simulator after successful runs. The command line above in `README.md` is the canonical replay recipe; the shell command itself was not separately archived at launch time. Effective arguments are independently reflected in request CSVs, console output, setup files, telemetry and run IDs. `--pd-kv-transfer-mode` defaulted to `LAYERWISE` on the observed run; the canonical recipe names it explicitly.

## Analysis and checksums

- `outputs/b_ep4_phase20us_requests.csv` is the valid post-wakeup-fix B3 run. The first run without passing the scheduler eligibility as a worker deadline was not used; it held the retry until an unrelated event and introduced ~6.1 ms extra first-interval delay. The fix is in `serving/__main__.py` plus `scheduler.next_scheduler_wakeup_time()` and is covered by `test_pd_decode_capacity_admission.py`.
- `06_B_PHASE_EXPERIMENTS.csv` SHA-256: `f1198a68ab23e0007302bec00b6868605853eefb7d5b4f6a8fdf6e5170c95667`.
- `outputs/b_ep4_a_only_requests.csv` SHA-256 is the same as the B-only output because the two isolated groups are symmetric under this model/profile and placement: `ad0ee5696b839e1725b69a11263aa8c0f5f40603fc8cc70f460077133436e32b`.
- Final analyzer source hash: `research_joint/scripts/analyze_b_phase_runs.py` `1df48618153551ae6474dc56ea0927e8d9d72c040f6d433d20e8504b36f23ef9`.
- All 11 focused scripts: 49/49 tests passed. Both B-only JSON files parse; every CSV under `research_joint/` and `research_joint/outputs/` parsed with Python's CSV reader; `git diff --check` passed.
- Raw scratch telemetry is retained in `/tmp`, not copied into Git, including `/tmp/research_joint_ep4_a_only_telemetry.jsonl`. It is compacted by the analysis script into group/run rows with per-group bytes, per-group mean collective CCT, request mean/max ITL, and common-path interval overlap counts.
