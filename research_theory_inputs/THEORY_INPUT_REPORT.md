# LLM Serving 计算—通信—网络—调度理论输入审计

审计日期：2026-10-13  
仓库：`/home/dell/lpm/LLMServingSim`  
范围：源码、模型配置、GPU profile、FlowSim、native ns-3、已有事件账本和历史实验报告。  
本轮不设计新调度器，不执行新的 serving/network 性能实验，不修改历史结果。

## 1. Executive Summary

当前证据可支持**局部、分层的理论计算**，但还不能支持“任意历史配置下完整 serving critical path”或“固定资源下 >15% serving 优化上界”的可信定量结论。

已可靠掌握的输入包括：Qwen3-30B-A3B BF16 的架构参数与 KV 字节公式；当前 RTX PRO 6000 profile 的测量范围和 MoE 越界风险；P/D `LAYERWISE` 的每层 KV 释放依赖；Decode admission、TTFT、TBT/TPOT 的代码定义；FlowSim 的 fluid max-min 语义；以及一组可追溯的 4P1D/200-Gbps ns-3 接收端 incast 网络级结果。

最强的同一事件账本结论是：四个 Prefill 请求在 96 个 profile-derived release wave 中传输 KV 时，CC_MODE=1 将 shard FCT 均值从 0.379 ms 拉长到 1.262 ms；最后所需 KV 仍在 profile Prefill 计算结束前 0.356 ms 完成。故该固定账本的 P2D 网络等待对 Prefill-end barrier 的**严格暴露上界为 0 ms**。这是固定 release schedule 的网络/barrier 投影，不是 integrated ns-3 的 TTFT 测量。

因此：

- 可复算模型 KV 字节、指定物理 cut 的串行化下界、固定 release ledger 的网络完成和某些明确的 barrier slack。
- 可用源码建立 Prefill/KV、EP collective、Decode admission 的因果 DAG；部分 FlowSim runs 有完整 serving 输出，但并非 packet replay 的同一次执行。
- 无法从当前 packet replay 得到 ns-3 驱动的 TTFT/TBT；replay completion callback 是 no-op，所有 release 预先固定。
- EP64 历史 serving 结果的 MoE compute profile 绝大多数落在 activated-experts 测量域以下，不能当作校准的 EP64 TBT 定量证据。
- **15% SERVING HEADROOM: NOT COMPUTABLE FROM AVAILABLE EVIDENCE**。某些小样本网络目标有 >15% 的 network-only 排序空间，但这不等于同一请求集合的 serving latency/goodput 收益。

当前最值得保留的是“网络延迟是否跨过真实 Prefill/Decode/collective barrier”这一分析框架，而不是由 queue、ECN、flow FCT 或 CCT 单独推导 serving 优化空间。

## 2. Source and Run Provenance

### 2.1 当前源码身份

| 项 | 当前值 | 证据状态 |
|---|---|---|
| Git HEAD | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` | `SOURCE_CONFIRMED` |
| 当前 tracked dirty diff SHA-256 | `089f3d35d5740b889d4906da48d4ccbf88b1b8ba5d5a048ec16f52806584cfa9` | `SOURCE_CONFIRMED`；包含用户工作区改动 |
| 工作区状态 | 多个 serving/converter 源文件已修改；多组研究目录、测试、配置和 workload 未跟踪 | `SOURCE_CONFIRMED` |
| FlowSim 集成 CLI | 当前 `serving/__main__.py` 有 `analytical/ns3/flowsim` 入口、P/D 与 EP 语义参数 | `SOURCE_CONFIRMED`，但该文件处于 dirty 状态 |
| ns-3 主子模块 | `git submodule status` 未输出可用于绑定本报告结果的独立 SHA；native replay binary 有逐次 hash | 结果级 provenance 优先使用 run manifest |

重要限制：历史结果不得仅凭 HEAD 绑定。4P1D packet replay 的每次成功运行 manifest 会记录 binary、event ledger、topology、rank-map、config hash、命令和 wall time；它没有自动证明其全部来源文件等于当前 dirty 源码。其他历史 FlowSim 结果不少是未跟踪目录，或配置/代码版本没有同等完整的逐 run hash，因此标成 `HISTORICAL_UNBOUND`，不与当前源码拼接。

### 2.2 核心输入及 hash

| 输入 | SHA-256 | 用途/状态 |
|---|---|---|
| `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json` | `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3` | 模型架构参数，`SOURCE_CONFIRMED` |
| RTXPRO6000 BF16 `meta.yaml` | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` | profile provenance，`PROFILE_MEASURED` 范围元数据 |
| TP1 `moe.csv` | `aa6e29a17412a62234a6610d7a699f72e5938f09386374b635925c5db29045f6` | EP rank compute profile，有限采样域 |
| TP2 `dense.csv` | `710f04261d67ec53639095cec91751c9a9dc1aa6f5b335c9decaee4802407633` | TP2 dense profile |
| TP2 `attention.csv` | `0b0fb7a5436cb4bffba5e89397cf747064b1566e0053db4584c70d766d243b10` | TP2 attention profile |
| packet LAYERWISE `events.csv` | `00ba29302252239323840c27d17b9cfcb8feadbf1d4bd3bb84836316625e32b7` | 768 个固定 P2D event，`MODEL_DERIVED` release + `SIMULATED_PACKET` completions |
| CC1 packet `network_run_manifest.json` | `3ee05e86939155f3059d05c9e73581b925765083b3ec065bef7914c87c5ce379` | packet run provenance |
| CC1 `comm_events.csv` | `4b0a638359f1cf798ad3eba0b49beada9ab3f5180e9e5d2df9805665507721b0` | packet message start/end |
| `03_NS3_NETWORK_GATES.csv` | `3f7994b7568109cef69d14b5330b1b8ba577acfb229a69d14bf289a5d8136e4d` | incast network outcomes |
| `09_CLOSED_LOOP_SERVING_RESULTS.csv` | `9adaef6917c1d6192b131f1289584ff18f048417ff020f8fe8e1a0ee1bf7a279` | 明确记录 serving 指标空缺/NOT_RUN |
| EP4 双 group summary CSV | `f1198a68ab23e0007302bec00b6868605853eefb7d5b4f6a8fdf6e5170c95667` | controlled FlowSim phase test |

Profile bundle 记录 vLLM 0.19.0、CUDA 13.0、NVIDIA RTX PRO 6000 Blackwell Server Edition、profile 时间 2026-04-24；profile 实际由单 GPU runner 采集并以 shape override 模拟 TP shape，不是多 GPU 集群实测。Profile meta 的 engine sweep 上限包括 `max_num_batched_tokens=2048`、`max_num_seqs=256`。

### 2.3 实验/文档存在性

重点目录 `research_ns3_incast/`、`research_sparse_foundation/`、`research_motivation/`、`research_joint/`、`experiments/pd_kv_ep/` 存在。`research_ns3_serving_feedback/` **不存在**；不能引用不存在目录中的结果。

## 3. Existing Experimental Evidence

以下每行是独立实验，不允许把一行的网络 metric 与另一行的 serving metric拼成因果链。

| 实验 ID/方向 | 模型与设置 | 后端/ workload | 主要指标与结论 | 可用性 |
|---|---|---|---|---|
| `RC_N0/N1/N2/N3/N4` receiver incast | Qwen KV，TP2 rank shard；200G NIC/cut；四发送节点至单或多 Decode NIC | native ns-3；固定 packet replay | N2 四流单收端 mean FCT 32.481310 ms；分两 NIC 后 16.261314 ms；四 NIC 后 8.151317 ms；最大 queue 3,148,584 B；无 PFC/drop | `SIMULATED_PACKET`，网络级，非 serving |
| `LAYERWISE4_CC0/CC1` | 4 请求，4096 prompt，TP2，48层；96 release wave；每 wave 8 个 2MiB/rank message | native ns-3 fixed replay；DCQCN 关闭诊断对照 / 开启 | shard FCT mean 0.378910→1.261535 ms；last required KV 134.059112→134.963180 ms；Prefill compute end 135.319248 ms，剩余 slack 1.260136/0.356068 ms | `SIMULATED_PACKET` + profile release；无 ns-3 TTFT/TBT |
| `ORDER8P2MS` | 相同四请求 post-prefill KV 总 bytes，8.2ms bundle spacing | native ns-3 fixed issue time | mean ready 20.451317 ms，相对 simultaneous 32.481310 ms 降37.04%；makespan 32.751317 ms，增加0.83% | offline network-only pacing oracle，不是在线Serving动作 |
| Controlled EP64 `EP_FIRST` vs FAIR | S16、8P/8D、Qwen3、32 active Decode + 64 个2048-token P2D，受控20ms相位 | integrated FlowSim，A2A_P2P 实验路径 | EP CCT P99 92.279→45.644 µs（−50.54%）；TBT P99 8.862→6.937 ms（−21.72%）；P2D ready不变 | `SIMULATED_FLUID`；controlled；EP64 MoE compute profile out-of-domain，不能视为已校准的现实 EP64 serving收益 |
| Azure Conversation16 / Code32 | S16、EP64、保留 trace arrival/length，LAYERWISE | integrated FlowSim | EP_FIRST 对EP CCT/TBT/TTFT几乎无影响；TTFT P99变化约−0.0017%/−0.0076%，TBT P99约0%/−0.275% | `SIMULATED_FLUID`，自然trace切片；同样有 EP64 profile 域风险 |
| S8 两个并发 KV（K8/K9） | 两个 P2D 请求；CC1 packet ledger | native ns-3 fixed replay | shard FCT P99增约101.3%/90.9%，但 request handoff 改变仅 +11.637µs（+0.0040%）或−41.312µs（−0.0141%）；大多数早层 shard 有 release slack | `SIMULATED_PACKET`，说明 flow tail 不等于 request barrier tail |
| S8 final shard residual drain | LAYERWISE；同一报告所述 case | packet/serving event 对照需按原报告边界理解 | final-shard residual drain +23.568%，request handoff仅+0.0115%；最后 shard仍早于 Prefill end 2.367 ms | network/serving证据分属报告口径；不是一项可移植到别处的普遍比例 |
| EP–EP phase staggering | 两个独立 EP4 group，各4请求，128 input/32 output | integrated FlowSim controlled | 同步 FAIR ITL 6.157552 ms；group-alone 6.1084 ms；20µs phase shift使两组均值约6.1184 ms、makespan只增加20µs；观察到 collective overlap被错开，但无总工作量/长期性能净收益 | `SIMULATED_FLUID`；Serving-only phase control；不是在线网络联合策略 |
| 1P2D EP16 minimal gate | 单 Prefill + 双 Decode、共享ToR；D16+K8 | integrated FlowSim | EP CCT P99 +5.11%，KV residual +3.66%，TTFT +1.60%，TBT P99 +0.47%；queue episode P95 3.258µs / EP period 6.237ms | `SIMULATED_FLUID`；controlled；正向但很弱 |
| FlowSim 512 fan-in | spread vs fan-in16，512 requests | network-only FlowSim | EP CCT P99约+201%，KV FCT P99约+99% | `SIMULATED_FLUID`；无 integrated TTFT/TBT，不能外推Serving |
| EP4 + KV_FIRST | 小型 integrated case | FlowSim | EP CCT P99 11.860→148.982µs，TBT P99约+8.3% | `SIMULATED_FLUID`；network变化被Serving barrier部分衰减 |
| EP32 KV_FIRST packet | S8 packet | ns-3 replay | EP CCT P99 +852.9%，request handoff基本不变 | `SIMULATED_PACKET`；不同于EP4 integrated case，不能合并为一条因果链 |
| Corrected S16 fan-in | EP flow fan-in | ns-3 network-only 与分开的 integrated FlowSim点 | packet EP flow FCT P99 +34.9%、EP CCT P99 +29.1%；另一 integrated FlowSim点 TBT P99 +5.01% | 两个不同运行；只支持定性机制一致，不支持精确同run归因 |
| EP64 route geometry 79% | GateRouter exact A2A_P2P vs same-byte uniform peer counterfactual | network-only FlowSim | EP CCT P99约0.1065→0.1909 ms（约+79%），EP_ONLY已存在近似差距；P2D未证明是差距主因 | Gate1结果为 generic EP route geometry，不是已证实PD特异竞争；Uniform是offline counterfactual |
| Progressive Push | Mooncake窗口等，whole vs progressive range publish | integrated FlowSim；小拓扑 | Mooncake 000087在原50G点TTFT P99改善20.22%，相邻000114/000103为17.76%/19.90%；TBT P99不变。相同工作负载改为100G/200G后TTFT P99改善11.03%/6.07% | 架构语义测试/有界Serving结果；与P2D×EP仲裁不是一回事；100/200G没有20%收益 |
| P4 remote KV provider placement / split-source | remote prefix reuse、provider放置和双目的端路径 | FlowSim integrated + 历史对照 | provider network backlog可以变化但未稳定改变TTFT；split-source合法variant在窗口中TTFT变差22.9%–61.1%；EP耦合不稳定 | 不能作为provider placement正向动机；architecture baseline语义通过但性能no-go |
| Sparse foundation | Qwen3真实路由/稀疏A2A校准 | 静态审计，关键仿真未执行 | 缺少真实token→expert route矩阵；EP32/64 AE profile out-of-domain；普通生成路径默认AG/RS，不是strict sparse A2A | `MISSING/PROFILE_OUT_OF_DOMAIN`，方向被证据阻塞，不是性能机制FAIL |

历史数据总判读：同类网络 flow 的竞争可以显著改变 packet/fluid FCT/CCT；只有在延迟越过下一 serving barrier 时才影响 TTFT/TBT。真实 arrival 的 Azure 切片多为负对照；受控 EP64 正例证明特定相位/人口下可暴露，但其 MoE计算 profile 不能作为校准性能结论。

## 4. Model and GPU Profiles

### 4.1 Qwen3-30B-A3B模型参数

模型 JSON 给出：48 Transformer layers、hidden size 2048、32 attention heads、4 KV heads、head_dim 128、128 experts、top-k 8、MoE intermediate size 768、BF16 weight dtype。数据状态为 `SOURCE_CONFIRMED`。配置文件未显式给出 KV dtype 时，所列字节默认 BF16 KV；FP8 KV会减半。

当前代码 [`trace_generator.py`](serving/core/trace_generator.py:1049) 的 per-layer/per-TP-rank P2D 字节为：

```text
KV_dim = num_kv_heads × head_dim = 4 × 128 = 512 elements
B_layer,rank(token) = K+V × KV_dim × bytes_per_element / TP
                    = 2 × 512 × 2 / TP bytes
```

全模型、单 token：

```text
B_KV/token = 2 × 4 × 128 × 48 × 2 = 98,304 bytes
B_KV/layer/token = 2,048 bytes across TP ranks
B_KV/layer/rank/token at TP2 = 1,024 bytes
```

| Prompt tokens | BF16 full request KV | TP2 per-rank shard |
|---:|---:|---:|
| 128 | 12,582,912 B = 12 MiB | 6 MiB |
| 2,048 | 201,326,592 B = 192 MiB | 96 MiB |
| 4,096 | 402,653,184 B = 384 MiB | 192 MiB |
| 8,192 | 805,306,368 B = 768 MiB | 384 MiB |

这些值是 `MODEL_DERIVED`，不是测量流量；按二进制 MiB 换算。KV公式与 `memory_model.py::calculate_sizes` / `get_kv_size_per_token` 的 layer、KV head、head dimension、TP分摊一致。P/D KV发送包括本轮新计算token及首轮prefix-cache hit token，不应拿 QKV activation 全部当 KV 发送。

### 4.2 Profile域与可用配置

Profile `meta.yaml` 声明 NVIDIA RTX PRO 6000 Blackwell Server Edition、vLLM 0.19.0、CUDA 13.0；TP1、TP2目录存在，dense/attention可按TP读取，MoE profile由代码固定从TP1读取。Profile本身是实测数据 `PROFILE_MEASURED`，但只对采样 grid 内输入成立；runtime lookup在格点间线性插值，超过边界时外推，MoE activated-expert低于最小值时则夹到AE最小行，而不是向下外推。

MoE profile grid（见 `research_sparse_foundation/01_PROFILE_DOMAIN_AUDIT.md`）：token `1…2048`，activated_experts=`8,16,32,64,128`。Qwen的每rank expert总量上限随EP为128/EP：EP4=32、EP8=16、EP16=8均触及/处于采样范围；EP32=4与EP64=2在AE轴越界，会被夹到8。历史路由 sidecar加权查询中 3,102,720/3,104,160（99.9536%）低于AE最小采样值。Sidecar为BALANCED分析矩阵，不是Qwen真实选中expert ID。当前无可用GPU driver进行补profile（历史审计记录 `nvidia-smi` 无法连驱动）。因此：

- EP4/8/16具备较好的 AE grid 支持，但还须逐run检查具体 token、AE 查询是否内插/外推。
- EP32/64 compute和由此得到的 integrated serving时间标为 `PROFILE_OUT_OF_DOMAIN`；不应用于论文级绝对 TBT/TTFT。
- 4096-token packet ledger把Prefill切为两个2048-token chunk，Profile的 `max_num_batched_tokens=2048`，这一输入长度维度在范围内；但模型的单卡 shape模拟并不等同真实多卡运行。
- 历史报告声称的“剩余Prefill计算时间”可用于该profile-derived释放投影，不是GPU在线实测。

### 4.3 计算profile可用性清单

| 功能 | 可用性 | 适用范围/限制 |
|---|---|---|
| TP2 dense layer | `PROFILE_MEASURED` | RTXPRO6000 TP2形状；查询域仍需核对 |
| TP2 attention | `PROFILE_MEASURED` | 4D轴：prefill chunk、KV prefill、decode batch count、KV decode；格间线性插值、超界外推 |
| MoE expert kernel | `PROFILE_MEASURED` at TP1 | 每rank `(tokens, activated_experts)`；不是分布式多卡测量 |
| EP4/8/16 MoE lookup | `PROFILE_MEASURED/PROFILE_INTERPOLATED` | AE轴在/贴近测量域，实际每请求仍需查具体坐标 |
| EP32/64 MoE lookup | `PROFILE_OUT_OF_DOMAIN` | Qwen自然每rank专家数4/2，lookup会夹到AE=8 |
| 集体通信时间 | 非GPU profile | 由ASTRA/FlowSim/ns-3网络模型承担 |
| 历史 EP64 serving结果 | 有方向性、非定量校准 | MoE AE out-of-domain；不得用于严格性能预测 |

## 5. Compute Execution Semantics

`profiler/models/qwen3_moe.yaml` 定义单层顺序：`layernorm → qkv_proj → qk_norm → rotary_emb → attention → o_proj → layernorm → moe`；MoE内部由trace generator围绕expert compute插入dispatch/compute/combine；模型前有embedding，末尾有final layernorm、lm_head、sampler。`trace_generator.py::_emit_sequence` 按架构YAML遍历序列；每个层的计算时间来自相应CSV，Profile单位µs，在运行时转ns。

**Prefill LAYERWISE release**：每层 `qkv_proj` 行携带该层、该TP rank的KV字节；converter在对应QKV/V projection计算节点后创建P2D SEND。下一Transformer layer依赖前层本地计算/collective，不依赖此前KV SEND结束，所以网络传输与后续Prefill计算并行。Chunked prefill由scheduler token budget与trace DAG表达，但固定packet ledger是事先导出的profile释放时刻，不会因网络完成反向改变实际Prefill发射节奏。

**Decode EP DAG**：MoE默认graph realization见trace generator：dispatch AG、expert compute、combine RS；按layer DAG组织。Exact `A2A_P2P` converter扩展则逐peer建SEND/RECV，并加一个等待所有该rank的nonlocal send/recv的零时长join。FlowSim worker进一步根据expected node集合在组内所有 required nodes完成后才记录P2P collective完成。Exact A2A在对应join上建立group-wide依赖；但历史实验采用AG/RS或A2A_P2P的run需逐一辨认，不能把所有历史 collective 都叫 exact sparse A2A。

Group barrier的代码含义：dispatch join之前，MoE专家计算不能越过它；expert计算完成后才进入combine阶段；后续layer/token依赖该轮图的通信/计算完成。对Exact P2P，CCT定义为集体开始到最后一个required peer flow完成。**CCT不必等于TBT增加量**：它可能与可并行计算、其它rank工作或当前batch推进发生重叠；要映射TBT需要同run的round start/end、token完成时间和依赖slack。当前packet replay没有Serving scheduler反馈，所以不能映射。

ASTRA单图的节点/通信完成可反馈网络图执行；Python serving主循环通常在整个scheduler batch/iteration完成后更新状态。可观测的“batch completion”不能自动说明某个EP packet/CNP被在线Serving policy消费。

## 6. KV Generation and Release Pipeline

### 6.1 当前语义

```text
Prefill request admitted
  → QKV layer l compute
      ├─→ next layer's compute DAG (does not wait for P2D send l)
      └─→ P2D KV_l send(s) → Decode destination rank(s)
  → later layers / final norm / lm_head / sampler
  → Prefill graph/batch completion including required sender graph work
  → router handoff with completion timestamp
  → Decode add_decode(KV_ready_time)
  → Decode queue/capacity + next legal scheduler batch
```

`LAYERWISE`表示逐层产生并发送，不等于“上层所有KV送完才开始下层”。这是一种producer与网络的pipeline；较早KV有后续层计算作为slack。`POST_PREFILL`则在完整Prefill后生成整体KV transfer marker，删除大部分该类重叠，只能在请求全prompt同一prefill graph完成、PP1的受限路径使用；它是机制敏感性，不应默认当作生产主路径。

在本源码/ASTRA DAG中，KV SEND以QKV compute为parent；SEND是侧支，后续layer compute依赖前一层compute/collective而非SEND。**Prefill graph结束/请求handoff仍必须等发送节点完成**（source ranks完成其Prefill图后前端才调用transfer）。所以每层传输可被之后计算隐藏，但最后required send若晚于Prefill graph的其它依赖端点，会推迟Prefill graph completion/TTFT与Decode handoff。不能简单说“只有最后一层KV决定”——严格是 `max(all required shard finish)` 与Prefill其它图依赖的join；可能是早层拥塞shard变成最后完成者。

### 6.2 96-wave packet账本的同run对齐

来源：`research_ns3_incast/fixtures_rankcap200g/network_only/layerwise_profiled_4p_v7/events.csv` +两个对应run目录；事件时间来自RTXPRO6000 TP2 profile投影，packet finish来自native ns-3。请求同步发起是控制性mechanism workload，不是自然请求频率主张。

| 字段 | 值 |
|---|---:|
| Prefill请求数 | 4 |
| prompt/output | 4096 / 1 token（输出1只做手递手/first token gate） |
| TP、layer数 | TP2、48层 |
| Chunk | 2 × 2048 tokens |
| release wave | 48层 × 2 chunks = 96 |
| 每wave message数 | 4请求 × 2 TP ranks = 8 |
| 每message payload | 2,097,152 B = 2 MiB |
| 每wave总payload | 16 MiB；每独立receiver rail 8 MiB |
| 总message数/总app bytes | 768 / 1,610,612,736 B |
| 首次release | 0.076554 ms |
| 最后release | 133.679955 ms |
| profile Prefill compute end | 135.319248 ms |
| event账本profile版本/运行时 | vLLM 0.19.0 RTXPRO6000 BF16 TP2 shape profile；ns-3 replay binary hash见第2节 |

release offset在manifest列出为96个点，层间大致每层约1.34 ms（末端间隔因chunk边界/最终层取值不同）；报告精确记载95个wave均在下wave发出前排空：CC0最小`prior-wave finish → next release`间隙959.943 µs，CC1为55.255 µs。每波之间正间隔不代表没有wave内部队列；也不等于链路持续空闲。

| CC配置 | shard FCT mean/max | Last required packet finish (max request-ready) | Prefill compute end | 计算余量 `end−lastKV` | 网络等待暴露于Prefill-end |
|---|---:|---:|---:|---:|---:|
| CC_MODE=0 | 0.378910 / 0.379157 ms | 134.059112 ms | 135.319248 ms | 1.260136 ms | 0 ms |
| CC_MODE=1 (DCQCN) | 1.261535 / 1.288550 ms | 134.963180 ms | 135.319248 ms | 0.356068 ms | 0 ms |

CC1关键KV事件是request 0、layer47最后事件，release 133.679955 ms、完成134.963180 ms。最后release到最后完成约1.283 ms；不能把首层释放到末层完成的134.9 ms称为网络传输时长。CC1影响的是shard FCT及波内排队，但最后required KV仍被后续Prefill计算覆盖。`09_CLOSED_LOOP_SERVING_RESULTS.csv`中TTFT/TBT/TPOT/SLO均空值，状态`NOT_RUN_NETWORK_ONLY`。因此数据状态为“Profile-derived fixed release + packet simulated completion”，不等于最新 integrated serving实测。

### 6.3 KV时间/Slack定义

- shard FCT：`packet finish_i − packet issue_i`（packet replay记录message start/finish，含packet/transport过程，不是单层KV请求端到端TTFT）。
- network-side KV barrier：`T_KV_network_ready = max(required shard finish_i)`；TP2有两条必要rank shard，位于两条receiver rail时按request取最大finish，不得把两shard bytes错误累加到一条NIC。这是packet-only ledger离线重建的时刻。
- integrated Serving handoff timestamp：当前`add_done()`把Prefill整图/批次的完成时间传给`router.transfer_prefill_request()`，`add_decode()`再把它写入`req.p2d_kv_ready_time_ns`。因此该字段在现行实现里是Prefill graph已完成且KV可交接的handoff时刻，可能晚于纯network-side `T_KV_network_ready`；不能只凭字段名认定它等于最后packet/flow完成。
- KV object slack：`request last required finish − shard_i finish`。
- Compute/Handoff slack：`Prefill_end − request last required finish`，若为正则网络等待被计算掩盖。
- 固定packet账本在CC1中该slack为0.356068ms；网络额外延迟若小于该值，不暴露到Prefill-end边界。

历史LAYERWISE cc1每个KV message event新建一个QP（768 QP/768 events），故不检验KV QP跨layer/请求继承DCQCN降速状态。96 wave均排空说明该固定负载没有跨波active-flow carry，不表示没有队列/CE/CNP。

## 7. MoE / EP Collective Semantics

### 7.1 默认路径与实验路径

当前普通 `trace_generator._emit_moe_block` 默认构造vLLM风格AG/RS：dispatch为AllGather、combine为ReduceScatter（代码`trace_generator.py:1131-1145`），不是GateRouter精确稀疏peer矩阵。研究实验可通过显式route ledger/converter path选择`A2A_P2P`；converter对给定`pair_matrix`为每个非本地peer发SEND/RECV，并创建等待每个required消息的join（`llm_converter.py:634-702`）。因此回答“当前实际运行哪种”的正确方式是看每次run config/manifest，不可由模型名推断；normal default为AG/RS，带exact route ledger的指定实验才是A2A_P2P。

### 7.2 Barrier与Token完成

- AG/RS：作为ASTRA collective节点交给backend；系统图的collective节点是该依赖边界。独立peer-flow拆分级别取决于所用backend/遥测，不能从一个AG/RS comm node推导精确peer最后完成。
- Exact A2A_P2P：每rank join等该rank参与的全部非本地SEND/RECV。FlowSim group ledger按group expected nodes集合完成后才出集体CCT行；完成时间是组内完整expected集合完成时刻。
- MoE dispatch join在expert compute之前；combine在expert compute之后；下一层依赖前层communication/compute。模拟图能表达barrier依赖。
- 但历史packet replay中EP事件缺失（receiver-incast ledger仅含P2D KV，没有EP）；不能报告该packet账本的EP CCT、EP TBT。
- 当前没有与receiver-incast固定release event完全同run、真实EP peer packets、Decode token完成和request TBT连通的packet serving ledger。

`EP CCT = max(peer finish) − collective start`是network collective完成量。要计算 `CCT → token` 的真实边际影响，至少还需该EP轮之后必要GPU compute/下游通信、同token end、下一layer/token barrier时间。当前许多历史报表没有 per-token 的全部这些同源事件，所以不能假定整个CCT都暴露在TBT上。

## 8. Physical Network and RDMA

### 8.1 4P1D receiver-incast fixture

拓扑来源：`research_ns3_incast/fixtures_rankcap200g/fixtures/4p1d_unique_spines/topology.txt`（SHA见第2节）；header `68 nodes, 28 switches, 66 physical links`。rank map明确40 GPU rank endpoint，10 NIC aggregation nodes（每台server 2 NIC、每NIC 4 GPU rank），10 leaf和8 spine。四Prefill源server、单Decode server；每条scale-out NIC uplink 200 Gbps，rank access也在校准fixture限为200 Gbps，**同一NIC上的4 rank仍共享一个200G uplink**；每server aggregate 400 Gbps，不是每GPU各有独立NIC。

receiver rail 0的示例rank0路径：`GPU rank 0 → P NIC 40 → P leaf 50 → source-specific spine 60 → D leaf 58 → D NIC 48 → D rank 32`，瓶颈link 113=`leaf58→D NIC48`、200G。另一rail瓶颈link123=`leaf59→D NIC49`。四个source paths在spine侧不同，收敛于指定Decode leaf→NIC egress。primary tests使用unique source spines，不依赖ECMP hash collision。单个flow的200G NIC瓶颈不会因Clos的parallel spine aggregate而获得3.2Tbps；aggregate只在多物理平行资源被抽象成同一fluid pair且traffic可被分散时代表总容量。此fixture没有将目的NIC切成四张独立NIC，分流N3才把sender分到两个receiver NIC。

Rank map: Decode ranks0–3→NIC48/rail0，ranks4–7→NIC49/rail1；四个TP2 Decode instances各取两rail对应rank。receiver incast由同一NIC egress资源真实发生。P2D和EP共用某个resource必须由各自rank map/path证实；receiver-incast测试自身不包含EP，不能声称测了KV×EP shared cut。

### 8.2 ns-3/RDMA配置和结果

LAYERWISE `replay.conf`：200 Gbps各链路、4,096 B packet payload、32 MiB switch buffer、ACK_HIGH_PRIO=1、CC_MODE=1、`RATE_DECREASE_INTERVAL=4`、`RP_TIMER=900`、`ALPHA_RESUME_INTERVAL=1`、`EWMA_GAIN=0.00390625`、`RATE_AI=50Mb/s`、`RATE_HAI=100Mb/s`、`MIN_RATE=100Mb/s`、200G `KMIN_MAP=600`、`KMAX_MAP=2400`、Pmax=0.2（ns3 MMU换算为约600,000 B与2,400,000 B threshold）。这是本次rankcap200g fixture配置，不要拿默认配置里不同packet大小、`ACK_HIGH_PRIO=0`、`CC_MODE=12`代替。

| Packet point | CC0 | CC1 / DCQCN | 队列与loss |
|---|---:|---:|---|
| N0 1 shard / one NIC | FCT 8.151317 ms | 同值；无拥塞信号 | 最大queue约4,132 B；CE/CNP/rate=0 |
| N1 2→1 receiver NIC | mean FCT16.261314 ms | 16.965970 ms | max1,057,792 B；CC1 110 rate-change events |
| N2 4→1 receiver NIC | mean32.481310 ms，P99 32.481552 ms | mean32.781754 ms，P99 34.277322 ms | max3,148,584 B；无PFC/drop |
| N3 4→2 receiver NIC | mean16.261314 ms | 17.091879 ms | 每rail两发送流 |
| N4 4→4 NIC | 每流8.151317 ms | — | 独立receiver capacity control |
| FULL4 simultaneous, two required shard/request | mean request max-shard32.481310 ms，max32.481557 | mean33.263584 ms，max33.888367 | 总1.611GB；网络级request-ready，不是TTFT |

CC_MODE=0能观察交换机本地CE/CNP遥测，但sender rate不执行DCQCN速率响应；只有CC_MODE=1是此分支中的DCQCN反馈模式。不能把mode0叫DCQCN，也不能把`CC_MODE=12`称为DCQCN。LAYERWISE CC1记录87,197个CNP telemetry events、13,006 rate-change events；768个QP都有CNP/rate-change，但事件条数不是QP数。local first CE标记统计87,197；下游携带CE的逐链路记录不能重复求和。queue峰值3.149MB远小于32MiB，PFC=0、drop=0；此case是排队/ECN/DCQCN，不是buffer overflow/PFC/HOL证据。

### 8.3 QP、ACK、结束语义及可见遥测

`KVEPReplay.cc`按预先给定的event issue timestamp调用`send_flow`，完成callback为`noop_message_handler`；所以完成不推动Serving。该layerwise replay对每条KV event启动新QP，不验证persistent KV QP。源码另有可选persistent EP QP功能，但不能因此假定真实部署/当前KV replay复用了QP。真实 runtime 中KV QP生命周期、跨request复用/状态reset目前 `MISSING`。

ns-3内部模拟RDMA packet/ACK/CNP；成功replay的QpComplete由网络模块的完成事件触发，作为该backend中message/QP完成；它不单独建模应用KV commit/设备端DMA后置延迟。packet event log可见 `comm_events.csv`（event id、issue/start/finish、src/dst、bytes/traffic class/QP）、`cc_events.csv`（QP_START、CNP、RATE及速率字段）、`local_ecn_marks.csv`（本地CE变化）、`qlen.txt`/link time series/summary（交换机queue及link数据）、`pfc.txt`（pause）。具体列依据run sidecar；旧输出必须避免把同一个CE packet经多跳重复计成多个独立源事件。

固定 replay能离线保存 ACK/CNP、当前QP rate、queue occupancy、CE、PFC、link utilization；但不能让Serving在线调度读取这些。普通integrated ASTRA/ns-3源码有`sim_send→send_flow→qp_finish→ASTRA message callback`，packet completion可能推动graph completion；但本custom 4P1D topology上的integrated runtime状态为NOT_RUN。已审代码没有经过验证的“queue/ECN/CNP/实时QP rate→Python scheduler决策”输入通道。Flow completion与早期拥塞信号不是同一个接口。

### 8.4 FlowSim的确切含义

`flowsim_backend.py::_waterfill/_rates`用有向路径容量做流级max-min water filling。FAIR是active fluid flows的max-min公平带宽分配；类策略可预留/严格优先级分配；同一路径的flow group优化不改变水位填充分配。并行物理链路若同方向、同latency，代码保留物理数量并按聚合capacity建fluid edge，也可按配置选physical channel hash；普通BFS路径与可选hash不等同于逐packet ECMP。没有packet serialization、switch FIFO buffer、ACK RTT或ECN/DCQCN/PFC。遥测中的`queue_bytes`明文是经过该link active path上的remaining fluid bytes，不是交换机packet queue。

因此FlowSim可回答model graph release下的流完工、fluid queue/backlog、collective join和集成Serving指标；不能回答packet queue/ECN/CNP/PFC机制。FlowSim integrated result的状态是`SIMULATED_FLUID`。

## 9. Serving Scheduler and Admission

### 9.1 Prefill

Scheduler有running与waiting集合；已有running在phase A优先推进，后从waiting头按arrival/FCFS顺序尝试纳入batch，受`max_num_seqs`、`max_num_batched_tokens`、KV容量、完整ISL reserve、chunk阈值限制。默认配置字段常用`max_num_seqs=128`、`max_num_batched_tokens=2048`。waiting admission遇到不适配请求会停在头部，不跳过，phase B不为新请求抢占；只有running阶段KV容量不足时按尾部回收进行vLLM式preemption。pipeline每stage最多pp_size个inflight batch。`num_computed_tokens`在schedule阶段推进。

有多个ready requests时，scheduler存在选择/排序影响“下一次prefill trace会产生哪些KV release”的控制点；当前默认不是基于网络queue/ECN的在线策略。batch中请求的chunk/order会改变KV release时刻与batch compute profile，因此serving-only调整必须重生成合法DAG，不能对固定network replay事后改issue time后就称为完整闭环。

### 9.2 Decode admission

Prefill完成后router以`completion_time_ns`转交请求。Decode `add_decode`设置`p2d_kv_ready_time_ns`，先记KV-ready，再检查`len(running) >= max_num_seqs`及可能的phase gate；满则放入waiting队列并等running slot退出，未满才把请求放入running。实际scheduler batch还需等待当前inflight/PP/Token budget条件，ready不保证立即执行。Decode waiting队列根据eligible time/request id插入；一般FCFS/可调度约束依然生效。

因此可分解：

```text
P2D_READY
  → decode_capacity/phase eligibility
  → waiting/running admission
  → next scheduler decision + batch graph submission
  → first decode iteration completion
  → second visible token
```

P2D提前可以被下一个可用batch机会吸收，或者请求先在Decode capacity queue中等待。对手递手压力下，必须记录真实Decode slots、KV block capacity、next batch时间，不可以简单把KV-ready时间等同first Decode execution。

### 9.3 指标定义

- `TTFT = prefill-first-complete timestamp − request arrival`。本模拟器在Prefill图经过final layers/lm_head/sampler后把首token记为可见；P/D模式中Prefill结束时已生成首token，Decode运行后续token。因此Decode admission不是本代码TTFT定义的必经点。P2D会影响TTFT的前提是required sends拖延Prefill graph/batch end；若last KV先完成，则网络延迟不会加到TTFT。
- `TBT/ITL`：`Request.add_itl`记录连续token可见完成时刻之差；prefill首token建立recent_end，后续Decode token完成形成间隔。每请求保存的ITL列表展开后做统计。
- `TPOT = (request total latency − TTFT)/(output_tokens−input_tokens−1)`（整数ns运算），是排除第一个token后的平均生成token耗时；输出仅1个新token时代码定义TPOT=0，不应用于steady decode性能结论。
- `TTST`：第一token到第二token可见时间，和第一条decode ITL语义相近，但记录为独立研究字段。
- `serving/__main__.py`还说明此TTFT记为first-token computation complete，与vLLM的client receive定义不同；横向结果必须统一语义。

## 10. Matched Event Timelines

### 10.1 Packet LAYERWISE最长可重建片段

可重建的同run片段：profile QKV release → packet message start/finish → request last required KV → 与固定Prefill compute end比较。Release和compute端点来自event manifest/profile-derived ledger；network完成来自同run ns-3输出。该片段不包含实际Serving callback、Decode scheduler batch、token completion或request completion。

| 时点/区间 | CC0 | CC1/DCQCN | 来源 |
|---|---:|---:|---|
| first QKV/KV release | 0.076554 ms | 0.076554 ms | 固定profile event ledger |
| last release | 133.679955 ms | 133.679955 ms | 固定profile event ledger |
| last required KV finish | 134.059112 ms | 134.963180 ms | ns-3 packet completion max |
| Prefill compute-end projection | 135.319248 ms | 135.319248 ms | RTXPRO6000 profile event ledger |
| Prefill-end projected KV slack | +1.260136 ms | +0.356068 ms | 算术差值，不是实测TTFT |
| integrated Decode admit/token/request end | MISSING | MISSING | 固定replay不连接Serving scheduler |

`comm_events.csv`保留每条Flow message具体时间与地址，但波release时间来源于另一个固定event file，不是Serving运行期生成的ns-3 callback。可靠结论只到“last KV在compute-end之前完成”，不扩展到TTFT数值。

### 10.2 EP与完整Serving时间线

历史integrated FlowSim的确保存过请求级TTFT/TBT、collective记录、P2D ready等数据；然而与4P1D packet ledger不是同一run，且EP64 MoE profile域存在问题。EP4双group实验有per-group/per-round计数和ITL，但它是独立控制实验。故本报告不拼接成一个包含Arrival、KV shard、EP packet、token finish的完整统一时间线。

## 11. Critical Path and Overlap Audit

### 11.1 一般DAG与slack定义

对Prefill请求 r：

```text
arrival → Prefill wait/admission → compute DAG (layer release)
        → each KV shard flows (fork after producer compute)
        → Prefill compute + required send graph completion
        → P2D handoff timestamp / TTFT timestamp
        → Decode capacity/admission wait
        → Decode batch execution → EP dispatch/join → expert compute
        → EP combine/join → next-layer/token output → TBT/TPOT/request end
```

手递手代码实际采用“Prefill graph完成回调时间作为request handoff time”；required P2D send是Prefill图相关node。区分网络barrier与Serving交接：

```text
T_KV_network_ready = max(all required KV flow finishes)
T_handoff = T_prefill_graph_done  # graph join含required KV send nodes
TTFT = T_handoff − arrival
req.p2d_kv_ready_time_ns = T_handoff  # 当前字段保存scheduler handoff时刻
T_decode_first_start ≥ max(T_handoff, T_decode_eligible,
                           next legal scheduler batch opportunity)
```

具体通信DAG若存在不同sender rank、PP阶段或虚拟shadow path，应读取对应生成器/ASTRA graph，不可把公式简化成一个KV总量/单NIC。

| Slack | 定义 | 解释 |
|---|---|---|
| KV object slack | `last_required_KV_finish − shard_i_finish` | 非critical shard可被其他KV工作追平的时间；不是所有shard FCT之和 |
| Compute/handoff slack | `Prefill_end − last_required_KV_finish` | 正值表示KV被Prefill计算隐藏；负值表示可能暴露，但TTFT还应核查同一图完成/输出语义 |
| Decode scheduling slack | `first Decode execution start − P2D_ready` | 拆成eligibility/capacity wait和下一batch wait；不等于network delay |
| EP peer slack | `collective_last_peer_finish − peer_i_finish` | 非末peer有剩余peer slack；加速已完成的非critical peer不一定改善CCT |
| EP→token exposed slack | 同一token DAG上collective completion与token end之间可并行/必经关系 | 需要同token的完整事件账本；当前packet run缺失 |

不要把上表slack直接相加。KV object slack和compute slack按嵌套 barrier定义；Decode wait发生在ready之后；EP可能嵌入一个或多个GPU计算阶段。必须从同一个DAG求最长路径。

### 11.2 已经可确认的关键路径结果

在LAYERWISE固定release packet ledger中，KV网络是活动通信，但最后KV到Prefill compute end有0.356ms（CC1）余量，因此KV网络不在Prefill-end critical path上，暴露KV等待为0。早层KV更早有layer计算slack；如果queue延长到Prefill末端以后，原先早完成的某shard可成为新的last required shard，不能只追踪“最终层”。

N2 receiver incast / FULL4 post-prefill case测得请求network max-shard readiness，但没有真实并行Prefill compute end与Decode scheduling callback，不能判定其TTFT。ORDER8P2MS mean-ready改善是对完成时刻分布重排，makespan却增加，尚无请求SLO权重与在线Serving目标。

EP64 controlled FlowSim说明某受控EP CCT差异可伴随TBT变化；Azure FlowSim负例及1P2D D16K8弱暴露点说明这种映射不是一般恒等式。其定量profile风险见第4节。

**当前数据不能回答“每个被测请求完整critical path是什么”**。可以给出最长同run合法片段和零暴露窗口；无法给packet replay对应的Decode token全部EP事件及request completion。

## 12. Theoretical Model Inputs

表内`Value/Range`只列可由当前代码/配置/报告追溯的数值；描述性值不冒充实时测量。下表共**36个量化参数/定义行**（按每行一个模型输入计数），不包含历史实验结果百分比。

| # | Symbol/参数 | Value/Range | Unit | Source | Confidence/state |
|---:|---|---:|---|---|---|
| 1 | Transformer layers `L` | 48 | layer | model JSON | `SOURCE_CONFIRMED` |
| 2 | hidden size `H` | 2048 | elements | model JSON | `SOURCE_CONFIRMED` |
| 3 | attention heads | 32 | heads | model JSON | `SOURCE_CONFIRMED` |
| 4 | KV heads | 4 | heads | model JSON | `SOURCE_CONFIRMED` |
| 5 | head dimension | 128 | elements | model JSON | `SOURCE_CONFIRMED` |
| 6 | experts | 128 | experts | model JSON | `SOURCE_CONFIRMED` |
| 7 | top-k | 8 | experts/token | model JSON | `SOURCE_CONFIRMED` |
| 8 | MoE intermediate | 768 | elements | model JSON | `SOURCE_CONFIRMED` |
| 9 | model/KV dtype in audited bundle | BF16/BF16 default | bytes/element=2 | model JSON/profile variant | `SOURCE_CONFIRMED` |
| 10 | full-model KV per input token | 98,304 | B/token | source formula + config | `MODEL_DERIVED` |
| 11 | KV per layer per token all TP | 2,048 | B/token/layer | formula | `MODEL_DERIVED` |
| 12 | TP2 KV shard per token all layers | 49,152 | B/token/rank | formula | `MODEL_DERIVED` |
| 13 | RTXPRO6000 profile | Blackwell Server Edition | GPU | meta.yaml | `PROFILE_MEASURED` identity |
| 14 | profile vLLM/CUDA | 0.19.0 / 13.0 | versions | meta.yaml | `PROFILE_MEASURED` provenance |
| 15 | profile batched-token bound | 2,048 | tokens | meta.yaml | `PROFILE_MEASURED` domain |
| 16 | profile max sequences | 256 | sequences | meta.yaml | `PROFILE_MEASURED` domain |
| 17 | MoE AE profile axis | 8,16,32,64,128 | activated experts | `moe.csv` | `PROFILE_MEASURED` samples |
| 18 | EP64 natural expert-host cap | 2 | experts/rank | 128/64 | `MODEL_DERIVED`; below profile min |
| 19 | EP32 natural expert-host cap | 4 | experts/rank | 128/32 | `MODEL_DERIVED`; below profile min |
| 20 | packet topology physical links | 66 | links | topology file | `SOURCE_CONFIRMED` |
| 21 | topology switches/nodes | 28 / 68 | count | topology header/map | `SOURCE_CONFIRMED` |
| 22 | GPUs/server in incast rank map | 8 | GPUs | rank map | `SOURCE_CONFIRMED` |
| 23 | NICs/server in incast rank map | 2 | NICs | rank map | `SOURCE_CONFIRMED` |
| 24 | GPU-ranks/NIC | 4 | ranks/NIC | rank map | `SOURCE_CONFIRMED` |
| 25 | NIC and tested bottleneck link rate | 200 | Gbps | topology/rank map | `SOURCE_CONFIRMED` |
| 26 | server aggregate NIC capacity | 400 | Gbps/server | two NICs | `MODEL_DERIVED` from topology |
| 27 | payload packet size | 4,096 | B | replay config | `SOURCE_CONFIRMED` |
| 28 | switch buffer | 32 | MiB | replay config | `SOURCE_CONFIRMED` configured |
| 29 | 200G ECN Kmin/Kmax | 600,000 / 2,400,000 | B | config + MMU conversion | `SOURCE_CONFIRMED` |
| 30 | Pmax | 0.2 | probability | replay config | `SOURCE_CONFIRMED` |
| 31 | DCQCN mode | CC_MODE=1 | enum | config/doc + run manifest | `SOURCE_CONFIRMED` |
| 32 | `RATE_DECREASE_INTERVAL`/`RP_TIMER` | 4 / 900 | config ticks | replay config | `SOURCE_CONFIRMED` |
| 33 | 4K BF16 request KV total | 402,653,184 | B/request | formula | `MODEL_DERIVED` |
| 34 | TP2 shard / 4K request | 201,326,592 | B/rank | formula | `MODEL_DERIVED` |
| 35 | 4P LAYERWISE replay total bytes/events | 1,610,612,736 / 768 | B / events | ledger | `MODEL_DERIVED` |
| 36 | Prefill compute end in frozen ledger | 135.319248 | ms | profile ledger | `PROFILE_INTERPOLATED` where applicable; fixed projection |

理论下界示例：只有当该flow确实贯穿单个200Gbps瓶颈且无并行独立receiver rail时，`T_serial ≥ bytes / 25×10^9 B/s`。TP2单shard 201,326,592B的payload-only下界=8.05306368ms；packet N0=8.151317ms，多出约98.253µs packet/transport开销。四个同cut等大流的max-min payload-only末完成下界32.21225472ms；N2 packet均值32.481310ms。两个receiver rails必须分别计算，request barrier取两者完成时间max，不能把两rail的bytes错误叠到一条200G link。

## 13. Controllable Actions and Observability

| 控制/信号 | 当前实现/最早作用点 | 网络字节/资源影响 | 在线观测和限制 |
|---|---|---|---|
| FAIR fluid allocation | FlowSim active-flow分配事件 | 不改字节/物理容量 | 依据FlowSim已知flows/release；fluid model，无packet telemetry |
| KV/EP class priority | FlowSim policy / ns-3 packet class branch | 改同一队列服务次序；不天然改变bytes | ns-3 priority replay可验证，但有无Serving feedback需分开 |
| Request-first/collective priority | 当前有离线FlowSim characterization controls | 只在flow active时改变速率；run-specific owner metadata需要保真 | 非通用在线可部署调度器；report不得称其已接收实时network signal |
| ns-3 ECN/CNP/DCQCN | QP内部packet运行中 | sender rate变化，影响当前QP剩余发送 | CSV可观测；当前Python scheduler无validated实时feed |
| 发送完成回调 | ASTRA/ns3集成`sim_send`路径 | 影响graph/iteration结束时刻 | 可间接影响下一Serving事件；自定义incast replay未接入Serving |
| Prefill waiting order | batch调度决策点 | 改计算顺序及未来KV release相位，通常不改每请求bytes | 仅有多个合法ready work时有选择空间；当前默认FCFS且running优先 |
| Chunk budget/order | Prefill下一batch决策点 | 可能改KV release times/重叠 | 改动须重新生成compute/network DAG；不能重放固定ledger称闭环 |
| Decode routing/instance selection | Prefill完成/配对阶段 | 改目的NIC、EP group/队列与路径 | 需固定资源并完整TP receiver mapping；不同旧配置不可混用 |
| Decode batch admission | KV-ready与next legal batch之间 | 不改network bytes，但影响capacity wait/token barrier | `max_num_seqs`、running、waiting、inflight、token budget可记录 |
| Path/ECMP selection | FlowSim固定BFS/hash或ns3 flow/QP路由 | 改route/cut，不改bytes | FlowSim path不是packet ECMP；packet route改变须匹配seed/hash |

必要判断：某些网络优化（如network-only mean FCT pacing）不要求Serving joint policy；Serving-only phase staggering也可改集体重叠但可能把delay转移给另一组。只有同资源同workload下联合决策严格优于最强network-only和serving-only基线，才有joint增量。

## 14. 15% Headroom Feasibility

延迟目标要求同一workload、同一资源、同一Serving指标：

```text
Headroom_UB = (J_baseline − J_valid_lower_bound) / J_baseline
```

目前可以算**network层**上界，例如ORDER8P2MS对平均request-ready下降37.04%，但makespan增加0.83%，且是预设issue schedule，不是在线Servingscheduler动作。也可对冻结LAYERWISE release schedule证明CC1/CC0两者最后KV都早于Prefill compute end，因此这一账本上P2D-ready之后、Prefill-end之前可节省的等待严格为0ms；该特定贡献不能改写成TTFT节省比例。

历史Integrated FlowSim存在真实TTFT/TBT变化，但受配置/模型profile有效性与同实验绑定限制；受控EP64有TBT P99约21.72%变化的记载，不过AE profile被大量夹到8，不能作为可信的EP64计算-网络总体Serving预测。Progressive Push在50G一个Mooncake窗口超过20%，100G/200G同样配置下约11.03%/6.07%，且TBT无收益；这属于另一传输架构，不是当前receiver-incast packet case，也不证明网络信号Serving反馈。

所以：

> **15% SERVING HEADROOM: NOT COMPUTABLE FROM AVAILABLE EVIDENCE**

可以计算的范围：模型KV byte、指定link的payload lower bound、有效release ledger的ns-3 packet FCT/last-shard ready、特定integrated FlowSim run的Serving指标（仅在其原profile合法时）。不能计算：统一、已校准的packet-level固定资源下S0/S1/S2/S3 serving最优差距、实时反馈相对offline oracle损失、具有生产意义的总体SLO增益。

## 15. Missing Information and Minimal Instrumentation

### P0（不能声称完整的同源Serving理论链）— 5项

1. **MISSING：同一运行的ns-3→Serving完整闭环账本。** 固定`KVEPReplay`所有issue time预先给定、callback no-op。需要在`AstraSimNetwork.cc::sim_send`完成回调及`serving/__main__.py`迭代完成边界导出request/batch/token事件，并让网络完成自然推进Serving clock；输出同run flow QP完成→graph node→batch结束→request token完成。没有它就不能把packet FCT/CCT量化为TTFT/TBT。
2. **MISSING：Decode每token完整EP依赖和last-peer映射。** 需要collective_id、request_ids/batch_id、layer/token index、每rank每peer发送/接收start/finish、dispatch join、expert start/end、combine join、token完成时间。建议插桩`llm_converter.py` exact A2A join、`flowsim_worker.py` collective event、scheduler `add_done`。否则不能计算EP→token critical slack。
3. **PROFILE_OUT_OF_DOMAIN：EP32/EP64真实AE=4/2下MoE compute profile。** 需在目标GPU测得tokens×activated_experts=2/4附近MoE kernel；现有clamp=8不够。没有这项，EP64 serving数字的绝对值与屏障相位不可信。当前硬件profile运行条件缺driver，需要恢复可用profile GPU或获得同型号可信profile。
4. **MISSING：真实部署的P/D GPU/NIC/rank路由绑定对所有历史run。** 4P1D incast fixture rank map完整，但旧S16/S8与多组FlowSim历史run未统一绑定logical rank→GPU→server→NIC→switch path。应每个run存拓扑、rank-map、route table、parallel links、物理容量和映射hash。
5. **MISSING：可供policy因果比较的同源S0/S1/S2/S3请求结果。** 需要同run request arrivals/tokens、compute profile、total bytes、实际Serving/network action、每请求 TTFT/TBT/TPOT/完成/容量等待、其它请求代价。现有 packet与FlowSim结果不构成同一基线。

### P1（特定网络/控制机制分析）— 4项

1. **MISSING：真实KV persistent-QP生命周期与状态关联。** 插桩producer、request、KV layer/shard到QP id、QP创建/复用/销毁、每event初始/末尾rate/alpha、CNP与恢复事件。当前packet layerwise是fresh QP/event，不可推断后续KV round继承降速。
2. **MISSING：ns-3早期拥塞信号被Serving读取的因果时间戳。** 需要CE/CNP/queue/rate callback到Python的IPC时间、可见延迟、所触发的scheduler decision和未来可变work集合。离线CSV不算在线信号。
3. **MISSING：业务真实应用级KV提交/注册/目标缓冲可用时刻。** ns-3 QP完成是网络层完成；如实际serving在KV接收、校验、block commit后才允许decode，需要其依赖与延迟。当前没有引入未经证实的额外delay。
4. **MISSING：按固定release波导出的每wave精简计算与链路账本。** 当前full comm/QP/ECN文件存在，但没有内嵌于简明报告的逐wave聚合CSV；后续理论作者可由`events.csv`和packet`comm_events.csv`按wave/event id计算release间隔、busy/idle、outstanding bytes、哪个request/shard跨波。不得从均值推导瞬时带宽。

### P2（论文验证与部署性）— 4项

1. **MISSING：有限硬件priority queue映射下的请求公平/饥饿与控制packet兼容验证。** FlowSim unlimited logical priorities不是packet hardware能力；需要明确K队列/QP/host pacing映射。
2. **MISSING：完整、经过验证的ns-3 ECMP/HASH路径可重复性统计。** 主incast用unique spines；N5中四流选到同一spine。不能据此声明负载均衡或随机碰撞概率。
3. **MISSING：来自同一合法request population的正式TTFT/TBT SLO定义/门槛。** 历史报告中的SLO空值不是零；不能事后调阈值。
4. **MISSING：同一profile与code/config版本的轻量可复现bundle。** 对每个历史结果需固定git diff、model/profile/workload/topology/routing/config/binary hash及命令，尤其untracked experiment目录应归档版本。

推荐的最小日志对象：

```text
request_id, batch_id, token_index, collective_id, layer_id, traffic_class,
flow_id, qp_id, src_rank, dst_rank, src_nic, dst_nic, directed_path,
required_for_barrier, release_ns, enqueue_ns, first_packet_ns,
last_packet/qp_finish_ns, bytes, queue_wait_ns, ECN/CNP/rate timestamps,
compute predecessor/successor node ids, barrier_ready_ns,
scheduler decision ns, selected request set, token_complete_ns, request_end_ns
```

无需保存每packet文本全量输出：可用per-flow/QP与每port时间bucket聚合保存，并在关键窗口保留包级trace。

## 16. Final Handoff to Theoretical Analysis

### 可以直接使用的数字/公式

1. Qwen BF16 KV：`98,304 B/token`（全48层）；`2,048 B/layer/token`全TP；TP2每rank/layer `1,024 B/token`。
2. `B_KV(req)=98,304×input_tokens`；4K prompt=402,653,184 B=384MiB；TP2每rank=201,326,592 B=192MiB。
3. 200 Gbps=25,000,000,000 B/s。只有单一200G cut确实串行承载该shard时，可用`bytes/capacity`作payload-only下界；TP2 4K shard下界8.05306368ms。
4. 4P1D ns-3 fixture资源：每server 8 GPU共享2×200G NIC；每NIC聚合4 rank；两个独立Decode rails；receiver egress link 113/123各200G；32MiB buffer、packet payload4KB、200G ECN Kmin约600KB/Kmax约2.4MB。
5. 固定LAYERWISE packet账本：4 request、4096 prompt、TP2、48层、2×2048 chunk、96 wave、768 message、1.610612736GB；last release 133.679955ms，profile Prefill end 135.319248ms；CC0/CC1 last packet finish134.059112/134.963180ms，compute slack1.260136/0.356068ms。
6. `P2D_ready_r=max_i(flow_finish_{r,i})`；该max不是各shard FCT求和。`TBT_n=token_finish_n−token_finish_{n−1}`；`TPOT`按request代码定义取TTFT之后总latency除以除首token外的生成token数。
7. FlowSim可用于有向链路共享下的fluid max-min/work-conserving completion与Serving DAG反馈；它不能表示packet queue/ACK/ECN/CNP/PFC/DCQCN。

### 固定资源约束

理论比较保持同一GPU总数、prefill/decode placement、TP/EP合法rank组、GPU↔NIC映射、每物理链路容量/数量、路由、KV dtype/字节公式、请求input/output/arrival、compute profile、batch limits、Decode KV capacity、collective语义与通信byte守恒。多条NIC rail分别算cut；必须以rank map判断flow瓶颈，不可把server aggregate带宽误作一条flow带宽。

### 可以/必须重叠与等待的过程

- LAYERWISE：每层QKV生成后该层P2D send可与之后层Prefill compute重叠；后层计算不等待此前send完成。
- request交接：Prefill整体图完成与required P2D send completion形成图完成条件；decode request携带这个completion时间。P2D_READY后还可能等Decode slot/下一个合法batch。
- MoE：dispatch required通信join后才能进入相应expert compute；combine依赖expert compute；group/round的last required peer决定collective join。是否与其它计算重叠需查精确图DAG，不能从CCT单值断言。
- TTFT按当前simulator在Prefill sampler后的首token计算完成记账；Decode首轮不会再定义first token。

### 目前最可能高估理论收益的假设

1. 把flow FCT/CCT的相对变化当作TTFT/TBT同比变化。
2. 忽略LAYERWISE release slack、下一Decode batch边界、token compute及Decode capacity wait。
3. 把一个collective所有通信时长都当作关键peer暴露时长。
4. 把aggregate server NIC容量当成单flow或单receiver rail可用带宽。
5. 把AE=8 clamped MoE时间当成EP32/64真实kernel time。
6. 把固定packet release replay的ECN/CNP时间线当成Serving实时可用控制输入。
7. 把不同run的packet queue、FlowSim CCT和Serving TTFT/TBT拼成因果路径。

### 当前可检验/暂不可判定的问题

- 可检验：特定同一有向receiver cut上P2D incast的packet queue/DCQCN影响；固定profile release schedule是否把网络delay隐藏于Prefill compute；FlowSim max-min下不同flow释放/路径竞争的fluid结果；给定合法EP4 group的FlowSim collective barrier与ITL关系。
- 暂不可判定：真实部署中KV QP跨层/请求的拥塞状态继承；packet级拥塞信号是否能在线改变下一批合法Prefill work并提升TTFT/TBT；profile校准EP64下的量化端到端效果；跨Serving、GPU profile、RDMA receiver commit的一体化理论最优上界；在公平保护其它请求后是否仍有>15%可实现的净收益。

### 结论

该仓库已具有可用于理论建模的模型字节公式、显式Serving/collective DAG、fluid backend和packet telemetry工具；但是这些数据源尚未在一条校准、同run、serving-feedback闭环中全部汇合。对外报告时最稳妥的状态为：

```text
BASELINE STATUS: PARTIALLY_VALIDATED
TRUSTED COMPLETE PACKET-TO-SERVING CRITICAL PATH: NO
15% SERVING HEADROOM UPPER BOUND: NOT COMPUTABLE FROM AVAILABLE EVIDENCE
NEW PERFORMANCE EXPERIMENTS THIS AUDIT: NONE
```

下一位理论分析者可直接使用第4、6、8、12、16节列出的公式/固定账本与资源限制；但在获得第15节P0事件前，不应输出一个声称覆盖packet network→serving端到端的精确最优收益数字。
