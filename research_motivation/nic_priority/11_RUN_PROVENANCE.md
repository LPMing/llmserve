# Run and artifact provenance

## Source state

- Repository: `/home/dell/lpm/LLMServingSim`
- Branch / HEAD: `main` / `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`
- Tracked worktree diff SHA-256: `a6c0c46698d4dd1900fa020d31e48d17cedb17d19e242a809631d2b21e22831c`
- The repository was already dirty before this motivation campaign. Its code
  modifications were preserved; no unrelated changes were reverted.
- Runtime: `/home/lpm/.conda/envs/llmsim-flowsim/bin/python`; Python 3.10.21.
- Environment used: `PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs`
  and `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`.
- Focused validation: 10 regression scripts, 36/36 assertions passed;
  byte-compilation and `git diff --check` passed. This is not the full
  repository test suite.

## Immutable input hashes

| Input | SHA-256 |
|---|---|
| Physical topology | `2e1ce6854d46164ec5b4dfdd5d0c4fec6f8ebba4572f6963f9a85331540b79fe` |
| B physical rank map | `3f5dc4f024912938012b0e97baaa406b5e0e0cd53cb3938d975e9f0bcdffc9e1` |
| Cluster config | `e3230f919db0de24f415e913f6220411c89376f247bd20218cc342b8cd8e5a04` |
| A8 workload | `794992ee36482be55dd68c6285f9d1b783274bba299e02ca6cbdc491c6a1955f` |
| A7L2M workload | `98ca59f75bb02cc23d7cfafec9fd9df3c08f8ac72304380721ab8d875b26c8cb` |
| B both-rails workload | `985b2df353134d334a7ec0c5f8811c134e2552d129f38284f6e811989a871722` |

Model/profile fingerprints:

| Input | SHA-256 |
|---|---|
| Qwen3 model config | `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3` |
| RTXPRO6000 BF16 profile metadata | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| TP1 dense profile | `90c13de3060552a314ed4819dcdbf82f843e292332054765abe8a0472d91ca96` |
| TP1 per-sequence profile | `6221393b77135bdaa41e7abe9993a528b49ceb34f2475423c5236f970c711bcc` |
| TP1 attention profile | `eea3376edc5329da5ceb9220a138895bf94ab063116a22919228f68a2d6015cc` |
| TP1 MoE profile | `aa6e29a17412a62234a6610d7a699f72e5938f09386374b635925c5db29045f6` |
| TP1 skew fit profile | `75ae7ef729152df4c1ed6f9ea4ca858949c789ad68f2de43531a9852cb91e950` |

The workload manifests also record model, profile, logical/physical sizes,
rank mapping, request mix and arrival time.

## Reproduction command shape

The run-specific shell command strings were not persisted beside every
output directory. The following is the exact CLI shape reconstructed from
the current entry point; substitute each listed policy and fixture, and use
the same environment above:

```bash
python -m serving \
  --cluster-config research_motivation/nic_priority/generated/cluster_4p2d_ep4.json \
  --dataset research_motivation/nic_priority/generated/B_both_rails.jsonl \
  --network-backend flowsim \
  --flowsim-policy FAIR \
  --flowsim-telemetry research_motivation/nic_priority/results/B_both_rails_fair/telemetry.jsonl \
  --output research_motivation/nic_priority/results/B_both_rails_fair/requests.csv \
  --log-level WARNING
```

For the recorded runs, `FLOWSIM_FLOW_TELEMETRY=0` and
`FLOWSIM_EP_FLOW_TELEMETRY=0`; KV event and collective-level telemetry were
retained, and link telemetry was limited to the selected D0 directed link(s)
and bounded observation window/row count. The A runs use `A8_neighbor.jsonl`
or `A7L2M_primary.jsonl`, with `FAIR` or `EP_ISOLATED`. B uses the same
`B_both_rails.jsonl` and policies `FAIR`, `EP_FIRST`, `KV_FIRST`, and
`EP_ISOLATED`.

**Reproducibility limitation:** because the original CLI transcripts were
not serialized with the result folders, the exact run IDs and all telemetry
row/window environment values cannot be proven from the output artifacts
alone. The input hashes and reported policy/output paths are verified; this
run-metadata omission should be fixed for future campaigns before calling
them fully release-reproducible.

## Outputs

Each run directory stores `requests.csv`, `kv_event_telemetry.jsonl`,
`collective_telemetry.jsonl`, a bounded `link_telemetry.jsonl`, and a brief
`link.csv`. The latter explicitly labels `queue_bytes` as residual fluid,
not a packet queue. Results are under `results/A8_*`, `results/A7L2M_*`, and
`results/B_both_rails_*`.

## Historical Direction-A evidence kept separate from this campaign

`02_DIRECTION_A_PRIOR_CASES.csv` is a supplementary evidence index, not an
assertion that these cases were rerun under the current campaign's exact
dirty worktree/configuration. For the 32+128-token KV–KV case, the original
command, input, and raw flow/request ledgers are documented in
`research_audit/01_REPRODUCIBILITY.md`. For the 128-token victim paired with
2048- and 8192-token backgrounds, the archived raw `flows.jsonl` and
`requests.csv` were re-read to recompute the victim's 96 shard FCTs and verify
unchanged request ready/TTFT; these are historical controlled runs. EP–EP
results are summarized in `research_audit/12_EP_EP_GROUP_VALIDATION.md`; the
config/workload hashes and rerun recipe are retained, but the large raw
telemetry was written to `/tmp` and is not archived. The earlier small
integrated KV–EP and ns-3 packet-only rows are transcribed from
`research_audit/02_MOTIVATION_RESULTS.csv` and its reproducibility audit; the
ns-3 row has no serving completion feedback. Keep these evidence classes
separate when reproducing or citing the new A7/A8/B matrix.
