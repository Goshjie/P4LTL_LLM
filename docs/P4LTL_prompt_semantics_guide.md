# P4LTL Prompt Semantics Guide

这份文档不是 parser 真值定义，parser 真值仍然以 `P4LTL_user_guide` 和当前仓库 parser 为准。

本文件的目的，是帮助大模型把“自然语言意图”稳定映射成当前仓库可接受的 `.p4ltl` 文本，减少以下错误：

- 选错时序算子
- 用错公式骨架
- 输出非法 DSL
- 写出 parser 不接受的谓词形式
- 输出额外说明性 marker 或推理内容

## 1. 总原则

生成 `.p4ltl` 时，必须同时满足两点：

1. 语法必须被当前仓库 parser 接受
2. 公式结构必须和用户意图的时序含义一致

优先顺序：

1. 先判断意图属于哪类时序模式
2. 再选模板
3. 再用程序上下文中的真实字段/表/动作替换模板槽位

不要反过来先随意写公式，再事后解释它是什么意思。

## 2. 每个时序符号的意义

### `[]`

含义：始终成立，任何时刻都必须满足。

适合表达：

- 始终
- 一直
- 永远
- always
- globally

优先模板：

```text
//#LTLProperty: [](AP(cond))
```

### `<>`

含义：最终发生，未来某个时刻会成立。

适合表达：

- 最终会
- 迟早会
- eventually
- 最后能够

优先模板：

```text
//#LTLProperty: <>(AP(event))
```

### `X`

含义：下一步成立。

适合表达：

- 下一步
- 下一拍
- 紧接着
- next

优先模板：

```text
//#LTLProperty: [](AP(A) ==> X(AP(B)))
```

### `W`

含义：弱直到。`A W C` 表示在 `C` 发生前，`A` 一直成立；并且 `C` 不一定必须发生。

适合表达：

- 在……之前一直
- 直到……前保持
- unless / until
- 保持某状态直到某条件出现

优先模板：

```text
//#LTLProperty: AP(A) W AP(C)
```

或带触发条件：

```text
//#LTLProperty: [](AP(trigger) ==> (AP(A) W AP(C)))
```

如果是“从下一步开始保持”，优先写：

```text
//#LTLProperty: [](AP(A) ==> X(AP(B) W AP(C)))
```

### `U`

含义：直到。`A U C` 表示在 `C` 发生前，`A` 一直成立，并且 `C` 必须最终发生。

除非用户明确要求终止条件一定会发生，否则优先用 `W` 而不是 `U`。

### `R`

含义：release。当前场景中很少需要，只有当用户意图本身明确是 release 语义时再用。

### `!`

含义：否定。可用于时序公式，也可用于 AP 内部谓词。

适合表达：

- 不会
- 不应
- 不是
- not

## 3. 意图到公式骨架映射

### 模式 A：始终满足

自然语言线索：

- 始终
- 一直
- 永远
- 总是

优先模板：

```text
//#LTLProperty: [](AP(cond))
```

例子：

```text
//#LTLProperty: [](AP(standard_metadata.ingress_port >= 0))
```

### 模式 B：最终发生

自然语言线索：

- 最终会
- eventually
- 迟早会

优先模板：

```text
//#LTLProperty: <>(AP(event))
```

例子：

```text
//#LTLProperty: <>(AP(drop))
```

### 模式 C：如果 A，则下一步必须 B

自然语言线索：

- 下一步必须
- 下一拍
- next

优先模板：

```text
//#LTLProperty: [](AP(A) ==> X(AP(B)))
```

### 模式 D：如果 A，则下一步开始保持 B，直到 C

自然语言线索：

- 一旦 A
- 从下一步开始
- 保持直到
- before/until

优先模板：

```text
//#LTLProperty: [](AP(A) ==> X(AP(B) W AP(C)))
```

### 模式 E：在 C 发生前，A 一直成立

自然语言线索：

- 在……之前一直
- 保持直到
- unless
- until

优先模板：

```text
//#LTLProperty: AP(A) W AP(C)
```

如果有触发条件：

```text
//#LTLProperty: [](AP(trigger) ==> (AP(A) W AP(C)))
```

### 模式 F：控制平面规则约束

自然语言线索：

- 某表必须选某动作
- rule should select action
- 表规则
- action selection

优先模板：

```text
//#CPI_SPEC: [](AP(Key(table, key_expr) == value ==> Apply(table, action)))
//#LTLProperty: [](AP(cond))
```

如果只是单条简单 key/action 关系：

```text
//#CPI_SIMP: Key(table, key_expr) == value; Apply(table, action)
//#LTLProperty: [](AP(cond))
```

### 模式 G：需要前态值

自然语言线索：

- 前态
- 上一轮值
- old value

优先写：

```text
old(term)
```

不要发明：

- `prev(...)`
- `previous(...)`
- `last(...)`

## 4. AP 内部如何写

`AP(...)` 内必须是当前 parser 支持的谓词。

优先使用：

- `drop`
- `fwd(term)`
- `valid(name)`
- `Apply(table)`
- `Apply(table, action)`
- `term == term`
- `term != term`
- `term > term`
- `term >= term`
- `term < term`
- `term <= term`

### 合法例子

```text
AP(drop)
AP(valid(hdr.ipv4))
AP(standard_metadata.ingress_port == 1)
AP(fwd(3))
AP(Apply(route_tbl, set_nhop))
AP(old(r_state_dropping[a]) == 1)
```

### 不合法或高风险例子

```text
AP(true)
AP(hdr.ipv4.isValid())
AP(meta.flag)
AP(forward(3))
AP(table_hit(route_tbl))
```

对应正确写法：

```text
AP(valid(hdr.ipv4))
AP(meta.flag == 1)
AP(fwd(3))
```

## 5. 常见错误及替换规则

### 错误：使用 `G` / `F`

不要写：

```text
G(AP(cond))
F(AP(drop))
```

请改成：

```text
[](AP(cond))
<>(AP(drop))
```

### 错误：使用 `->`

不要写：

```text
AP(A) -> AP(B)
```

请改成：

```text
AP(A) ==> AP(B)
```

### 错误：使用 `hdr.xxx.isValid()`

不要写：

```text
AP(hdr.bfsTag.isValid())
```

请改成：

```text
AP(valid(hdr.bfsTag))
```

### 错误：输出额外说明性 marker

不要输出：

```text
//#Description:
//#Pattern:
//#Trigger:
//#Condition:
//#Entities:
```

系统接受的 marker 只有：

```text
//#LTLProperty:
//#LTLFairness:
//#LTLVariables:
//#CPI:
//#CPI_SPEC:
//#CPI_SIMP:
```

### 错误：输出别的 DSL

不要输出：

```text
spec eventually_drop
  eventually drop
end
```

请改成：

```text
//#LTLProperty: <>(AP(drop))
```

### 错误：返回工具计划或推理数组

不要输出：

```json
[{"tool":"search_code","pattern":"..."}]
```

也不要把这些内容放进 `spec_text`。

## 6. 对模型的最终生成要求

如果你要生成 `.p4ltl`，请遵守：

1. `spec_text` 必须是 `.p4ltl` 文件正文
2. 至少有一行 `//#LTLProperty: ...`
3. 只使用当前仓库接受的 `.p4ltl` 语法
4. 如果意图是“始终”，优先 `[]`
5. 如果意图是“最终”，优先 `<>`
6. 如果意图是“在……之前一直”，优先 `W`
7. 如果需要前态，优先 `old(...)`
8. 如果字段/表/动作不确定，先从上下文检索，不要猜
9. 不要输出解释、注释说明、推理内容、工具计划

## 7. 最小示例

```text
//#LTLProperty: <>(AP(drop))
```

```text
//#LTLProperty: [](AP(standard_metadata.ingress_port >= 0))
```

```text
//#LTLProperty: [](AP(A) ==> X(AP(B)))
```

```text
//#LTLProperty: [](AP(A) ==> (AP(B) W AP(C)))
```
