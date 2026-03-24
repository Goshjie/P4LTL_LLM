from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--guide-path", required=True)
    parser.add_argument("--max-rounds", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    _bootstrap_import_path()

    from P4LTL_LLM import load_default_benchmark_cases
    from P4LTL_LLM.pipeline.models import IntentToP4LTLRequest
    from P4LTL_LLM.pipeline.pipeline_protocol import IntentToP4LTLPipeline

    args = _parse_args()
    cases = {case.case_id: case for case in load_default_benchmark_cases()}
    case = cases[args.case_id]

    request = IntentToP4LTLRequest(
        intent=case.intent,
        admin_description=case.admin_description,
        p4_program_paths=case.p4_program_paths,
        artifact_paths=case.artifact_paths + case.control_plane_paths,
        control_plane_surface="\n".join(case.control_plane_paths),
        extra_constraints=case.extra_constraints,
        guide_path=args.guide_path,
        benchmark_case_id=case.case_id,
        max_rounds=args.max_rounds,
    )

    pipeline = IntentToP4LTLPipeline(
        use_agents=True,
        allow_heuristic_fallback=False,
        agent_timeout_seconds=25,
        agent_max_retries=1,
        agent_retry_delay_seconds=2,
        enable_learning=False,
    )

    try:
        result = pipeline.generate_and_validate(request)
        payload = {
            "ok": True,
            "result": result.model_dump(),
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
