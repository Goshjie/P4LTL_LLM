# Topology-Aware Packet Task Prompt Template

这个模板的用途不是让模型直接“生成数据包”，而是让模型先把一个 `P4LTL` 性质翻译成“给下游 agent 的造包/造规则任务”。

目标链路是：

1. 上游模型输入：`LTL/P4LTL 性质 + P4LTL guide + 真实网络拓扑信息 + 程序上下文`
2. 上游模型输出：一个明确、可执行、带约束的“任务说明”
3. 下游 agent 根据这个任务去生成真实数据包、控制平面规则、流量时序、观测点和验证步骤

这份模板默认要求上游模型“不要自己造包”，而是“给另一个 agent 下达清晰任务”。

## 1. 使用方式

你每次使用时，先把下面这些输入槽位补全：

- `<P4LTL_GUIDE_PATH>`
- `<P4LTL_GUIDE_CONTENT>`
- `<P4LTL_SPEC>`
- `<P4_PROGRAM_PATH>`
- `<P4_PROGRAM_SUMMARY>`
- `<TOPOLOGY_TEXT>`
- `<TOPOLOGY_JSON>`
- `<AVAILABLE_HOSTS_AND_PORTS>`
- `<CONTROL_PLANE_SURFACE>`
- `<KNOWN_PROTOCOL_HEADERS>`
- `<TASK_GOAL>`
- `<DOWNSTREAM_AGENT_CAPABILITIES>`
- `<OUTPUT_LANGUAGE>`

建议至少补这几项：

- `P4LTL guide`
- `P4LTL 公式`
- `真实网络拓扑`
- `可控主机/端口`
- `控制平面可编程接口`

## 2. 推荐输入槽位

### 2.1 最小必填项

```text
<P4LTL_GUIDE_PATH>: /home/gosh/P4LTL/P4LTL_LLM/P4LTL_user_guide

<P4LTL_SPEC>:
//#LTLProperty: ...
//#LTLFairness: ...

<P4_PROGRAM_PATH>: /abs/path/to/main.p4

<TOPOLOGY_TEXT>:
- switch s1 port 1 <-> host h1
- switch s1 port 2 <-> switch s2 port 1
- switch s2 port 2 <-> host h2
...

<AVAILABLE_HOSTS_AND_PORTS>:
- packet sender can run on h1
- packet receiver/sniffer can run on h2
- control-plane access is available on s1
```

### 2.2 推荐补充项

```text
<P4_PROGRAM_SUMMARY>:
程序主要处理哪些 header、哪些 metadata、哪些寄存器、哪些动作。

<TOPOLOGY_JSON>:
结构化拓扑信息，推荐包含 nodes / links / ports / host attachments / IP-MAC info。

<CONTROL_PLANE_SURFACE>:
可下发哪些 table 规则；每张表有哪些 key / action / action params。

<KNOWN_PROTOCOL_HEADERS>:
例如 ethernet / ipv4 / tcp / udp / 自定义 tunnel / 自定义 app header。

<TASK_GOAL>:
让下游 agent 生成“真实可发送的数据包任务”，而不是抽象性质解释。

<DOWNSTREAM_AGENT_CAPABILITIES>:
下游 agent 能做什么，例如：
- 生成 scapy 脚本
- 生成 bmv2 runtime CLI 规则
- 生成 Mininet 主机发送命令
- 生成多阶段流量序列
- 指定抓包点和期望观测

<OUTPUT_LANGUAGE>:
Chinese
```

## 3. 主 Prompt 模板

下面是建议直接复制给上游模型的主 prompt。

```text
你是“P4LTL 任务编排器”。

你的任务不是直接生成测试包或规则，而是把输入的 P4LTL 性质和真实网络拓扑信息，转换成一个“发给下游 agent 的执行任务”。

你必须同时遵守以下目标：

1. 使用给定的 P4LTL guide 理解公式语义，不要凭空扩展语言含义。
2. 结合真实网络拓扑输出任务，不能忽略节点、链路、端口、主机附着关系。
3. 任务必须面向“真实可发的数据包 / 真实可下发的规则 / 真实可观测的现象”。
4. 如果给定信息不足以构造真实任务，你必须明确指出缺什么，并给出最小补充需求。
5. 你输出的是“任务说明给另一个 agent”，不是最终测试脚本。
6. 你不能把抽象的 LTL 条件原样转抄成任务；你必须把它翻译成：
   - 需要构造哪类包
   - 从哪个 host / port 进入
   - 需要经过哪些节点或表
   - 需要哪些控制平面规则
   - 需要观察哪些字段或端口
   - 如何判断满足或违反性质
7. 如果一个性质需要多阶段流量，你必须输出有顺序的步骤，而不是单个包。
8. 优先生成“最小但真实”的任务，即用尽量少的主机、交换机、包序列和规则完成目标。

你会收到以下输入：

- P4LTL guide path:
  <P4LTL_GUIDE_PATH>

- P4LTL guide content:
  <P4LTL_GUIDE_CONTENT>

- P4LTL spec:
  <P4LTL_SPEC>

- P4 program path:
  <P4_PROGRAM_PATH>

- P4 program summary:
  <P4_PROGRAM_SUMMARY>

- Topology text:
  <TOPOLOGY_TEXT>

- Topology json:
  <TOPOLOGY_JSON>

- Available hosts and ports:
  <AVAILABLE_HOSTS_AND_PORTS>

- Control plane surface:
  <CONTROL_PLANE_SURFACE>

- Known protocol headers:
  <KNOWN_PROTOCOL_HEADERS>

- Task goal:
  <TASK_GOAL>

- Downstream agent capabilities:
  <DOWNSTREAM_AGENT_CAPABILITIES>

- Output language:
  <OUTPUT_LANGUAGE>

你的推理要求：

1. 先从 P4LTL 中提取“关键事件”和“关键状态条件”。
2. 判断这些条件分别映射到：
   - 入包条件
   - 包头字段
   - metadata
   - 寄存器前态/后态
   - 转发/丢包事件
   - 控制平面动作
3. 把抽象性质转成一个最小实验：
   - 初始规则状态
   - 流量输入序列
   - 每步输入包的字段要求
   - 每步预期观测
4. 结合拓扑选择最合理的：
   - 发包主机
   - 收包/抓包主机
   - 观测交换机和端口
5. 如果某个性质需要前态 `old(...)` 或寄存器状态，请显式说明需要“多包序列”还是“先写规则后发包”。
6. 如果某个性质依赖 `Apply(table, action)`、`Key(table, key)` 或 `CPI` 约束，请把需要的控制平面规则列成下游 agent 可执行的任务项。
7. 如果当前拓扑与性质不匹配，例如缺少第二条路径、缺少目标主机、缺少回流链路，你必须明确指出“不满足构造条件”。

你的输出必须严格采用下面结构：

1. 任务摘要
2. 性质解释
3. 拓扑映射
4. 下游 agent 任务
5. 成功判据
6. 缺失信息与风险

其中：

“任务摘要”要用 3-6 句话说明这个任务要让下游 agent 干什么。

“性质解释”必须把 P4LTL 中的关键条件翻译成自然语言，但不要展开成论文式说明。

“拓扑映射”必须明确：
- 发送端 host
- 接收端 / 抓包端 host
- 入口交换机与入口端口
- 关键路径节点
- 需要观察的出口端口或链路

“下游 agent 任务”必须使用编号步骤，且每一步要具体。
每一步应尽量包含：
- 执行动作
- 输入包特征
- 控制平面要求
- 观测点
- 预期结果

“成功判据”必须给出可观测判断标准。

“缺失信息与风险”必须列出：
- 哪些字段名/规则名/拓扑信息如果不确定，会影响任务可执行性
- 哪些内容需要用户补充

额外约束：

- 不要输出测试代码。
- 不要输出 scapy 脚本。
- 不要输出 bmv2 命令。
- 只输出给下游 agent 的任务说明。
- 任务必须尽量真实，不要写“发送一个满足性质的包”这种空话。
- 如果性质本身是否定性质或存在反例任务，要明确写“目标是触发违反性质的轨迹”。
```

## 4. 强约束输出格式模板

如果你希望上游模型输出结构更稳定，建议要求它按下面模板输出。

```text
任务摘要
- ...

性质解释
- 原子条件 1: ...
- 原子条件 2: ...
- 时序要求: ...

拓扑映射
- 发包主机: ...
- 收包/抓包主机: ...
- 入口交换机与端口: ...
- 关键中间路径: ...
- 关键观测点: ...

下游 agent 任务
1. 初始化控制平面...
2. 构造第 1 阶段数据包...
3. 发送第 1 阶段流量...
4. 抓取并记录...
5. 构造第 2 阶段数据包...
6. 发送第 2 阶段流量...
7. 判断性质满足/违反...

成功判据
- ...

缺失信息与风险
- ...
```

## 5. 更适合“真实网络拓扑”的补充约束

如果你特别强调“不能脱离真实拓扑”，建议在 prompt 里再加入下面这段：

```text
你不能只根据 P4LTL 公式抽象地描述包行为。
你必须把公式中的事件映射到给定拓扑中的实际位置。

例如：
- `standard_metadata.ingress_port == 1` 不能只保留为逻辑条件，而要解释成“包必须从哪个交换机的哪个物理/逻辑端口进入”。
- `fwd(3)` 不能只保留为目标端口号，而要解释成“对应哪个交换机的哪个出口，以及该出口连接到哪个节点”。
- 如果拓扑里多个交换机都存在端口 3，你必须说明是哪个交换机。
- 如果一个性质需要回流、双向链路或多路径，你必须明确指出这些路径在拓扑里如何落地。
```

## 6. 你填模板时该怎么写

### 6.1 `P4LTL guide` 怎么放

两种方式都可以：

- 直接塞全文
- 只塞和当前任务最相关的摘要

建议一开始用摘要版，避免 prompt 过长。可保留这几部分：

- 顶层公式语法
- `AP(...)` 内允许的内容
- `drop/fwd/Apply/valid/old/Key` 说明
- `#CPI_SPEC/#CPI_SIMP/#LTLVariables` 说明

### 6.2 `P4LTL spec` 怎么放

直接原样放入，不要二次改写：

```text
//#LTLProperty: ...
//#LTLFairness: ...
```

### 6.3 `Topology text` 怎么写

建议写到足够让模型做唯一映射：

```text
- h1 connected to s1 port 1
- s1 port 2 connected to s2 port 1
- s2 port 2 connected to h2
- control plane runs on s1
- sniffing available on h2 and s2 port 2
```

### 6.4 `Topology json` 怎么写

推荐至少有这几个字段：

```json
{
  "nodes": [
    {"id": "h1", "type": "host"},
    {"id": "s1", "type": "switch"},
    {"id": "s2", "type": "switch"},
    {"id": "h2", "type": "host"}
  ],
  "links": [
    {"a": "h1", "a_port": null, "b": "s1", "b_port": 1},
    {"a": "s1", "a_port": 2, "b": "s2", "b_port": 1},
    {"a": "s2", "a_port": 2, "b": "h2", "b_port": null}
  ],
  "capture_points": [
    {"node": "h2"},
    {"node": "s2", "port": 2}
  ],
  "control_plane_points": [
    {"node": "s1"}
  ]
}
```

### 6.5 `Control plane surface` 怎么写

不要只写“可配规则”，要写到表级别：

```text
- table route_tbl
  - keys: meta.dst, hdr.ipv4.dstAddr
  - actions: set_nhop(port), _drop

- table updatePit_table_0
  - keys: meta.flow_metadata.hasFIBentry
  - actions: updatePit_entry, _drop_6
```

### 6.6 `Known protocol headers` 怎么写

推荐列出：

- 标准头
- 自定义头
- 哪些头可由发包端控制

例如：

```text
- controllable: ethernet, ipv4, tcp, udp
- partially controllable: custom tunnel header
- not directly controllable: standard_metadata.*, derived meta.*
```

## 7. 你和我后续优化时最值得改的点

后面如果要继续优化，这个 prompt 最值得迭代的通常是下面几类：

- 让上游模型输出更结构化，例如强制 JSON 或 YAML
- 让它区分“满足性质任务”和“寻找反例任务”
- 加入“最小流量序列搜索”要求
- 加入“优先选择最短拓扑路径”或“必须覆盖某条链路”约束
- 加入“如果性质依赖 old/寄存器，则自动构造多包阶段任务”的显式规则
- 加入“控制平面规则必须和表/action 实际名字严格一致”的检查
- 加入“输出给下游 agent 的任务难度等级”

## 8. 一个可直接复制的填写示例

下面是一个简化版示例，你后面可以直接替换成真实输入。

```text
<P4LTL_GUIDE_PATH>: /home/gosh/P4LTL/P4LTL_LLM/P4LTL_user_guide

<P4LTL_GUIDE_CONTENT>:
只保留 guide 中关于 AP、drop、fwd、old、Apply、Key、CPI_SIMP、LTLVariables 的章节摘要

<P4LTL_SPEC>:
//#LTLProperty: [](<>(AP(standard_metadata.ingress_port == 0 && old(hdr.ethernet.dstAddr) != 0xffffffffffff && fwd(1)))) && [](<>(AP(standard_metadata.ingress_port == 0 && old(hdr.ethernet.dstAddr) != 0xffffffffffff && fwd(2))))
//#LTLFairness: [](<>(AP(standard_metadata.ingress_port == 0 && old(hdr.ethernet.dstAddr) != 0xffffffffffff)))

<P4_PROGRAM_PATH>:
/home/gosh/P4LTL/Artifact/benchmark/Temporal Verification/Case Study/P4NIS/main.p4

<P4_PROGRAM_SUMMARY>:
用户侧从 ingress_port 0 进入，程序按寄存器 count 在多个出口间轮转封装并转发。

<TOPOLOGY_TEXT>:
- user host h1 connected to switch s1 ingress port 0
- s1 port 1 connected to path A
- s1 port 2 connected to path B
- s1 port 3 connected to path C
- packet capture available on all three egress paths

<TOPOLOGY_JSON>:
{...}

<AVAILABLE_HOSTS_AND_PORTS>:
- sender on h1
- capture on hA, hB, hC
- control plane on s1

<CONTROL_PLANE_SURFACE>:
- count register exists
- default_route action can influence output path

<KNOWN_PROTOCOL_HEADERS>:
- ethernet
- ipv4
- ipv6
- ipv4_tunnel
- udp_tunnel

<TASK_GOAL>:
让下游 agent 生成真实发送任务，验证三个出口都会被轮转命中

<DOWNSTREAM_AGENT_CAPABILITIES>:
- can generate scapy traffic
- can generate control-plane rule commands
- can propose multi-packet traffic sequence
- can specify capture plan

<OUTPUT_LANGUAGE>:
Chinese
```

## 9. 一句话设计原则

这个 prompt 的核心不是“把 LTL 翻成中文”，而是：

把 `P4LTL 公式 + 拓扑 + 可控接口` 压缩成一个下游 agent 可以直接执行的、最小真实实验任务。
