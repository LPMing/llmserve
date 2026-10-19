# 01 — Reproducibility and provenance ledger

## Audited source identity

| Field | Value |
|---|---|
| Repository | `/home/dell/lpm/LLMServingSim` |
| Remote | `origin https://github.com/LPMing/llmserve.git` |
| Branch | `main` |
| HEAD | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| `origin/main` local ref | Same SHA as HEAD at audit time |
| `git describe --tags --always` | `v1.1.0-123-g0c0839a` |
| Latest local release tag | `v1.1.0` |
| README branding | LLMServingSim 2.0 |
| Submodules | None represented as Git gitlinks; simulator/network sources are vendored in the monorepo |
| Existing worktree modifications before this audit | Clean at the start of this audit session |
| Current worktree | Contains the fixes in `01_CODE_FIXES.md`; not committed |

Remote network access was unavailable during this audit, so no remote fetch or
current remote HEAD check was performed. The statement about `origin/main` is
only about the local ref.

## Runtime environment

| Component | Value / limitation |
|---|---|
| Python used | Conda `/home/lpm/.conda/envs/llmsim-flowsim/bin/python`, Python 3.10.21 |
| protobuf | 7.35.1 |
| rich | 15.0.0 |
| Chakra Python package | Not installed in that environment |
| Chakra source | Vendored at `astra-sim/extern/graph_frontend/chakra` |
| Import workaround | Temporary `/tmp/llmsim-chakra-shim.TzDOXs` symlinks to vendored Chakra modules plus `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` |
| Analytical backend binary | `astra-sim/build/astra_analytical/build/bin/AstraSim_Analytical_Congestion_Unaware` |
| Binary SHA-256 | `21d9cea84ab3f560becf89a9cf3884a00127fc7207e29df4f9dc76af2e709090` |
| Native ns-3 binary | Not invoked for the minimal run in this ledger |

The import workaround is environment-specific and temporary. It is not a
dependency installation or a portable project setup. Reproduction should
install the repository's intended Chakra dependency/version or recreate an
equivalent import path and protobuf compatibility setting.

## Reproduced serving smoke

Exact command:

```bash
PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --cluster-config experiments/pd_kv_ep/configs/small_pd_tp2_to_decode_tp2.json \
  --dataset experiments/pd_kv_ep/workloads/moe_i8_o1_n1.jsonl \
  --num-reqs 1 \
  --output research_audit/results/current_head_pd_ep2_smoke_final.csv \
  --run-id audit-pd-ep2-smoke-final-20261011 \
  --inputs-root /tmp/llmsim-audit-pd-ep2-smoke-final-20261011 \
  --log-level WARNING
```

This is an ASTRA analytical, one-request execution check. It completed in
0.482 s reported simulator wall time and emitted TTFT 16.766583 ms. The request
has one output token, so TPOT has no post-first-token sample and is recorded as
0; that value must not be used as a performance result. The emitted CSV is
[`results/current_head_pd_ep2_smoke_final.csv`](results/current_head_pd_ep2_smoke_final.csv).

Input/output provenance hashes:

| Artifact | SHA-256 |
|---|---|
| Config `small_pd_tp2_to_decode_tp2.json` | `3e12c7577d14cd511430308cd8eba6a79335a5b9402f66f3817c3d6f1d3b9595` |
| Workload `moe_i8_o1_n1.jsonl` | `782a87d7e73ee415eaa015ba524978a3607578cce82d78cb7554bbbfb404b1df` |
| Request output CSV | `95019922bc4480927b09b04bcf30562b3130fd39e2222eff5cce7394072db363` |
| Analytical binary | `21d9cea84ab3f560becf89a9cf3884a00127fc7207e29df4f9dc76af2e709090` |

The run generated six Chakra ET rank files under the `/tmp` input root. ET
inspection showed P2D sends 0→2 and 1→3, while the actual Decode instance
occupies ranks 4 and 5. Those ET files are temporary and were not copied into
the repository; the compact summary and output CSV are retained. This is
reproducible as an execution smoke, not as a validated P2D-to-real-Decode
network experiment.

## P/D role-axis / EP16 analytical smoke

Command:

```bash
timeout 180s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --cluster-config experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_shared_400g.json \
  --dataset experiments/pd_kv_ep/workloads/moe_i8_o1_n1.jsonl \
  --num-reqs 1 \
  --output research_audit/results/current_head_ep16_role_axis_smoke.csv \
  --run-id audit-ep16-role-axis-smoke-20261011 \
  --inputs-root /tmp/llmsim-audit-ep16-role-axis-smoke-20261011 \
  --log-level WARNING
```

Result: exit code 0; wall time 1.274 s; simulated clock 29,656,122 ns; one
request reached Decode instance 8; `p2d_kv_ready_time_ns` and
`decode_admit_time_ns` were both 22,628,004 ns; TTFT 22.628 ms. The Decode
DP-group graph had one ET file for each rank 16–31 and ASTRA exited normally.
Output length 1 has no valid post-first-token TPOT sample. Network config was
analytical `FullyConnected` with three dimensions and 50 GB/s per dimension;
the explicit six-200-Gbps-NIC ns-3 topology was not loaded. This verifies the
role-axis/control collective smoke only, not P2D physical destination or
shared-fabric contention.

Output SHA-256:

```text
ae0d325ae8105b4938a69461e15a966ce4f45583bf14a5f1af0bea66c26716db  current_head_ep16_role_axis_smoke.csv
```

## Historical experiment binding

The historical report `KV_EP_SYSTEM_AUDIT.md` identifies source SHA
`a4053bc1161872420e1e0607cb3409ef659b828e`. `git cat-file -t` cannot resolve
that object in the current repository. Historical documents also claim the
current serving path uses actual Decode receivers and integrated FlowSim,
contradicting current `graph_generator.py` and `serving/__main__.py`.

Therefore prior results are not joined to this run. They are labeled
`UNVERIFIED_HISTORICAL` until a matching source snapshot or complete source
patch, configuration, workload, backend binary/build provenance, exact command,
and output artifact are available.

## Saved 1P2D / EP16 shared-NIC fixture check

The following read-only validation was run with the Python environment above:

```text
load minimal_1p2d_ep16_shared_400g.json
resolve Decode DP groups with _resolve_dp_groups()
evaluate _compute_network_dims() and _validate_network_rank_count()
```

Observed values:

```text
physical GPU ranks: 24
legacy frontend ranks including Prefill shadows: 32
inferred dimensions after the worktree P/D role-axis fix: [2, 8, 2], product 32
Decode DP-group size: 8
resolved EP total/local: 16/2
resolved Decode EP scope: [true, true, false]
rank-count gate: passes logical rank cardinality (32 == 32)
```

This check did not launch ASTRA-Sim, FlowSim, or ns-3 and did not modify the
generated topology. The generator's 200-Gbps NIC-to-ToR edges and 7.2-Tbps
GPU-to-NIC attachments remain only a topology description; the serving path
does not consume its `rank_to_nic.csv` or `pd_pairing.json` mappings. Logical
rank cardinality passing is not physical endpoint or collective-runtime
validation.

| Artifact | SHA-256 |
|---|---|
| `minimal_1p2d_ep16_shared_400g.json` | `655b9023209420630c99d93c41512ad2d03f6409d71a018df3d41d6f1488071c` |
| `minimal_1p2d_ep16_manifest.json` | `a0b2d254b9279ad6b01622a28fcfd0e72469f2915f46d34e091dbeb9727afa0c` |
| `minimal_1p2d_ep16_rank_to_nic.csv` | `c29dacafb35003cc4dc9da1f63e59d1110120908146a86fc3d31765c921c0e7a` |
| `minimal_1p2d_ep16_pairing.json` | `d1dafb7572f236a79da701286a5ee7f91e1c7e1c73aba7d0d584c14613bdd8b6` |
| `minimal_1p2d_ep16_2x200g_single_tor.txt` | `cdc372524e0661da4e693099238539dcb4b1d2e245c3dfeb4660ef4d96e9b6e6` |
| `generate_minimal_1p2d.py` | `4b427785cce070b385dd60fc44a8455ead7d869fb11e45806d686ad057d47569` |

The configuration, manifest, and pairing map are **not** evidence of a
completed physical-topology simulation. The analytical smoke above does not
consume the 24-GPU/6-NIC topology; its physical rank mapping and P/D pairing
remain `NOT_RUN`.

## Current evidence identity and status

The current source modifications plus the compact request CSV create a local
audit record, but the modified code has not been committed. Do not cite the
results as an immutable release. Before paper use, commit the baseline fixes,
record that new SHA, record compiler/dependency versions and binary build
inputs, preserve the compact ET/event provenance needed for the claim, and
rerun the correctness gate from that SHA.

**Reproducibility gate: PARTIAL.** The analytical smoke is reproducible; the
historical claims and target integrated data path are not yet reproducible on
the checked-out source.

The role-axis worktree is uncommitted. Relevant source hashes at this point:

| Source | SHA-256 |
|---|---|
| `serving/core/config_builder.py` | `005309235be5a4be063003f05034ba07e8b6cda61aeb9cb13765474179ea4846` |
| `serving/__main__.py` | `eb1a789584a8e1106a2f71c41bd4b4bffe9307ea172a040fc43ed8e2471fbc53` |
| `serving/core/scheduler.py` | `85fc07b2aa42409bf85fd4b653f59008314ca2126246fb13bf3d14dc808cf921` |
| `serving/core/router.py` | `502d4dcab2834faa94a4a84b549466762994f23bdf338c2961291a8355c7a3be` |
| `serving/core/request.py` | `ba4a582d05e47f13863b4c0cc8fcba1d82327b9c72f2ceedc10840d0e4a0cbd3` |

The tracked `git diff --binary` SHA-256 was
`1072d62b5da6705e1a058f70dd38042f001b093b40eaf7c8b7f8aa83bffc9f4f`.
Commit and rerun from the immutable SHA before treating this as final evidence.

## Recovery run — FlowSim integrated smoke (2026-10-11)

This new uncommitted-worktree run follows explicit local-fabric topology
generation. It supersedes earlier FlowSim execution smokes for entrypoint and
path correctness, but remains a one-request check.

Exact command, run from repository root:

```bash
timeout 180s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --network-backend flowsim \
  --cluster-config experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json \
  --dataset experiments/pd_kv_ep/workloads/moe_i1_o3_n1.jsonl \
  --num-reqs 1 \
  --output research_audit/results/current_baseline_flowsim_ep16_i1_o3.csv \
  --run-id baseline-flowsim-ep16-i1-o3-20261011 \
  --inputs-root /tmp/llmsim-baseline-flowsim-ep16-i1-o3-20261011 \
  --flowsim-policy FAIR \
  --log-interval 100 --log-level WARNING
```

Result: exit 0; reported runner time 13.066 s; simulated request end
7,307,044,176 ns. The request has TTFT 4,042,694,000 ns, TPOT 1,632,175,088
ns, and two ITL values of 1,632,175,088 ns. This is one request, not a tail
statistic or SLO distribution. Output:
[`results/current_baseline_flowsim_ep16_i1_o3.csv`](results/current_baseline_flowsim_ep16_i1_o3.csv).

The corresponding flow ledger is retained compressed at
[`results/current_head_flowsim_ep16_local_nvlink_corrected_telemetry.jsonl.gz`](results/current_head_flowsim_ep16_local_nvlink_corrected_telemetry.jsonl.gz)
(46,176 flow rows; 564 KiB compressed):

| Class | Events | Total event bytes | Path check |
|---|---:|---:|---|
| P2D KV | 96 | 98,304 B | all cross the ToR and a Decode NIC uplink |
| EP AG/RS realization | 46,080 | 106,168,320 B | 21,504 same-server flows use local paths; 24,576 cross-server flows use the ToR |

There are 192 EP collectives, each expanded to 240 directed peer flows. The
first EP issue (4,074,638,000 ns) is later than P2D-ready/Decode admission
(4,042,694,000 ns). The last KV flow completed at 3,742,664,241 ns, before
Prefill compute finished; in this request the Prefill completion, not the KV
network, gates TTFT. The EP realization is AG/RS with balanced expert routing,
not exact GateRouter A2A-P2P. There is no contention claim from this run.

## Minimal topology/config provenance

The 1P2D fixture represents 24 physical GPUs, three servers, two 200-Gbps
NICs/server, four GPUs/NIC rail, one ToR, 400 Gbps/server, and a 1:1 ToR
uplink-to-server-uplink ratio. FlowSim uses 34 nodes / 10 forwarding nodes /
57 physical-link records: GPU endpoints 0–23, NIC nodes 24–29, ToR 30, local
fabrics 31–33. GPU/NIC and GPU/local attachments are 7.2 Tbps per GPU; each
NIC-to-ToR link is 200 Gbps. The local fabric is an idealized nonblocking
NVSwitch-like fluid abstraction.

The ns-3 graph uses 32 logical rank hosts (including eight explicit P2D
shadow aliases), six shared NIC forwarding nodes, one ToR, and three local
fabrics: 42 nodes / 10 switches / 70 links. Shadow hosts and their Decode GPU
rank hosts attach to the same Decode NIC and local-fabric nodes, preserving
the scale-out NIC limit. They remain distinct logical host endpoints, so this
does not model a single shared GPU ingress queue.

The original `minimal_1p2d_ep16_2x200g_single_tor.txt` remains unchanged. The
current cluster config points to the new FlowSim physical topology and ns-3
logical-rank topology, plus `replay_template_dcqcn.conf` (`CC_MODE 1`,
4096-byte payload). The generic ns-3 template's `CC_MODE 12` is not used by
this fixture.

## Native ns-3 attempt status

The first one-request attempt exposed that the serving frontend passed
`--start-npu-ids`/`--end-npu-ids` to the ns-3 binary, which rejects these
analytical-backend options. The worktree now omits them for ns-3, generates
logical dimensions from the configured rank shape, and uses the selected
topology/config template. A retry did not produce a serving result before it
was manually interrupted, so it is **INCOMPLETE / NOT VALIDATED**—not a
120-second timeout and not a performance result. No packet queue, ECN/CNP,
PFC, ACK, or packet-level completion claim is made.

## Current content hashes

| Artifact | SHA-256 |
|---|---|
| Current cluster config | `93abc0562ab3bb26c2955c25604e28ec3620465852dd80452726d5427931ff7b` |
| Logical→physical FlowSim map | `5b7c91e6b1937e23bcc342655f9335f9a1dc3b43b2f52affa9a3c29ebdd6ba41` |
| FlowSim topology | `3fa000e6ff3b26fb77f00645a0ddac82f993ca0e831e4abd5cd208baa14995ca` |
| ns-3 logical-rank topology | `911b0dceeb17823b0feb7d4ce98c78f76846c642624195bd613bac9cee3d6c99` |
| DCQCN template | `9ea1ac87e17867c729b3d3a56fe1939ee5c179edffb4507ddc4ad3090c5182be` |
| Workload `moe_i1_o3_n1.jsonl` | `0c3b666743a6a85d698cd7e244f553cd39350a18ec1c4271eab0233a0c4e38e1` |
| FlowSim request output | `13ef62baabe1ad425842c3c53148d06e1cbf3f6b4728b97044b9f1bd53e7bae9` |
| Compressed flow ledger | `4f87617becbd7924cb5aac5fefb0ece10a617d635dddc5d0d12374be7b8715d4` |
| Two-request no-overlap output | `edba2018d65fbffb4ab9748c2e1263475460d353f8576483414eb0ca8dc75280` |
| Two-request no-overlap compressed ledger | `02729b57373f1f06a0d316844501fffc6136606d13bb3b5f1546a9a13eb132b3` |
| Two-request no-overlap workload | `f0121c8188cde1b20b73f319e28c590aa2d2eed9150cfcca2afde62bfcd6904f` |
| First phase-target workload | `955dd1ee0a940168b59cd6bbdfe510995d35e69c9adedffcb7409bdbec108f89` |
| First phase-target output | `ccfe3a23806286ee96b5e8745a2c1363ce1421014b3cf65cfe575795eccb97ef` |
| First phase-target compressed ledger | `a82db3094f7e56cdce422cf19a8f2b2afb2bdca48b7e9c4e941b53416591e74c` |
| Two-request phase-target workload | `89096f25581243e25ae12146193471d298c26a8bcc16a7e69cc0d715122a4102` |
| Two-request phase-target output | `f44c5059cb5dcf4e900c916759eda73dd1d9e3f764a55f36bd7a1a9fb3c7f6ec` |
| Two-request phase-target compressed ledger | `681c87498f19d4169cd38060c58a21e0aea3016de5957f4da9568c280a22d8a0` |
| `serving/__main__.py` worktree | `5292c48807e5fda644752d143d9a21c9541d9f092579ea5a29a1350477677fc2` |
| `flowsim_backend.py` worktree | `0a9f42ebaa323e1a37397519cb7996a9de7e6b0b7466630b9f634de31e8e321a` |
| `flowsim_worker.py` worktree | `d12890f1481ca6a8dc823478a91b6fdb68de951712188315bb7f29af4f71868e` |

### Modified source and regression file hashes

| File | SHA-256 |
|---|---|
| `serving/core/config_builder.py` | `346131f4b7cf16e9e3bcd20db632e7682b99506f61ef1414e6707db828b90106` |
| `serving/core/controller.py` | `cd22e7179d31bd86161dd3c62b4287a0b3033f437e9ae996b17253ea0b55da5c` |
| `serving/core/flowsim_groups.py` | `6461c571c112f812ece9060d26bc351c89fb521a7d4148506f3f0d187e56bb19` |
| `serving/core/graph_generator.py` | `63b9b049e4ed6e7c3668302d3f21619f422d4da2b1fb5658a7da6574496adcbb` |
| `serving/core/request.py` | `2b85416f9f361fe20c22924380bb4aa5005dc145ed61ec24734289628a89a912` |
| `serving/core/router.py` | `822b766485c48d2e4985fbd0972ff5062114589418288e83a4e732adf18c8bc1` |
| `serving/core/scheduler.py` | `f11c617fb9727c3afa35d03c488bc75695e5b73d97592c510f51b9ebb043ab12` |
| `experiments/pd_kv_ep/configs/generate_minimal_1p2d_rank_mapped_tp2.py` | `65f51fa579725a4842706cf0a9380abfc00934eae16ccadd1f843d18afe25118` |
| `test_config_topology_rank_count.py` | `f2ae9c6176004802b60f27d513c4951840d5ad7731c7200502627c6660f40b62` |
| `test_flowsim_collective_scope.py` | `ae24357ca490e7a4c5701a8e8c4332d82e252fbe2d38d5f65199070029e7419b` |
| `test_flowsim_group_queue_ownership.py` | `118c4a493fb50b45308beae617a8b93a65102aa04654040f1301ac0b99da5320` |
| `test_flowsim_rank_mapping.py` | `59d11b3d4d657e3e55068c44c786fe8c7d3d080d86d001ad43239cf7a61f1953` |
| `test_ns3_config_topology_selection.py` | `5368da695e4e803cc57a8305ffdc4acf8b3b42d6c61488dc25233a89a45f2427` |
| `test_pd_decode_capacity_admission.py` | `d0488caa8543028c7fb91d130df2bb4462b9bfca5f3fde6eb71bdcdb114a8f27` |
| `test_pd_request_pairing.py` | `2f275a4260ab46d1c6a5992354d77699e37947eb14c355d56077217335af4371` |

These hashes identify files but do not make the dirty worktree immutable. Git
HEAD remains `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`; do not attribute this
run to that commit.

**Updated reproducibility gate: PARTIAL.** The one-request FlowSim path is
reproducible; packet-level serving completion, legal multi-request integrated
contention, exact MoE route realization, and historical runs remain
unvalidated.

## Recovery run record (2026-10-11)

The latest worktree was exercised with the following one-request FlowSim
smoke. It is a correctness/serving-path check, not a contention experiment:

```bash
timeout 180s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  /home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --network-backend flowsim \
  --cluster-config experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json \
  --dataset experiments/pd_kv_ep/workloads/moe_i1_o3_n1.jsonl \
  --num-reqs 1 \
  --output research_audit/results/current_baseline_flowsim_ep16_i1_o3.csv \
  --run-id baseline-flowsim-ep16-i1-o3-20261011 \
  --inputs-root /tmp/llmsim-baseline-flowsim-ep16-i1-o3-20261011 \
  --flowsim-policy FAIR --log-interval 100 --log-level WARNING
```

Exit status was 0; measured wall time was 13.066 s. The single request had
input=1 and output=3, simulated TTFT=4.042694 s, TPOT=1.632175088 s, and two
TBT/ITL samples, each 1.632175088 s. P2D-ready/Decode-admission occurred at
4.042694 s; the first EP issue followed at 4.074638 s. These are one-sample
raw observations, not percentile/SLO evidence. This smoke used native AG/RS
with balanced routing, not exact GateRouter A2A-P2P.

The previous full event ledger for the corrected local-fabric topology is
retained compressed at
`research_audit/results/current_head_flowsim_ep16_local_nvlink_corrected_telemetry.jsonl.gz`
(SHA-256 in the artifact table above). It contains 46,176 flow rows. This is
an earlier one-request smoke and must not be mixed with packet-level or
multi-request results.

The ns-3 retry used the same one-request serving setup with the explicit
`replay_template_dcqcn.conf` (`CC_MODE 1`) and generated logical-rank topology.
It reached “Starting simulation...” but was manually interrupted before a
request CSV was produced. Status: **INCOMPLETE / NOT VALIDATED**. It is not a
runtime estimate and supplies no packet queue, ECN/CNP, PFC, DCQCN response,
FCT, TTFT, or TBT result.

The environment required a temporary Chakra import shim at
`/tmp/llmsim-chakra-shim.TzDOXs`; this shim is not part of the repository and
must be recreated or replaced by installing the project’s declared Chakra
dependency for an independent reproduction. Python was 3.10.21 in
`/home/lpm/.conda/envs/llmsim-flowsim`; protobuf was 7.35.1 and PyYAML 6.0.3.

Targeted regression status at this recovery point: **23 tests passed**,
including FlowSim rank mapping/local-vs-scale-out path checks, explicit
ns-3-template/topology selection, request pairing, decode admission capacity,
collective scope, group queue ownership, and topology rank-count checks.
`git diff --check` passed. Because this is a dirty worktree, reproducing the
result requires the recorded file hashes and exact worktree state, not only
the Git HEAD.

## Two-request cross-phase correctness probe (2026-10-11)

The two-request probe was intentionally tiny (two one-token prompts, output
lengths 3 and 1) and used no byte overrides. The first no-overlap run used the
same request fields as
`experiments/pd_kv_ep/workloads/minimal_cross_request_no_overlap_control.jsonl`;
the flat loader ignores the extra descriptive `request_id` fields and assigns
request IDs 0 and 1.

An earlier phase target used arrival 4.092426 s in
`minimal_cross_request_overlap.jsonl`, with the same invocation pattern but
output `current_baseline_flowsim_two_request_aligned.csv` and run ID
`baseline-flowsim-cross-request-aligned-fulltelemetry-20261011`. Its request-1
layer-12 KV release was at 4.131944 s; the realized request-0 EP round began
at 4.124370 s, again 7.574 ms apart. The full ledger is retained as
`research_audit/results/current_baseline_flowsim_two_request_aligned.jsonl.gz`.

The later phase-targeted run command was:

```bash
timeout 90s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  FLOWSIM_FLOW_TELEMETRY=1 FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP \
  FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=0 \
  /home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --network-backend flowsim \
  --cluster-config experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json \
  --dataset experiments/pd_kv_ep/workloads/minimal_cross_request_ep_round_aligned.jsonl \
  --num-reqs 2 \
  --output research_audit/results/current_baseline_flowsim_ep_round_aligned.csv \
  --run-id baseline-flowsim-ep-round-aligned-fulltelemetry-20261011 \
  --inputs-root /tmp/llmsim-baseline-flowsim-ep-round-aligned-20261011 \
  --flowsim-policy FAIR \
  --flowsim-telemetry research_audit/results/current_baseline_flowsim_ep_round_aligned.jsonl \
  --log-interval 100 --log-level WARNING
```

The full 51-MB JSONL flow ledgers were compressed after analysis; the retained
artifacts are
`research_audit/results/current_baseline_flowsim_two_request_aligned.jsonl.gz`
and
`research_audit/results/current_baseline_flowsim_ep_round_aligned.jsonl.gz`.
The later ledger has 192 P2D flow rows (96 per request, 98,304 bytes/request), 34,560 EP
dispatch rows and 34,560 EP combine rows. Request 0's 46,080 EP rows total
106,168,320 bytes. Request 1 arrived at 4.960607680 s; its layer-12 KV shard
was released at 5.000125680 s. The realized request-0 EP collective started
at 4.992551680 s, so the target missed by 7.574 ms. Across all request-1 KV
and request-0 EP rows, exact interval intersection on shared directed links
was zero. Link telemetry had no sample with both active KV and EP flows.
The maximum analytical residual backlog on `30->26` was 147,356 bytes while
EP-only flows were active; KV-active intervals on that link had zero backlog.
This run therefore verifies lifecycle/path telemetry but **does not** verify
KV/EP contention.

Serving CSV values were raw single-request observations, not SLO statistics.
Request 0 had TTFT 4.042694 s, TPOT 2.091131928 s, ITL
`[2.550088768, 1.632175088]` s. Request 1 had arrival 4.960607680 s,
P2D-ready/decode-admission 9.003301680 s, TTFT 4.042694 s, and one ITL of
1.632175088 s. Request 0's first ITL differs from the one-request smoke, but
because no KV/EP flow service intervals overlapped, that change is
unattributed and must not be presented as a network-caused latency effect.

Artifacts from the no-overlap and phase-targeted probes are retained as CSV
plus compressed full flow ledgers. The run-to-worktree association remains
dirty-worktree provenance; these outputs do not belong to Git HEAD.

## Corrected P2D handoff wakeup replay (2026-10-11)

Code review of the debug trace found that Decode ranks could remain suppressed
until a future request arrival after a P2D-ready handoff. The frontend now
prefixes the next FlowSim worker response with `wake-decode`; the worker
invalidates Decode arrival deadlines before processing the otherwise unchanged
response. The exact same phase-targeted workload and topology were replayed:

```bash
timeout 60s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  FLOWSIM_FLOW_TELEMETRY=1 FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP \
  FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=0 \
  /home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --network-backend flowsim \
  --cluster-config experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json \
  --dataset experiments/pd_kv_ep/workloads/minimal_cross_request_ep_round_aligned.jsonl \
  --num-reqs 2 \
  --output research_audit/results/current_baseline_flowsim_handoff_fix.csv \
  --run-id baseline-flowsim-handoff-fix-20261011 \
  --inputs-root /tmp/llmsim-baseline-handoff-fix-20261011 \
  --flowsim-policy FAIR \
  --flowsim-telemetry research_audit/results/current_baseline_flowsim_handoff_fix.jsonl \
  --log-interval 100 --log-level WARNING
```

Exit status 0; wall time 21.465 s. Request 0: TTFT 4.042694 s, TPOT
1.632175088 s, ITL `[1.632175088, 1.632175088]` s. Request 1: arrival
4.960607680 s, P2D-ready/decode admission 9.003301680 s, TTFT 4.042694 s,
ITL `[1.632175088]` s. Request 0's pre-fix first ITL 2.550088768 s is
withdrawn; it was caused by the missed Decode wakeup and is not network
evidence.

The corrected ledger has 69,312 rows before gzip: 96 P2D shard flows for
request 1 (98,304 bytes) and 46,080 EP flow rows for request 0. The ledger
gives 192 request-0 collective CCTs (mean 13.4775 µs, P50 10.856 µs,
P95/P99 16.099 µs; within-run collective samples, not independent-request
tail estimates) and zero KV/EP active interval intersections on shared
directed links. This remains a lifecycle correctness test, not a contention
result.

Hashes:

| Artifact | SHA-256 |
|---|---|
| `serving/__main__.py` | `5a2e39892683c82fda9dd6f33fa502dc91b313bc04cc75e96707ca895bc144a5` |
| `serving/core/flowsim_worker.py` | `b7f99358e278ec55ae55d53b24e6917027d319a6ceb6bdae237f916ddeb181d5` |
| handoff workload | `89096f25581243e25ae12146193471d298c26a8bcc16a7e69cc0d715122a4102` |
| cluster config | `93abc0562ab3bb26c2955c25604e28ec3620465852dd80452726d5427931ff7b` |
| request CSV | `6e8680f2c7d8ef25f04b0c910810bcb9e109f06f1b4d7fdd8925b8ff3aa5c4ef` |
| compressed flow ledger | `aafa5f2a6721fecfaf2ae47a6b38c9e16f651c8d229e31a6f164e28acdfe9cd6` |
| wakeup regression test | `3fe525932eefff304f55fb788f46a779bc80b526d068dff25066aaa54d8da161` |

All eight focused test scripts now pass, 26 tests total. The 50-MB raw ledger
was gzip-compressed to limit retained result size. All source edits remain
uncommitted; these results are bound to the dirty worktree and not to Git HEAD.

## Bounded native ns-3 packet replay — 2026-10-11

This is a network-only replay. It does not run the serving scheduler and does
not generate TTFT/TPOT/TBT. The source slice is extracted reproducibly by
[`build_ns3_baseline_smoke_input.py`](scripts/build_ns3_baseline_smoke_input.py)
from the corrected integrated FlowSim ledger: request 1's 96 P2D shard events
plus request 0's EP collective 10000303. Bytes and `requested_start_ns` are
unchanged. FlowSim physical rank endpoints are translated through the saved
logical-to-physical mapping into ASTRA logical endpoints; the generated
32-entry rank-to-NIC map also preserves server identity for excluding
same-server EP from scale-out packet replay.

Reproduction commands (use fresh, nonexistent directories):

```bash
SMOKE_ROOT=$(mktemp -d /tmp/pd-moe-ns3-smoke.XXXXXX)
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_audit/scripts/build_ns3_baseline_smoke_input.py \
  --output-dir "$SMOKE_ROOT/input"
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/run_model_derived_replay.py \
  --replay-dir "$SMOKE_ROOT/run" \
  --input-replay-dir "$SMOKE_ROOT/input" \
  --scale S1P2D_EP16 \
  --template experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf \
  --packet-payload-size 4096 --telemetry-interval-ms 0.1 \
  --policy FAIR --cc-mode 1 --timeout-s 60
```

Recorded replay: [`network_run_manifest.json`](results/ns3_packet_smoke_minimal_logical_20261011_reproduced/network_run_manifest.json).
It completed 336 input events in 3.3716 s wall time: 96 P2D messages (98,304
B) and 128 inter-server EP messages (32,768 B) were issued; 112 same-server
EP messages (28,672 B) were counted as local and not packetized. All 224
issued messages completed. Mean message service/completion duration was
20.490 us for P2D and 20.711 us for remote EP. These are not request-level KV
FCT or EP collective CCT. The replay saw no directed-link interval with
simultaneous KV and EP service, no ECN mark, PFC pause, drop, CNP, or DCQCN
rate-change event. NetDevice-queue telemetry reports 4,964 B maximum on
ToR→D0 NIC link (30→26); it is not direct switch-MMU occupancy. The MMU
monitor samples every 100 μs and only logs samples ≥1 KB; `qlen.txt` had none.
With ~20-μs message service, this sampling cannot establish that the switch
queue remained empty between samples.

The same 336-event input was replayed twice; SHA-256 hashes for `fct.txt`,
`comm_events.csv`, `link_summary.csv`, and `cc_events.csv` matched exactly.
The input events, generated rank map, manifests, full link timeseries, and
packet outputs are retained under:

- [`input/`](results/ns3_packet_smoke_minimal_logical_20261011/input/)
- [`reproduced/`](results/ns3_packet_smoke_minimal_logical_20261011_reproduced/)

Provenance hashes:

| Artifact | SHA-256 |
|---|---|
| FlowSim source ledger | `aafa5f2a6721fecfaf2ae47a6b38c9e16f651c8d229e31a6f164e28acdfe9cd6` |
| ns-3 topology (32 logical ranks) | `911b0dceeb17823b0feb7d4ce98c78f76846c642624195bd613bac9cee3d6c99` |
| logical→physical rank map | `5b7c91e6b1937e23bcc342655f9335f9a1dc3b43b2f52affa9a3c29ebdd6ba41` |
| physical rank→NIC map | `c29dacafb35003cc4dc9da1f63e59d1110120908146a86fc3d31765c921c0e7a` |
| generated event slice | `2e2b7185db71b82f6981976c8428c83ad37b1ec17aaf8d37e60e98753c34b36e` |
| DCQCN template | `9ea1ac87e17867c729b3d3a56fe1939ee5c179edffb4507ddc4ad3090c5182be` |
| `KVEPReplay` executable | `79f8f6e6dd2fbc6af061e1a11f08dd3431f58bb61a162f06d452beb2589eadea` |
| replay runner | `89683559251d19d65f569cb373f31fd7258c97ccc1da5ec96570499b3946664e` |
| slice builder | `7ca8c1ff8e948dfb5f333e6982968d870d56899069ff90bbd81b3568e491cdcd` |

The simulator binary receives a no-op message-completion callback in
`KVEPReplay.cc`; packet completion is not fed back to the request scheduler.
This validates packet-level path/queue/completion instrumentation only. The
separate ASTRA/ns-3 integrated serving path remains unvalidated.

## Machine-readable baseline provenance — current worktree

Refresh the compact source/config/profile/workload/backend/output binding with:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_audit/scripts/write_baseline_manifest.py
```

The generated file is
[`results/01_baseline_run_manifest.json`](results/01_baseline_run_manifest.json).
It binds the corrected integrated FlowSim smoke, corrected controlled
two-request run and KV-only control, corrected native ns-3 complete MoE-layer
FULL/EP_ONLY/KV_ONLY replay and repeat, plus explicitly invalidated historical
runs, to their source/config/workload/binary/output hashes. At the last
manifest generation it records `HEAD=0c0839aff54ec0abb1810dc09cf3d66f06b1b078`,
tracked-diff hash `323971218bbfff71e7fa6c91f0c0fc358bc373928016e3aac84e1811bc2f4d4c`,
and modified/untracked worktree paths. The result must be regenerated if any
source, configuration, workload, backend binary, output, or audit file changes. Python
invocation must use the recorded conda Python 3.10 environment; the shell's
default `python` here is Python 2.7.18 and is not the experiment interpreter.

The manifest is a provenance aid, not an immutable release: the source edits
remain uncommitted. A Git commit of the audited baseline followed by a rerun
is still required before these measurements can be cited as a versioned
artifact.

The request/collective barrier checks can be rerun without simulating traffic:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_audit/scripts/validate_baseline_barriers.py
```

The pre-unit-fix two-request output described by earlier paragraphs is stale;
the updated barrier validator defaults to the corrected single-request
control. Use explicit paths for other outputs. The corrected two-request
output verifies both 96-shard P2D barriers and all 288 group-wide EP barriers
against their 240 peer-flow completions, and finds nonzero KV/EP
active-service interval overlap on three of five common directed links. This
is a consistency/path check, not by itself evidence of material serving
contention.

## Corrected same-class KV–KV case and isolated controls — 2026-10-11

This case tests whether two distinct requests with unequal, model-derived KV
sizes can contend on the same P2D path. It is controlled, not trace-natural.
The request pair arrives together, is assigned to different Prefill instances
by the configured LOAD router, and uses the existing 1P2D/EP16 topology with
TP2, Qwen3-30B-A3B, LAYERWISE P2D, FAIR FlowSim, and 200-Gbps server NIC rails.

FULL workload:

```jsonl
{"input_toks":32,"output_toks":1,"arrival_time_ns":0}
{"input_toks":128,"output_toks":1,"arrival_time_ns":0}
```

The comparison controls contain one request each, with the same prompt size
and arrival time as its corresponding FULL request. Example invocation (the
same command was used for all three files, with the workload/output/run-id
paths substituted):

```bash
timeout 180s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
FLOWSIM_FLOW_TELEMETRY=1 FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP \
FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=0 \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --network-backend flowsim \
  --cluster-config experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json \
  --dataset experiments/pd_kv_ep/workloads/minimal_kv_kv_distinct_sizes.jsonl \
  --num-reqs 2 \
  --output research_audit/results/minimal_kv_kv_distinct_sizes/requests.csv \
  --run-id minimal-kv-kv-distinct-sizes \
  --inputs-root /tmp/llmsim-minimal-kv-kv-distinct-sizes \
  --flowsim-policy FAIR \
  --flowsim-telemetry research_audit/results/minimal_kv_kv_distinct_sizes/flows.jsonl.gz \
  --log-interval 100 --log-level WARNING
```

The historical `.jsonl.gz` name for this particular output is misleading:
it is plain-text JSONL, as `file` confirmed. Do not pass it to `gzip -d`.
The two one-request controls are `minimal_kv_kv_control_i32` and
`minimal_kv_kv_control_i128`; each has its own request CSV and FlowSim flow,
link, KV-event, and collective ledgers.

| Request | Model-derived P2D bytes / shards | Shard FCT mean FULL/control | Shard FCT P99 FULL/control | TTFT FULL/control | KV-ready FULL/control |
|---|---:|---:|---:|---:|---:|
| input 32 | 3,145,728 B / 96 | 11.632 / 11.538 µs | 13.443 / 12.822 µs | 41.466 / 41.466 ms | 41.466 / 41.466 ms |
| input 128 | 12,582,912 B / 96 | 15.693 / 15.552 µs | 21.308 / 20.686 µs | 43.051 / 43.051 ms | 43.051 / 43.051 ms |

For each input size the slowdown percentages are: mean +0.81% / +0.90%, P99
+4.84% / +3.01%. Both requests have active P2D service overlap on `24->30`
and `30->26`; pairwise shard interval intersections sum to 267,408 ns on each
directed link. TTFT and the simulator's `p2d_kv_ready_time_ns` are unchanged
at displayed nanosecond precision. One run per condition is a mechanism
probe, not a statistical characterization. These results show a small
same-class network interaction, not a serving-level motivation PASS.

Historical pre-fix attempt (superseded by the 2026-10-11 grouped-topology
validation below): the two-independent-EP8-group topology was rejected before
simulation because configured logical rank count was 32 while first-group-
only dimension inference returned `[2,4,2]` (16 coordinates). It is not a
current capability claim; see the later EP4 validation section. No synthetic
EP group or per-request splitting of an aggregate collective was used.

## Independent EP-group validation — 2026-10-11

This section supersedes the preceding EP8-attempt paragraph as a statement of
current representability. It records four bounded integrated FlowSim runs;
all ran from the same dirty worktree and used the same existing one-ToR
physical topology. The exact input artifacts are included in the refreshed
`01_baseline_run_manifest.json` under `bounded_ep_ep_validation`.

| Run ID | Config | Workload | Requests | Request CSV (transient) | Telemetry |
|---|---|---|---:|---|---|
| `ep_ep_minimal_full4` | `ep_ep_minimal/two_ep4_groups_full.json` | `two_ep4_groups_full_4req.jsonl` | 4 (2/group) | `/tmp/ep_ep_minimal_full4_requests.csv` | `/tmp/ep_ep_minimal_full4/` |
| `ep_ep_minimal_a_only2` | `ep_ep_minimal/two_ep4_groups_a_only.json` | `two_ep4_groups_a_only_2req.jsonl` | 2 | `/tmp/ep_ep_minimal_a_only2_requests.csv` | `/tmp/ep_ep_minimal_a_only2/` |
| `ep_ep_minimal_full` | `ep_ep_minimal/two_ep4_groups_full.json` | `two_ep4_groups_full_8req.jsonl` | 8 (4/group) | `/tmp/ep_ep_minimal_full_requests.csv` | `/tmp` scratch ledgers |
| `ep_ep_minimal_a_only4` | `ep_ep_minimal/two_ep4_groups_a_only.json` | `two_ep4_groups_a_only_4req.jsonl` | 4 | `/tmp/ep_ep_minimal_a_only4_requests.csv` | `/tmp/ep_ep_minimal_a_only4/` |

Common arguments: `--network-backend flowsim --request-routing-policy RR
--max-num-seqs 8 --max-num-batched-tokens 512 --no-enable-prefix-caching
--no-enable-chunked-prefill --log-level WARNING --log-interval 60`, with
`FLOWSIM_MAX_TELEMETRY_ROWS=200000` and
`FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=200000` on the 8-request exploratory run.
The smaller matched runs disabled full per-flow telemetry and retained
collective/KV/link summaries. Environment: Python 3.10.21 from
`/home/lpm/.conda/envs/llmsim-flowsim/bin/python`,
`PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs`, and
`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`.

### Input hashes

| Artifact | SHA-256 |
|---|---|
| generator `generate_two_decode_ep4_groups_flowsim.py` | `d59734fb0c6100c1b9413db30857b914678f0054ba4496ddd298af2230786085` |
| full config | `2a91e26179b8e2bace307bde4f8a118d32f984531426e7b120173f679fb3c1fa` |
| full logical→physical rank map | `d5c18ecd573480f2dc28e1c7f95e09a88f6f70e88197ea9ce3e9d0c9e3e62f54` |
| A-only config | `1545b8390fca7e71b261da0a4c049a6aafbd7a267c72e7eaf198fc565ecaeba7` |
| A-only logical→physical rank map | `0abe367dc466b8d6d52ab6edcad83919d5d708602cc8235dddf8f77b6b276135` |
| full 4-request workload | `336f0fea76be5b8839439f1906a170cbf49176aabb95e21ad7b350b64a92122e` |
| full 8-request workload | `8e6280ae241494e412553dbf6f3dd57221d6a799bb38f1914e0338e09f6ad4f8` |
| A-only 2-request workload | `8efb93d76029aae98aba7f83ee14fcd664b25b852d60da00ed9b2a2e5bf2987d` |
| A-only 4-request workload | `336f0fea76be5b8839439f1906a170cbf49176aabb95e21ad7b350b64a92122e` |
| shared FlowSim topology | `3fa000e6ff3b26fb77f00645a0ddac82f993ca0e831e4abd5cd208baa14995ca` |

The compact result table is in `02_MOTIVATION_RESULTS.csv`; full experimental
interpretation is in `12_EP_EP_GROUP_VALIDATION.md`. Raw large telemetry remains
in `/tmp` only and is not part of the durable artifact. Thus the run is
reconstructable from the source/config/workload hashes and recipe, but the
large raw telemetry must be regenerated for independent re-analysis.

## Corrected Chakra timing units and matched two-request FlowSim run — 2026-10-11

The serving-to-Chakra adapter had a 1000× compute-duration unit bug: internal
profile-backed values are ns, while Chakra `duration_micros` is µs. The old
adapter passed ns directly. `trace_generator.indexed_cols()` now performs a
ceil-rounded ns→µs conversion with a 1-µs floor. Prior serving-time and
temporal-alignment claims generated by the old adapter are withdrawn. Packet
replay inputs derived from those timestamps are stale for timing/overlap
claims too.

Targeted test:

```bash
PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/test_trace_time_units.py
```

Result: 2/2 PASS. The nine focused regression scripts were rerun: 28/28
PASS. This is not the repository's full test suite.

Corrected one-request command:

```bash
timeout 120s env PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
FLOWSIM_FLOW_TELEMETRY=1 FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP \
FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=0 \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --network-backend flowsim \
  --cluster-config experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json \
  --dataset experiments/pd_kv_ep/workloads/moe_i1_o3_n1.jsonl \
  --num-reqs 1 \
  --output research_audit/results/time_unit_fix_flowsim_ep16_i1_o3.csv \
  --run-id time-unit-fix-flowsim-ep16-i1-o3-20261011 \
  --inputs-root /tmp/llmsim-time-unit-fix-flowsim-ep16-i1-o3-20261011 \
  --flowsim-policy FAIR \
  --flowsim-telemetry research_audit/results/time_unit_fix_flowsim_ep16_i1_o3.jsonl \
  --log-interval 100 --log-level WARNING
```

It reports TTFT 4.266 ms, TPOT 2.339088 ms, and ITLs 2.339149/2.339088 ms.
This single-request output is a timing smoke, not a performance result.

The controlled overlap workload is model-derived but not trace-natural:

- `minimal_time_unit_corrected_kv_ep_overlap.jsonl`: request 0 is
  `(input=1, output=3, arrival=0)`; request 1 is
  `(input=128, output=1, arrival=4,302,000 ns)`.
- `minimal_time_unit_corrected_kv_control.jsonl`: same 128-token request and
  absolute arrival, without the Decode background request.

Both use the same 1P2D/EP16 mapped topology, Qwen3-30B-A3B profile, TP2,
200-Gbps endpoint NICs, LAYERWISE model-derived P2D, and FAIR FlowSim. The FULL
case completed in 23.9 s wall time; the matched KV-only case in 10.3 s.

For each KV shard, FCT is `end_ns - requested_start_ns`; request handoff is
the last required shard completion checked against the serving CSV. Request 1
has 96 layer×TP shards totaling 12,582,912 B. Shard mean/P99 (nearest-rank)
is 0.016156/0.021342 ms in FULL and 0.015552/0.020686 ms in KV-only, a
3.88%/3.17% increase. Its last shard completes at 46.259443 ms, and the
serving `p2d_kv_ready_time_ns`/Decode admission is 47.353 ms. TTFT is 43.051
ms in both matched runs.

EP CCT is collective completion minus collective start, with collective end
checked against the maximum of its required peer-flow completions. Request
0's 192 within-run collectives have mean/P99 13.4775 µs/16.099 µs in EP-only
and 13.4869 µs/16.273 µs in FULL (+0.07%/+1.08%). These are recurrent samples
from one request/run, not independent-request tail estimates. Request 0 TPOT
is 2.339088 ms in EP-only and 2.339118 ms in FULL (~+0.0013%). No SLO is
defined or claimed.

The corrected FlowSim ledger finds overlapping active-service intervals on
directed links 26→10 (28.912 µs), 26→11 (289.688 µs), and 30→26 (318.600 µs).
FlowSim's intervals/backlog are fluid analytical state, not packet-buffer
occupancy. Barrier accounting returns
`PASS_BARRIER_ACCOUNTING_OVERLAP_PRESENT`. The effect at this chosen point is
small: overlap exists, but no significant TTFT/TBT opportunity is demonstrated.
Do not turn this controlled phase into a natural-load or CCF-motivation claim.

## Corrected native ns-3 complete MoE-layer overlap replay — 2026-10-11

The dispatch-only packet slice is retained as a debug artifact and is not
used for the collective result. The authoritative input includes both a
complete dispatch collective (`collective_id=1082`) and its combine
collective (`collective_id=1103`), plus all 96 model-derived P2D KV shards.
The layer has 480 logical EP peer-flow events (240 dispatch and 240 combine);
112 peers per collective are intra-server and treated as local, leaving 128
packetized messages per collective. Bytes and `requested_start_ns` are copied
from the corrected integrated FlowSim ledger.

Build the input:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_audit/scripts/build_ns3_baseline_smoke_input.py \
  --ledger research_audit/results/time_unit_fix_two_req/flows.jsonl.gz \
  --kv-request-id 1 --ep-request-id 0 \
  --ep-collective-id 1082 --ep-collective-id 1103 \
  --expected-kv-flows 96 --expected-ep-flows 480 \
  --output-dir research_audit/results/ns3_corrected_full_moe_layer_108/input
```

For each `CLASS` in `FULL`, `EP_ONLY`, `KV_ONLY`, run the following with a
fresh output directory `research_audit/results/ns3_corrected_full_moe_layer_108/${CLASS,,}`:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/run_model_derived_replay.py \
  --replay-dir "$OUT" \
  --input-replay-dir research_audit/results/ns3_corrected_full_moe_layer_108/input \
  --scale S1P2D_EP16 \
  --template experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf \
  --packet-payload-size 4096 --telemetry-interval-ms 0.01 \
  --policy FAIR --traffic-class "$CLASS" --cc-mode 1 --timeout-s 60
```

FULL was repeated once in a fresh `full_repeat` directory. Each replay took
about 5.3–6.0 s wall time and exited 0. The matched summary is regenerated by:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_audit/scripts/analyze_corrected_ns3_moe_layer.py
```

[`matched_network_summary.csv`](results/ns3_corrected_full_moe_layer_108/matched_network_summary.csv)
defines packet-message FCT as `network_end_ns - issue_time_ns`; each
dispatch/combine network CCT is the latest packetized remote peer completion
minus the common collective issue time. Results:

- Dispatch: 29.262 µs EP-only vs 31.342 µs FULL (+7.11%).
- Combine: 28.878 µs EP-only vs 30.958 µs FULL (+7.20%).
- P2D message FCT mean: 25.967 µs KV-only vs 26.009 µs FULL (+0.16%); nearest-rank
  P99 is 31.139 µs in both.
- Shared 200-Gbps directed link 38→34 queue peak: 4,132 B KV-only, 70,244 B
  EP-only, 121,404 B FULL. This is the `PointToPointNetDevice` transmit queue,
  not direct switch-MMU or per-priority occupancy.
- All three runs: ECN=0, PFC=0, packet drops=0; no CNP or QP rate-change event.

The repeated FULL run matched SHA-256 for `comm_events.csv`
(`1a597430e7fcbdad70ccad43a2c595d40dd281fc518ea87fc2110a6e7e2c8da3`),
`link_summary.csv`
(`7f59f5798278e672f1bda06eec21bcb0df4ca62478e9c8399b087dbd0687eec8`), and
`fct.txt` (`e33ab642333ba2d841f1fd768c3b44ce852ff00535c1eb89ba28528081eef7e0`).

This verifies a modest packet-level shared-link queue/CCT effect in a
controlled slice. It is network-only and does not produce serving TTFT/TBT;
the integrated FlowSim result for this workload has negligible serving-level
change.

## Decode graph-completion wakeup repair and post-fix matched run

An additional event-loop bug was found after the handoff wakeup repair. A
Decode graph completion could advance an existing request but leave its
start rank suppressed until the next external request arrival. The pre-fix
9.13-ms token interval reproduced even with KV on a separate virtual network,
so it is retired as a network effect. The frontend now compares
scheduler-relevant request/token/inflight state around `scheduler.add_done()`;
state changes send `pass -1` and reopen Decode ranks.

The regression is:

```bash
PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/test_flowsim_decode_completion_wakeup.py
```

It has four assertions/tests. The full focused set now contains ten scripts
and 33 assertions/tests; the command to rerun all scripts is:

```bash
for t in experiments/pd_kv_ep/scripts/test_*.py; do
  PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  /home/lpm/.conda/envs/llmsim-flowsim/bin/python "$t" || exit 1
done
```

Post-fix D4-only result is preserved in
`results/minimal_ep4_decode_cohort_wakefix/`. The matched post-fix D4+late
8192-token KV result is in `results/minimal_ep4_then_kv8192_wakefix/`, with
the `KV_ISOLATED` counterfactual in the sibling `_kv_isolated` directory.
The workload is
`experiments/pd_kv_ep/workloads/minimal_ep4_then_kv8192.jsonl`; config is
`experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json`.
Both use Qwen3-30B-A3B, TP2/EP16, FlowSim FAIR versus the independent virtual
link-copy counterfactual, model-derived layerwise KV and controlled arrival
13.396596 ms.

The exact transient shell invocations for these newest post-fix outputs were
not separately saved at run time. The source/config/workload/output artifacts
are retained, but this pair is **not marked command-complete provenance**;
before publication, rerun from an immutable commit and save exact argv plus
hashes. Reported result: 672 collective samples; EP CCT mean 13.495635 vs
13.4775 µs, P99 16.273 vs 16.099 µs; new-request TTFT 295.328 ms and KV-ready
308.724596 ms in both runs; Decode TPOT difference <0.01%. This is a
controlled diagnostic, not a multi-request tail-distribution/SLO claim.

The matching unequal-size KV–KV inputs and controls are documented in the
preceding section and retained under `results/minimal_kv_kv_*`. Their 96
shards/request produce a within-run shard distribution, but do not move the
last required shard or TTFT in the reported comparisons.
