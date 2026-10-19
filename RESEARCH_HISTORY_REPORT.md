# LLMServingSim 历次研究思路与仿真实验汇报

截至 2026-10-15。面向项目汇报的证据总账；“当前”指本工作区，不代表已经发布的稳定版本。当前 HEAD 为 0c0839a，研究代码、配置和报告有大量未提交改动。本文的推导值来自现有源码和配置，实验值来自相应报告；不能仅凭 HEAD 复现所有历史结果。

## 一、给领导的结论

1. **最早的判断成立，但只是网络机制。** 长时大体积 P2D KV 与短而有集体完成屏障的 Decode EP 可在同一有向链路竞争。早期人工 ns-3 场景的 EP 尾延迟相对 EP-only 为约 9.6–58.6 倍，而 KV 完成时间相对 KV-only 约 1.03–2.06 倍。模型驱动的小型 native ns-3 配对实验也观察到 EP P99 CCT 6.545→13.270 µs，即 2.028 倍。严格 EP 优先级可保护 EP，KV_FIRST 往往严重伤害 EP。
2. **研究重心随后转向“网络变化是否到达 Serving 屏障”。** 当前 LAYERWISE 仿真图允许 KV 传输与后续 Prefill 计算重叠；许多 shard 的排队与降速在仿真图的完成屏障前被计算吸收。集成仿真器把发送节点接在 `qkv_proj` 后，真实 KV cache 写入/可发送时刻尚未校准，不能把该重叠量直接当作真实系统结论。EP dispatch/compute/combine 则逐层串接，最后一个 peer 容易决定 collective CCT；CCT 变化仍须经过计算和调度才能成为 token TBT/TPOT 变化。
3. **静态三策略未形成可发表的双边权衡。** FAIR、KV_FIRST、EP_FIRST 在受控窗口能造成很大的 EP 差异；但经物理并行链路修正后，EP_FIRST 对 KV handoff/TTFT 的额外代价在许多测试点几乎为零。自然 Azure 小窗的端到端策略差异也接近零。因此“需要动态 KV/EP 优先级算法”的动机没有通过强基线与自然负载门槛。
4. **后续大量方向是有价值的阴性结果。** Placement、路径、关键 EP peer、ECN/DCQCN、持久 QP、远端热前缀、split-source、progressive push、稀疏 A2A、EP–EP 相位、接收端 incast、批次边界、同类流优先级等，分别暴露了临界路径被隐藏、收益被简单基线吃掉、仿真语义不足、配置失效或缺少来源负载的问题。详见第四节。
5. **截至目前最扎实的新动机是 P/D KV 驻留不对称，而非新算法收益。** 受控、profile 支持的 Llama-3.1-8B 实验中，P 命中 1,984-token 前缀而 D 正常淘汰它，目标请求由 64-token 增量传输转为 2,048-token 全量传输，模型完成时间从 56.971 增至 79.029 ms。此机制达到 MOTIVATION_VALIDATED；加入合法历史后，普通 LFU 已达到本场景的理想目标时间。另一个提前取得 D 容量 credit 的 25.35% 改善也被普通两阶段 FIFO 几乎完全获得。尚无 PAPER_HEADROOM_VALIDATED、SOLUTION_VALIDATED 或 PAPER_READY 结论。

**汇报口径：**网络 FCT、EP CCT、模拟器记录的首 token 事件、真实客户端 TTFT 与 SLO 是不同指标。FlowSim 是共享容量的流体模型，不产生包级 ECN/PFC；固定 ns-3 replay 没有 Serving 完成反馈。本文保留每项结果的后端、对照和证据边界。

## 二、文档覆盖范围与平台沿革

写作前逐份读取了工作树原有的 **490 份 Markdown，约 88,408 行**（含被 rg 默认忽略的 CLAUDE.md），并查看了 Git 历史和 IISWC24、ISPASS26 artifact 分支的评估说明。工作树内约 115 份位于 astra-sim，主要说明底层网络/Chakra/第三方组件；约 108 份位于 experiments/pd_kv_ep，58 份位于 research_autonomous，53 份位于 research_motivation，41 份位于 docs，其余为研究审计、主线筛查、系统手册和顶层总结。本文按“研究问题—合法场景—观察—为何转向”合并重复报告；第三方使用说明和 CLI 文档用于核实语义，不当作本项目研究结果。

| Markdown 文档群 | 对本报告的贡献 |
|---|---|
| 顶层 README、CHANGELOG、AGENTS/CLAUDE、CONTRIBUTORS | 版本与论文沿革、代码结构、语义约定、研究边界；AGENTS/CLAUDE 是开发说明，不是实验证据。 |
| serving、profiler、bench、workloads、configs 及 docs 下手册 | 确认调度、P/D handoff、KV block/缓存、trace 格式、CLI 默认值、模型/集群字段、profile 域、vLLM 对照和基准验证方式。 |
| experiments/pd_kv_ep 与 results 下研究报告 | 保留原始 KV/EP、packet、FlowSim、placement、远端 KV、50G/200G 等场景的具体对照、修正和失败记录。 |
| research_audit、research_final_audit、research_joint、research_motivation 等系列 | 对自然暴露、同类流、联合四格、物理 incast、缓存/层级消费与 sparse MoE 的理论、门槛和 NO-GO 进行交叉复核。 |
| research_autonomous 与 RESEARCH_LOG | 逐轮 R1–R20 的候选、来源 trace、强基线、冻结动机和最新待验证状态。 |
| astra-sim 下的第三方 Markdown | 用于理解底层网络模拟器和 Chakra 输入，不把其中示例性能算作本研究 KV/EP 结果。 |

| 时期 | 仿真平台与已归档的研究范围 | 对本次 KV/EP 研究的作用 |
|---|---|---|
| 2024 IISWC artifact | 初代 HW/SW 协同仿真；五组评估脚本对应论文图 6–10，涵盖吞吐和仿真时间等。 | 是平台历史，不是 KV/EP 网络竞争证据。参见 Git 分支 iiswc24-artifact 的 evaluation/README.md。 |
| 2025 v0.1/v0.2 | 加入性能模型、PyTorch profiler 等；早期调度与 KV 管理逐步完善。 | 历史基线不应直接套用当前代码参数。参见 [CHANGELOG.md](CHANGELOG.md)。 |
| 2026 v1.0 / ISPASS26 artifact | P/D 拆分、MoE、前缀缓存、PIM、功耗/内存模型；图 5–10 分别验证 GPU 吞吐、功率、KV 缓存、其他模拟器对比、TPU 与 PIM。 | 证明功能范围与旧版验证路径，不能替代本次多流包级网络验证。参见 [artifact-evaluation.md](docs/docs/artifact-evaluation.md)。 |
| 2026 v1.1 及当前工作区 | Python Serving 前端 + profile CSV + Chakra DAG + ASTRA；另有实验性 FlowSim/native ns-3、P/D pairing、精确 A2A、物理 rank/NIC 映射等。 | 本报告实验的主要代码与证据平台。参见 [系统审计](KV_EP_SYSTEM_AUDIT.md)、[代码说明](docs/docs/contributor/codebase-tour.md)。 |

## 三、当前仿真器及网络流量的基础配置

### 3.1 一套可复算的基准配置

仓库没有唯一的“全局实验配置”。下表固定为大规模研究常引用的 **S16/EP64 Qwen3 场景**；后文的 1P2D、S64、Llama 和 Qwen3-32B 另标其配置。S16 文件与 manifest 分别为 [集群 JSON](experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_qwen.json)、[物理拓扑](experiments/pd_kv_ep/configs/large_scale/ns3/s16_8p8d_ep64_200g_clos.txt)、[拓扑/模型清单](experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_manifest.json)。

| 参数 | S16 配置及解释 |
|---|---|
| 模型 | Qwen3-30B-A3B-Instruct-2507，BF16；48 层，hidden 2048，Q heads 32，KV heads 4，head_dim 128，128 experts，top-k 8。[模型 JSON](configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json) |
| 物理规模 | 16 server × 8 GPU = 128 GPU；8 Prefill server、8 Decode server；每 server 4 个 TP2 instance；32 Decode instance 组成一个 EP64 group，每 EP rank 2 experts。 |
| 物理网络 | 4 leaf、2 spine，256 条物理链路；拓扑文件每链路 200 Gbps、0.005 ms。每端点 200 Gbps；16 根并行 leaf–spine 200-Gbps 链路构成 3.2-Tbps **聚合**流体资源，单 flow 仍受端点/NIC 约束。所用 rank→NIC 映射必须随 run 检查，不能默认每 GPU 独占网卡。 |
| 两种带宽字段 | 集群 JSON 的 link_bw=200 按 ASTRA logical network.yml 文档解释为 **200 GB/s**，link_latency=5000 ns；研究用物理 ns-3/FlowSim 拓扑文件写的是 **200 Gbps**。两者不可直接混为一个“200G”值。[配置字段说明](docs/docs/reference/cluster-config.md) |
| NPU 内存 | RTX PRO 6000，JSON 每 rank mem_size=96 GiB、mem_bw=1597 GB/s；未指定 mem_util 时 CLI 默认 0.9。CPU 每 node 512 GiB、256 GB/s。 |
| 默认调度与 KV | block_size=16 token；max_num_batched_tokens=2048、max_num_seqs=128；reserve_full_isl 开启；KV dtype=auto 即 BF16。P2D 默认 LAYERWISE，网络后端默认 analytical；FlowSim/native ns-3 均须显式选择，并提供物理拓扑/映射。 |
| EP 实现 | 普通 trace 的 MoE 通信为 ALLGATHER dispatch + REDUCESCATTER combine。研究实验的 A2A_P2P 明确启用并携带 pair_matrix 时才有稀疏逐 peer SEND/RECV。不能由“EP64”自动推断稀疏 A2A。 |
| 校准风险 | 现有 RTX PRO 6000 MoE profile 的 activated_experts 测量轴为 8、16、32、64、128；EP64 每 rank 只有 2 experts，EP32 为 4，绝大多数查询出域。故历史 EP64 integrated 时间可说明模型内的趋势，不可宣称已由真实 EP64 kernel 校准。 |

CLI 默认值见 [serving/__main__.py](serving/__main__.py)；内存容量实现见 [memory_model.py](serving/core/memory_model.py)；profile 范围见 [理论输入审计](research_theory_inputs/THEORY_INPUT_REPORT.md)。

### 3.2 KV block、token、传输的精确关系

对任一模型，KV_dim = KV_heads × head_dim；单 token 全模型 KV 字节 = 2(K、V) × KV_dim × 层数 × KV 每元素字节。TP rank 均分时再除以 TP。NPU block 覆盖 16 token，请求至少占 ceil(当前需驻留 token 数/16) 个 block；真实占用还受缓存命中、分块预填充、生成 token、共享/淘汰及预留策略影响。P2D **只传 K+V，不传 Q**；首轮 P 侧命中的 prefix 在默认 handoff 中仍需传给未持有它的 D。启用经过验证的 destination DELTA 时，只扣除 D 已 pin 住的匹配前缀。

Qwen3-30B-A3B BF16：KV_dim=4×128=512；**每层每 token 全 TP 为 2,048 B，每层 TP2 每 rank 为 1,024 B；48 层合计每 token 98,304 B，TP2 每 rank 49,152 B。** 因此一个 16-token block 是全 TP 1,572,864 B（1.5 MiB），每 rank 786,432 B（0.75 MiB）。下表假设全量 P2D、TP2、PP1、一次完整 prompt，无 destination hit；LAYERWISE 为 48 层 × 2 rank = 96 个 layer/rank SEND，分块 Prefill 时事件可进一步拆分。

| Prompt token | block 数/请求 | 每层每 TP2 rank P2D flow | 全 48 层、全 TP P2D | 每 TP2 rank 总量 |
|---:|---:|---:|---:|---:|
| 32 | 2 | 32,768 B | 3,145,728 B（3 MiB） | 1.5 MiB |
| 128 | 8 | 131,072 B | 12,582,912 B（12 MiB） | 6 MiB |
| 2,048 | 128 | 2,097,152 B（2 MiB） | 201,326,592 B（192 MiB） | 96 MiB |
| 4,096 | 256 | 4,194,304 B（4 MiB） | 402,653,184 B（384 MiB） | 192 MiB |
| 8,192 | 512 | 8,388,608 B（8 MiB） | 805,306,368 B（768 MiB） | 384 MiB |

按当前 [memory_model.py](serving/core/memory_model.py) 的 weight 公式和 S16 的 96 GiB/rank、0.9 利用率推导，Prefill TP2/EP1 约占 55.447 GiB 权重，**42,260 个 block/rank，676,160 token 容量**；Decode TP2/EP64 约占 2.291 GiB 权重，**114,836 个 block/rank，1,837,376 token 容量**。这是以源码重算的容量上界，不是 vLLM 实测 num_gpu_blocks：模型尚未扣除 activation peak、CUDA context。它也不说明已经同时容纳这么多请求，max_num_seqs 和动态状态仍限制调度。FP8 KV 字节与 block 容量相应减半/约翻倍，且必须使用相应 profile variant。

最近的 R18/19 使用另一套 **Llama-3.1-8B BF16 / RTX4090 TP1 / 16-token block**：每 token 131,072 B、每 block 2 MiB，正常 D 池为 **3,400 blocks=54,400 token**；2,048-token 全量 handoff 为 268,435,456 B，64-token delta 为 8,388,608 B。R20 理论筛查使用 **Qwen3-32B TP2**：每 token 262,144 B、每 rank 每 block 2 MiB，96 GiB/rank、0.9 下 **28,614 blocks/rank=457,824 token**。这些数不可与 S16 Qwen MoE 容量混用。[R18 动机](research_autonomous/MOTIVATION_REPORT.md)、[R20 理论卡](research_autonomous/theory/r20_held_kv/card.md)。

### 3.3 EP 每条、每层、每步、总流量

**精确路由 A2A_P2P：**对 Qwen BF16，一个被选中的 expert 接收一份 2048×2 = **4,096 B** hidden activation；其 combine 返回同尺寸。若路由矩阵 M(i,j) 是从源 EP rank i 到 expert-owner rank j 的 expert-token 数，则非本地 dispatch flow(i→j)=4,096×M(i,j) B，combine flow(j→i) 同量。每层所有网络 EP payload = 8,192×Σ(i≠j)M(i,j) B。单有效 token 路由 top-k=8 时，**含本地路径的逻辑上限**为 dispatch 32,768 B + combine 32,768 B = 65,536 B/层；48 层为 **3,145,728 B/token（3 MiB）**。一个 Decode step 有 S 个有效 token 时逻辑上限为 3,145,728×S B；O 个单请求 Decode step 则为 3,145,728×O B。实际网内字节需扣除本地 expert，并按真实 token→expert 路由、coalescing、TP/DP 对应关系与物理 cut 读取事件账本；不能把逻辑总量当一根链路负载或替代实测路由。

**普通 AG/RS trace：**dispatch 的 Chakra per-rank 输入是 max(1, floor(S/EP))×(2048+128)×2 = max(1, floor(S/EP))×4,352 B；combine 的 per-rank 输入是 S×2048×2 = S×4,096 B。S 为代码使用的有效/padded token 计数，DP group 会按 trace 的 max_total_len 口径设置，具体需查 run。FlowSim direct-peer 展开中，每个远端 peer 接收完整 dispatch local chunk；combine 每远端 peer 接收 ceil(combine_input/EP) B。例如 EP64、S=64：每 rank 的 63 条 dispatch peer flow 各 4,352 B、63 条 combine peer flow 各 4,096 B；全组每层分别 17,547,264 B 和 16,515,072 B，合计 **34,062,336 B/层、1,634,992,128 B/48层 Decode step**。这些是 **FlowSim direct-peer 展开字节**，不是 native ASTRA ring/tree 实际跨物理网总字节，也不是 64 个独立请求各自的 EP 流量。S<EP 时 max(1, floor(S/EP)) 使简单的“按每 token 线性缩放”不成立。[trace_generator.py](serving/core/trace_generator.py)、[flowsim_worker.py](serving/core/flowsim_worker.py)、[MoE 语义审计](research_audit/02_THEORETICAL_CONTENTION_MODEL.md)。

EP collective CCT 是本轮所有必需 peer 的最后完成时间减 collective start；它不是任一单 flow FCT。48 层各有 dispatch/compute/combine 依赖，具体总时延还要加入核函数、TP 通信、batch 调度与可隐藏的重叠。

### 3.4 路径、网络模型和大规模 trace 所在位置

| 工件 | 当前路径/意义 |
|---|---|
| 主模型 profile | [profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507](profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507)，按 variant/tpN 存 dense、attention、moe 等 CSV；实际目录以 resolve_variant 和 run manifest 为准。 |
| 物理拓扑 | [S16 200G Clos](experiments/pd_kv_ep/configs/large_scale/ns3/s16_8p8d_ep64_200g_clos.txt)、[S64 200G Clos](experiments/pd_kv_ep/configs/large_scale/ns3/s64_64_servers_200g_clos.txt)；FlowSim 需显式拓扑及 logical-rank→physical-endpoint 映射，ns-3 用拓扑和 packet config。 |
| Azure converted | [Conversation 8.416 GB](experiments/pd_kv_ep/workloads/real/azure2024/conversation/converted.jsonl)，[Code 5.159 GB](experiments/pd_kv_ep/workloads/real/azure2024/code/converted.jsonl)。原始一周 CSV 在父目录。 |
| BurstGPT converted | [437.7 MB](experiments/pd_kv_ep/workloads/real/burstgpt/converted.jsonl)；原始 BurstGPT_1.csv 同目录。 |
| Mooncake converted | [Tool/Agent](experiments/pd_kv_ep/workloads/real/mooncake_fast25/toolagent/converted.jsonl)、[Conversation](experiments/pd_kv_ep/workloads/real/mooncake_fast25/conversation/converted.jsonl)；hash_ids 是 opaque block ID，不是 token ID。 |
| 更新的生产 trace | [SwissAI exact-model Qwen3-32B，4.618 GB](research_autonomous/workloads/swissai_raw/qwen3-32b-buckets.jsonl)；[Qwen-Bailian 原始目录](research_autonomous/workloads/qwen_bailian_raw)、[来源矩阵](research_autonomous/workloads/SOURCE_MATRIX.md)。前者有时间/长度/16-token bucket ID，但无生产 P/D/NIC 布置和 D cache 实际驻留。 |
| 选定窗口 | [real/slices](experiments/pd_kv_ep/workloads/real/slices) 下按来源和 30/60/300 秒编号；严禁把窗口实验称全量 week replay。 |
| 运行时 Chakra graph | astra-sim/inputs/runs/运行ID/workload/硬件/模型/批次/llm.某rank.et；例如 [保留的一组 BurstGPT S16 graph](astra-sim/inputs/runs/jointcap_burstgpt_w148333_n16_alpha1_naturalcompact_noflowdetail/workload/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/dp_decode_ep64_pool000_batch10/llm.78.et)。 |
| 可读 trace 文本 | astra-sim/inputs/runs/运行ID/trace/instanceN_batchM.txt；需 --save-trace-text，且隐含 --keep-inputs。默认不写文本，成功后默认清理中间输入。Chakra converter 在内存读取 rows，不依赖文本。[graph_generator.py](serving/core/graph_generator.py)、[trace 格式](docs/docs/reference/trace-format.md)。 |

Azure Code/Conversation 分别有 16,803,695/27,303,999 条，BurstGPT 有 1,429,737 条，Mooncake Tool/Conversation 分别 23,608/12,031 条。S64=64 server/512 GPU、P:D=32:32、EP16；S256=256 server/2048 GPU 是配置与尺度门禁，**尚无全量 packet integrated TTFT/TBT/SLO 矩阵**。这与已完成的 8/16/64 请求或 ≤25,000 请求候选窗口不同。[trace 总账](TRACE_WORKLOADS.md)、[规模计划](LARGE_SCALE_PLAN.md)。

## 四、研究主线：可直接拆成 PPT 的分点版

**总览：**KV/EP 竞争 → Serving 临界路径 → 共享 NIC 与物理拥塞 → Prefill cache 缩短计算掩蔽 → 自然负载频率 → 其他联合机制 → P/D KV 驻留与容量联动。每一箭头都由上一方向的证据缺口触发；自然 trace 筛查贯穿多个方向，这里集中汇报。

**LAYERWISE 发送点的证据边界：**阶段一的四请求独立 FlowSim 构造器把每层 KV 事件放在该层 profile 时间末尾；阶段二等集成仿真由 Chakra 在 `qkv_proj` 后接出该层 SEND。两者都不是已校准的真实 KV cache 写入/网络读取时间。vLLM 的 Qwen3 路径在 `qkv_proj` 后还执行 Q/K 归一化、旋转位置编码和 attention；缓存写入由 attention 路径处理。因此下文“KV 比 Prefill 早到 2.367 ms”只说明**当前集成仿真图的时序**，尚需把发送点移到 cache 更新完成或 attention 结束后复核。[独立构造器](experiments/pd_kv_ep/scripts/build_flowsim_motivation.py)、[集成 trace](serving/core/trace_generator.py)、[Chakra 发送依赖](astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py)、[vLLM v0.19 Qwen3](https://github.com/vllm-project/vllm/blob/v0.19.0/vllm/model_executor/models/qwen3_moe.py)、[vLLM cache update](https://github.com/vllm-project/vllm/blob/v0.19.0/vllm/model_executor/layers/attention/attention.py)。

### 阶段一｜发现 KV/EP 竞争：三类策略为何产生不对称影响

- **起因与目标：**P2D 的长 KV 流和 Decode 的短 EP collective 共用链路；比较 FAIR、KV_FIRST、EP_FIRST，确认谁受损、谁可被优先级保护。
- **怎么验证：**
  - 人工 ns-3：100 Gbps host link、共享 ToR 出端口、1 GiB KV 加周期 EP burst；跑 KV_ONLY、EP_ONLY、RR、STRICT_EP、WRR。
  - 模型驱动：Qwen3-30B-A3B、48 层、TP2、EP2、200 Gbps；3 个 Decode 请求 + 1 个新 P2D，请求长度 128/8,192 token，比较三策略与 POST_PREFILL/LAYERWISE。
  - 包级匹配复核：固定 Decode cohort，仅加入 1×512、1×2,048、2×2,048-token P2D；最后一组 KV 共 402,653,184 B。
- **结论与原因：**
  - 人工 RR 下，EP 尾完成相对 EP_ONLY 为 9.6–58.6 倍，KV 相对 KV_ONLY 为 1.03–2.06 倍；STRICT_EP 将 EP 压回 EP_ONLY 的 1.009–1.024 倍。
  - 8,192-token POST_PREFILL 中，**相对 FAIR**，EP_FIRST 的 EP CCT P99 −24.71%、KV FCT 约不变；KV_FIRST 的 EP CCT +10,027.81%、KV FCT −2.29%。另有 native ns-3 配对实验：两条 2,048-token KV 流使匹配 EP P99 从 6.545 升至 13.270 µs。
  - EP 要等最后一个必需 peer 完成；KV 的层级流量可与后续 Prefill 计算并行。该结论限于上述尺寸与发送时机：128-token POST_PREFILL 的 KV FCT 也曾 +10.670%。[早期汇总](MOTIVATION_RESULTS.md)
- **为何转向：**上述指标是 flow FCT 或 collective CCT，还要确认是否真的推迟请求 TTFT/TBT。

**阶段一/二共用的策略对照（同一四请求 FlowSim，均相对本行 FAIR）：**Qwen3-30B-A3B、TP2/EP2、200 Gbps，共 3 条已有 Decode + 1 条新 P2D；8,192-token 和 128-token 各跑三策略。EP 指 Decode collective CCT P99，KV 指新请求从首个 P2D 发送事件到全部 KV 到达的跨度；`+` 为变慢，`−` 为变快。[POST_PREFILL 原始结果](experiments/pd_kv_ep/results/flowsim_layerwise_motivation_200g/post_prefill/SIMPLE_MOTIVATION_REPORT.md)、[LAYERWISE 原始结果](experiments/pd_kv_ep/results/flowsim_layerwise_motivation_200g/layerwise/SIMPLE_MOTIVATION_REPORT.md)。

| 模式、Prompt | FAIR：EP / KV | EP_FIRST 相对 FAIR：EP / KV | KV_FIRST 相对 FAIR：EP / KV |
|---|---:|---:|---:|
| POST_PREFILL，8,192 | 0.127330 / 16.485118 ms | −24.71% / ≈0% | +10,027.81% / −2.29% |
| LAYERWISE，8,192 | 0.127330 / 143.440060 ms | −24.71% / 0% | +238.82% / 0% |
| POST_PREFILL，128 | 0.104877 / 0.280172 ms | −8.59% / 0% | +231.37% / −9.64% |
| LAYERWISE，128 | 0.101115 / 5.575287 ms | −5.19% / +0.20% | 0% / −0.28% |

**读表要点：**POST_PREFILL 为 2 条 TP shard 一次发出，LAYERWISE 为 48 层 × TP2 共 96 个逐层释放事件；后者的 KV 跨度包含层间计算/释放间隔，因此不能把 143.440 ms 与 16.485 ms 当作同一笔纯网络服务时间比较。原报告的 +13,351% 指 KV_FIRST 相对 **EP_ONLY**，上表 +10,027.81% 才是用户要求的 **相对 FAIR**。这四组是网络事件重放，不是闭环 TTFT/TBT。

### 阶段二｜检查端到端效应：发现 KV 延迟被分层流水吸收

- **起因与目标：**集成仿真器的 LAYERWISE 把 SEND 接在每层 `qkv_proj` 后，Prefill 图随后仍执行 attention、MoE、后续层和最终 sampler；这是模拟发送点，不等于证明真实 cache 已可发送。即使把最后一层的发送移到 attention 完成后，该层的 `o_proj`、MoE 和最终 head 仍未完成。若最后 KV 在模拟 Prefill 结束前到达，网络变慢但未越过完成屏障，就可能不改变 P2D-ready；因此要把网络事件接到 Serving 调度与 token 完成事件。
- **怎么验证：**
  - EP4/100G 闭环：3 个各输出 128 token 的 Decode 请求 + 1 个 8,192-token P2D；三策略同请求集对照。
  - S16/EP64 闭环：16 server×8 GPU、8P8D、TP2、200G，32 个 active Decode + 64 个 2,048-token P2D，每个 Decode 输出 4 token。
  - 严格共享 cut：1P2D/EP16、每 server 两条 200G NIC；先让 D cohort 完成 4 个 token，再注入 8,192-token KV；D_ONLY、K_ONLY、FULL 匹配比较。
- **结论与原因：**
  - EP4/LAYERWISE：FAIR、EP_FIRST、KV_FIRST 的 EP CCT P99 分别为 11.860、9.365（−21.04%）、148.982 µs（+1,156.17%）；Decode TBT P99 为 5.541、5.526（−0.27%）、6.003 ms（+8.34%）。三者 P2D TTFT 均为 925.320 ms，说明这组 KV 请求完成没有随策略改变。[EP4 闭环](experiments/pd_kv_ep/CHARACTERIZATION_REPORT.md)
  - 受控 EP64：FAIR→EP_FIRST 使 Decode TBT P99 从 26.041 降至 7.421 ms，P2D TTFT P99 仍为 292.119 ms；EP64 的每 rank 2-expert 核函数时延超出已有 profile 的测量轴，绝对值须谨慎使用。
  - D64K1：在现有 `qkv_proj` 发送点下，最后 KV shard 多耗 41.945 µs（+23.568%），于 454.107 ms 送达；Prefill 图到 456.474 ms 才结束，尚有 2.367 ms 模拟重叠空间。已获 D credit 时，ready 由两者中较晚者决定，故本次 P2D-ready 不变，Decode TBT P99 只 +0.122%；发送点后移的敏感性尚未验证。[容量校准事件](experiments/pd_kv_ep/CAPACITY_CALIBRATED_KV_EP_RESEARCH.md)
- **为何转向：**在当前集成仿真图中，网络时间在端到端时间中占比小，LAYERWISE 发送可与后续计算重叠；于是尝试让多 GPU 共用 NIC，并改变接收端放置来增大真正共享的网络 cut，同时保留真实 KV 可发送时刻的校准任务。

### 阶段三｜尝试 NIC 共享调度、接收端放置和拥塞控制

- **起因与目标：**检查分散路径是否掩盖了资源争用；如果多个 GPU 共享一条真实 NIC，流量调度或 receiver 选择是否能影响 Serving。
- **怎么验证：**
  - 共享 NIC FlowSim：4P+2D server、每台 8 GPU/两条 200G NIC，18 条 P2D 与 8 条 Decode seed 请求；在同一 D 接收 rail 上比 FAIR、KV_FIRST、EP_FIRST。
  - 物理 packet：S16/EP64、32D+64P2D、4 KiB packet、16 条并行 leaf–spine 链路，比较 spread 与 fan-in16；另测 4P1D 的 4→1/2/4 条接收 NIC。
  - 对照 DCQCN 开关、TOP5 关键 EP peer 优先级、P/D pairing 与 alternate spine；保持请求字节不变。
- **结论与原因：**
  - 共享 D NIC rail 的时间加权占用达 87.29%，但 FAIR→EP_FIRST 的 mean TPOT 仅 6.045367→6.008587 ms（−0.61%），ITL P99 不变；KV_FIRST 才把 TPOT 推到 8.733146 ms。EP_FIRST 已覆盖可见的类别调度收益。[NIC 共享门槛](research_motivation/nic_priority/10_FINAL_MOTIVATION_DECISION.md)
  - 修正并行链路路由后，fan-in16 的单流 FCT P99 +34.9%、EP CCT P99 +29.1%，请求 KV handoff P99 仅 +0.39%。旧的 KV +23.44% 来自把 16 条并行链路误合并，已撤回。
  - 4→1 NIC 的 packet 平均 FCT 为 32.481 ms，分散到 2 NIC 为 16.261 ms；最后 KV 仍比 Prefill 完成早 0.356 ms。DCQCN 可使长 KV 单流 P99 +85.9%，请求 handoff P99 仅 +0.66%。[物理网络复核](experiments/pd_kv_ep/RESEARCH_HISTORY_AND_RESULTS.md)、[incast 复核](research_ns3_incast/12_FINAL_GO_NO_GO.md)
  - TOP5 只保护此前最慢的 EP peer，却会换出新的最后 peer：两组 packet 窗口的 EP CCT P99 相对 EP_FIRST 恶化 39.9%–57.7%，KV P99 至多改善 0.33%。静态关键 peer 标记未打开可靠的双边收益。[关键 peer 复核](experiments/pd_kv_ep/PACKET_LEVEL_AUTONOMOUS_RESEARCH.md)
- **为何转向：**已能制造物理网络拥塞，但 Prefill 计算仍覆盖最后 KV 完成时刻；下一步缩短 Prefill 计算跨度，寻找网络真正进入请求临界路径的条件。

### 阶段四｜尝试 Prefill cache 复用：缩短计算掩蔽，暴露全量 KV 传输

- **起因与目标：**cache 命中会缩短 Prefill 计算；若 P 命中而 D 未驻留前缀，D 仍需要全量 KV。这样即使仍按层传输，网络也可能不再被长 Prefill 流水隐藏。
- **怎么验证：**
  - Llama-3.1-8B/RTX4090/TP1：1、2、4、8 张 P GPU 共用 100G source NIC；预热 1,984-token prefix，目标追加 64 token；D-miss 与已有副本的 D-hit 对照，保持目的端和物理链路资源不变。
  - 为排除“空闲 warm D 可选”的反例，再让 8P2D 中两台 D 接受 64 条不同 filler（每 D 32 条、每 P 8 条）；观察 8 个目标前缀是否经正常淘汰后同时在 D miss。
  - 并行检验 remote-prefix/provider 选择、合法 split-source、目的端 prefix pin/DELTA、Progressive Push；分别核对复制成本、Prefill 的 prefix 依赖和真实 first-token 事件。
- **结论与原因：**
  - 单层全量 KV 在 100G cut 的发送下界为 671 µs；profile 的冷 Prefill block 约 5,995 µs，1,984-token hit 后只约 614 µs。两股及以上共享源 NIC 时，网络服务需求开始超过热 Prefill 的层级计算间隔。
  - 8P 的热 P、冷 D 使 P2D-ready 为 171.876 ms，几乎贴合 171.799-ms 链路下界；D 已驻留时只需 64-token delta，ready 为 20.969 ms。但这一组有空闲 warm D，普通 cache-aware 选 D 就能规避 miss，尚无新调度收益。[cache 暴露实验](research_autonomous/ROUND12_PREFIX_INVERSION.md)
  - 8P2D 普通淘汰后，8/8 个目标仍 P-hit、D-miss，ready 仍为 171.876 ms；该 100G cut 的全量服务下界是 171.799 ms，改变同一 cut 的发送顺序已无 10% 空间。真实请求是否常产生 8 个不同热前缀的短窗，仍需查来源 trace。[R13 逐轮记录](research_autonomous/ITERATION_INDEX.md)
  - Mooncake 既有副本在 packet replay 中把 remote barrier mean 从 7.605 降至 1.633 ms；计入副本 warm-up 的闭环 TTFT P99 却从 238.698 升至 274.939 ms。DELTA 可把 child P2D 从 403,537,920 B 降至 884,736 B，但完整会话 mean 只改善 2.59%；少传字节仍要看完整请求路径。[远端前缀](experiments/pd_kv_ep/RESEARCH_HISTORY_AND_RESULTS.md)、[DELTA 复核](research_cache_network_joint/12_FINAL_GO_NO_GO.md)
  - 合法 split-source 须同时给 Prefill 提供 prefix，双目的地版本使命中请求 TTFT 反增 22.9%–61.1%；Progressive Push 在 200G 小型匹配实验中 TTFT P99 降 6.07%，TBT 不变，旧 50G 的 −20.22% 因拓扑编号冲突撤回。[split-source 审计](experiments/pd_kv_ep/P4_SPLIT_SOURCE_RESEARCH.md)、[Push 审计](experiments/pd_kv_ep/PROGRESSIVE_PUSH_RESEARCH.md)
- **为何转向：**受控 filler 已证明 P-hit/D-miss 可以由正常 D 淘汰产生，但共享源 cut 已贴近物理下界；转而检查生产请求里这种多前缀短窗有多常见，以及是否存在容量与调度联动的新增空间。

### 阶段五｜用自然 trace 检查：关键碰撞与热前缀场景是否常见

- **起因与目标：**受控同步 burst 能证明机制，不能证明生产请求会频繁落在同一关键 cut；这一自然负载门槛横贯 KV/EP 和 cache 两条线。
- **怎么验证：**
  - Azure S8/EP32 的原序 16 请求：保持真实 arrival/长度，审计 P2D/EP 同向重叠与关键 peer；S16/EP64 的 Azure Conversation16、Code32 做 matched FAIR/EP_FIRST 闭环。
  - Qwen-Bailian 269,681 条有序请求筛 1,984–2,304-token、短输出、不同热前缀的 100-ms/1-s 窗；另查 Chutes 精确模型高命中记录及来源偏斜，SwissAI 精确模型 trace 留作后续容量筛查。
- **结论与原因：**
  - Azure16 虽有 24.910 ms 跨请求并存，只有 8.98% 的关键或近最后 EP peer 同时满足 KV 同向路径与时间条件；FAIR 相对隔离的 EP CCT P99 只 +0.525%、KV handoff P99 只 +0.00475%。
  - 自然 Azure matched 策略：Conversation16 的 TBT mean −0.00067%，Code32 的 TBT P99 −0.2754%，P2D-ready 分布不变。仅有全局时间重叠，无法保证最慢 EP peer 或最后 KV shard 被推迟。[自然对照](experiments/pd_kv_ep/PD_MOE_NETWORK_PAPER_PROBLEM_FINAL_NO_GO.md)
  - Qwen-Bailian 近 profile 长度只有 440 个候选；100 ms 或 1 s 内最多两个不同热前缀，不支持受控 8P 热前缀 burst 的常见性。SwissAI 有 arrival/长度/bucket ID，但没有生产 P/D/NIC 布置或 D 驻留。[逐轮来源索引](research_autonomous/ITERATION_INDEX.md)
  - Chutes shard40 虽有 1,102 万条 >88.3% 报告命中率的请求，但 95.2% 调用来自单一用户，且缺精确 prefix ID 和 P/D/NIC 状态；高命中比例不能推导真实冷 D 全量传输频率。[逐轮来源索引](research_autonomous/ITERATION_INDEX.md)
- **为何转向：**类别优先级缺自然频率证据；继续找同时影响网络与 Serving 资源的结构性瓶颈，并要求同资源强基线。

### 阶段六｜继续试过的替代方向：逐一检查是否有新增空间

- **起因与目标：**类别优先级和 receiver 选择空间有限，转而检查同类流排序、collective 相位、通信结构、按层消费、agent 工作负载。
- **阶段内的方向切换：**
  - 类别优先级收益见顶 → 精确 receiver assignment 与关键 EP peer 选择：检查放置和少量保护能否替代全类优先。
  - 放置收益极小、关键 peer 会转移 → EP–EP collective 相位与 KV–KV 同类 coflow：检查跨请求或同类流的阻塞。
  - 同类流已被 FIFO/SRPT 覆盖 → Decode batch 边界与按层 KV 消费：检查网络延迟能否越过 Serving 调度门槛。
  - 边界仍未变化 → sparse A2A、lower-tier/异构 TP、agentic/decode skew：检查是否存在不同的通信语义或负载来源。
- **怎么验证：**
  - 3P2D/2,048-token 的 8 种 receiver assignment；两组独立 EP4、8 请求共 200G cut，首轮错开 20 µs；POST_PREFILL 双 KV 共 rail、KV-KV/EP-EP 同类流对照。
  - PP2 的 4P1D/200G 接收端 coflow；1P2D/EP4 的 Decode batch-miss 门槛；EP32/64 sparse A2A/owner streaming 的真实 expert route、profile 和物理 rank 检查。
  - 按层 KV 消费的 4 会话 Qwen3/TP2/4P1D/200G fixture；agent fork、lower-tier prefetch、异构 TP、decode skew 的来源与强基线检查。
- **结论与原因：**
  - 精确 receiver 最优相对 greedy 只多改善 0.00422%；EP4 相位错开消除 2,976 对 collective 重叠，mean ITL 仅改善 0.793%、makespan 0.638%。同类 KV POST_PREFILL 可令一条 TTFT +5.857%，但普通 FIFO/SRPT/coflow 给出相同流序。[联合候选](research_joint/15_FINAL_GO_NO_GO.md)、[KV coflow](research_motivation/kv_handoff/08_FINAL_GO_NO_GO.md)
  - batch-miss 场景最后 KV flow 由 177.973 升至 684.649 µs，P2D-ready 与 Batch9 选择仍相同；理论上约需 19 条同时释放的全尺寸流越过计算和 batch 边界，已测配置最多只有 4 条。[batch-miss 复核](research_motivation/batch_miss/10_FINAL_MOTIVATION_DECISION.md)
  - PP2 的 0.336-ms KV wave 低于 1.339-ms 阶段计算，最后流仍早于 ready 1.157 ms。按层消费 Oracle 可遮住 5.471-ms 传输尾段，但 token2 已与简单 DELTA 同为 191.570 ms，且缺独立客户端发 token 事件与可用的逐层 Decode 提交语义。[PP2 筛查](research_autonomous/ITERATION_INDEX.md)、[按层消费审计](research_token_consumption_scheduling/08_FINAL_GO_NO_GO.md)
  - sparse A2A 缺真实 token→expert route，EP32/64 的每 rank 4/2 expert 也落在 profile 最小测量值 8 之外；不能给出合法性能收益。agentic 765 个 prompt 的 sidecar 每个缺 141 个 token ID，CXL miss 未计时；249 个可行串行 skew split 全变慢。[稀疏门槛](research_sparse_foundation/12_FINAL_RESEARCH_DECISION.md)、[逐轮索引](research_autonomous/ITERATION_INDEX.md)
- **为何转向：**多数改动只改变局部流时间、被简单基线覆盖，或缺完整输入语义；因此把研究焦点转到 P/D 两侧 KV 驻留与 D 容量 credit 的联动。

### 阶段七｜当前方向：P 命中、D 淘汰后的全量重传与容量阻塞

- **起因与目标：**热 P 缩短了计算，但只有 D 自然 miss、源 NIC/目的容量成为瓶颈时，额外网络字节才可能稳定影响完成时间。
- **怎么验证：**
  - R18：Llama8/RTX4090/TP1、2P1D、共享 100G source cut、D 正常 3,400-block 池；预热两个不同的 1,984-token 前缀，用 24 与 28 条 2,048-token filler、普通 refresh 三组对照。
  - R19：同资源下加入异构已到达历史，比较 LRU/LFU/DELTA；4P1D、四条 14k-input/64-output 总需约 3,504 blocks，对比 EARLY_POST、TWO_STAGE_FIFO 与网络 FIFO。
- **结论与原因：**
  - D 需求由 24 fillers 时的 3,320 blocks（可放）升至 28 fillers 时的 3,832（超 3,400），P 仍保留前缀；每目标从 64-token delta 变成 2,048-token 全量 KV。目标 P2D-ready 20.969→43.027 ms，模型完成 56.971→79.029 ms；普通 refresh 恢复原值。[R18 因果对照](research_autonomous/MOTIVATION_REPORT.md)
  - 两目标全量 KV 在 100G cut 的发送下界为 42.950 ms，实测 ready 43.027 ms，说明全量传输确实在关键路径；这是动机验证。
  - 加入合法历史后，普通 LFU 已使目标回到 56.971 ms；普通 TWO_STAGE_FIFO 使末完成 6.487→4.842 s，距条件 admission oracle 仅 12.2 µs。现有受控 fixture 没证明新算法超过强基线。[R19 强基线](RESEARCH_LOG.md)
- **因此进入下周：**用 SwissAI 的有序 exact-model trace 搜索“P 源块被占、D credit 等待、网络与 Decode 同时在临界路径”的真实共现窗口；先算强基线后上界，再决定是否扩展 TP2 仿真。

### 可在 PPT 末页使用的研究判断

- **已确认的机制：**特定共享 cut 上的 KV/EP 竞争、EP 集体屏障敏感、分层 KV 的计算掩蔽，以及受控 P-hit/D-miss 导致全量重传。
- **尚未确认的论文空间：**自然工作负载中的发生频率、完整客户端指标上的稳定收益，以及超过 EP_FIRST、LFU、DELTA、TWO_STAGE_FIFO、网络 FIFO 等强基线的新增收益。
- **本阶段取舍：**以自然来源和临界路径筛查决定下一步；R20 目前仅为 THEORY_SCREENED / NEED_DATA，不能将 27/28 个 held 请求的容量阈值当成已测策略收益。[当前候选状态](CANDIDATE_STATUS.md)

## 五、哪些数字必须从正式汇报中撤回或降级

| 旧说法或看似正面的结果 | 现在应使用的口径 |
|---|---|
| S16 FULL-vs-KV_ONLY 的 KV +23.44% 可证明 EP_FIRST 会拖慢 KV。 | 旧 FlowSim 平行链路被合并为一根；修复后的同网络重放为 0%，且 FULL-vs-KV_ONLY 也不是 EP_FIRST-vs-FAIR。 |
| 旧 S16 packet fan-in KV request P99 +96.5%、EP P99 +54.3%。 | route table 遗漏平行物理链路；修正后相应 KV request +0.39%、EP CCT +29.1%，仍是 packet/network-only。 |
| 50G Progressive Push TTFT -20.22% 可以作为拓扑正确的论文 PASS。 | 旧 1P(TP1)+2D(TP2) 拓扑 rank4 与 switch ID4 冲突；合法修正拓扑未获得相应 integrated TTFT。 |
| 旧 CC_MODE=12 是 DCQCN。 | 当前分支已验证的 DCQCN 反馈是 CC_MODE=1；旧模式可报独立 ECN telemetry，但不能报 sender rate evolution。 |
| 远程复制/纯 split-source 可免费缩短 TTFT。 | replica warm-up 要计成本，Prefill 必须拥有 prefix attention state；合法 V1 双目的地反而恶化 TTFT。 |
| EP64 模拟 TBT 已由真实 EP64 MoE profile 校准。 | AE=2 查询落在现有 profile 最小 AE=8 之外，只能用于趋势性模拟机制。 |
| Prefix-hit 实验的 16.82% 是真实 TTFT 优化。 | 用 P2D-ready 充当 TTFT 的旧上界被后续同源事件复核否定；sampler-ready 不变、没有独立客户端发 token 时间。 |
| Round18 22.058 ms D-state 差或 two-stage 25.35% 是新算法收益。 | 前者是动机，后者是普通两阶段 FIFO 对旧提前 credit 协议；合法 LFU/FIFO 已覆盖受控 fixture。 |
| 所有大规模 trace 已完成 packet + Serving SLO 验证。 | 只完成选定 bounded 小窗、若干 FlowSim 集成与 network-only packet replay；S64/S256 全量矩阵未完成。 |

原始失效说明见 [FAILED_RESEARCH_ATTEMPTS.md](experiments/pd_kv_ep/FAILED_RESEARCH_ATTEMPTS.md)、[RESEARCH_HISTORY_AND_RESULTS.md](experiments/pd_kv_ep/RESEARCH_HISTORY_AND_RESULTS.md)、[最终审计](research_final_audit/06_KV_EP_FINAL_GO_NO_GO.md)。

## 六、现在可承诺的结论与未完成事项

**已证实：**模型驱动 KV/EP 在特定共享有向链路上竞争；EP collective 的最后 peer 易放大 CCT；**当前仿真图中的** LAYERWISE P2D 流水可隐藏显著 KV flow 延迟（真实 cache 完成后发送的重叠量未校准）；某些物理 incast/DCQCN/前缀驻留机制在受控场景成立；目的端前缀 pin/DELTA 和两阶段 credit 的模拟器协议可按现有测试运行。

**尚未证实：**真实生产 P/D/NIC 配置中该组合的发生频率；packet 网络完成对同一次 Serving 调度的客户端 TTFT/TBT/SLO 收益；优于 EP_FIRST、FIFO、LFU、DELTA、cache/load/network routing 和已有 stage-aware 调度的显著新增收益；同一自然 trace 的 system/network/joint 四格协同；可校准的 EP32/64 sparse A2A 绝对延迟。未测量不是零。

若下一阶段继续，R20 的判别步骤已足够具体：先用 SwissAI 原始有序 trace 检查 **P 源块持有阻止新 Prefill + D credit 阻塞 + 网络/Decode 时间暴露** 是否同时出现；再用相同 GPU/NIC、相同请求和 bytes 的 TWO_STAGE_FIFO、网络 FIFO/SRPT、LFU/DELTA 与 cache-aware routing 组合推导合法上界。若理论上仍无 ≥10–15% 强基线后空间，则停止，不做新策略大规模仿真。[候选状态](CANDIDATE_STATUS.md)、[R20 理论卡](research_autonomous/theory/r20_held_kv/card.md)。

## 七、证据索引与复核方式

- **系统与计量：**[系统审计](KV_EP_SYSTEM_AUDIT.md)、[理论输入报告](research_theory_inputs/THEORY_INPUT_REPORT.md)、[trace 格式](docs/docs/reference/trace-format.md)、[配置参考](docs/docs/reference/cluster-config.md)、[CLI 参考](docs/docs/reference/cli-flags.md)。
- **早期至 2026-10-02：**[实验历史](EXPERIMENT_HISTORY.md)、[动机结果](MOTIVATION_RESULTS.md)、[主实验历史](experiments/pd_kv_ep/RESEARCH_HISTORY_AND_RESULTS.md)、[失败实验](experiments/pd_kv_ep/FAILED_RESEARCH_ATTEMPTS.md)；每组具体原始 CSV/JSON 与脚本在 [experiments/pd_kv_ep](experiments/pd_kv_ep)。
- **自然暴露与联合方向：**[joint_exposure](experiments/pd_kv_ep/joint_exposure/reports)、[research_audit](research_audit)、[research_joint](research_joint)、[research_final_audit](research_final_audit)。
- **后续物理/缓存/稀疏方向：**[ns-3 incast](research_ns3_incast)、[prefix exposure](research_prefix_exposure)、[cache/network](research_cache_network_joint)、[token consumption](research_token_consumption_scheduling)、[sparse foundation](research_sparse_foundation)、[new mainline](research_new_mainline)、[motivation 子问题](research_motivation)。
- **逐轮最新记录：**[RESEARCH_LOG.md](RESEARCH_LOG.md)、[R1–R20 索引](research_autonomous/ITERATION_INDEX.md)、[R18 冻结图文](research_autonomous/MOTIVATION_REPORT.md)、[当前候选状态](CANDIDATE_STATUS.md)、[来源矩阵](research_autonomous/workloads/SOURCE_MATRIX.md)。按每个 run 的 manifest/hash 与原始事件账本复核；未提交工作区不能仅以 Git commit 绑定结果。

**建议 PPT 排布：**第三节参数表、第四节七阶段路线与关键数字、第五节旧结果降级、第八节下周判别计划。展示性能时给每个数字标明模型、TP/EP、物理 cut、workload、后端、policy 对照、统计单位和是否闭环 Serving。

## 八、下周计划（2026-10-19—10-23）：先判定真实共现，再决定是否做新调度

**目标：**在 SwissAI Qwen3-32B 有序 exact-model trace 上，检验“P 持有 KV 阻塞新 Prefill、D 容量 credit 等待、传输/Decode 同时在完成时间临界路径”是否共现；只把 **4P1D、TP2、每 rank 200 Gbps** 当成声明过的假设拓扑。SwissAI 未给生产 P/D 角色、NIC 或 D 实际驻留，结果只能解释该假设下的来源负载潜力。[R20 理论卡](research_autonomous/theory/r20_held_kv/card.md)

| 时间 | 具体工作与怎么验证 | 当日交付及判别点 |
|---|---|---|
| 周一：锁定来源 | 固定 SwissAI 原始文件 hash、时间顺序、长度和 bucket ID；只从原始 arrival 中抽有序窗口，匹配已完成请求的前缀，不合成同步 burst。 | 候选窗口清单：原始行号、到达时刻、长度、前缀历史、可复算脚本；报告候选数及窗口发生频率。 |
| 周二：筛容量共现 | 用 RTXPRO6000/Qwen3-32B BF16/TP2 profile 与 0.9 内存利用率重放 P block 占用及 D credit；比较提前 credit 与 TWO_STAGE_FIFO。16,384-token held 请求每条连同首个 Decode 槽需 1,025 blocks；同一 P 实例上 27 条占 27,675，28 条占 28,700，后者超过 28,614 blocks/rank。 | P 占用、等待的新 Prefill、D credit 时间线；计数 P 阻塞、D 等待及二者交集，未出现就记录首个失败条件。 |
| 周三：查真正临界路径 | 对保留窗口计算每层最后 KV shard、Prefill 结束、D credit、首个 Decode 可运行时刻；以 16,384-token 全量 KV 在 200-Gbps/rank cut 的 85.899-ms 串行下界筛查网络暴露。 | 每请求 P2D-ready/Decode 完成关键路径图；确认网络延迟是否越过计算掩蔽，并量化可归因的等待时间。 |
| 周四：算强基线后空间 | 在同 GPU/NIC、相同请求与传输字节下，比较 TWO_STAGE_FIFO、网络 FIFO/SRPT、LFU/DELTA 与合法 Oracle；只有扩展为多个 D 时才比较 cache-aware D routing，4P1D 本身没有选 D 空间。 | 同口径报告模拟器首 token、token 间隔和目标完成事件；以目标完成时间计算 `G=(M_strong−M_oracle)/M_strong`。**G<10% 停止；10%–15% 扩窗复核；≥15% 优先验证实现。** |
| 周五：最小闭环或停止 | 若 G≥15% 且临界条件通过，先验证 TP2 两阶段容量/传输路径的实现与字节、credit、P block 释放事件，再运行一个最小同源窗口和强基线；10%–15% 扩大原序窗口样本；不足 10% 则归档失败条件。 | **GO：**可重放的同源、同资源临界窗口与最小闭环对照；**NEED_DATA：**来源窗口是否重复出现；**NO-GO：**有数字支撑的停止报告。Oracle 上界不写成新算法收益。 |

**预期达到的效果：**下周得到明确的研究取舍，而不是预设性能提升。理想结果是找到至少一个同时通过容量、credit、临界路径且强基线后上界 ≥15% 的来源窗口；若上界为 10%–15%，交付复核样本；若不足 10% 或共现条件失败，交付首个失败门槛并收缩或终止该方向。TP2 两阶段路径目前尚未受支持，闭环数字以先完成正确性验证为前提。[当前状态](CANDIDATE_STATUS.md)
