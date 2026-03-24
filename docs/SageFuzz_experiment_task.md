# SageFuzz P4LTL Experiment Task

本任务文档用于在新窗口中独立执行 `SageFuzz/P4` 相关实验，不依赖当前聊天上下文。

## 1. 任务目标

对 `/home/gosh/SageFuzz/P4` 下的 P4 程序进行“自然语言意图 -> `.p4ltl`”生成测试。

要求：

1. 不把 5 个程序粗暴地当成 5 个实验。
2. 要按每个程序的原始实验目标拆成多个更贴近真实意图的子实验。
3. 生成结果必须经过：
   - syntax checker
   - context alignment
   - semantic review
4. 保存每个实验的：
   - 输入
   - 每次尝试
   - 最终输出
   - 汇总结果

## 2. 程序范围

目标目录：

```text
/home/gosh/SageFuzz/P4
```

涉及程序：

- `firewall`
- `link_monitor`
- `Heavy_Hitter_Detector`
- `Fast-Reroute`
- `Congestion_Aware_Load_Balancing`

## 3. 实验拆分

当前 SageFuzz 实验必须按以下 11 个 case 执行：

### firewall

1. `sagefuzz:firewall:block-new-external`
   意图：外部主机不能主动发起到内部网络的新 TCP 连接；当一个外部到内部的 TCP SYN 试图建立新连接时，程序应阻断或丢弃这类包。

2. `sagefuzz:firewall:allow-return-traffic`
   意图：如果内部主机先建立了连接，那么外部主机的返回 TCP 流量应被允许通过，而不是一直被阻断。

### link_monitor

3. `sagefuzz:link-monitor:collect-per-hop-utilization`
   意图：当 probe 包穿过交换机时，程序应逐跳把出口链路利用率相关数据写入 probe 数据头。

4. `sagefuzz:link-monitor:deliver-monitoring-data`
   意图：probe 包最终应把收集到的链路利用率监控信息带到主机端用于观测。

### Heavy_Hitter_Detector

5. `sagefuzz:heavy-hitter:block-heavy-flow`
   意图：当某个 TCP 流的计数超过阈值后，程序应阻断或丢弃该流。

6. `sagefuzz:heavy-hitter:forward-normal-flow`
   意图：未超过阈值的正常 TCP 流应继续被正常转发，而不是被误丢弃。

### Fast-Reroute

7. `sagefuzz:fast-reroute:failover-to-lfa`
   意图：当主下一跳对应链路故障时，交换机应立即选择无环备用下一跳转发流量。

8. `sagefuzz:fast-reroute:use-primary-when-healthy`
   意图：当主链路正常时，程序应继续使用主下一跳，而不是无条件切到备用路径。

### Congestion_Aware_Load_Balancing

9. `sagefuzz:load-balancing:add-telemetry-in-network`
   意图：当 TCP 包在网络内部传输时，程序应在网络内部维护 telemetry 信息以携带路径上的队列深度。

10. `sagefuzz:load-balancing:remove-telemetry-before-host`
    意图：带 telemetry 的包在离开网络到达主机前，应去掉 telemetry 头并恢复正常以太网类型。

11. `sagefuzz:load-balancing:reroute-congested-flow`
    意图：当出口检测到流经历拥塞并触发通知后，入口交换机最终应把该流迁移到其他路径，避免长期停留在拥塞路径上。

## 4. 执行要求

### 4.1 输入要求

每个实验都必须使用：

- 真实自然语言意图
- 对应程序源码
- 对应编译产物
- 必要时可补充控制平面信息

禁止再退回到以下占位式意图：

- “验证 ingress_port 为非负”
- “验证 egress_spec 为非负”
- 其他与原实验目标无关的 trivially-true 性质

### 4.2 生成要求

必须使用当前仓库的 `.p4ltl` 语法约束：

- 语法 guide：
  `/home/gosh/P4LTL/P4LTL_LLM/docs/P4LTL_user_guide`
- prompt 语义 guide：
  `/home/gosh/P4LTL/P4LTL_LLM/docs/P4LTL_prompt_semantics_guide.md`

### 4.3 判定要求

每个实验都必须记录：

- `syntax`
- `context`
- `semantic`

其中 `semantic` 采用当前“模型语义审查”路径，而不是旧的脚本启发式路径。

### 4.4 重试要求

如果出现 `TypeError`，必须继续重试，最多 10 次。

每个实验的总耗时定义为：

- 从这个实验启动开始
- 到最终成功或最终失败为止
- 中间所有失败重试时间都要计入

## 5. 输出与保存

每个实验目录必须保存：

- `input.json`
- `attempt_01.json`, `attempt_02.json`, ...
- `attempts_summary.json`
- `output.json`

整轮实验目录必须额外保存：

- `summary.json`
- `summary.md`

## 6. 建议执行方式

优先单独为 SageFuzz 建一个新目录，例如：

```text
/home/gosh/P4LTL/P4LTL_LLM/run/<timestamp>_sagefuzz_split
```

再把 11 个实验逐个落盘。

## 7. 验收标准

执行结束后，应能直接回答：

1. 11 个实验各自的最终状态
2. 每个实验的总耗时
3. 每个实验是否：
   - syntax 通过
   - context 通过
   - semantic 通过
4. 哪些实验失败，以及失败原因是什么

如果某个实验失败，必须保留失败时的 `output.json` 和全部 attempt 记录。
