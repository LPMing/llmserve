# Provenance and reproducibility snapshot

- Repository: `/home/dell/lpm/LLMServingSim`, origin `https://github.com/LPMing/llmserve.git`.
- HEAD at audit: `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` (`main`).
- Worktree was already extensively dirty before this motivation run. No existing modifications were reset or overwritten. The task-specific scripts/docs and current scheduler/network changes share a dirty working tree; therefore the whole current diff must not be attributed solely to this run.
- Python: `/home/lpm/.conda/envs/llmsim-flowsim/bin/python`, Python3.10.21. `python` on this host resolves to an incompatible legacy interpreter; use the conda path.
- Runtime: full serving-integrated FlowSim; network model is directed fluid max-min sharing, not packet simulation.
- Model config SHA-256: `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3`.
- Profile `dense.csv` SHA-256: `90c13de3060552a314ed4819dcdbf82f843e292332054765abe8a0472d91ca96`.
- 200G topology SHA-256: `3fa000e6ff3b26fb77f00645a0ddac82f993ca0e831e4abd5cd208baa14995ca`.
- 200G minimal config SHA-256: `b0669a2dec3cbd3285156a84e6b5fd63801479596c14e3557a58bfed8234df2e`.
- Rank map SHA-256: `1bc7c61dfc1f871969b1d05be76878df4be298151eba9bfb0fc96612fef18b9a`.
- Commands and workloads: `RUN_COMMANDS.md`; request plans and model sizes: this directory's generator/configs/JSONL.
- Compact exported results: root `06_EXPERIMENT_RESULTS.csv`, candidate-level SLO rows and event/flow/link ledgers in `results/`.
- Full transient outputs for E1/E2/E3/E4 lived under `/tmp/bm_*`; selected full scheduler/graph event streams were copied into `results/`.
- Phase scan: not run, with prerequisite reason in `PHASE_SCAN_STATUS.md`.
- Graph debug capture for the 400G and E4 runs did not retain the candidate's first Decode graph-submit/completion events. Their scheduler decision times and request-level serving metrics are present; unavailable graph timestamps are left blank in the exported CSV rather than inferred from scheduler timestamps.
- Regression status: 36 focused tests passed across topology/rank mapping, FlowSim collective scope and wakeups, queue ownership, NS-3 topology selection, Decode capacity admission, P/D pairing, and trace time units. Python 3.10 `py_compile` and `git diff --check` passed.
- Tracked dirty-diff SHA-256 excluding this self-referential provenance file: `a6c0c46698d4dd1900fa020d31e48d17cedb17d19e242a809631d2b21e22831c`. It excludes all untracked artifacts; artifact hashes and run commands are listed separately. The result exporter SHA-256 is `f89364ebf271c5ea8485519346808dab06e98497d882820b7e268387d0c5eb11`; root summary CSV SHA-256 is `06138a585799c02b637eddb63899f758c5b0b96d46cef6bae18c70898c0a1d13`; candidate CSV SHA-256 is `3a0697596bbd8e442fbc335431a5129148ee6e9385d71feb23055661b5569e7c`.
