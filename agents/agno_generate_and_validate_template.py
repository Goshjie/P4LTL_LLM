from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

try:
    from P4LTL_LLM import P4LTLAgentSyntaxInterface
except ImportError:
    from P4LTL_LLM.syntax_checker import P4LTLAgentSyntaxInterface

try:
    from P4LTL_LLM.config import load_api_config
except ImportError:
    from P4LTL_LLM.config import load_api_config


DEFAULT_GUIDE_PATH = Path(__file__).resolve().parents[1] / "docs" / "P4LTL_user_guide"


def _ensure_supported_python() -> None:
    if sys.version_info < (3, 9):
        cur = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise SystemExit(
            "Unsupported Python runtime detected: "
            f"{cur}. Please use Python 3.9+ (recommended: python3.12).\n"
            "Example: python3.12 agno_generate_and_validate_template.py"
        )


def build_default_model():
    from agno.models.openai.like import OpenAILike

    api_config = load_api_config()
    return OpenAILike(
        id=api_config.model_id,
        api_key=api_config.api_key,
        base_url=api_config.base_url,
    )


def _build_learning_kwargs(enable_learning: bool, learning_db_url: Optional[str]) -> dict[str, Any]:
    if not enable_learning:
        return {}
    if not learning_db_url:
        raise ValueError("learning_db_url is required when enable_learning=True")

    from agno.db.postgres import PostgresDb

    return {
        "db": PostgresDb(db_url=learning_db_url),
        "learning": True,
    }


class GenerateAndValidateRequest(BaseModel):
    intent: str = Field(description="Natural-language intent to convert into a .p4ltl spec.")
    p4_program_context: str = Field(
        default="",
        description="Relevant P4 program context, tables, metadata, or behavior summary.",
    )
    known_field_names: list[str] = Field(
        default_factory=list,
        description="Known headers/metadata/register identifiers that should be reused.",
    )
    control_plane_surface: str = Field(
        default="",
        description="Available tables, keys, actions, and rule-writing surface.",
    )
    extra_constraints: list[str] = Field(
        default_factory=list,
        description="Hard constraints for the generated .p4ltl text.",
    )
    guide_path: str = Field(
        default=str(DEFAULT_GUIDE_PATH),
        description="Path to the P4LTL user guide used as generation ground truth.",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Optional Agno user_id. Useful if learning is enabled.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional Agno session_id. Useful for multi-turn refinement.",
    )
    max_rounds: int = Field(default=3, ge=1, le=10)


class P4LTLCandidate(BaseModel):
    spec_text: str = Field(
        description="Complete .p4ltl file text only, including //# markers."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit assumptions the generator made.",
    )
    self_checks: list[str] = Field(
        default_factory=list,
        description="Short self-checks performed before returning the candidate.",
    )


class AttemptRecord(BaseModel):
    round_id: int
    candidate: P4LTLCandidate
    validation: dict[str, Any]


class GenerateAndValidateResult(BaseModel):
    ok: bool
    final_spec_text: Optional[str] = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    final_validation: dict[str, Any] = Field(default_factory=dict)


class GenerateAndValidateProtocol:
    """
    Minimal Agno-based protocol template:
    1. Generate a candidate .p4ltl file with an Agent.
    2. Validate it with the local P4LTL checker tool.
    3. Feed validation feedback back into the next round.
    """

    def __init__(
        self,
        *,
        model: Optional[Any] = None,
        strict_validation: bool = True,
        enable_learning: bool = False,
        learning_db_url: Optional[str] = None,
        guide_path: str | Path = DEFAULT_GUIDE_PATH,
        markdown: bool = False,
        debug_mode: bool = False,
    ) -> None:
        _ensure_supported_python()

        from agno.agent import Agent
        from agno.tools import tool

        self.guide_path = Path(guide_path)
        self.checker = P4LTLAgentSyntaxInterface(strict=strict_validation)
        self.model = model or build_default_model()

        @tool(name="validate_p4ltl_candidate")
        def validate_p4ltl_candidate(spec_text: str) -> dict[str, Any]:
            """Validate a candidate .p4ltl file using the current local parser-backed checker."""
            return self.checker.validate_spec_text(spec_text).to_dict()

        learning_kwargs = _build_learning_kwargs(enable_learning, learning_db_url)

        self.agent = Agent(
            name="p4ltl-generate-and-validate",
            model=self.model,
            markdown=markdown,
            debug_mode=debug_mode,
            tools=[validate_p4ltl_candidate],
            tool_choice="auto",
            output_schema=P4LTLCandidate,
            parse_response=True,
            structured_outputs=True,
            instructions=[
                "Return a valid JSON object that matches the P4LTLCandidate schema.",
                "You generate .p4ltl file text for the current P4LTL implementation.",
                "The spec_text field must contain the exact .p4ltl file body, not prose and not any other DSL.",
                "At least one line must start with //#LTLProperty:.",
                "Use only repository-supported .p4ltl markers and syntax.",
                "Do not output formats like 'spec ... end', plain-English LTL, Markdown fences, or explanatory text.",
                "Always reuse the provided field names, table names, keys, and actions when available.",
                "Before returning a final candidate, call validate_p4ltl_candidate on the candidate spec_text.",
                "If validation fails, repair the candidate and validate again before finalizing.",
                "Return ASCII-only .p4ltl text in spec_text, including //# markers.",
                "Do not return prose inside spec_text.",
            ],
            expected_output=(
                "Return a JSON object with spec_text, assumptions, and self_checks."
            ),
            **learning_kwargs,
        )

    def generate_and_validate(
        self,
        request: GenerateAndValidateRequest,
    ) -> GenerateAndValidateResult:
        guide_text = Path(request.guide_path).read_text(encoding="utf-8")
        feedback: Optional[str] = None
        previous_candidate: Optional[P4LTLCandidate] = None
        attempts: list[AttemptRecord] = []

        for round_id in range(1, request.max_rounds + 1):
            prompt = self._build_round_prompt(
                request=request,
                guide_text=guide_text,
                feedback=feedback,
                previous_candidate=previous_candidate,
                round_id=round_id,
            )

            run_output = self.agent.run(
                prompt,
                user_id=request.user_id,
                session_id=request.session_id,
                output_schema=P4LTLCandidate,
            )

            candidate = self._coerce_candidate(run_output.content)
            validation = self.checker.validate_spec_text(candidate.spec_text)

            attempts.append(
                AttemptRecord(
                    round_id=round_id,
                    candidate=candidate,
                    validation=validation.to_dict(),
                )
            )

            if validation.valid:
                return GenerateAndValidateResult(
                    ok=True,
                    final_spec_text=candidate.spec_text,
                    attempts=attempts,
                    final_validation=validation.to_dict(),
                )

            feedback = validation.feedback_for_agent
            previous_candidate = candidate

        final_validation = attempts[-1].validation if attempts else {}
        final_spec_text = attempts[-1].candidate.spec_text if attempts else None
        return GenerateAndValidateResult(
            ok=False,
            final_spec_text=final_spec_text,
            attempts=attempts,
            final_validation=final_validation,
        )

    def _build_round_prompt(
        self,
        *,
        request: GenerateAndValidateRequest,
        guide_text: str,
        feedback: Optional[str],
        previous_candidate: Optional[P4LTLCandidate],
        round_id: int,
    ) -> str:
        known_fields = (
            "\n".join(f"- {item}" for item in request.known_field_names)
            if request.known_field_names
            else "- <none provided>"
        )
        extra_constraints = (
            "\n".join(f"- {item}" for item in request.extra_constraints)
            if request.extra_constraints
            else "- <none provided>"
        )
        previous_block = ""
        if previous_candidate is not None:
            previous_block = (
                "\nPrevious invalid candidate:\n"
                f"{previous_candidate.spec_text}\n"
            )
        feedback_block = ""
        if feedback:
            feedback_block = f"\nValidation feedback from the previous round:\n{feedback}\n"

        return f"""
Round: {round_id}

Task:
Generate a complete `.p4ltl` file from the user's intent, then validate it with the provided tool before finalizing.

Return a valid JSON object only.

spec_text must be the literal .p4ltl file body.
At least one line must start with //#LTLProperty:.
Do not output 'spec ... end' or any non-.p4ltl DSL.

Intent:
{request.intent}

P4 program context:
{request.p4_program_context or "<none provided>"}

Known field names and identifiers:
{known_fields}

Control plane surface:
{request.control_plane_surface or "<none provided>"}

Extra constraints:
{extra_constraints}

Guide path:
{request.guide_path}

Guide content:
{guide_text}
{previous_block}{feedback_block}
Protocol requirements:
1. Produce a full `.p4ltl` file in `spec_text`.
2. Use the validation tool before finalizing your answer.
3. If the validator reports any error, repair the candidate first.
4. Do not invent unsupported syntax or unknown field names.
5. If free variables are used, declare them explicitly with supported types.
""".strip()

    def _coerce_candidate(self, content: Any) -> P4LTLCandidate:
        if isinstance(content, P4LTLCandidate):
            return content
        if isinstance(content, dict):
            return P4LTLCandidate.model_validate(content)
        return P4LTLCandidate.model_validate_json(json.dumps(content))


def main() -> None:
    protocol = GenerateAndValidateProtocol()
    request = GenerateAndValidateRequest(
        intent="验证 ingress_port 为 1 的 IPv4 包最终会从端口 3 转发",
        p4_program_context="Known headers include hdr.ipv4 and standard_metadata.ingress_port.",
        known_field_names=[
            "hdr.ipv4",
            "standard_metadata.ingress_port",
            "fwd",
        ],
        extra_constraints=[
            "Prefer a single //#LTLProperty line.",
            "Do not invent new field names.",
        ],
    )
    result = protocol.generate_and_validate(request)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
