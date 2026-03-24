# P4LTL Syntax Checker

这个模块分成两层：

- `p4ltl_formula_checker.cpp`
  直接复用当前仓库里的 P4LTL lexer/parser，检查单条公式能否通过 parser。
- `checker.py`
  面向 `.p4ltl` 文件做整文件检查，包括：
  - marker 识别
  - `//#LTLVariables:` 的当前实现约束
  - `//#CPI_SIMP:` 到实际 parser 公式的展开
  - 每条公式的 parser 校验

## 构建底层 checker

```bash
/home/gosh/P4LTL/P4LTL_LLM/syntax_checker/build_checker.sh
```

构建产物：

```text
/home/gosh/P4LTL/P4LTL_LLM/syntax_checker/bin/p4ltl_formula_checker
```

## 命令行用法

检查单条公式：

```bash
python3 /home/gosh/P4LTL/P4LTL_LLM/syntax_checker/checker.py \
  --formula '<>(AP(drop))' \
  --json
```

检查整个 `.p4ltl` 文件：

```bash
python3 /home/gosh/P4LTL/P4LTL_LLM/syntax_checker/checker.py \
  --file /abs/path/to/spec.p4ltl \
  --json
```

严格模式会把 guide 级别的问题也当作错误，例如多条 `//#LTLProperty:`：

```bash
python3 /home/gosh/P4LTL/P4LTL_LLM/syntax_checker/checker.py \
  --file /abs/path/to/spec.p4ltl \
  --strict \
  --json
```

## 作为 Python 模块使用

```python
from P4LTL_LLM.syntax_checker import validate_p4ltl_text

report = validate_p4ltl_text(spec_text, strict=True)
if not report.ok:
    print(report.errors)
```

## 面向 agent 的稳定接口

如果后续是 Python agent 框架在调用，建议不要直接依赖底层 dataclass 细节，而是使用：

```python
from P4LTL_LLM import P4LTLAgentSyntaxInterface

checker = P4LTLAgentSyntaxInterface(strict=True)
result = checker.validate_spec_text(candidate_text)

if result.valid:
    print(result.summary)
    print(result.normalized_formulas)
else:
    print(result.feedback_for_agent)
    print(result.to_dict())
```

也可以校验单条公式：

```python
from P4LTL_LLM import P4LTLAgentSyntaxInterface

checker = P4LTLAgentSyntaxInterface()
result = checker.validate_formula("<>(AP(drop))")
print(result.to_dict())
```

这个接口的返回值包含：

- `valid`: 是否通过当前实现
- `summary`: 简短摘要
- `errors`: 结构化错误列表，包含行号、marker、原始文本
- `warnings`: guide 级别警告
- `normalized_formulas`: 成功通过 parser 后的规范化公式
- `feedback_for_agent`: 可直接回喂给生成 agent 的修复提示
- `raw_report`: 保留底层 checker 的原始结果
