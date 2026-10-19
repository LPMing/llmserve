# Public workload evidence and replay limits

All sources below are public primary artifacts. Counts marked "released" come
from dataset cards; local statistics live in the linked `*_analysis/summary.json`
files. A model or provider named in a trace is not evidence for its hidden
serving topology.

| Source and pinned identity | Useful fields | Local screen | Causal limit for a Serving × Network claim |
|---|---|---|---|
| [FreeInference](https://huggingface.co/datasets/harvardMadsys/freeinference_agentic_trace), revision `16d3c04dae6ccaa0c48a9064e204e3a8f1eb9ade`, CC-BY-4.0 | Full nested subagent sessions, real request/tool times, 16-token prefix IDs, provider token counts | Full 119 files downloaded with per-file SHA256 in `freeinference_manifest.json`; 16-week result in `freeinference_analysis/`: 12,002 roots, 288 same-request sibling groups | Prefix blocks use `o200k_base`, not provider or Qwen tokenization. Provider models lack matching local latency profiles. A nested child link is real; a parent *join* is not explicit. No physical NIC/path or actual cache-residency events. |
| [TraceLab v0.0.2](https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2), SHA256 `11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65`, CC-BY-4.0 | 665,453 coding-agent rounds, timestamps, prompt/cache token split, tool calls | `tracelab_analysis/summary.json`: median prompt 132,092, 30.2% prompt >=8,192 with output <=128 | No released ground-truth content block IDs or reliable parent/child join edges; model providers are not locally profiled. Synthetic replay tools reconstruct these fields. |
| [ServeGen conversations](https://github.com/alibaba/ServeGen), commit `d70c8b2d5bc45f4b60a146fbc43dc5523f871c8b`, repository Apache-2.0 | Selected multi-turn token counts and timestamps | `servegen_analysis/summary.json`: 1,616 conversations, 5,720 turns, median prompt 7,745; 1,769 prompts <=2,048 | Selective release is not a full-fleet arrival trace. `input_tokens` list length never equals `input_token_count` in this slice, so its hash-list semantics need source verification before exact KV replay. No model/hardware or P/D path. |
| [Mooncake FAST'25](https://github.com/kvcache-ai/Mooncake/tree/1204367d7c7165d80c6b234190ed90e4f58e7bbf/FAST25-release/traces), pinned commit | 12,031 conversation + 23,608 tool/agent requests, lengths and 512-token prefix IDs, one-hour relative timestamps | `mooncake_analysis/summary.json`: all block counts match `ceil(input/512)`; exactly 1,180 distinct timestamps in each trace, positive gaps almost always 3,000 ms | Ten or twenty requests sharing a 3-second timestamp bucket must not be treated as same-millisecond incast. Model, instance and NIC mapping are not released. |
| [Chutes one-year metadata](https://huggingface.co/datasets/harvardMadsys/chutes_metadata), revision `85722e694bf7bb8a5a5ccdf70424fa5998372467`, CC-BY-4.0 | 6.12B unsampled requests, model ID, instance ID, token counts, observed TTFT; cached tokens for last ~10 weeks | Pinned model table maps a `chute_id` to exact profiled `Qwen/Qwen3-32B`; `pro_6000` is among supported GPUs. Full shards 20/40 contain 1.54M/40.27M model rows, exactly matching the ID-only scans. Shard 20 has 3.245 rps and no `ct`; shard 40 has 45.892 rps, but one user contributes 95.2% of rows and 97.2% of >88.3%-cache-hit rows, all without TTFT. The model table's `invocation_count` is not a trace total. | `supported_gpus` is not actual per-instance GPU identification. No network topology, P/D split flag, or exact prefix hashes. Production TTFT cannot be decomposed into P/D transfer without an independent signal. |
| [Qwen-Bailian public trace](https://github.com/alibaba-edu/qwen-bailian-usagetraces-anon), commit `5f7439c51ec248a0c585f7d90a41a6f57773b912`, Apache-2.0 | Four sampled two-hour Qwen-cluster files, 16-token input-content hashes, millisecond relative arrivals, input/output lengths, parent chat links | Full 269,681 rows and four LFS-object SHA256 hashes verified. `qwen_bailian_analysis/` records exact earlier-input prefix and short-window arrivals. Coder: 43,011 requests, median 4,540 input tokens, 29.0% with >=88.33% earlier-input prefix; a deliberately cold all-on-one-cut 200-Gbps full-KV proxy averages 72 Gbps. | Original model, sampling fraction, worker/P/D map, network and cache state, TTFT, completion and output hashes absent. Prior-arrival prefix is not a realized cache hit. December 2024 To-B cannot be matched to a Qwen3 profile; surrogate replay needs clear labeling and an adapter from block hashes to simulator token IDs. |
| [SwissAI/OpenTela serving trace](https://huggingface.co/datasets/eth-easl/swissai-serving-trace), revision `c3dd66602b564ce189f7db81115620413e646cd5`, card license `other` | Released exact-model Qwen3-32B timestamps, input/output lengths and 16-token input block hashes | `qwen3-32b-buckets.jsonl` archived raw: 4,617,817,342 B, 3,994,435 lines; SHA256 `58b2265b98a10ec3bb2a0b455c520731c1296967906c7adc7b6d3710a013e402`, with first/middle/last 4096-B HTTP Range comparisons to the pinned source. Full mining deferred by the revised theory-first ordering. | [OpenTela's OSDI'26 paper](https://www.usenix.org/system/files/osdi26-yao.pdf) describes colocated serving without P/D disaggregation or global prefix caching. The release has no per-request GPU/NIC route or realized Decode cache residence, so its completion times cannot validate P/D scheduling. The source ETag is not the raw file SHA256. |

## Reproduction

```bash
PYTHONPATH=/tmp/freeinference_pydeps python3 research_autonomous/workloads/mine_freeinference.py
python3 research_autonomous/workloads/mine_tracelab.py
python3 research_autonomous/workloads/mine_servegen.py
python3 research_autonomous/workloads/mine_mooncake.py
PYTHONPATH=/tmp/research_pydeps /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/workloads/scan_chutes_shard_ids.py --shards 20 30 40
python3 research_autonomous/workloads/download_chutes_shard.py --shard 20
PYTHONPATH=/tmp/research_pydeps /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/workloads/extract_chutes_qwen.py --shards 20
PYTHONPATH=/tmp/research_pydeps /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/workloads/mine_chutes_qwen.py --shard 20
python3 research_autonomous/workloads/download_chutes_shard.py --shard 40
PYTHONPATH=/tmp/research_pydeps /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/workloads/extract_chutes_qwen.py --shards 20 40
PYTHONPATH=/tmp/research_pydeps /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/workloads/mine_chutes_qwen.py --shard 40
python3 research_autonomous/workloads/download_qwen_bailian.py
python3 research_autonomous/workloads/mine_qwen_bailian.py
python3 research_autonomous/theory/qwen_bailian_cut_screen.py
python3 research_autonomous/workloads/download_swissai.py
```

The raw downloads are locally retained but gitignored. Public source URLs,
revisions and SHA256 hashes are kept in the manifests and summaries. Network
access and the temporary `zstandard`/`duckdb` Python packages are needed to
repeat the downloads/extraction; the analyses consume local files.
