from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

from ..config import load_api_config
from .models import AlignedContextSummary, ContextValidationReport, IntentFeatureBundle, SemanticReviewReport


@lru_cache(maxsize=1)
def _build_semantic_review_agent() -> Any:
    from agno.agent import Agent
    from agno.models.openai.like import OpenAILike

    api_config = load_api_config()
    model = OpenAILike(
        id=api_config.model_id,
        api_key=api_config.api_key,
        base_url=api_config.base_url,
    )
    return Agent(
        name="p4ltl-semantic-reviewer",
        model=model,
        output_schema=SemanticReviewReport,
        structured_outputs=True,
        parse_response=True,
        stream=api_config.stream,
        instructions=[
            "Return a valid JSON object matching the SemanticReviewReport schema.",
            "You are reviewing whether a generated .p4ltl spec matches the natural-language intent.",
            "Judge semantic alignment by reading the intent, the generated spec, and the aligned program context summary.",
            "Do not judge based on parser legality alone; judge whether the spec actually expresses the intended behavior.",
            "semantic_verdict must be exactly one of: correct, plausible, weak, incorrect.",
            "Use 'correct' only if the generated property clearly matches the intended behavior.",
            "Use 'plausible' if it is mostly aligned but there is some remaining uncertainty.",
            "Use 'weak' if it is related but misses important parts of the intent.",
            "Use 'incorrect' if it does not match the intent in any reliable way.",
            "Do not return tool plans, prose outside JSON, or extra fields.",
        ],
    )


def review_semantics(
    intent: str,
    features: IntentFeatureBundle,
    spec_text: str,
    context_report: ContextValidationReport,
    aligned_context_summary: Optional[AlignedContextSummary] = None,
) -> SemanticReviewReport:
    agent = _build_semantic_review_agent()
    context_summary = aligned_context_summary.model_dump() if aligned_context_summary is not None else {}
    prompt = f"""
Review whether the following generated .p4ltl spec matches the user's intended meaning.

Return a valid JSON object only.

Allowed semantic_verdict values exactly:
- correct
- plausible
- weak
- incorrect

User intent:
{intent}

Intent feature bundle:
{features.model_dump_json(indent=2)}

Generated spec:
{spec_text}

Context validation report:
{context_report.model_dump_json(indent=2)}

Aligned context summary:
{context_summary}

Requirements:
- Read the intent directly and decide whether the spec matches it.
- Do not rely only on syntax or token overlap.
- intent_coverage should list the parts of the intent the spec captures.
- context_support should explain which context facts support the interpretation.
- suspicious_mismatches should list semantic gaps or wrong interpretations.
- review_reason should be a short direct explanation of the verdict.
""".strip()

    run_output = agent.run(
        prompt,
        stream=load_api_config().stream,
        stream_events=load_api_config().stream,
        output_schema=SemanticReviewReport,
    )

    if load_api_config().stream:
        from agno.run.agent import RunCompletedEvent, RunErrorEvent

        final_content = None
        run_error: Optional[str] = None
        for event in run_output:
            if isinstance(event, RunCompletedEvent):
                final_content = event.content
            elif isinstance(event, RunErrorEvent):
                run_error = event.content or event.error_type or "unknown semantic review error"
        if run_error is not None:
            raise RuntimeError(f"semantic reviewer failed: {run_error}")
        content = final_content
    else:
        content = run_output.content

    if isinstance(content, SemanticReviewReport):
        return content
    if isinstance(content, dict):
        return SemanticReviewReport.model_validate(_normalize_semantic_payload(content))
    if hasattr(content, "model_dump"):
        return SemanticReviewReport.model_validate(_normalize_semantic_payload(content.model_dump()))
    if isinstance(content, str):
        parsed = _try_parse_json_string(content)
        if isinstance(parsed, dict):
            return SemanticReviewReport.model_validate(_normalize_semantic_payload(parsed))
        return _fallback_semantic_report(
            review_reason=f"semantic reviewer returned raw string output: {content[:300]}"
        )
    return _fallback_semantic_report(
        review_reason=f"unexpected semantic reviewer output type: {type(content)!r}"
    )


def _normalize_semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for key in ["intent_coverage", "context_support", "suspicious_mismatches"]:
        value = normalized.get(key)
        if value is None:
            normalized[key] = []
        elif isinstance(value, str):
            normalized[key] = [value]
        elif isinstance(value, list):
            normalized[key] = [str(item) for item in value]
        else:
            normalized[key] = [str(value)]
    verdict = normalized.get("semantic_verdict")
    if verdict not in {"correct", "plausible", "weak", "incorrect"}:
        normalized["semantic_verdict"] = "plausible"
    normalized["review_reason"] = str(normalized.get("review_reason", ""))
    return normalized


def _try_parse_json_string(content: str) -> Optional[dict[str, Any]]:
    text = content.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def _fallback_semantic_report(review_reason: str) -> SemanticReviewReport:
    return SemanticReviewReport(
        semantic_verdict="plausible",
        intent_coverage=[],
        context_support=[],
        suspicious_mismatches=["semantic reviewer output was not fully structured; fallback report used"],
        review_reason=review_reason,
    )
