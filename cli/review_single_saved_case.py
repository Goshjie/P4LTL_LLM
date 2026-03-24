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
    parser.add_argument("--case-dir", required=True)
    return parser.parse_args()


def main() -> None:
    _bootstrap_import_path()

    from P4LTL_LLM.context.context_store import load_context
    from P4LTL_LLM.context.context_validator import validate_context_alignment
    from P4LTL_LLM.pipeline.models import IntentFeatureBundle, IntentToP4LTLRequest
    from P4LTL_LLM.pipeline.semantic_reviewer import review_semantics

    args = _parse_args()
    case_dir = Path(args.case_dir).resolve()
    input_payload = json.loads((case_dir / "input.json").read_text(encoding="utf-8"))
    output_payload = json.loads((case_dir / "output.json").read_text(encoding="utf-8"))

    if "final_spec_text" not in output_payload:
        print(
            json.dumps(
                {
                    "ok": False,
                    "case_id": input_payload.get("case_id"),
                    "error": "No final_spec_text in saved output",
                },
                ensure_ascii=False,
            )
        )
        return

    request = IntentToP4LTLRequest(
        intent=input_payload["intent"],
        admin_description=input_payload.get("admin_description", ""),
        p4_program_paths=input_payload.get("p4_program_paths", []),
        artifact_paths=input_payload.get("artifact_paths", []) + input_payload.get("control_plane_paths", []),
        control_plane_surface="\n".join(input_payload.get("control_plane_paths", [])),
        extra_constraints=input_payload.get("extra_constraints", []),
        guide_path=input_payload["guide_path"],
        benchmark_case_id=input_payload.get("case_id"),
        max_rounds=input_payload.get("max_rounds", 2),
    )
    loaded = load_context(request)
    aligned_summary = loaded.summary()
    context_report = validate_context_alignment(output_payload["final_spec_text"], loaded)

    features_data = output_payload.get("intent_features")
    if isinstance(features_data, dict):
        features = IntentFeatureBundle.model_validate(features_data)
    else:
        features = IntentFeatureBundle()

    semantic = review_semantics(
        intent=request.intent,
        features=features,
        spec_text=output_payload["final_spec_text"],
        context_report=context_report,
        aligned_context_summary=aligned_summary,
    )

    print(
        json.dumps(
            {
                "ok": True,
                "case_id": input_payload.get("case_id"),
                "spec": output_payload["final_spec_text"],
                "semantic": semantic.model_dump(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
