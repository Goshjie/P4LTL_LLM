from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def _bootstrap_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-run semantic review with the LLM for an existing saved run directory."
    )
    parser.add_argument("--run-dir", required=True, help="Existing run directory to review")
    return parser.parse_args()


def main() -> None:
    _bootstrap_import_path()

    from P4LTL_LLM.context.context_store import load_context
    from P4LTL_LLM.context.context_validator import validate_context_alignment
    from P4LTL_LLM.pipeline.models import (
        AlignedContextSummary,
        ContextValidationReport,
        IntentFeatureBundle,
        IntentToP4LTLRequest,
    )
    from P4LTL_LLM.pipeline.semantic_reviewer import review_semantics

    args = _parse_args()
    source_root = Path(args.run_dir).resolve()
    if not source_root.exists():
        raise SystemExit(f"run dir not found: {source_root}")

    out_root = source_root.parent / f"{source_root.name}_semantic_llm_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_root.mkdir(parents=True, exist_ok=True)

    summary: list[dict] = []
    for case_dir in sorted([p for p in source_root.iterdir() if p.is_dir()]):
        input_path = case_dir / "input.json"
        output_path = case_dir / "output.json"
        if not input_path.exists() or not output_path.exists():
            continue

        input_payload = json.loads(input_path.read_text(encoding="utf-8"))
        output_payload = json.loads(output_path.read_text(encoding="utf-8"))

        target_dir = out_root / case_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "input.json").write_text(
            json.dumps(input_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (target_dir / "original_output.json").write_text(
            json.dumps(output_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if "final_spec_text" not in output_payload:
            review_payload = {
                "ok": False,
                "error": "No final_spec_text in original output; semantic review skipped.",
            }
            (target_dir / "semantic_review.json").write_text(
                json.dumps(review_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            summary.append(
                {
                    "case_id": input_payload.get("case_id"),
                    "ok": False,
                    "semantic": "skipped",
                    "review_reason": review_payload["error"],
                }
            )
            continue

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

        semantic_report = review_semantics(
            intent=request.intent,
            features=features,
            spec_text=output_payload["final_spec_text"],
            context_report=context_report,
            aligned_context_summary=aligned_summary,
        )

        review_payload = {
            "case_id": input_payload.get("case_id"),
            "final_spec_text": output_payload["final_spec_text"],
            "original_semantic": output_payload.get("final_validation", {}).get("semantic"),
            "llm_semantic": semantic_report.model_dump(),
        }
        (target_dir / "semantic_review.json").write_text(
            json.dumps(review_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary.append(
            {
                "case_id": input_payload.get("case_id"),
                "ok": True,
                "semantic": semantic_report.semantic_verdict,
                "review_reason": semantic_report.review_reason,
                "spec": output_payload["final_spec_text"],
            }
        )

    (out_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "summary.md").write_text(
        _render_markdown_summary(summary),
        encoding="utf-8",
    )

    print(str(out_root))


def _render_markdown_summary(summary: list[dict]) -> str:
    lines = [
        "# Semantic LLM Review Summary",
        "",
        "| Case | OK | LLM Semantic | Review Reason | Spec |",
        "|---|---:|---|---|---|",
    ]
    for item in summary:
        reason = str(item.get("review_reason", "")).replace("\n", " ").replace("|", "\\|")
        spec = str(item.get("spec", "")).replace("\n", " ").replace("|", "\\|")
        lines.append(
            f"| {item.get('case_id','')} | "
            f"{'yes' if item.get('ok') else 'no'} | "
            f"{item.get('semantic','')} | "
            f"{reason} | "
            f"{spec} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
