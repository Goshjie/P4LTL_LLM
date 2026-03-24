# P4LTL_LLM

This package contains a retrieval-oriented intent-to-P4LTL system.

## Main modules

- `syntax_checker/`
  Parser-backed P4LTL syntax checker and agent-facing validation interface.
- `context_store.py`
  Loads P4 sources, build artifacts, runtime JSON, and guide content into memory.
- `context_tools.py`
  Read-only retrieval tools for code search, JSON queries, bounded snippet reads, and graph queries.
- `intent_decomposer.py`
  Structured intent decomposition layer.
- `context_validator.py`
  Checks whether referenced fields/tables/actions/keys match the aligned context.
- `semantic_reviewer.py`
  Heuristic semantic review for generated specs.
- `pipeline_protocol.py`
  End-to-end `IntentToP4LTLPipeline` orchestration.
- `benchmark_specs.py`
  Default benchmark catalog for Case Study and SageFuzz/P4 programs.
- `benchmark_runner.py`
  Runs reference benchmark validation or a pipeline over the benchmark catalog.

## Quick usage

Run the default reference benchmark validation:

```bash
PYTHONPATH=/home/gosh/P4LTL python3.12 /home/gosh/P4LTL/P4LTL_LLM/benchmark_runner.py
```

Use the pipeline from Python:

```python
from P4LTL_LLM import IntentToP4LTLPipeline, IntentToP4LTLRequest

pipeline = IntentToP4LTLPipeline(use_agents=False)
request = IntentToP4LTLRequest(
    intent="生成一个简单性质，验证 ingress_port 始终为非负",
    p4_program_paths=["/abs/path/to/program.p4"],
    artifact_paths=["/abs/path/to/build.json"],
    guide_path="/home/gosh/P4LTL/P4LTL_LLM/P4LTL_user_guide",
)
result = pipeline.generate_and_validate(request)
print(result.model_dump_json(indent=2))
```

Run the online Agno pipeline directly:

```bash
PYTHONPATH=/home/gosh/P4LTL python3.12 /home/gosh/P4LTL/P4LTL_LLM/agno_online_generate.py \
  --intent "验证 ingress_port 为 1 的 IPv4 包最终会从端口 3 转发" \
  --admin-description "Use exact fields from the program and artifacts." \
  --p4 /abs/path/to/program.p4 \
  --artifact /abs/path/to/build.json
```

The online model configuration is now read from:

```text
/home/gosh/P4LTL/P4LTL_LLM/config/api_config.json
```

Notes:

- Online mode uses `IntentToP4LTLPipeline(use_agents=True)`.
- By default it enables streaming model calls because the configured gateway may reject non-streaming requests.
- Pass `--no-stream` only if your backend supports non-streaming structured responses.
