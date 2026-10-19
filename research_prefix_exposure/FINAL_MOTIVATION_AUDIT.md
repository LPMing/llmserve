# Prefix Cache Hit 引起的网络关键路径迁移：最终动机审计

日期：2026-10-14（实验环境本地时区）  
仓库：`/home/dell/lpm/LLMServingSim`  
研究状态：`MECHANISM_PASS / IDEAL_HEADROOM_BOUND_PASS / DEPLOYABLE_15_PERCENT_GAIN_NOT_PROVEN`

## 结论摘要

在固定 Qwen3-30B-A3B、TP2、RTX PRO 6000 profile、200-Gbps NIC、4P1D、Decode 两条 200-Gbps receiver rail 的受控实验里，4096-token 本地 NPU prefix hit 确实把 Prefill 工作压缩到只需计算 9 个新 token，但当前 P/D 实现仍把完整 4105-token KV 发给 Decode。补充的 Decode-side lookup telemetry 还确认：同一个4096-token prefix已在 Decode local cache 命中，但查询发生在完整 P2D handoff之后；本场景中每个命中请求约99.78%的 P2D payload因而是重复搬运。

结果显示了关键路径迁移：1、2 个同时命中请求时，P2D 最后一个 flow 分别比请求达到 Decode-ready 早 0.589 ms、0.421 ms；4 个同时命中请求时，P2D 最后一个 flow 与 Decode-ready/首 token 同时完成，且比低并发时的计算完成基线晚 5.471 ms。4-request FAIR 的 integrated FlowSim TTFT 为 32.539 ms；保持同一 Prefill 工作、假设完全消除暴露在关键路径上的网络等待，得到 27.068 ms 的乐观下界，即最多约 **16.82%** 的该点 TTFT 空间。这个上界略过 15%，但它不是一个已实现的调度收益。

已经测试的控制没有证明总体 serving 能净优化 15%：FlowSim 的离线 `KV_REQUEST_FIRST` 使一个请求达到 27.068 ms，却把另外三个推迟到 36.445 ms，四请求平均 TTFT 从 32.539 ms 恶化到 34.101 ms（+4.80%）；ns-3 的离线 request pacing 降低了单 flow/FCT 和扣除 pacing 偏移后的网络服务时间，但把真实请求到全部网络-ready 的队列总等待拉长。因此本轮结论是：

- **Prefix hit → P2D barrier 暴露：成立。**
- **固定 FlowSim 点的理想 TTFT 上界超过 15%：成立，约 16.82%。**
- **存在已验证、可部署且对请求集合净收益超过 15% 的网络控制：未证明。**
- **是否形成新调度论文动机：NO-GO。** 不能把理想下界、单请求胜出或 packet-only ready 冒充成 serving-level 方法收益。
- **是否值得做下一个机制验证：CONDITIONAL GO。** 目的端已有prefix却仍全量P2D，且相同Serving路径的理想上界略过15%；应先验证P2D重复prefix shard能否安全省略，而非实现新scheduler。

另一个重要边界：共享 CXL pool 的 hash hit 已经发生，但 FlowSim 对 Chakra memory-load 节点赋零模拟时延。CXL restore 的 integrated TTFT 因此 `NOT_PROVEN`，不得引用该次 TTFT 作为 CXL 性能数据。

## 1. 固定配置、工作负载与证据类型

### 固定配置

| 项目 | 实际配置 |
|---|---|
| 模型 | `Qwen/Qwen3-30B-A3B-Instruct-2507`，48 layers，KV heads=4，head_dim=128，BF16 |
| TP / 活跃 GPU ranks | TP2；每个逻辑 serving instance 使用两个 RTXPRO6000 ranks |
| Prefix | 4096 个相同 token IDs；block size=16；warm-up request 后在同一 session 发起后续 request |
| 后续 request | input=4105 tokens：4096-token prefix + warm-up 输出的 1 token + 8 个新 token；output=3 |
| 网络 | 固定 200-Gbps 物理链路；4 Prefill instances → 1 Decode instance；Decode 数据 ranks 映射到两个 receiver NIC rails |
| 物理 NIC 共享 | rank-to-NIC fixture 为每 server 8 GPU、2×200G NIC、每 NIC 由 4 GPU 共享；本组模型计算只启用 TP2 ranks，映射到两条 rails。不是八条独立 GPU 链路 |
| P2D | `LAYERWISE`；Gate/EP traffic 在本 workload 中不产生，测量的是 Prefix-hit 的 P2D 网络路径 |
| Serving | integrated FlowSim；完整 KV handoff 后才 Decode admission；首 token、second-token、TPOT/ITL 从真实 scheduler event/CSV 读出 |
| Packet | native ns-3 fixed-event replay，4096-byte packet，`CC_MODE=1`（DCQCN），同一 rank-to-NIC map；packet replay 不向 Serving scheduler 回调 |

4-session 受控 fixture 是合法模型 token-ID/hash/session 依赖测试，不是生产 trace，也不能用于声称该同步模式在生产中的频率。每个 session 先完成 4096-token warm-up（output=1），再以 `tool_duration_ns=0` 释放子请求；4-target workload 中四个 target 同时于 150.107 ms 到达。这里的同步是机制验证的 workload 定义，不是自然到达分布的证据。

### 配对组

- `MISS`: 相同 session/token IDs，但运行日志实际显示 Prefill NPU/lower-tier hit 均为 0。
- `LOCAL_NPU_HIT`: 开启现有 Prefix cache；日志逐请求记录 NPU hit=4096、lower-tier hit=0。
- `SHARED_CXL_HIT`: 显式指定 Prefill 的 CXL pool placement；日志实际记录 NPU hit=0、lower-tier hit=4096。此组只验证 cache semantics/生成的 memory load，不验证 CXL 延迟。
- `DECODE_LOCAL_PREFIX`: 用新增的 Decode-side lookup telemetry 重跑 1-target correctness case 后，确证 warm-up 后 Decode cache 实际命中4096 tokens；但 lookup 时间是177.175 ms，发生在完整 P2D 完成/`P2D_READY`时。因此它能复用目标 request 的 Decode block allocation，却不能据此声称 P2D 已经绕过 Decode 已缓存的 prefix。本组没有可执行的“先查询 Decode cache、再抑制 P2D prefix shards”路径。

Cache keys 来自 workload 提供的真实 token-ID 序列，经现有 block-hash chain 生成；不是直接伪造 hash 作为 token ID。Router 会保留 `session_id` 与 `sub_request_index`，但 LOAD/RR 本身不提供 session-affinity 保证。本实验以 event ledger 中的实际 instance 和实际 cache-hit tokens 判定命中，不以 CLI 开关推断命中。当前 LOAD fixture 中各 warm-up/child 实际落在同一 Prefill instance，因而发生本地命中。

## 2. 缓存和 P2D 语义审计

### Serving DAG

MISS：

```text
Request arrival
  → Prefix lookup (miss)
  → Prefill computes all 4105 prompt tokens, layer by layer
  → each layer releases its model-derived P2D KV shard
  → all required P2D shards complete
  → Decode admission
  → first output token
```

LOCAL NPU HIT：

```text
Request arrival
  → NPU Prefix lookup (4096 tokens hit; simulated lookup cost = 0 ns)
  → Prefill computes 9 new tokens with cached 4096-token context
  → each layer still releases full request KV to Decode
  → all required P2D shards complete
  → Decode admission
  → first output token
```

已有 NPU pool 在 warm-up request 完成后保留可索引 block；命中是由 request 的累计 block hashes 与 Prefix index 匹配得出的。缓存 lookup 的 CPU/hash 处理成本没有被单独计时，日志字段明确为 `lookup_simulated_duration_ns=0`。本地 NPU hit 无 restore/memory movement；CXL hit 则会生成 CXL `MEM_LOAD`，但 FlowSim 忽略其 duration，见第 6 节。

### 审计发现并修复的 P2D 字节错误

在本轮 Prefix-hit 正式测量前，检查发现 Prefill `_build_batch()` 原来只按 `num_new` 计 P2D bytes，漏掉已经命中、但 Decode 尚未拥有的 cached-prefix KV。该逻辑会把 4096-token prefix 当作“已算过所以不需发送”，即使 prefix 实际只在 Prefill cache。

已修复 `serving/core/scheduler.py::_build_batch()`：首次调度命中后首个 Prefill chunk 时，将 `prefix_cache_hit` 加入 P2D 发送 token 数一次；后续 chunk 不重复加。新增 `research_prefix_exposure/test_p2d_cache_hit_bytes.py`，测试 miss、4096-hit+9-new、后续 chunk 不重发，并断言 TP2 model-derived byte conservation。测试输出：

```text
PASS: cache-hit P2D token/byte accounting is conserved
```

这项修正对结果解释至关重要：以下全部 cache-hit FlowSim 和 packet inputs 都按修复后的完整 KV 字节运行。否则会错误地得到一个更小、并非当前 P/D handoff 语义的网络 workload。

### Model-derived KV bytes

每 token、所有层、TP ranks 合计：

```text
2 (K,V) × 48 layers × 4 KV heads × 128 head_dim × 2 B(BF16)
= 98,304 B / token
```

因此后续 request：

```text
B_total = 4105 × 98,304 = 403,537,920 B/request
B_prefix = 4096 × 98,304 = 402,653,184 B/request
B_new(9) = 9 × 98,304 = 884,736 B/request
TP2 per-rank/rail bytes = 201,768,960 B/request
```

约 99.78% 的该请求 KV bytes 是已命中的 4096-token prefix。虽然 Prefill 不再重算这些 tokens，当前实现仍将它们从 Prefill P2D 到 Decode。每个命中请求由 48 layer × 2 TP ranks = 96 个 P2D shard flows 组成；miss 使用三个 Prefill chunks，日志中为 288 个 flow records，但总字节仍严格相同。FlowSim request barrier 取所有 required shard 的最后完成时间，不把 shard FCT 相加。

## 3. Integrated FlowSim：缓存命中是否迁移关键路径

所有时间为模拟时间；TTFT/TPOT/TBT 是 serving scheduler 输出，不是宿主机运行墙钟时间。每个单元的 target 请求具有相同值，因此表中报告逐请求值/范围，不把 1–4 样本伪称为生产 P99。

### Miss 与命中配对结果

| Cache-hit targets | 实际命中 / 新计算 | 每请求 P2D bytes / flow 数 | GPU compute finish（TP ranks max） | 最后 P2D shard 完成 | P2D-ready = Decode admit | TTFT | TPOT / token ITL |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | NPU 4096 / 9 | 403,537,920 B / 96 | 177.175 ms | 176.586341 ms | 177.175 ms | 27.068 ms | 4.698 ms / `[4.698, 4.698]` ms |
| 2 | 每请求 NPU 4096 / 9 | 每请求 403,537,920 B / 96 | 177.175 ms | 每请求 176.754482 ms | 177.175 ms | 每请求 27.068 ms | 每请求 9.256 ms / `[9.256, 9.256]` ms |
| 4 | 每请求 NPU 4096 / 9 | 每请求 403,537,920 B / 96 | 每请求 177.175 ms | 每请求 182.646480 ms | 182.646480 ms | 每请求 32.539480 ms | 每请求 14.395 ms / `[14.395, 14.395]` ms |
| Miss，1/2/4 targets | NPU 0 / lower tier 0；计算完整 4105 | 每请求 403,537,920 B / 288 | Prefill graph complete 312.887 ms | 每请求 312.131675 ms | 312.887 ms | 每请求 162.780 ms | 1/2/4 targets 分别为 4.698/9.256/14.395 ms |

逐请求 CSV 还记录了请求完成：1-hit absolute `end_time=186.571 ms`（arrival→complete36.464ms）；2-hit `195.687 ms`（45.580ms）；4-hit `211.436480 ms`（61.329480ms）。对应 first token / Decode admission 分别为177.175、177.175、182.646480ms；second-token 分别为181.873、186.431、197.041480ms。Miss 的1-target完成于322.283ms（arrival→complete172.176ms），4-target完成于341.677ms（191.570ms）。全部 target output=3，完整 TBT/ITL sequence 在 CSV `ITL` 列保留。

这里 TPOT/TBT 随 Decode batch population 增大而增加，主要反映对应 RTXPRO6000 batch profile 的 Decode 计算时间；本 workload 没有 EP collective。不能把它解释为 EP 网络损伤，也没有定义/套用 SLO threshold。

补充的 per-compute-node debug run 为 four-hit workload 逐个 rank 记录 `COMP_NODE` 完成时间。4个 Prefill 图均从150.107ms开始：每对 TP ranks 中 rank0/4/8/12 的最后 `COMP_NODE_sampler_483` 在177.175ms完成，rank1/5/9/13 在176.702ms完成；因此 request 的 GPU compute critical completion 为 `c=27.068ms`。这是 per-node timestamp直接观测，不是用历史 EP64 TPOT替代计算时间。

四个 hit target 的完整事件链为：Prefill queue wait=0；NPU lookup发生在150.107ms且模拟cost=0；本地restore=0；GPU首次compute node在150.107ms开始；TP rank max compute finish=177.175ms；首个KV shard于150.125ms release，最后KV shard于176.398ms release；最后KV shard finish在1/2/4 targets下分别为176.586341/176.754482/182.646480ms；Decode admission、first token分别为177.175/177.175/182.646480ms；second token分别为181.873/186.431/197.041480ms；请求absolute completion分别为186.571/195.687/211.436480ms。Decode capacity queue wait均为0。4-target路径中，GPU计算先于KV完成5.471480ms；request等待P2D barrier后才能first-token。

### 逐事件关键路径

四个命中目标在 150.107 ms 到达 Prefill 并立刻开始；Cache lookup 记录为 0 ns。Layerwise P2D 的首个 shard 在 150.125 ms release，最后一个 shard 在 176.398 ms release，release span 是 26.273 ms。最后 KV flow 的等待及其后的层计算共同决定具体请求是否 ready：

| 同时命中数 | 最后层 release | 最后 shard 完成 | Decode-ready/首 token | 解释 |
|---:|---:|---:|---:|---|
| 1 | 176.398 ms | 176.586341 ms | 177.175 ms | 网络比 serving ready 早 0.588659 ms；关键路径仍是命中后 Prefill/剩余模型工作，网络 slack 约 0.589 ms |
| 2 | 176.398 ms | 176.754482 ms | 177.175 ms | 网络比 ready 早 0.420518 ms；仍是计算侧先决定 ready |
| 4 | 176.398 ms | 182.646480 ms | 182.646480 ms | network handoff barrier 成为 critical；last-release 到 last-shard completion 为 6.248480 ms |

同一 4-request cohort 的每个 Prefill instance 都只承担一个目标，Prefill compute 请求形状相同；从 1/2-hit 的实际完成时间读取到的非网络暴露路径 `c=27.068 ms`。在 4-hit FAIR 下，TTFT 比该 measured compute floor 多 `32.539480−27.068=5.471480 ms`。相对于实际 4-hit TTFT，消除这部分暴露网络等待的理想上界为：

```text
1 − 27.068 / 32.539480 = 16.82%
```

这是相同 FlowSim Serving DAG/compute 下的乐观可移除上界，不是已实现策略收益；它也不是把 `network-only FCT` 直接等同 TTFT。网络层的 last-shard barrier 与 integrated scheduler 的 Decode admission/首 token 时间在此 FlowSim run 中有明确 event 对应。

Miss 对照中，Prefill 完整 4105-token 路径的 TTFT 是 162.780 ms，P2D last flow 为 312.131675 ms，目标 Prefill request 从 150.107 ms 到首 token 312.887 ms，最后 KV shard 早约 0.755325 ms。Prefix hit 将 TTFT 降至 27.068 ms（1/2 hit）或 32.539 ms（4 hit）；这是常规 Prefix-cache compute saving。相较 miss，四请求 cache-hit TTFT 降低约 80.01%，但不能把这项缓存收益归因于本轮网络调度。

### 关键路径迁移判定

判定为 **PASS（controlled workload）**：cache hit 后 compute 大幅缩短，layerwise KV 仍然有完整字节与持续 release；当四个独立 Prefill sender 同时向一个双 rail Decode receiver incast 时，KV request-level last-shard barrier 越过 Prefill compute floor，直接推迟首 token。它不是“平均 flow latency 变差”的替代说法，而是 `P2D last required flow → Decode admission → TTFT` 的时间闭环。

限制：该正例依赖 4 个 session target 在同一时刻进入固定 4P1D receiver。它证明合法机制和所给 operating point，不证明自然生产流量中常见，也不证明其他模型、网络或 cache placement 中常见。

## 4. Strong-baseline 和可实现收益审计

| Baseline / control | 本轮结果 | 对 15% claim 的含义 |
|---|---|---|
| MISS vs LOCAL NPU HIT | 完整相同 target、prefix hit 实测。MISS 162.780 ms；hit 1/2=27.068 ms，hit4=32.539 ms | 证明 caching 自身收益大；不是新网络方法收益 |
| FlowSim FAIR | 1/2 target 尚有 0.42–0.59 ms compute slack；4 targets network barrier 暴露5.471 ms | 给出16.82% ideal upper-bound，mechanism pass |
| FlowSim `KV_REQUEST_FIRST` | 四目标只把请求1置于优先；请求1 TTFT27.068ms，其他各36.445387ms；平均34.101040ms vs FAIR32.539480ms（+4.80%），最差样本也更差 | 单请求可胜过15%，但代价转嫁给同 cohort，整体不优；是离线表征，不是可部署/公平实现 |
| ns-3 same-priority simultaneous replay | 1/2/4 request matched KV flows，DCQCN enabled；验证物理队列与 packet barrier，不连接 scheduler | 只报告 network result，不把 packet-ready 称 TTFT |
| ns-3 offline request pacing | 2/4 target 用8.070759ms间隔错开完整 request flow bundle；每请求内部 layerwise offset/bytes不变 | 单 flow FCT 大幅降低；但包括 pacing wait 后共同到达→ready 的均值和 cohort makespan变长，未证明 serving收益 |
| RR / LOAD / prefix affinity | Runtime 默认 LOAD；四个 fixture 中实际 target 保持在各自 Prefill warm-up 所在实例，因而本地 hit。Router 保存 session provenance，但 LOAD/RR 无 sticky-session guarantee；RR 情况由 CXL 语义试验观察到 child 被路由到另一 Prefill 后通过共享 CXL pool 命中 | LOAD 已足够使这组人为一对一 warm-up/child 获得 locality；未独立实现 prefix-affinity router，不能宣称超越 locality baseline |
| Decode-local prefix | 单target重跑实际记录 Decode `npu_hit_tokens=4096`；但 lookup发生在完整P2D完成时。每target仍发送403,537,920B | **确认存在重复P2D payload**，可形成新的测试假设：在注入前复用目的端block是否可安全省略prefix shards。当前没有该协议，收益尚未实测 |
| Network-aware Decode placement | 只有一个 Decode instance，没可选 destination | 不适用；不能评估 placement 增益 |
| Local Prefill at Decode | 需要重分配 4P1D GPU/TP 配置，改变本任务固定资源/拓扑 | 未作为公平 matched baseline 执行 |
| Progressive Push | 采用已有独立 matched 实验作为旁证：200G、相同小型 integrated workload 下 Whole→Progressive 的 TTFT P99 1954.557→1835.835 ms（6.07%），TBT P99不变；不是本 cache-hit trace 的直接对照 | 在相关200G证据中未达15%；不能替代本轮 matched baseline |
| Offline zero-exposed-network oracle | 用同 workload 的实际 compute floor 27.068ms 对照4-hit FAIR 32.539480ms | 上界16.82%；oracle不可部署，未证明有限优先级/在线控制可达到 |

## 5. Native ns-3 Packet-level 交叉验证

包级 events 是由同一 4-target FlowSim event ledger 导出的 96 flows/request，共享相同 src/dst、model-derived bytes、layer release time 和两条 Decode receiver rails。每次 1/2/4 请求分别为 96/192/384 个 flows；各 request 仍是 403,537,920 B。`FAIR` 在本表中指同步同优先级 FULL packet replay baseline；它不是 ns-3 内置的 per-request max-min scheduler。Packet replay 使用`CC_MODE=1`，且没有 network completion → Serving scheduler callback。

| ns-3 replay | flow FCT mean / P99 (ms) | 请求 packet-ready elapsed（相对首个 release） | 最后 release→ready | receiver queue / ECN / CC | 宿主墙钟运行 |
|---|---:|---:|---:|---|---:|
| 同步 FAIR-like，1 hit | 0.212 / 0.294 | 26.484 ms | 0.211 ms | 无 bottleneck queue/ECN/CNP | 20.4 s |
| 同步 FAIR-like，2 hits | 1.534 / 2.177 | 27.635 ms mean；makespan27.642 | 1.356–1.369 ms | 两条 receiver rails peak queue2.36/3.04 MB；ECN 3,633/3,941 observations；192/192 QPs有 CNP/rate change；无 PFC/drop | 44.3 s |
| 同步 FAIR-like，4 hits | 14.536 / 29.194 | 34.426 ms mean；makespan34.651 | 7.947–8.378 ms | rails113/123 peak queue8.52/8.05 MB；ECN89,387/86,358 observations；384/384 QPs有 CNP/rate change；无 PFC/drop | 109.8 s |
| Offline paced，2 hits | 0.213 / 0.295 | 两个共同到达→ready：26.484/34.554 ms；mean30.519，makespan34.554 | 各0.211 ms；第二请求前置等8.071ms | peak queue0.269 MB；无 ECN/CNP/PFC/drop | 38.7 s |
| Offline paced，4 hits | 1.319 / 6.058 | mean39.898 ms；makespan50.696 | 0.211–4.073 ms | rails peak queue约3.61/3.59 MB；仍有ECN7,213/7,005 observations，CNP14,218；无PFC/drop | 83.6 s |

ns-3 确认了 receiver ingress 上存在真实 packet serialization/queueing、ECN/CNP/DCQCN 响应和 last-shard tail 增大；它是独立 packet-level 机制证据。它没有集成 serving completion callback，所以上表所有 ready 都不是 TTFT。把 4-request packet-only barrier直接与 FlowSim TTFT相加会重复/错算 layerwise compute-network overlap，本报告不这样做。

Pacing 的关键反例：4-request pacing 的事件 FCT mean 比同步 baseline 低约90.9%，扣除人为释放 offset 后的 request network-duration mean 从34.426降到27.791 ms（约19.3%）；但是共同到达→ready均值从34.426升到39.898 ms（+15.9%），makespan从34.651升到50.696 ms（+46.3%）。两请求亦是共同 ready mean27.635→30.519 ms、makespan27.642→34.554 ms。即：更好的网络服务时间不等于更好的 serving latency；释放 pacing 的等待必须计入请求关键路径。

## 6. Lower-tier CXL 与 Decode-local cache 语义

共享 CXL case 使用同样 4096-token 前缀和模型派生 KV；target 从 Prefill instance1 接受 cache lookup，event ledger 为 `npu_hit_tokens=0, lower_tier_hit_tokens=4096`。Trace 确实产生 `kv_load_0`，memory-location字段为`CXL:0`，size=402,653,184 B；配置采用仓库 CXL memory pool 的 60 GB/s 与250 ns参数。若只做带宽除法，读完整 prefix 的理想序列化量约6.711 ms，但这不是本次 FlowSim measured latency。

直接代码审查 `serving/core/flowsim_worker.py::AsyncGraphExecutor.simulate()`：非 SEND/RECV/COLLECTIVE Chakra node 按 `node.duration_micros` 推进；生成的 `MEM_LOAD_NODE` 的 duration 为0，FlowSim没有调用 CXL/CPU memory model。因此 CXL case 的27.068 ms TTFT与本地 NPU hit相同是模型缺失的后果，不能解释为 CXL restore免费或 CXL与NPU性能相同。**CXL restore → compute → TTFT：NOT_PROVEN。** 本轮未为补正结果而改后端或重跑大规模实验。

Decode warm-up 后确实存在同样的4096-token local prefix。本轮加入显式 `DECODE_PREFIX_CACHE_LOOKUP` ledger 并重跑单 target：request1 在 Decode instance4 观察到 `npu_hit_tokens=4096, lower_tier_hit_tokens=0`。然而该 lookup timestamp是177.175ms，即P2D最后flow于176.586341ms完成之后、`P2D_READY`当时。P2D flow ledger仍有403,537,920B，其中402,653,184B是已命中的prefix。因此Decode cache hit真实性已确认，但它只在handoff之后用于本地allocation/cache reuse，**不节省已经发生的P2D网络流量**。这是结构性重复搬运观察，而不是已实现机制的结果；目的端复用要求在P2D注入前验证模型/TP layout/hash一致、block未被驱逐，并正确处理竞争请求、miss race和并发写入。

## 7. 用户提供的15%理论阈值复核

按题目给定参考数复算：

```text
0.85 × 135.319248 ms − 33.263584 ms = 81.757777 ms ≈ 81.758 ms
12.029993 ms / (c + 32.481310 ms) > 0.15
  ⇔ c < 47.718643 ms ≈ 47.719 ms
```

本轮本地 NPU hit 的实测 non-network-exposed path `c=27.068 ms`，低于两个代数筛选阈值。由此可以说：**给定假设模型没有因计算阶段太长而排除15%机会。**但用户提供的 reference compute/network数不是本轮同一运行的实测结果；不能仅因 `c` 通过这两个阈值就宣布真实Serving PASS。

本轮同一 workload 真正能支持的 Serving 量化是：4-hit FAIR TTFT 32.539 ms，匹配 compute floor 27.068 ms，最多可移除约5.471 ms，即16.82%。这是大于15%的窄上界，余量仅1.82个百分点。ns-3 pacing具有更强 network-only流指标，却因请求释放等待而没有证明同等端到端收益。故严格结论是“**理论/FlowSim oracle 空间略超15%，可部署净收益未达到证明门槛**”，而不是“已优化15%”。

## 8. 已有工作/新颖性边界

本报告只验证动机，不做完整系统论文 novelty claim。以下点本身不能作为创新：Prefix caching 降 Prefill compute；按请求 affinity 路由到缓存所在 Prefill；根据 network load选择请求/目的地；layerwise KV release；在固定事件 replay 中用 pacing降低 queue/FCT；理想 oracle消除 critical path网络延迟。

在本轮证据范围内，有区别于简单 prefix-cache miss的系统事实是：**Prefix hit与PD handoff组合后，Decode不一定持有 Prefill 命中的blocks，而当前sender仍会把完整prefix KV发给Decode；cache hit因此可能把瓶颈从可省的 Prefill compute移到仍需交接的最后KV shard。**不过“目的端已缓存时抑制重复P2D”是否已有系统实现、该机制是否具有新的协议/一致性/并发价值，尚未完成相关工作审计；不能宣称无人研究，也不能以此文件宣称论文创新。

## 9. 复现信息与证据目录

### 代码/输入 provenance

| Artifact | SHA-256 / provenance |
|---|---|
| Git HEAD | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| Tracked diff snapshot `git diff --binary HEAD` | `2029f85bef8227d6b4a863444b62d4e8fc6651e2f6e803a4cfff41c8f014c2dd`。仅覆盖相对 HEAD 的已跟踪文件差异；不包含 untracked 文件，也不是本研究独占 patch。仓库还存在与本研究无关的 dirty/untracked 内容 |
| Qwen config `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json` | `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3` |
| RTXPRO6000 BF16 TP2 attention profile | `0b0fb7a5436cb4bffba5e89397cf747064b1566e0053db4584c70d766d243b10` |
| RTXPRO6000 BF16 TP2 dense profile | `710f04261d67ec53639095cec91751c9a9dc1aa6f5b335c9decaee4802407633` |
| RTXPRO6000 BF16 TP2 per-sequence profile | `ed094edb86909d5ceaf9c9a0c14c1711508ffb6211f92196a0536dc6c65de097` |
| FlowSim main config | `research_prefix_exposure/4p1d_tp2_flowsim.json`, SHA `a75d43f50e1fff8365529e5f25130ca7b4ec2cd78df6a1bf10dabbb8e5f0a7fd` |
| 4-target workload | SHA `2261e7521b1844aa3186a1a78dcdac7407dab402ba4b9ebfa15be601f613faec` |
| 4-target FlowSim flow ledger | SHA `b7d737f0dc91685fcf5f78ff9c620c5e9a58b0bcad658d9779b1cc6dbf001050` |
| ns-3 physical topology | SHA `4254141f11f0ea8d03a27f7b1fecbd04e0697327eed61ccb7ec5de3fd2ce2df7` |
| ns-3 replay binary | SHA `79f8f6e6dd2fbc6af061e1a11f08dd3431f58bb61a162f06d452beb2589eadea` |
| Python | `/home/lpm/.conda/envs/llmsim-flowsim/bin/python`, 3.10.21；Chakra shim `/tmp/llmsim-chakra-shim.TzDOXs`；`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` |

Because the worktree was already broadly dirty, this report binds its observations to explicit config/workload/profile/output hashes and the listed HEAD + tracked-diff snapshot. The tracked diff hash excludes untracked files; generated research artifacts are identified separately by path. The report does not claim the HEAD alone contains the experimental code state.

### 主要输入与输出

- Config/workload generators: `generate_fixture.py`, `generate_cxl_shared_case.py`
- Matched datasets: `workload_{1,2,4}_targets.jsonl`
- FlowSim request results: `results/{miss,hit}_{1,2,4}_requests.csv`
- FlowSim flow/scheduler ledgers: `results/{miss,hit}_{1,2,4}_flows.jsonl`, `*_scheduler.jsonl`
- Request-priority counterfactual: `results/request_first_4_{requests.csv,flows.jsonl,scheduler.jsonl}`
- Decode-side cache lookup correctness: `results/decode_cache_lookup_{requests.csv,flows.jsonl,scheduler.jsonl}`
- Per-rank GPU compute finish: `results/hit_4_compute_nodes_{requests.csv,flows.jsonl,scheduler.jsonl}` and `results/hit_4_compute_nodes.jsonl`
- CXL semantic/timing audit: `results/cxl_placed_{requests.csv,flows.jsonl,scheduler.jsonl}` and `astra-sim/inputs/runs/prefix-exposure-cxl-placed/trace/.../instance1_batch2.txt`
- Packet event generator: `export_packet_events.py`; matched inputs: `packet_inputs/{fair,paced}_{1,2,4}/events.csv`
- ns-3 network outputs: `packet_results/{fair,paced}_{1,2,4}/`; `network_run_manifest.json` stores command, topology, binary and config hashes. `paced_1` input equals `fair_1`; no separate paced_1 ns-3 run was needed.
- Byte-accounting regression: `test_p2d_cache_hit_bytes.py`

Representative reproduction commands (the preserved `network_run_manifest.json` is authoritative for each ns-3 replay command):

```bash
PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
research_prefix_exposure/test_p2d_cache_hit_bytes.py

/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
research_prefix_exposure/export_packet_events.py \
  --count 4 --mode fair --output research_prefix_exposure/packet_inputs/fair_4

/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
research_ns3_incast/run_packet_replay.py \
  --events research_prefix_exposure/packet_inputs/fair_4/events.csv \
  --topology research_ns3_incast/fixtures_rankcap200g/fixtures/4p1d_unique_spines/topology.txt \
  --rank-map research_ns3_incast/fixtures_rankcap200g/fixtures/4p1d_unique_spines/rank_to_nic.csv \
  --output research_prefix_exposure/packet_results/fair_4 \
  --cc-mode 1 --stop-guard-ns 120000000
```

Integrated run CSVs, scheduler ledgers, flow ledgers and CXL trace are preserved. The exact historic shell invocation used to launch each FlowSim run was not saved as a per-run manifest; use the preserved workload/config, CLI `python -m serving --help`, and run artifacts for reproduction. This is a provenance limitation and is not hidden.

## 10. Gate 决策

| Gate | 结果 | 依据 |
|---|---|---|
| Cache hit semantics | PASS | 每 request event ledger 真正记录 NPU 4096 hit / CXL lower-tier 4096 hit；Miss实际为0 |
| P2D bytes/hash semantics | PASS after fix | Prefix-hit也发送完整4105-token KV；bytes conservation regression PASS |
| Integrated key-path migration | PASS (controlled 4-target point) | 1/2 hit network早于ready；4 hit last P2D shard=Decode-ready=首token |
| >15% potential serving headroom | PASS only as a tight ideal bound | 同配置 compute floor oracle约16.82%；不代表方法收益 |
| >15% deployable/overall serving optimization | NOT PROVEN | Request-first损害cohort mean；pacing packet-only且计入release wait后更慢；ns-3未集成Serving |
| CXL hit serving timing | NOT PROVEN | FlowSim `MEM_LOAD_NODE`零duration |
| 新调度算法 GO | NO-GO | Request-first/pacing未带来>15% cohort serving净收益，不能据此设计scheduler |
| 目的端已缓存 Prefix 的 P2D 重复数据抑制机制验证 | CONDITIONAL GO | Decode端4096-token prefix已命中，但当前仍完整P2D 403.5MB；省略重复prefix shards是一个可测的后续机制假设，尚无实现或收益证据 |
| 论文/新颖性 GO | NOT YET | 受控同步正例、无可部署收益、未审计目的端cache reuse相关工作；当前不能形成论文claim |

**停止条件：**不继续改变带宽、prefix hit ratio、request长度、拓扑或同步方式追求更大数字。本轮停止 scheduler/论文动机的正向主张；仅对一个具体机制保留 `CONDITIONAL GO`：对 Decode 已确认命中的4096-token prefix，在 P2D 发起前省略命中 prefix shards、仅传9-token新后缀，并校验模型/TP layout/hash、block所有权与驱逐、miss race、并发写入；随后在固定资源与到达的 matched integrated run 测 TTFT。如果不能将TTFT从32.539ms逼近27.068ms compute floor，或新依赖/等待吞掉收益，则关闭该机会。它不是已实现 scheduler 或已证明收益；related-work审计仍是论文 claim 前的必需 gate。

## 11. 主要代码位置

- Prefix hit 的 waiting admission / lookup: `serving/core/scheduler.py::_schedule_waiting()`
- P2D token/byte 形成（本轮修复）: `serving/core/scheduler.py::_build_batch()`
- P2D 完成后 Decode allocation/handoff: `serving/core/scheduler.py::transfer_prefill_request()`
- session 子请求释放及 routing provenance: `serving/core/router.py::notify_request_completed()` / `load_requests()`
- FlowSim 对普通 Chakra node 的时长处理（CXL limitation）: `serving/core/flowsim_worker.py::AsyncGraphExecutor.simulate()`
- CXL memory analytical model（当前 FlowSim worker未调用）: `astra-sim/extern/memory_backend/analytical/AnalyticalMemory.cc::get_mem_runtime()`

