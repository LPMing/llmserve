# PD-disaggregated MoE serving 网络研究：历次方向、实验配置与结果总账

> 汇报版证据索引；依据当前仓库保留的原始/汇总材料整理。更新日期：2026-10-02。本文的“无数据”表示未测、未完成或无法从现存工件核验，**不表示 0**。本文不将网络代理指标当作 TTFT/TBT，也不把历史失效数字当作当前结论。

## 一、领导先看：研究到了哪里

研究主线从“P2D KV 与 Decode MoE EP 在交换网络竞争”出发，先后研究了静态流量优先级、请求驱动的多层 KV、EP64 高并发、拓扑/placement/路径/collective barrier、包级拥塞控制与有限资源、远程前缀 KV、split-source assembly、progressive push，以及 50/200G 速率敏感性。下面的目录表和逐项结果包括成功、阴性及无效尝试。

目前最稳固的发现有三项：

1. **网络竞争确实存在，EP barrier 可能被明显放大。** 原始人工 ns-3 ordered case 的 RR/EP-only slowdown 为 9.6–58.6 倍；模型驱动的小型 native ns-3 matched case 为 2.028 倍；正确链路配置下的高并发 FlowSim S16 也出现数毫秒级 EP CCT 差异。不过三者的工作负载、后端和统计口径不同，不能拼接成一个统一“收益”。
2. **网络指标不自动转化为 serving 收益。** 已完成的 EP64 integrated 96-request、4-token 运行中，`EP_FIRST` 相对 FAIR 把 Decode TBT P99 从 26.041 降到 7.421 ms（−71.5%），但 P2D KV FCT P99 仍为 283.909 ms、P2D TTFT P99 仍为 292.119 ms。相反，经过修正的 S16 packet fan-in case 虽使 EP CCT P99 增加 29.1%，对应较小 integrated 窗口的 TBT P99 仅增加约 5.0%，TTFT 不到 1%。**不能宣称所有网络 20% headroom 都有 serving 20% headroom。**
3. **至今没有完成“可发表的双边静态优先级 crossover”或远程 KV 新架构 PASS。** `EP_FIRST` 对 KV/TTFT 的额外代价在当前非阻塞、分层 P2D 语义下通常不到 1%；`KV_FIRST` 经常严重伤害 EP/TBT。远程 provider 离线 packet barrier 有 37%–79% headroom，但计入 replica warm-up 并跑 integrated 后没有稳定 TTFT 改善；合法 split-source 反而恶化 TTFT。50G packet-level 放大 EP 竞争，却没有完成 integrated serving 验证。

**证据等级。** `P`：完成的 native ns-3 packet replay，可谈物理队列/ECN/PFC，但若仅 network-only，不可谈 TTFT；`F`：完成的 FlowSim network replay，可谈有向流体容量、FCT/CCT/analytical backlog，不能谈 packet queue/ECN；`I`：完成的 integrated serving，才可谈真实仿真 TTFT/TPOT/TBT；`H`：历史、已失效或仅口头/摘要保留；`X`：超时/模型缺项，没有结果。下文每项都标等级。所有时延均为**仿真时间**，不是实验运行墙钟时间。P99 应注明样本量；一个 KV-bearing request 的 mean=P99 只是单样本。

### 统一计量与可比性

| 指标 | 本文采用的含义 | 重要限制 |
|---|---|---|
| KV flow FCT | 单个 layer/shard flow 的完成−请求时间 | 不是 request handoff，更不是 TTFT |
| KV request handoff/FCT | 一个请求所有 required P2D shard 最后完成，减该请求的首个 KV request/相应到达锚点；具体锚点随实验报告注明 | 是 `max` barrier，不是各 flow FCT 之和；异构 512 表只统计 256 个 P2D 请求 |
| EP CCT | 一轮 dispatch/combine 所有 peer flow 的最后完成−collective start | 不是单 flow latency；网络 replay 的 EP_CCT 不能直接改名 TBT |
| TBT/ITL、TPOT、TTFT | integrated serving request/token CSV 记录 | 1-token case 没有稳态 TPOT；network-only 表格一律标“未测” |
| FlowSim backlog | residual analytical/fluid backlog | 不是交换机 packet-buffer occupancy；没有 ECN/PFC/drop |
| 百分比 | 除非特别注明，`(实验值/同工作负载对照值−1)×100%` | `FULL vs KV_ONLY` 与 `EP_FIRST vs FAIR` 是不同问题 |

## 二、实验平台和配置总图

| 代号/阶段 | 大小与模型 | 网络/通信配置 | 主要用途与状态 |
|---|---|---|---|
| 原始 HPCC/ns-3 | P0/P1→D0–D3、共享 ToR egress，100G host links；人为有限 256MiB–2GiB KV，EP burst 数 `B`/周期 | packet/RoCE；RR、STRICT_EP、static WRR | 证明物理竞争；无 LLM request semantics，无 TTFT/TPOT；仅 `ordered`/sanity valid 行可用 |
| 小型 LLMServingSim | 1P2D/EP2，或 3 Decode+1 P2D；Qwen3-30B-A3B，128 experts、top-k8、48层；100/200G | FlowSim LAYERWISE 或 POST_PREFILL；旧 packet matched EP4；数据量由模型+token 导出 | cross-request overlap、handoff gate、静态 policy；有 network-only 和少量 integrated |
| S16/EP64 | 16 server ×8GPU=128 GPU，8P:8D；TP2、Decode EP64，Qwen3-30B-A3B；4 leaf/2 spine，endpoint 200G | 正确 FlowSim：每 leaf→spine 有 16×200G=3.2Tbps 定向 bundle、单 endpoint 仍 200G；native ns-3 必须逐根物理链路建模 | 96/256/512 请求，高并发、异构 KV、placement/path、packet gate；部分 integrated |
| S64 | 64 server/512GPU，P:D=32:32，EP16、200G 1:1 Clos | real-trace slices、FlowSim/native ns-3/HTSim 尝试 | 有 bounded network replay；**没有 1万/2.5万 request 的合法 integrated packet TTFT/TBT/SLO matrix** |
| S256 | 256 server/2048GPU，P:D=128:128、EP64、200G | topology/cost/config audit | 完整 real-trace integrated packet matrix 未完成，不报告性能 |
| S16 速率敏感性 | 同 S16/EP64，3/4 请求，8192-token KV | 50G **和** 200G endpoint+fabric，4KiB packet；native ns-3 | 有完成的 packet network-only；50G **不是**“4 GPU 共用 1 块 200G NIC” |

S16 中 leaf–spine 3.2Tbps 是 16 根并行物理 200G 链路的**aggregate fluid capacity**，不能解释为单 flow 3.2Tbps；单 GPU/NIC 路径仍受 200G endpoint 限制。旧 parser/旧 packet route 曾只保留一根链路，以下专列失效数字。详细拓扑及审计见 [拓扑/网络门禁](PD_NETWORK_RESEARCH_GATES.md)、[失败与边界总表](FAILED_RESEARCH_ATTEMPTS.md)。

## 三、方向索引：最后能得出什么结论

| 方向 | 最后有结论的配置/对照 | 后端与级别 | 最终判断 |
|---|---|---|---|
| A. 原始 KV–EP/静态 WRR | ordered C1–C8、EP-only/KV-only/mixed/STRICT_EP | 旧 ns-3 `P` | 网络机制成立；synthetic workload，不能外推 TTFT |
| B. model/request-driven KV–EP | 4-request 200G，POST_PREFILL vs LAYERWISE；native matched EP4 | FlowSim `F`、ns-3 `P` | 网络效应成立，transfer granularity 敏感 |
| C. policy crossover/finite buffer | 8P8D EP64，32D+64P2D，FAIR/EP_FIRST/KV_FIRST，1/4-token、32MiB staging | FlowSim `I` | EP_FIRST 保护 EP/TBT，但额外 KV/TTFT 代价 <1%；未见预期双边 crossover |
| D. high-concurrency/heterogeneous KV | S16 256/512 request，spread/fan-in，small/mixed/large KV | FlowSim `F` | 平均和 P99 均有网络差异；无 512-request integrated serving |
| E. P1 placement/critical-cut | S16 real window DEFAULT/LOAD/ORACLE | FlowSim `F` | 0–7.1% EP 变化、KV 几乎不变；serving PASS 未建立 |
| F. P2 last shard/path、多路与 P3 ingress | S16 path seed/alternate/RR、fanin 与 packet correction | FlowSim `F` + ns-3 `P` +小窗 `I` | flow/EP tail 可放大，但 request/TTFT gate 小 |
| G. EP critical-flow selective protection | EP64 Mooncake/BurstGPT，TOP1/5/10 vs EP_FIRST | FlowSim `F` | TOP5 造成新 straggler，几乎没有 KV 收益；NO-GO |
| H. same-byte EP peer geometry | GateRouter A2A vs uniform；EP_ONLY/FULL | FlowSim `F` | 约 78% 差异在 EP-only 已存在，不是 PD-specific；无 serving PASS |
| I. packet CC/QP/backpressure/burst | DCQCN vs无反馈；QP 生命周期与资源审计 | ns-3 `P` +语义审计 | per-flow 可大幅变动，barrier <1%；其余缺真实资源语义 |
| J. remote hot-prefix/provider | Mooncake 8 request packet FIRST vs replica oracle；4 request integrated with warm-up | ns-3 `P`、FlowSim `I` | packet remote barrier 有 headroom，计成本后的 serving 动机 NO-GO |
| K. split-source KV assembly | B1 R→P→D vs合法 V1 双目的地，2个 Mooncake 高复用窗 | FlowSim `I` | TTFT 恶化 22.9%–61.1%，NO-GO |
| L. N1–N5 新方向 | Decode boundary、handoff wave、multi-NIC、KV batching、recovery | FlowSim `I`/trace 审计 | N1 暴露 1.2%–6.5% TTFT；N2–N5 未具可信仿真机制 |
| M. Progressive Push | Whole vs progressive，Mooncake 窗、不同带宽 | FlowSim `I`，但旧小拓扑 `H` | 50G 曾见 20.22% TTFT，拓扑 rank 冲突；100/200G 更弱；不能做权威 PASS |
| N. 50G packet rate sensitivity | S16 EP64 4 req、50 vs 200G、3 policy | ns-3 `P` | EP CCT 尾部 +189%，KV handoff +0.7%；integrated 全超时 |

## 四、各方向的“问题—配置—网络结果—端到端结果”

### A. 最早的人工 ns-3/HPCC motivation（包级，旧仓库）

目的：证明长生命周期 bulk P2D KV 与短、突发且 barrier-sensitive 的 EP 在共享 ToR egress 竞争，以及 RR/STRICT_EP 的顺序效应。配置为 100G host link、共享 `ToR 6 egress ifindex 3`，有限 1GiB KV（WRR 敏感性另有 256MiB、512MiB、2GiB），人工 EP burst 参数 `B` 与 period；**不是 request/model 驱动**。有效 ordered case 下 EP RR/EP_ONLY slowdown：C1 10.233×、C2 9.628×、C3 10.612×、C4 10.110×、C5 12.789×、C6 **58.632×**、C7 13.217×、C8 12.772×；STRICT_EP 对 EP 为 1.009–1.024× EP_ONLY。KV RR/KV_ONLY 为 1.034–2.063×，STRICT_EP 的 KV slowdown 几乎相同。有效 case 共享队列峰值约 1.45–2.09MB，ECN 32,736–117,844，PFC=0。WRR 16 个 `(KV大小,B)` cell 有时 EP 最优 share 与 KV 最优 share 不同，但不构成 LLM serving-level 动态调度结论。C1/C2/C3/C4/C4_retry/C5/C6/C7/C8_retry 的旧 unordered/不完整 run 标为 `FAILED_SANITY`/`FAILED_INCOMPLETE_FLOW`，**不能拿“1.0×”当阴性结果**。TTFT/TPOT/TBT/SLO：未模拟。原始依据：[旧 ns-3 REPORT](/home/dell/lpm/ns3-kv-ep/experiments/pd_kv_ep/results/REPORT.md)。

### B. 小规模模型驱动 KV–EP 与层级粒度（流级 + packet）

目的：不再把 1GiB KV 当 synthetic byte，而由 Qwen3 prompt/48层 KV、GateRouter MoE routing 产生 P2D/EP。核心 4-request 结构是 **3 个已在 Decode 的请求 + 1 个新 P2D**，同一请求的 P2D 必须在其 Decode EP 之前完成；这里只研究跨请求 overlap。小型 FlowSim 200G 表如下（`+%` 相对同 workload EP_ONLY/KV_ONLY；表中无 TTFT）：

| P2D mode/新请求 | policy | EP CCT P99 / 对照变化 | KV request FCT / 对照变化 | 说明 |
|---|---|---:|---:|---|
| POST_PREFILL，8192 tokens | FAIR | 0.127330 ms / +32.812% | 16.485118 ms / +2.344% | EP 明显更敏感 |
| 同上 | EP_FIRST | 约 0.096 ms / 0% | 16.485 ms / +2.344% | 保护 EP，KV 与 FAIR 基本相同 |
| 同上 | KV_FIRST | 12.895746 ms / +13,351% | 16.108 ms / 0% | 极强 EP penalty，非合理性能目标 |
| POST_PREFILL，128 tokens | FAIR | 0.104877 ms / +9.393% | 0.280172 ms / +10.670% | 小 KV 绝对规模低 |
| 同上 | EP_FIRST | 约 0.096 ms / 0% | 0.280172 ms / +10.670% | 注意这不是 EP_FIRST-vs-FAIR 的 +10.67% |
| 同上 | KV_FIRST | 0.347531 ms / +262.495% | 约 0.253 ms / 0% | tradeoff 仅网络层 |
| LAYERWISE，8192 tokens | FAIR | EP_ONLY +32.812% | 143.440 ms / +0% | 96 layer/shard P2D events；累积生成/释放与 post-prefill 不同 |
| 同上 | EP_FIRST/KV_FIRST | 约 EP_ONLY / EP_ONLY +349.993% | KV 与 FAIR 基本相同 | 分层 P2D 无明显 KV-side policy crossover |
| LAYERWISE，128 tokens | FAIR/EP_FIRST | +5.469% / 0% | 5.575/5.587 ms | policy KV 差异约 0.2% |

一次早期 POST_PREFILL integrated sanity 有小 KV FAIR TTFT P99 59.425 ms、TPOT 7.313 ms、TBT P99 9.276 ms；EP_FIRST TTFT P99 59.384 ms。它与上表的 network-only 版本/时间锚点不是完全匹配的同一试验，因此**不能把 +32.8% EP CCT 直接换算成端到端变化**。有模型驱动 native ns-3 matched EP4：1×512-token P2D，EP P99 6.545→6.762 µs（+3.3%）；1×2048，6.545→6.827 µs（+4.3%）；2×2048、P2D 402,653,184 B，6.545→13.270 µs（+102.8%），共享 core queue mean 约 2 B→84,444 B，ECN/PFC/drop=0。早期另一个 EP4 matched cohort 中 FAIR 16.748→EP_FIRST 9.456 µs（−43.54%）；**都是网络/cohort 结果，不是 whole-run TPOT/TTFT gain**。依据：[FlowSim 原始小型报告](results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md)、[分层报告](results/flowsim_layerwise_motivation_200g/layerwise/SIMPLE_MOTIVATION_REPORT.md)、[characterization](CHARACTERIZATION_REPORT.md)。

### C. EP4/EP64 integrated：static priority 与 backpressure

目的：验证 `EP CCT→TBT` 与 `KV drain→TTFT` 是否能在真实 serving DAG 闭合；比较 `FULL vs isolated` 和 `EP_FIRST vs FAIR`，后者才是 policy 的额外 KV 代价。EP4/100G LAYERWISE integrated（3 Decode×128 output +1 新 8192-token P2D）：FAIR EP CCT P99 11.860 µs、Decode TBT P99 5.541 ms、TPOT 5.491 ms、P2D TTFT 925.320 ms；EP_FIRST 9.365 µs、5.526、5.482、925.320；KV_FIRST 148.982 µs、6.003、5.661、925.320。可见网络 CCT 的大倍率到 TBT 只剩约 +8.3%（KV_FIRST vs FAIR），KV TTFT 不变。另一个 EP4/100G 2D+2P2D/2048-token integrated：FAIR TBT P99 5.683 ms/TPOT 5.251/P2D TTFT 246.550；EP_FIRST 5.670/5.246/246.345；KV_FIRST 5.767/5.405/246.856。见 [EP4 integrated](results/integrated_characterization/ep4_100g_3ep1kv_policy_summary.md)。

更高 EP degree 的历史 integrated 窗口：8P8D/EP64/200G、32 active Decode+64 新 P2D（2048-token）、LAYERWISE、同一 request set。1-output gate 完成 96 请求及 9,216 P2D shard；**这是首 token 邻近验证，不能用零/缺失 TPOT 冒充稳态 TPOT**：

| policy | EP CCT P99 ms | request KV handoff FCT P99 ms | TTFT P99 ms | token TBT P99 ms | max generated−completed KV GB |
|---|---:|---:|---:|---:|---:|
| FAIR | 1.747824 | 285.070825 | 298.845624 | 46.927517 | 6.308 |
| EP_FIRST | 0.380377 | 286.400189 | 299.982055 | 13.679489 | 6.442 |
| KV_FIRST | 128.899535 | 280.945042 | 308.863184 | 265.812184 | 6.241 |

这组内 `EP_FIRST vs FAIR`：EP P99 −78.24%、TBT P99 −70.85%、KV FCT **+0.47%**、TTFT **+0.38%**。只比较 FULL vs KV_ONLY 会得到不同因果问题。32MiB 可选 per rank/request staging-buffer sensitivity（非真实 runtime 已校准容量）：FAIR `EP/KV/TTFT/TBT P99=1.055880/285.028701/298.741470/28.760167 ms`；EP_FIRST `0.380377/286.382053/299.922104/13.651404`，即 KV +0.47%、TTFT +0.40%；max outstanding 从无 BP 6.308/6.442GB 降到 4.765/4.865GB，但不能据此声称已经建模 GPU producer stall。生成速率约 447–452Gbps、drain 347–354Gbps，是**全体 P2D 的 aggregate**，非单根链路吞吐。

同一历史 32D+64P2D 的 **4-output** integrated run（TBT/TPOT 更有意义）：

| policy | Decode TTFT P99 ms | Decode TPOT P99 ms | Decode TBT P99 ms | P2D KV FCT P99 ms | P2D TTFT P99 ms |
|---|---:|---:|---:|---:|---:|
| FAIR | 53.713 | 15.408 | 26.041 | 283.909 | 292.119 |
| EP_FIRST | 50.472 | 4.947 | 7.421 | 283.909 | 292.119 |
| KV_FIRST | 308.127 | 5.511 | 265.076 | 280.910 | 297.238 |

这里 EP_FIRST 的 Decode TBT/TPOT P99 分别 −71.5%/−67.9%，P2D TTFT/FCT **不变**；KV_FIRST 使 Decode TBT P99 +917.9%。这些是完成的 integrated 运行，但与后续**拓扑容量修正后的网络-only S16 replay不是同一可替换实验**；绝对量级和论文主张在引用前应以修正后的统一配置复测。另一 4-output FAIR run 完成 1,232 EP rounds、TTFT P99 302.777 ms、TPOT P99 32.363 ms、TBT P99 51.544 ms，但只有 25 条 token 可精确映射 EP round，135 条不能精确归因，不能拿它证明所有 token 的 EP critical fraction。详情：[EP64 characterization](CHARACTERIZATION_REPORT.md)。

**关键历史纠错：**旧 EP64 network-only `32D+64P2D` 的 FULL-vs-KV_ONLY KV FCT P99 `318.116/257.718−1=+23.44%` 是旧 parser 把 16×200G 并行 bundle 错作 1×200G；纠正后相同网络 flow 重放 FULL FAIR 与 KV_ONLY 都为 **46.192 ms，slowdown 0%**。即使旧值正确，也不是 EP_FIRST-vs-FAIR 的代价。不能用旧 +23.44% 支撑 crossover。

### D. 正确 S16 下的高并发、目的地聚集与异构 KV（FlowSim network-only）

目的：检查请求数/混合长度/receiver concentration 能否自然产生共同 cut 竞争。S16 200G，TP2、EP64、LAYERWISE。256 请求为 128 active Decode+128 P2D，P2D 12,288 events/25.77GB，EP 129,024 events/25.37GB：FAIR EP CCT mean/P99=0.359476/0.586232 ms、KV request FCT mean/P99=46.527557/46.527557 ms；EP_FIRST EP 0.348697/0.523317、KV 不变；KV_FIRST EP 0.500518/1.865495、KV 不变。KV mean=P99 源于**同尺寸且同步**的 P2D request barrier，没有形成分布，不是“所有 shard 求和”。

512 请求为 256 Decode+256 P2D，P2D 24,576 events/51.54GB、EP 258,048 events/50.73GB。同 request 与 bytes 下仅将 destination 从 `spread` 改为 `fan-in16`：

| placement/policy | EP CCT mean / P99 ms | request KV FCT mean / P99 ms | FlowSim max residual backlog |
|---|---:|---:|---:|
| spread/FAIR | 1.390452 / 4.385188 | 74.510843 / 74.510843 | 2.499GB |
| spread/EP_FIRST | 0.677393 / 1.026633 | 74.510847 / 74.510847 | 未列 |
| spread/KV_FIRST | 12.106721 / 73.601330 | 64.444513 / 64.444513 | 未列 |
| fan-in16/FAIR | 6.077813 / 13.211696 | 148.277146 / 148.277146 | 9.862GB |
| fan-in16/EP_FIRST | 0.677393 / 1.026633 | 148.498375 / 148.498375 | 未列 |
| fan-in16/KV_FIRST | 45.447981 / 146.895603 | 128.869021 / 128.869021 | 未列 |

FAIR 下 fan-in16 相对 spread：EP P99 **+201.3%**、KV P99 **+99.0%**。但这是集中目的地的 **network-only** 操作，不是已证实的 TTFT/TBT 改善。高并发离线 alternate-spine/round-robin path 曾把网络 EP P99 从 4.385 降到 2.002/1.105 ms、KV 从 74.511 降到 65.779/46.528 ms；这是 FlowSim 的逻辑 path-sensitivity，不等于 packet ECMP hash 的可部署收益。见 [高并发结果](results/HIGH_CONCURRENCY_MOTIVATION_REPORT.md)。

为修正上述“KV mean=P99”的统计问题，512 请求中 256 个 P2D 改成 2,048-token 小 KV（201,326,592B/request）或 8,192-token 大 KV（805,306,368B/request），Decodes 为 128 输入/64 输出，P2D 在 20ms 到达。下面全部是**request-level KV FCT**，单位 ms；EP 按 collective 统计，P99 用 nearest-rank。`sm/lg` 为小/大 KV 的 request mean/P99；没有 integrated TTFT/TBT：

| profile（小/大数） | policy | EP mean/P99 | 全 KV mean/P99 | 小 KV mean/P99 | 大 KV mean/P99 |
|---|---|---:|---:|---:|---:|
| 小为主 205/51 | FAIR | 1.313/3.719 | 85.680/144.465 | 71.106/72.062 | 144.262/144.465 |
|  | EP_FIRST | 0.677/1.027 | 86.084/144.465 | 71.610/72.075 | 144.262/144.465 |
|  | KV_FIRST | 25.413/108.200 | 78.736/144.465 | 62.435/62.652 | 144.262/144.465 |
| 混合 128/128 | FAIR | 1.699/2.953 | 125.706/183.276 | 68.137/68.137 | 183.276/183.276 |
|  | EP_FIRST | 0.677/1.027 | 125.710/183.276 | 68.145/68.145 | 183.276/183.276 |
|  | KV_FIRST | 66.823/179.878 | 110.604/159.620 | 61.588/61.588 | 159.620/159.620 |
| 大为主 51/205 | FAIR | 3.174/4.997 | 213.519/258.345 | 68.509/68.761 | 249.595/258.345 |
|  | EP_FIRST | 0.677/1.027 | 213.051/258.422 | 68.546/68.881 | 249.001/258.422 |
|  | KV_FIRST | 132.734/256.231 | 187.982/228.617 | 62.307/62.546 | 219.248/228.617 |

随大 KV 占比增加，FAIR 下 EP mean 从 1.313→3.174ms、全 KV mean 从 85.680→213.519ms；EP_FIRST EP 固定较低而 KV 变化小，KV_FIRST KV 改善但 EP mean 激增。注意 [另一份异构摘要](HETEROGENEOUS_512_POLICY_SUMMARY.md) 的“全 KV mean”约为此表**一半**，与 [按 256 个 P2D request 统计的汇总](PD_KV_EP_RESEARCH_SUMMARY.md) 冲突；本文以后者和分组加权一致的值为准。例如小为主 FAIR `(205×71.105697+51×144.262057)/256=85.679816 ms`，不是 42.84ms。不能混用两份表的 quantile 算法。

### E–H. Placement、路径、barrier、selective EP：有网络现象，但论文 gate 未过

| 假设/最后测试 | 配置与要验证的问题 | 网络量化结果 | integrated serving / 结论 |
|---|---|---|---|
| P1 P/D pairing×EP critical path | S16 EP64 200G、64-request BurstGPT/Mooncake 窗，保持 bytes/Decode load，仅 DEFAULT vs MAX_OVERLAP | BurstGPT `074181` EP P99 106.508→106.508µs、KV 23.741→23.741ms；`148335` EP 98.644→105.660µs (+7.1%)、KV 16.990ms 不变；Mooncake conv EP 363.895→380.829µs (+4.7%)、KV 933.265ms 不变 | 无 ≥20% serving gap；对称 Decode cuts/共有 ingress 限制 geometry 收益。`FAIL` |
| P2 last-shard/多路径 | 相同 flow bytes，alternate spine/逻辑 RR，观察 `max shard` 与 request handoff | 早期合法低负载路径改动未改 KV handoff；高并发离线 path sensitivity 有网络 gap（见上），但不能当 packet ECMP/serving 结论 | 缺 packet ECMP collision→last shard→TTFT 完整链。`未PASS` |
| P3 Decode receiver incast | 4 Decode instance 平衡 vs fan-in，另有极端1 instance upper bound | realistic 4-instance EP P99 +10.9%，KV P99 +0.07%；极端1-instance EP 明显升高，KV/TTFT proxy <1% | integrated 64D+64P2D TBT 约 +2.5%、TTFT <1%；网络机制存在，serving gate `FAIL` |
| P4 barrier-aware multipath | ECMP-like/striping vs offline best path | 正确聚合低负载下 last-shard barrier 无差别；FlowSim 不模拟 packet hash | `FAIL`；不能声称 ECMP 可部署方案已验证 |
| EP critical-only priority | S16 EP64 Mooncake Tool 64req 与 BurstGPT，EP_FIRST vs TOP5 离线真正/近 critical peer | Mooncake EP P99 98.644→155.582µs (+57.72%)、KV P99 159.852→159.318ms (−0.33%)；BurstGPT EP 98.644→137.966µs (+39.86%)、KV 25.382ms 不变 | 保护少数 flows 会产生新的 last peer；没有可观 KV/TTFT headroom，`NO-GO` |
| exact GateRouter vs same-byte uniform peer | BurstGPT 64req，EP_ONLY/FULL，P2D 3.099GB、EP 29.219GB，不改 total bytes | EP-only P99 exact/uniform 0.099/0.175ms；FULL 仍 0.099/0.175ms；gap +77.56% **在 EP-only 已存在**；加入 P2D 的 incremental P99≈0 | 是 generic EP geometry，非 PD-specific 放大；未继续伪造 integrated TBT，`GATE1_FAIL` |

来源：[placement/路径门禁](MOTIVATION_GATES_REPORT.md)、[selective EP](CRITICAL_EP_PROTECTION_VALIDATION.md)、[same-byte gate](results/exposed_barrier_validation/EXPOSED_BARRIER_FAIL_REPORT.md)。

### F 的包级复核：为什么“flow 尾部”不是“request/serving 尾部”

旧 S16 packet fan-in replay 由于平行物理链路 route table 只暴露一根而**失效**，旧所谓 KV request P99 +96.5%、EP CCT P99 +54.3% 不能再引用。修正后相同 32D+64P2D、S16 EP64、200G、4KiB native ns-3 ledger 中 12,240 events 全完成（9,216 P2D+3,024 EP），spread/fan-in16 比较：

| 正确 packet metric | spread | fan-in16 | 变化 |
|---|---:|---:|---:|
| 单 flow FCT mean / P99 ms | 0.233 / 0.591 | 0.304 / 0.797 | +30.7% / +34.9% |
| KV request handoff mean / P99 ms | 32.753 / 46.493 | 32.881 / 46.673 | +0.39% / +0.39% |
| EP collective CCT mean / P99 ms | 0.203 / 0.366 | 0.222 / 0.473 | +9.6% / +29.1% |

链路物理路由正确后有全部 16 根 parallel links，单对 leaf–spine max packet queue ≈4.05MB，某对链路 ECN 19,689（旧错误路由 76,683，不可直接作政策对照）。墙钟约 410/432s、RSS 约 344/342MB，只说明这段 bounded replay 的仿真成本。对应**较小的 96-request integrated FlowSim** `spread→fan-in16`：Decode TTFT 49.844→50.185ms (+0.68%)、TPOT 4.529→4.755ms (+5.01%)、TBT P99 6.793→7.134ms (+5.02%)；新 P2D TTFT 114.275→114.596ms (+0.28%)。两个后端/窗口不能合并成同一次因果测量，但共同表明 flow tail 到 request barrier 会被 `max` 与 compute/admission 日程过滤。256-request integrated 超时、RSS≈2.76GB，无合法 TTFT CSV。见 [packet replay gate](P2_PACKET_REPLAY_GATE.md)；**该源文档开头仍保留旧错误路由表，必须看后半部分的“Corrected fan-in16 replay”，不能直接引用开头表格**。

### I. 包级特有机制：CC、QP 生命周期与资源语义

目标：寻找 FlowSim 看不到的 ECN/CNP/DCQCN 反馈跨 EP burst、持久 QP 继承、有限发送资源反压、layerwise injection shaping。native ns-3 正确 DCQCN 是 `CC_MODE=1`；某些旧配置的 `CC_MODE=12` **不实现同一个 DCQCN 模式**，只能统计 packet ECN，不能据其声称 DCQCN rate evolution。正确模式下 packet S16 32D+64P2D、4KiB 的一次诊断观察到 CNP 51,784、rate reductions 36,939、recovery 1,926，CNP→rate decrease median/P95=2.3/4.0µs，恢复约 0.9ms，说明反馈确实存在。与 CC_MODE=0 对照、long-KV8 窗口，flow FCT mean 0.257→0.396ms (+54%)、P99 1.054→1.959ms (+85.9%)，但 request KV handoff mean/P99 仅 +0.52%/+0.66%、EP CCT 约 0%；long-KV16 handoff +0.49%/+0.59%、EP 约 0%。**P1 CC mismatch 对单 flow 显著，对 serving barrier 未过关**。

P2 persistent-QP：当前 replay 每 flow 新建 QP，不复用 DCQCN 状态；未找到可校准的跨请求 QP lifecycle，故 `NO MODEL`，不能虚构 inheritance 20%。P3 generation–drain backpressure：虽见 6GB 级 outstanding KV，前端没有已验证会阻塞 Prefill producer 的 NIC/WQE/注册缓冲容量；32MiB buffer 只是可选 sensitivity，不能宣称真实 stall。P5 layerwise burst shaping：当前没有 NIXL/UCX chunk/WQE/NIC pacing 的可信 release 模型，改 MTU 只是 packetization，不是合法 transport shaping。以上结论见 [packet autonomous research](PACKET_LEVEL_AUTONOMOUS_RESEARCH.md) 和 [失败总账](FAILED_RESEARCH_ATTEMPTS.md)。

### J. Mooncake remote prefix / provider 热点：packet barrier 有、serving headroom 没有

真实 trace：Mooncake Tool/Agent 23,608 requests、409,616 block references、183,300 unique、重复引用 55.25%、最热 block 10,938 次；Conversation 12,031 requests、288,500 refs、182,790 unique、重复 36.64%、最热 block 12,031 次。`hash_ids` 是 block identity，**不是 token ID**。Azure code/conversation 约 1,680万/2,730万 requests、BurstGPT 约 143万 requests 的 converter/materialization 曾审计，但未跑完整 packet trace；Azure 无 prefix token identity，不用于 remote reuse 论证。真实 arrival 及模型 KV byte 必须保留，不能把 block hash 伪造成 token。见 [Mooncake packet direction](PACKET_LEVEL_PAPER_FEASIBILITY.md)、[trace审计背景](P4_RESEARCH_AUDIT.md)。

P4 native packet S16/EP64/TP2、200G、4KiB、8 个 Mooncake Tool 请求、同 total remote bytes/EP ledger：

| 原始 trace window / offline provider | remote flow数、总 bytes | remote request barrier mean / P99 ms | EP CCT P99 ms | 结论 |
|---|---:|---:|---:|---|
| Tool offset 13327，FIRST_PRODUCER | 14、352MiB | 7.6049 / 7.6052 | 0.1296 | provider 源 egress 热点 |
| 同窗 BALANCED_REPLICA_ORACLE | 14、352MiB | 1.6328 / 2.0977 | 0.1298 | barrier mean −78.5%、P99 −72.4%；EP 未改善 |
| Tool offset 0，FIRST | 10、768MiB | 6.0596 / 4.3743 | 0.1136 | 时间/样本分布偏斜，mean 可大于 P99 |
| 同窗 oracle | 32、768MiB | 3.8077 / 2.0809 | 0.1171 | mean −37.2%、P99 −52.5%；EP 略恶化 |

这里 replica **必须已存在** 才能称 oracle；复制成本不免费。纠正远程 prefix baseline 后，B1 路径为 `Remote→Prefill` 取得命中 prefix，Prefill 只计算 suffix，仍 `Prefill→Decode` 传完整 KV。4-request 高复用 simultaneous integrated FlowSim：FIRST remote fetch 1.125GiB、peak analytical backlog 1.142GiB、TTFT P99 238.698ms，EP CCT mean/P99 3.6/5.0µs；BALANCED_REPLICA_ORACLE remote 0.844GiB **另有 warm-up 0.563GiB**、backlog 降至 0.299GiB，但 TTFT P99 **274.939ms（+15.2%，更差）**；NO_REMOTE TTFT 214.177ms。Staggered high-reuse 窗 FIRST vs existing-holder source TTFT P99 约 129.920/130.183ms（无改进）。因此“provider placement 降低 queue”不等于“TTFT 降低”；没有稳定 EP/TBT coupling。早期 sibling-waiter integrated 表被 corrected B1 semantics 取代，不应作为权威 serving 结论。见 [P4 GO/NO-GO](P4_GO_NO_GO.md)、[critical path](P4_REQUEST_CRITICAL_PATH.md)。

### K. Split-source KV assembly：合法性 gate 后的阴性结果

原 B1 的 cached prefix **须在 Prefill materialize** 才能计算 uncached suffix。纯 V2 `Remote→Decode prefix + Prefill→Decode suffix` 会遗漏 Prefill 对 prefix attention state 的依赖，不能模拟成合法实现。唯一在当前语义下合法的 V1 是 `Remote→Prefill prefix` **加** `Remote→Decode prefix`，Prefill 只 `P2D suffix`；Decode 需等两来源 barrier。它改变了依赖/path，但没有无成本删除 R→P leg；Decode 收到 prefix+suffix 一次，不能 double count。

相同两段真实 Mooncake high-reuse、4-request、EP4/200G integrated 比较：simultaneous 窗 B1 full P2D 2,436,857,856B、R→P 1,207,959,552B；V1 suffix P2D 624,918,528B、R→P 不变，**新增 R→D 1,811,939,328B**，总逻辑 KV movement 近似守恒而非免费降低。两个命中请求之一 TTFT B1 123.012→V1 198.160ms（+61.1%），另一个 238.698ms 不变；EP CCT mean/P99 3.626/4.968µs 不变。staggered 窗 3 个命中请求 TTFT 分别 93.546→123.478 (+32.0%)、53.479→65.732 (+22.9%)、99.939→126.187ms (+26.3%)；EP CCT mean 3.609→4.510µs (+25.0%)、P99 4.968→8.072µs (+62.5%)。**P4B FINAL NO-GO**；不能把非法 V2 的想象收益当论文动机。见 [split-source audit/results](P4_SPLIT_SOURCE_RESEARCH.md)、[final decision](P4B_FINAL_NO_GO.md)。

### L. 其他新方向 N1–N5 的末次证据

| 方向 | 最后配置与量化结果 | 结论 |
|---|---|---|
| N1 Decode batch-boundary amplification | EP64 integrated 8D+8P2D/4-output、16D+16P2D：未出现所需 wait；32D+32P2D/16-output 等待 6.568ms，占 TTFT 101.586ms 的 6.5%；相邻 32D+64P2D 等待 1.418ms，占 TTFT 116.232ms 的 1.2% | 不是稳定 ≥20% serving 效应 |
| N2 P2D handoff phase synchronization | Mooncake 16req 真窗 5/10ms bin 最多 2 个 handoff completion，EP CCT 约 0.099–0.107ms | 没有自然窄 handoff wave；不能人工同步 |
| N3 multi-NIC/rail | S16 没有已验证的 rail/NIC 分配与独立资源 | 语义缺失，不报数 |
| N4 cross-request KV batching/HOL | 当前 KV 按 request/layer/shard；仅 EP 有 memory coalescing | 没有真实跨请求 KV HOL event，不造机制 |
| N5 recovery/rehydration storm | 当前无 failure、restart、cache invalidation/migration 触发 | 没有可验证 event；不报性能 |

详情：[新方向结论](NEW_DIRECTIONS_FINAL_REPORT.md)。

### M. Progressive Push：可运行 sensitivity，但旧小拓扑不能作为权威论文结果

目的：用随 layer release 的 progressive NIXL Push 对照等完整 KV 后 whole push，测试计算与传输 overlap。PP1、无 prefix cache、Qwen3、model-derived bytes 的 1-request correctness：1024 tokens TTFT 70.318→70.318ms (0%)、4096 197.656→181.550 (−8.15%)、16384 1060.301→947.558 (−10.63%)、32768 2874.590→2632.998 (−8.41%)。4-request Mooncake 小拓扑历史结果：50G window `000087` TTFT P99 2397.957→1913.099ms (−20.22%)，邻窗 `000114` −17.76%、`000103` −19.90%；同窗 100G −11.03%，200G −6.07%；TBT P99 未改善。**但早期 1P(TP1)+2D(TP2) 拓扑只有 endpoint IDs 0–3，rank4 与 switch ID4 冲突，50/100/200G 这类旧 4-rank 文件的百分比仅能作探索性诊断，不能作为 validated 5-rank packet/serving PASS。** 后续 endpoint-consistent S16 packet replay 仅 network-only，未获得修正拓扑下的 integrated TTFT/TBT。见 [progressive Push](PROGRESSIVE_PUSH_RESEARCH.md)、[失效检查](FAILED_RESEARCH_ATTEMPTS.md)。

### N. 50G vs 200G：真正完成的包级速率敏感性

纠正 endpoint 的 S16/EP64 native ns-3，8P8D/128 GPU，4KiB payload；4 请求=3 active Decode+1 新 8192-token KV，P2D 805,306,368B/96 events、EP 1,157,627,904B/5,888 events；同 event ledger/路径/time anchor。下表均为**network-only**，一个 KV request 所以其 mean=P99：

| 速率/policy | EP CCT mean/P99 µs | request KV FCT mean/P99 ms | ECN marks | PFC/drops |
|---|---:|---:|---:|---:|
| 200G FAIR | 112.38 / 112.25 | 143.48 / 143.48 | 4,985 | 0/0 |
| 50G FAIR | 324.79 / 324.63 | 144.50 / 144.50 | 50,495 | 0/0 |
| 50G EP_FIRST | 324.50 / 324.57 | 144.50 / 144.50 | 318 | 0/0 |
| 50G KV_FIRST | 427.09 / 1,873.32 | 144.50 / 144.50 | 49,535 | 0/0 |

50G FAIR 相对 200G FAIR：EP P99 +189.2%，KV handoff +0.7%；50G 内 KV_FIRST 相对 FAIR EP P99 +476.5%，EP_FIRST 与 FAIR 近乎相同（**不是 EP_FIRST 总能恢复 EP**）。同链路最大 KV/EP overlap 12.05→79.24ms；packet max queue 约 1.42MB、跨链路 max-mean queue 1.45→4.51KB。另一个 3-request 小窗 75.5MB KV/191.5MB EP：200G FAIR EP mean/P99 91.71/92.20µs、KV mean/P99 8.072/12.870ms；50G FAIR 314.05/321.31µs、8.140/12.943ms；50G EP_FIRST 313.83/316.37µs、8.276/12.949ms；50G KV_FIRST 314.06/321.25µs、8.105/12.934ms。差异方向一致。

**交换机配置和 ECN 解读。** 这组 ns-3 packet switch buffer 为 **32 MiB/switch**（`BUFFER_SIZE 32`，源码乘 `1024×1024`）；ECN KMIN/KMAX 随速率单独配置：50G 为 **250/900 kB**，200G 为 **600/2400 kB**（`ConfigEcn` 源码乘 `1000`，所以这里不是 KiB），Pmax=0.2。50G 的相同字节在链路上停留更久、重叠窗口更长，且绝对 ECN 阈值更低，所以 marks 50,495 > 4,985 不矛盾；不应用 marks 总数直接当公平的“拥塞严重度”或 DCQCN 表现，需归一化按包/bytes、阈值、时间、方向比较。此表原配置模板里 `CC_MODE=12` 不是已确认的 DCQCN 模式，故只声称 ECN telemetry，不声称其后有正确 DCQCN 速率控制。50G 在这里是**独立 50G endpoint NIC 和 fabric**，不是 4GPU→1×200G NIC 的 shared-resource 模型。

4-request integrated 50G 经两个 frontend bug 修复后仍超过 900s；3-request >600s；1-request >300s；8-token/1-output >180s，**均没有合法 request CSV**。因此 TTFT/TPOT/TBT/SLO 均“未获得”，不能从上表插值。来源：[50G packet validation](PACKET_RATE_50G_VALIDATION.md)。

## 五、大规模真实 trace：做过什么，哪些结果不能当完整 serving 结果

三大来源的历史 conversion/materialization 规模：Azure Code 16,803,695、Azure Conversation 27,303,999、BurstGPT 1,429,737、Mooncake Tool/Agent 23,608、Mooncake Conversation 12,031 requests。曾按 ≤25k/request window 与更小 8/16/64 请求片段抽样；**没有对 Azure/BurstGPT 全量或 S64/S256 2.5万请求完成 native packet integrated TTFT/TBT/SLO matrix**。Azure 没有可靠 prefix identity，不能用作 remote-prefix hit 证据；Mooncake `hash_ids` 为块哈希而非 token IDs。S4/S8 仅通信正确性，S64/S256 原定大规模目标并非已经完成的大规模 outcome。具体 real trace Window、arrival 和 prefix 验证须沿每个 materialized manifest 查证，不能只靠规模表。

历史 S64 bounded native counterfactual 曾在摘要中记录 Azure EP P99 +1.39%、BurstGPT +14.60%、Mooncake Tool +19.15%、Conversation +21.52%；更小 1000B packet 窗 BurstGPT +25.45%、Mooncake +20.11%。这些百分比的**原始 matched ledger/队列/完整请求级 CSV 目前未全部在保留工件中统一核对**，只能作 `H` 级历史线索，不用来支持 S64 完整 serving 主张。可核对的 S64 BurstGPT 64-request FlowSim 弱干扰窗仅约 1.58ms overlap/0.84s，EP_FIRST 的 KV P99 1×/4× 仅 +1.12%/+1.72%；过去 prose-only `+24.7%` 没有原始复核工件，不能继续引用。某些 S64 1/2-request native integrated 尝试 180–300s 超时；既无 64-request integrated packet TTFT，也无 1万-request/day 成功记录。HTSim S16 endpoint-consistent topology 可构建，但多请求 interactive HTSim 未产生可完成的 serving CSV；network-only replay 的流数/完成时长不能替代 integrated 结果。见 [characterization](CHARACTERIZATION_REPORT.md)、[packet gate](P2_PACKET_REPLAY_GATE.md)、[网络研究门禁](PD_NETWORK_RESEARCH_GATES.md)。

另外一个 1P2D/100G EP2 **已完成** 的 16-request integrated FlowSim load test：low-load baseline TTFT/TPOT/TBT P99=95.354/4.771/4.827ms；20ms burst FULL FAIR=1191.303/20.420/25.145ms，EP_FIRST=1197.537/20.336/25.145，KV_FIRST=1191.844/20.422/25.145，joint SLO 0/16。它说明高 load 会极大恶化 serving，但三种 policy 差异极小，**主要不能归因于 KV–EP 数据面竞争**：global KV/EP overlap 仅约 0.0057–0.0099。早期 10/25G integrated 也有大绝对 TTFT，但非 100/200G 主配置，且负载/排队因素显著，应列负对照而不是网络动机。见 [FlowSim integrated validation](FLOWSIM_INTEGRATED_VALIDATION.md)。

## 六、失效/未完成结果的“禁用清单”

| 历史数字/说法 | 为什么不能再作为最终结论 | 可保留的含义 |
|---|---|---|
| S16 `+23.44%` FULL-vs-KV_ONLY KV slowdown、由旧 FlowSim 推出的 S64/S256 tail | leaf–spine parallel links 被 `edges[(src,dst)]` 覆写；正确 16×200G 后重放为 0% | 发现过容量建模 bug，不能支持 crossover |
| 旧 S16 packet fan-in KV P99 +96.5%、EP P99 +54.3% | packet route 只暴露一个 parallel interface；纠正后 request KV +0.39%、EP +29.1% | 使用本报告修正后表格 |
| 旧 1P(TP1)+2D(TP2) 50/100/200G 小拓扑收益 | rank4 与 switch ID4 冲突，rank world/endpoint 不一致 | 探索性诊断；以 endpoint-consistent S16 packet 作速率边界 |
| 旧 `CC_MODE=12` 被称 DCQCN | backend 不对应已验证的 DCQCN；正确模式 `CC_MODE=1` | ECN marks 如已完成仍可报；不报 DCQCN rate/alpha |
| 旧 P/D handoff “P2D 未结束但同 request EP 已启动” | 早期 admission/barrier bug，修正前 CSV 已废弃 | 需以 `all shards done→Decode admit→EP` 作为 correctness gate |
| 远程 KV legacy sibling waiter、split-source 纯 V2 | B1 correction 后 prefix 依赖与 P2D bytes 变了；纯 V2 让 suffix Prefill 缺 prefix | 只引用 corrected B1、合法 V1 与其负结果 |
| `EP_FIRST` 必然损 KV/TTFT ≥20% | 已完成 EP64 integrated 只见 +0.38–0.40% TTFT，且旧 +23.44% 失效 | 不能把 FULL-vs-KV_ONLY 和 priority 增量混淆 |
| `HETEROGENEOUS_512_POLICY_SUMMARY` 全 KV mean | 分母口径错误，约为按 256 P2D 计算值的一半；quantile 口径也略异 | 本文用 `PD_KV_EP_RESEARCH_SUMMARY` 与加权校验 |
| 50G/S64 integrated packet TTFT、TPOT、TBT、SLO | 超时或无完整 serving CSV | network-only 已完成的 CCT/FCT/queue/ECN 可以报 |

## 七、从所有尝试中能归纳的规律与汇报建议

1. **被放大的是 barrier-sensitive EP，不必然是 request KV/TTFT。** KV 分层非阻塞释放，上一层传输未完可继续计算下一层，Decode 在全部 KV 完成后 admission；少数 flow 的尾部或 CC 速率下降并不等于 `max-shard` barrier 一定改变。相反 MoE round 的最后 peer 对 CCT/TBT 更敏感。原始 ns-3、corrected packet、EP64 integrated 三个层级均支持“EP 更敏感”，但具体倍数不同。
2. **负载不足和拥塞模型错误必须区分。** EP_ONLY/FULL 对照有时弱是因为 timing/共享 cut/feedback 没激活；另一些曾经很强只是 parallel-link 容量 bug。正确 S16 的单 endpoint 200G 与 3.2Tbps bundle 同时成立。
3. **改变 request composition 可产生网络压力，但已验证的 serving headroom 比 network headroom 小。** 512-request FlowSim 的 KV 混合长度和目的地集中度极大改变 EP/KV 均值与 P99，然而尚无相同 512-request integrated/packet TTFT/TBT 验证。不能对领导说“512 请求 TTFT 优化 99%”。
4. **严格 EP priority 在当前实现下接近有效静态选择；这恰恰是否定动态 arbitration 故事的重要结果。** `KV_FIRST` 会恶化 EP/TBT，但 `EP_FIRST` 的 KV-side 额外代价很小；没有被证明的双边 crossover 不应包装成算法需求。若继续研究应先有新的 packet/endpoint 机制或真实 producer stall 证据。
5. **remote prefix provider 的 packet-level headroom 不等于系统收益。** 真实 Mooncake 热块和源端 egress 竞争已存在；但要把“复制”纳入成本、保持 prefix Prefill 依赖、追踪完整 handoff critical path。修正后 placement 和 split-source 均未 PASS。
6. **50G 是合理边界，不是自动的论文动机。** 完成的 S16 packet replay 显示 EP P99 对带宽非常敏感，ECN 随 exposure/阈值增加；但 50G 是独立 endpoint 速率，不是 GPU:200G-NIC>1 的共享网卡实现，且无 integrated serving 结果。真正 4GPU/1NIC 需显式 NIC-sharing 资源和实测参数。

对领导汇报宜用三张主表：①本报告“三、方向索引”说明做过什么；②“四、C/D/F/J/N”展示网络与 serving 并列的代表数字；③“六、禁用清单”解释为什么没有把大百分比全部写成论文收益。**当前严谨结论是已经找到多个可信网络机制，但尚未完成一个同时具有新颖 packet mechanism、真实 request/barrier 影响、稳定 ≥20% integrated serving headroom 的最终 CCF-A/B 论文动机。** 下一阶段若继续投入，先选一个机制配套可完成的 integrated serving/实机小窗验证，而不是扩大无端到端证据的 network-only sweep。
