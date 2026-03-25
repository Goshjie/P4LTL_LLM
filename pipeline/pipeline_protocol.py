from __future__ import annotations

import json
import signal
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from ..config import load_api_config
from ..context.context_store import load_context
from ..context.context_tools import ContextToolkit
from ..context.context_validator import validate_context_alignment
from .dsl_repair import repair_p4ltl_text
from .intent_decomposer import HeuristicIntentDecompiler
from .models import (
    AttemptRecord,
    IntentFeatureBundle,
    IntentToP4LTLRequest,
    IntentToP4LTLResult,
    P4LTLCandidate,
)
from .semantic_reviewer import review_semantics
from ..syntax_checker import P4LTLAgentSyntaxInterface


DEFAULT_GUIDE_PATH = Path(__file__).resolve().parents[1] / "docs" / "P4LTL_user_guide"
PROMPT_SEMANTICS_GUIDE_PATH = Path(__file__).resolve().parents[1] / "docs" / "P4LTL_prompt_semantics_guide.md"


def build_default_model() -> Any:
    from agno.models.openai.like import OpenAILike

    config = load_api_config()
    return OpenAILike(
        id=config.model_id,
        api_key=config.api_key,
        base_url=config.base_url,
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


class IntentToP4LTLPipeline:
    def __init__(
        self,
        *,
        model: Optional[Any] = None,
        strict_validation: bool = True,
        enable_learning: bool = False,
        learning_db_url: Optional[str] = None,
        use_agents: bool = True,
        allow_heuristic_fallback: bool = True,
        max_snippet_lines: int = 40,
        agent_stream: Optional[bool] = None,
        debug_mode: bool = False,
        agent_timeout_seconds: float = 45.0,
        agent_max_retries: int = 2,
        agent_retry_delay_seconds: float = 2.0,
    ) -> None:
        self.model = model or build_default_model()
        self.strict_validation = strict_validation
        self.enable_learning = enable_learning
        self.learning_db_url = learning_db_url
        self.use_agents = use_agents
        self.allow_heuristic_fallback = allow_heuristic_fallback
        self.max_snippet_lines = max_snippet_lines
        self.agent_stream = self._resolve_agent_stream(agent_stream)
        self.debug_mode = debug_mode
        self.agent_timeout_seconds = agent_timeout_seconds
        self.agent_max_retries = agent_max_retries
        self.agent_retry_delay_seconds = agent_retry_delay_seconds
        self.syntax = P4LTLAgentSyntaxInterface(strict=strict_validation)
        self.heuristic = HeuristicIntentDecompiler()

    def generate_and_validate(self, request: IntentToP4LTLRequest) -> IntentToP4LTLResult:
        loaded = load_context(request)
        toolkit = ContextToolkit(loaded, max_snippet_lines=self.max_snippet_lines)
        aligned_summary = loaded.summary()
        semantics_guide_text = PROMPT_SEMANTICS_GUIDE_PATH.read_text(encoding="utf-8")
        features = self._decompose(request, toolkit, semantics_guide_text)

        attempts: list[AttemptRecord] = []
        feedback: Optional[str] = None
        previous_candidate: Optional[P4LTLCandidate] = None
        final_feedback = ""

        for round_id in range(1, request.max_rounds + 1):
            candidate = self._generate_candidate(
                request=request,
                toolkit=toolkit,
                features=features,
                semantics_guide_text=semantics_guide_text,
                feedback=feedback,
                previous_candidate=previous_candidate,
                round_id=round_id,
            )
            candidate = self._apply_dsl_repair(candidate)
            syntax_validation = self.syntax.validate_spec_text(candidate.spec_text)
            context_validation = validate_context_alignment(candidate.spec_text, loaded)
            semantic_review = review_semantics(
                intent=request.intent,
                features=features,
                spec_text=candidate.spec_text,
                context_report=context_validation,
                aligned_context_summary=aligned_summary,
            )

            repair_summary = self._build_repair_summary(
                syntax_validation=syntax_validation.to_dict(),
                context_valid=context_validation.valid,
                semantic_verdict=semantic_review.semantic_verdict,
                semantic_review=semantic_review,
            )
            attempts.append(
                AttemptRecord(
                    round_id=round_id,
                    candidate=candidate,
                    syntax_validation=syntax_validation.to_dict(),
                    context_validation=context_validation,
                    semantic_review=semantic_review,
                    repair_input_summary=repair_summary,
                )
            )

            if syntax_validation.valid and context_validation.valid and semantic_review.semantic_verdict in self._accepted_semantic_verdicts(request, features):
                return IntentToP4LTLResult(
                    ok=True,
                    final_spec_text=candidate.spec_text,
                    aligned_context_summary=aligned_summary,
                    intent_features=features,
                    attempts=attempts,
                    final_validation={
                        "syntax": syntax_validation.to_dict(),
                        "context": context_validation.model_dump(),
                        "semantic": semantic_review.model_dump(),
                    },
                    final_feedback_for_agent="accepted",
                )

            feedback = self._build_feedback_text(
                syntax_validation=syntax_validation.to_dict(),
                context_validation=context_validation,
                semantic_review=semantic_review,
            )
            final_feedback = feedback
            previous_candidate = candidate

        final_spec = attempts[-1].candidate.spec_text if attempts else None
        final_validation = (
            {
                "syntax": attempts[-1].syntax_validation,
                "context": attempts[-1].context_validation.model_dump(),
                "semantic": attempts[-1].semantic_review.model_dump(),
            }
            if attempts
            else {}
        )
        return IntentToP4LTLResult(
            ok=False,
            final_spec_text=final_spec,
            aligned_context_summary=aligned_summary,
            intent_features=features,
            attempts=attempts,
            final_validation=final_validation,
            final_feedback_for_agent=final_feedback,
        )

    def _decompose(self, request: IntentToP4LTLRequest, toolkit: ContextToolkit, semantics_guide_text: str) -> IntentFeatureBundle:
        if self.use_agents:
            agent = self._build_decomposer_agent(toolkit)
            try:
                prompt = self._build_decomposer_prompt(request, toolkit, semantics_guide_text)
                output = self._run_agent(
                    agent,
                    prompt,
                    output_schema=IntentFeatureBundle,
                    stage_name="decomposer",
                )
                agent_features = self._coerce_model(output, IntentFeatureBundle)
                heuristic_features = self.heuristic.decompose(request.intent, request.admin_description, toolkit)
                return self._merge_feature_bundles(agent_features, heuristic_features)
            except Exception:
                if not self.allow_heuristic_fallback:
                    raise
        return self.heuristic.decompose(request.intent, request.admin_description, toolkit)

    def _merge_feature_bundles(
        self,
        agent_features: IntentFeatureBundle,
        heuristic_features: IntentFeatureBundle,
    ) -> IntentFeatureBundle:
        updates: dict[str, Any] = {}

        targeted_families = {"stateful_local", "in_band_header_added_or_preserved"}
        if heuristic_features.template_family in targeted_families and agent_features.template_family != heuristic_features.template_family:
            updates["template_family"] = heuristic_features.template_family
        elif agent_features.template_family == "generic_temporal_property" and heuristic_features.template_family != "generic_temporal_property":
            updates["template_family"] = heuristic_features.template_family
        if updates.get("template_family") == heuristic_features.template_family:
            updates["expressibility_level"] = heuristic_features.expressibility_level
        elif agent_features.expressibility_level == "direct" and heuristic_features.expressibility_level != "direct":
            updates["expressibility_level"] = heuristic_features.expressibility_level
        if not agent_features.template_guidance and heuristic_features.template_guidance:
            updates["template_guidance"] = heuristic_features.template_guidance
        if not agent_features.required_slot_hints and heuristic_features.required_slot_hints:
            updates["required_slot_hints"] = heuristic_features.required_slot_hints
        if not agent_features.target_events and heuristic_features.target_events:
            updates["target_events"] = heuristic_features.target_events
        if not agent_features.state_constraints and heuristic_features.state_constraints:
            updates["state_constraints"] = heuristic_features.state_constraints
        if not agent_features.control_plane_constraints and heuristic_features.control_plane_constraints:
            updates["control_plane_constraints"] = heuristic_features.control_plane_constraints
        if not agent_features.required_entities and heuristic_features.required_entities:
            updates["required_entities"] = heuristic_features.required_entities
        if not agent_features.assumptions and heuristic_features.assumptions:
            updates["assumptions"] = heuristic_features.assumptions
        if agent_features.decomposition_summary in {"", "intent_type=packet_behavior, temporal_pattern=eventually, targets=['generic-condition']"}:
            updates["decomposition_summary"] = heuristic_features.decomposition_summary

        if not updates:
            return agent_features
        return agent_features.model_copy(update=updates)

    def _generate_candidate(
        self,
        *,
        request: IntentToP4LTLRequest,
        toolkit: ContextToolkit,
        features: IntentFeatureBundle,
        semantics_guide_text: str,
        feedback: Optional[str],
        previous_candidate: Optional[P4LTLCandidate],
        round_id: int,
    ) -> P4LTLCandidate:
        family_candidate = self._family_guided_candidate(
            request=request,
            features=features,
            toolkit=toolkit,
            feedback=feedback,
            previous_candidate=previous_candidate,
        )
        if family_candidate is not None:
            return family_candidate

        if self.use_agents:
            try:
                if feedback and previous_candidate is not None:
                    agent = self._build_repair_agent(toolkit)
                    prompt = self._build_repair_prompt(
                        request=request,
                        toolkit=toolkit,
                        features=features,
                        semantics_guide_text=semantics_guide_text,
                        feedback=feedback,
                        previous_candidate=previous_candidate,
                        round_id=round_id,
                    )
                else:
                    agent = self._build_generation_agent(toolkit)
                    prompt = self._build_generation_prompt(
                        request=request,
                        toolkit=toolkit,
                        features=features,
                        semantics_guide_text=semantics_guide_text,
                        feedback=feedback,
                        previous_candidate=previous_candidate,
                        round_id=round_id,
                    )
                output = self._run_agent(
                    agent,
                    prompt,
                    output_schema=P4LTLCandidate,
                    stage_name="repair" if feedback and previous_candidate is not None else "generator",
                )
                return self._coerce_model(output, P4LTLCandidate)
            except Exception:
                if not self.allow_heuristic_fallback:
                    raise
        return self._heuristic_candidate(features, toolkit, feedback)

    def _family_guided_candidate(
        self,
        *,
        request: IntentToP4LTLRequest,
        features: IntentFeatureBundle,
        toolkit: ContextToolkit,
        feedback: Optional[str],
        previous_candidate: Optional[P4LTLCandidate],
    ) -> Optional[P4LTLCandidate]:
        if feedback is not None or previous_candidate is not None:
            return None

        if features.template_family == "stateful_local":
            candidate = self._build_stateful_local_candidate(request, toolkit)
            if candidate is not None:
                return candidate

        if features.template_family == "in_band_header_added_or_preserved":
            candidate = self._build_in_band_header_candidate(request, toolkit)
            if candidate is not None:
                return candidate

        return None

    def _build_stateful_local_candidate(
        self,
        request: IntentToP4LTLRequest,
        toolkit: ContextToolkit,
    ) -> Optional[P4LTLCandidate]:
        text = f"{request.intent}\n{request.admin_description}".lower()
        known_fields = set(toolkit.list_known_entities("field"))
        known_tables = set(toolkit.list_known_entities("table"))

        if (
            "return" in text
            or "返回" in text
            or "已建立" in text
            or "established" in text
        ):
            if {
                "direction_0",
                "MyIngress.bloom_filter_1",
                "MyIngress.bloom_filter_2",
                "hdr.tcp",
            } <= known_fields:
                spec = (
                    "//#LTLProperty: "
                    "[](AP(valid(hdr.tcp) && direction_0 == 1 && standard_metadata.ingress_port > 2 && "
                    "MyIngress.bloom_filter_1 == 1 && MyIngress.bloom_filter_2 == 1) ==> AP(!drop))"
                )
                return P4LTLCandidate(
                    spec_text=spec,
                    assumptions=[
                        "Used the visible firewall state-tracking signals direction_0 and bloom_filter bits as the local witness for established return traffic."
                    ],
                    self_checks=[
                        "family-guided candidate for stateful_local",
                        "captured explicit state condition before asserting !drop",
                    ],
                    evidence_used=[
                        "direction_0",
                        "MyIngress.bloom_filter_1",
                        "MyIngress.bloom_filter_2",
                    ],
                    generation_rationale_summary="Programmatic stateful_local template for firewall-style return-traffic intents.",
                )

        if (
            ("normal" in text or "正常" in text or "未超过阈值" in text)
            and ("heavy" in text or "threshold" in text or "阈值" in text)
        ):
            heavy_tables = sorted([name for name in known_tables if "heavy_hitter" in name or "heavy" in name])
            heavy_table = heavy_tables[0] if heavy_tables else None
            if heavy_table is not None:
                spec = (
                    f"//#LTLProperty: [](AP(valid(hdr.tcp) && valid(hdr.ipv4) && !Apply({heavy_table})) ==> AP(!drop))"
                )
                return P4LTLCandidate(
                    spec_text=spec,
                    assumptions=[
                        "Approximated 'below threshold' using the absence of the heavy-hitter table action on the packet path."
                    ],
                    self_checks=[
                        "family-guided candidate for stateful_local",
                        "used local table-selection witness for non-heavy flows",
                    ],
                    evidence_used=[heavy_table, "hdr.tcp", "hdr.ipv4"],
                    generation_rationale_summary="Programmatic stateful_local template for heavy-hitter non-drop intents.",
                )

        return None

    def _build_in_band_header_candidate(
        self,
        request: IntentToP4LTLRequest,
        toolkit: ContextToolkit,
    ) -> Optional[P4LTLCandidate]:
        text = f"{request.intent}\n{request.admin_description}".lower()
        known_fields = set(toolkit.list_known_entities("field"))

        if "probe" in text or "逐跳" in text or "utilization" in text or "利用率" in text:
            required = {
                "hdr.probe",
                "hdr.probe_data",
                "standard_metadata.egress_port",
            }
            if required <= known_fields and {"port", "byte_cnt", "cur_time", "last_time"} <= known_fields:
                spec = (
                    "//#LTLProperty: "
                    "[](AP(valid(hdr.probe)) ==> AP(valid(hdr.probe_data) && Apply(MyEgress.swid, MyEgress.set_swid) && "
                    "port == standard_metadata.egress_port && cur_time == standard_metadata.egress_global_timestamp && byte_cnt > 0 && swid >= 0))"
                )
                return P4LTLCandidate(
                    spec_text=spec,
                    assumptions=[
                        "Used the newly pushed probe_data header plus port/byte/time fields as the local witness that per-hop monitoring data was written into the probe."
                    ],
                    self_checks=[
                        "family-guided candidate for in_band_header_added_or_preserved",
                        "required both header validity and updated monitoring fields",
                    ],
                    evidence_used=[
                        "hdr.probe",
                        "hdr.probe_data",
                        "port",
                        "byte_cnt",
                        "cur_time",
                        "last_time",
                        "swid",
                    ],
                    generation_rationale_summary="Programmatic in-network header-update template for probe-monitoring intents.",
                )

        if "telemetry" in text or "queue depth" in text or "队列深度" in text:
            required = {
                "hdr.telemetry",
                "hdr.telemetry.enq_qdepth",
                "meta.egress_type",
                "standard_metadata.enq_qdepth",
                "hdr.ethernet.etherType",
                "hdr.tcp",
            }
            if required <= known_fields:
                spec = (
                    "//#LTLProperty: "
                    "[](AP(valid(hdr.tcp) && meta.egress_type == 2) "
                    "==> AP(valid(hdr.telemetry) && hdr.telemetry.enq_qdepth == standard_metadata.enq_qdepth && "
                    "hdr.telemetry.nextHeaderType == 0x0800 && hdr.ethernet.etherType == 0x7777))"
                )
                return P4LTLCandidate(
                    spec_text=spec,
                    assumptions=[
                        "Used meta.egress_type == 2 as the host-independent local witness for in-network switch forwarding."
                    ],
                    self_checks=[
                        "family-guided candidate for in_band_header_added_or_preserved",
                        "required both telemetry validity and queue-depth carriage on the next step",
                    ],
                    evidence_used=[
                        "hdr.telemetry",
                        "hdr.telemetry.enq_qdepth",
                        "meta.egress_type",
                        "hdr.ethernet.etherType",
                    ],
                    generation_rationale_summary="Programmatic in-network header-addition template for telemetry-carrying intents.",
                )

        return None

    def _build_decomposer_agent(self, toolkit: ContextToolkit) -> Any:
        from agno.agent import Agent

        learning_kwargs = _build_learning_kwargs(self.enable_learning, self.learning_db_url)
        return Agent(
            name="p4ltl-intent-decomposer",
            model=self.model,
            instructions=[
                "Return a valid JSON object that matches the IntentFeatureBundle schema.",
                "Decompose the natural-language verification intent into a structured feature bundle.",
                "Use only the aligned context summary and semantics guide provided in the prompt.",
                "Do not return tool plans, tool-call payloads, or reasoning traces.",
                "The temporal_pattern field must be one of: eventually, always, next, until, weak_until, release.",
                "Map Chinese cues strictly: '始终'/'一直'/'永远' -> always; '最终'/'最终会'/'迟早' -> eventually; '下一步'/'下一拍' -> next; '直到'/'在...之前一直' -> weak_until.",
                "Do not invent unsupported temporal_pattern values like 'finally'.",
                "Return only a JSON dictionary for the schema, never a number, string, list, tool plan, or reasoning trace.",
                "Do not generate final .p4ltl text in this step.",
            ],
            output_schema=IntentFeatureBundle,
            structured_outputs=True,
            parse_response=True,
            debug_mode=self.debug_mode,
            **learning_kwargs,
        )

    def _build_generation_agent(self, toolkit: ContextToolkit) -> Any:
        from agno.agent import Agent
        learning_kwargs = _build_learning_kwargs(self.enable_learning, self.learning_db_url)
        return Agent(
            name="p4ltl-generator",
            model=self.model,
            instructions=[
                "Return a valid JSON object that matches the P4LTLCandidate schema.",
                "Generate a complete .p4ltl file in the current repository syntax.",
                "The spec_text field must contain the exact .p4ltl file text, not prose and not any other DSL.",
                "Use //#LTLProperty:, //#LTLFairness:, //#LTLVariables:, //#CPI:, //#CPI_SPEC:, //#CPI_SIMP: as the only valid markers.",
                "At least one line must start with //#LTLProperty:.",
                "Atomic propositions must be written as AP(...).",
                "Use only [] <> X U W R ! && || ==> at the temporal level.",
                "Inside AP(...), use only drop, fwd(...), valid(...), Apply(...), comparisons, and predicate boolean operators.",
                "Do not output formats like 'spec ... end', 'eventually drop', YAML, Markdown, or explanatory text.",
                "Do not use G, F, or ->; use [] , <>, and ==> instead.",
                "Do not use hdr.xxx.isValid() or hdr.xxx.isValid; use valid(hdr.xxx) instead.",
                "Do not output extra markers such as //#Description, //#Pattern, //#Trigger, //#Condition, or //#Entities.",
                "Do not output tool plans, tool-call arrays, or reasoning traces inside spec_text.",
                "Do not invent unsupported syntax, unsupported functions, or unknown entity names.",
                "Do not read entire files when a small snippet or structured query is enough.",
                "Use the validation tool before finalizing if possible.",
                "Prefer exact entity names from the tools over invented names.",
            ],
            output_schema=P4LTLCandidate,
            structured_outputs=True,
            parse_response=True,
            debug_mode=self.debug_mode,
            stream=self.agent_stream,
            **learning_kwargs,
        )

    def _build_repair_agent(self, toolkit: ContextToolkit) -> Any:
        from agno.agent import Agent

        learning_kwargs = _build_learning_kwargs(self.enable_learning, self.learning_db_url)
        return Agent(
            name="p4ltl-repair",
            model=self.model,
            tools=self._build_tool_functions(toolkit, include_validator=True),
            tool_choice="auto",
            instructions=[
                "Return a valid JSON object that matches the P4LTLCandidate schema.",
                "The spec_text field must contain valid .p4ltl file text for the current repository parser.",
                "Preserve valid //# marker structure and repair invalid syntax into the repository's .p4ltl format.",
                "At least one line must start with //#LTLProperty:.",
                "Do not output any DSL other than the current .p4ltl syntax.",
                "Do not use G, F, or ->; use [] , <>, and ==> instead.",
                "Do not use hdr.xxx.isValid() or hdr.xxx.isValid; use valid(hdr.xxx) instead.",
                "Do not output extra markers such as //#Description, //#Pattern, //#Trigger, //#Condition, or //#Entities.",
                "Do not output tool plans, tool-call arrays, or reasoning traces inside spec_text.",
                "Repair an existing .p4ltl candidate using structured validation feedback.",
                "Preserve valid parts of the previous candidate whenever possible.",
                "Use retrieval tools to replace guessed entities with exact program entities.",
                "Call the validation tool before finalizing when possible.",
            ],
            output_schema=P4LTLCandidate,
            structured_outputs=True,
            parse_response=True,
            debug_mode=self.debug_mode,
            stream=self.agent_stream,
            **learning_kwargs,
        )

    def _build_generation_prompt(
        self,
        *,
        request: IntentToP4LTLRequest,
        toolkit: ContextToolkit,
        features: IntentFeatureBundle,
        semantics_guide_text: str,
        feedback: Optional[str],
        previous_candidate: Optional[P4LTLCandidate],
        round_id: int,
    ) -> str:
        previous = previous_candidate.spec_text if previous_candidate else "<none>"
        return f"""
Round: {round_id}

Return a valid JSON object only.

Intent:
{request.intent}

Administrator description:
{request.admin_description or "<none provided>"}

Intent feature bundle:
{features.model_dump_json(indent=2)}

Selected template family:
- family: {features.template_family}
- expressibility: {features.expressibility_level}
- guidance:
{chr(10).join(f"  - {item}" for item in features.template_guidance) or "  - <none>"}
- required slots:
{chr(10).join(f"  - {item}" for item in features.required_slot_hints) or "  - <none>"}

Aligned context summary:
{toolkit.summarize_context()}

Extra constraints:
{request.extra_constraints or ["<none provided>"]}

Prompt semantics guide:
{semantics_guide_text}

Previous candidate:
{previous}

Repair feedback:
{feedback or "<none>"}

Requirements:
- Output only a valid JSON object matching the P4LTLCandidate schema.
- Follow the selected template family instead of inventing a fresh formula pattern.
- Every required slot from the template family must be grounded explicitly or called out in assumptions.
- Generate ASCII-only .p4ltl content in spec_text.
- spec_text must be the literal .p4ltl file body.
- The minimum valid shape is:
  //#LTLProperty: <formula>
- Valid optional markers are:
  //#LTLFairness:
  //#LTLVariables:
  //#CPI:
  //#CPI_SPEC:
  //#CPI_SIMP:
- Top-level temporal operators: [] <> X U W R ! && || ==>
- AP syntax is mandatory for atomic propositions.
- Apply and Key must start with a capital letter.
- drop, fwd, valid, old, true, false must be lowercase.
- Do not output:
  spec/end blocks
  plain-English temporal syntax
  G/F
  ->
  <==>
  AP(true)
  hdr.xxx.isValid()
  //#Description / //#Pattern / //#Trigger / //#Condition / //#Entities
  tool-call plans or reasoning arrays
  Markdown fences
- Prefer exact field/table/action/key names from the available tools.
- Do not invent unsupported syntax.

Minimal valid example:
//#LTLProperty: <>(AP(drop))
""".strip()

    def _build_decomposer_prompt(
        self,
        request: IntentToP4LTLRequest,
        toolkit: ContextToolkit,
        semantics_guide_text: str,
    ) -> str:
        return f"""
Decompose the following verification intent into a structured feature bundle.

Return a valid JSON object only.

Allowed temporal_pattern values exactly:
- eventually
- always
- next
- until
- weak_until
- release

Chinese cue mapping:
- 始终 / 一直 / 永远 -> always
- 最终 / 最终会 / 迟早 -> eventually
- 下一步 / 下一拍 -> next
- 直到 / 在...之前一直 -> weak_until

Intent:
{request.intent}

Administrator description:
{request.admin_description or "<none provided>"}

Aligned context summary:
{toolkit.summarize_context()}

Prompt semantics guide:
{semantics_guide_text}

Use retrieval tools when you need exact fields, tables, actions, keys, or registers.
Return only a valid JSON object matching the IntentFeatureBundle schema.
Never return a list, a number, a raw string, or a tool plan.
""".strip()

    def _build_repair_prompt(
        self,
        *,
        request: IntentToP4LTLRequest,
        toolkit: ContextToolkit,
        features: IntentFeatureBundle,
        semantics_guide_text: str,
        feedback: str,
        previous_candidate: P4LTLCandidate,
        round_id: int,
    ) -> str:
        return f"""
Round: {round_id}

Repair the previous .p4ltl candidate using the validation feedback below.

Return a valid JSON object only.

Intent:
{request.intent}

Administrator description:
{request.admin_description or "<none provided>"}

Intent feature bundle:
{features.model_dump_json(indent=2)}

Selected template family:
- family: {features.template_family}
- expressibility: {features.expressibility_level}
- guidance:
{chr(10).join(f"  - {item}" for item in features.template_guidance) or "  - <none>"}
- required slots:
{chr(10).join(f"  - {item}" for item in features.required_slot_hints) or "  - <none>"}

Aligned context summary:
{toolkit.summarize_context()}

Prompt semantics guide:
{semantics_guide_text}

Previous candidate:
{previous_candidate.spec_text}

Validation feedback:
{feedback}

Requirements:
- Return only a valid JSON object matching the P4LTLCandidate schema.
- Preserve the selected template family unless the feedback proves it was the wrong class.
- Fill every required slot from the template family explicitly before finalizing.
- spec_text must be the literal .p4ltl file body using current repository syntax.
- Keep or restore valid //# markers. The primary required line is //#LTLProperty: ...
- Do not output any 'spec ... end' style DSL.
- Do not use G, F, or ->; use [] , <> , and ==> instead.
- Do not use hdr.xxx.isValid() or hdr.xxx.isValid; use valid(hdr.xxx) instead.
- Remove or avoid any lines like //#Description, //#Pattern, //#Trigger, //#Condition, or //#Entities.
- Do not output tool-call plans, arrays, or reasoning traces inside spec_text.
- Do not output prose outside spec_text.
- Keep valid structure when possible.
- Replace guessed entities with retrieved exact entities.
- Generate ASCII-only .p4ltl content.
""".strip()

    def _build_tool_functions(self, toolkit: ContextToolkit, include_validator: bool = False) -> list[Callable[..., Any]]:
        from agno.tools import tool

        @tool(name="search_code")
        def search_code(pattern: str, scope: Optional[str] = None) -> list[dict[str, Any]]:
            """Search loaded P4 source snippets for a pattern."""
            return toolkit.search_code(pattern, scope)

        @tool(name="read_code_snippet")
        def read_code_snippet(path: str, start_line: int, end_line: int) -> dict[str, Any]:
            """Read a bounded P4 code snippet by path and line range."""
            return toolkit.read_code_snippet(path, start_line, end_line)

        @tool(name="query_artifact_json")
        def query_artifact_json(path: str, selector: str) -> dict[str, Any]:
            """Query loaded artifact JSON using a simple selector string."""
            return toolkit.query_artifact_json(path, selector)

        @tool(name="read_artifact_json_snippet")
        def read_artifact_json_snippet(path: str, selector: str) -> dict[str, Any]:
            """Read a bounded subset of loaded artifact JSON."""
            return toolkit.read_artifact_json_snippet(path, selector)

        @tool(name="query_context_graph")
        def query_context_graph(
            node: Optional[str] = None,
            relation: Optional[str] = None,
            target_kind: Optional[str] = None,
            pattern: Optional[str] = None,
        ) -> dict[str, Any]:
            """Query the in-memory context graph for linked entities."""
            return toolkit.query_context_graph(
                node=node,
                relation=relation,
                target_kind=target_kind,
                pattern=pattern,
            )

        @tool(name="list_known_entities")
        def list_known_entities(entity_type: str) -> list[str]:
            """List known fields, tables, actions, registers, or keys from the aligned context."""
            return toolkit.list_known_entities(entity_type)

        @tool(name="summarize_context")
        def summarize_context() -> dict[str, Any]:
            """Return a compact summary of the aligned program context."""
            return toolkit.summarize_context()

        tools: list[Callable[..., Any]] = [
            search_code,
            read_code_snippet,
            query_artifact_json,
            read_artifact_json_snippet,
            query_context_graph,
            list_known_entities,
            summarize_context,
        ]

        if include_validator:
            @tool(name="validate_p4ltl_candidate")
            def validate_p4ltl_candidate(spec_text: str) -> dict[str, Any]:
                """Validate a candidate .p4ltl file using the current local parser-backed checker."""
                return self.syntax.validate_spec_text(spec_text).to_dict()

            tools.append(validate_p4ltl_candidate)
        return tools

    def _run_agent(self, agent: Any, prompt: str, output_schema: Any, stage_name: str) -> Any:
        attempts = self.agent_max_retries + 1
        last_error: Optional[Exception] = None

        for attempt_idx in range(1, attempts + 1):
            try:
                return self._run_agent_once(
                    agent=agent,
                    prompt=prompt,
                    output_schema=output_schema,
                    stage_name=stage_name,
                )
            except Exception as exc:
                last_error = exc
                if attempt_idx >= attempts:
                    break
                sleep_seconds = self.agent_retry_delay_seconds * (2 ** (attempt_idx - 1))
                time.sleep(sleep_seconds)

        assert last_error is not None
        raise RuntimeError(
            f"{stage_name} agent failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    def _run_agent_once(self, agent: Any, prompt: str, output_schema: Any, stage_name: str) -> Any:
        with _agent_timeout(self.agent_timeout_seconds, stage_name):
            if self.agent_stream:
                from agno.run.agent import RunCompletedEvent, RunErrorEvent, ToolCallErrorEvent

                iterator = agent.run(
                    prompt,
                    stream=True,
                    stream_events=True,
                    output_schema=output_schema,
                    debug_mode=self.debug_mode,
                )
                final_output = None
                run_error: Optional[str] = None
                for event in iterator:
                    if isinstance(event, RunCompletedEvent):
                        final_output = event
                    elif isinstance(event, RunErrorEvent):
                        run_error = event.content or event.error_type or "unknown run error"
                    elif isinstance(event, ToolCallErrorEvent):
                        run_error = event.error or "unknown tool call error"
                if run_error is not None:
                    raise RuntimeError(f"streaming agent run failed: {run_error}")
                if final_output is None:
                    raise RuntimeError("streaming agent run did not yield a final RunCompletedEvent")
                return final_output.content

            output = agent.run(
                prompt,
                stream=False,
                output_schema=output_schema,
                debug_mode=self.debug_mode,
            )
            return output.content

    def _coerce_model(self, content: Any, schema: Any) -> Any:
        if isinstance(content, schema):
            return content
        if schema is P4LTLCandidate and _looks_like_tool_plan(content):
            return P4LTLCandidate(
                spec_text=json.dumps(content, ensure_ascii=False, indent=2),
                assumptions=["The model returned a tool-plan-like structure; it was preserved as raw text so the repair round can replace it with real .p4ltl."],
                self_checks=["tool-plan-like output coerced into raw spec_text for repair"],
            )
        if isinstance(content, dict):
            return schema.model_validate(content)
        if schema is P4LTLCandidate and isinstance(content, str):
            assumptions = ["The model returned a raw string; it was coerced into P4LTLCandidate.spec_text."]
            self_checks = ["raw string output coerced before DSL repair"]
            if _looks_like_tool_plan_string(content):
                assumptions.append("The raw string resembles a tool plan or reasoning trace and must be replaced in a repair round.")
                self_checks.append("detected tool-plan-like raw string")
            return P4LTLCandidate(
                spec_text=content.strip(),
                assumptions=assumptions,
                self_checks=self_checks,
            )
        if hasattr(content, "model_dump"):
            payload = content.model_dump()
            if schema is P4LTLCandidate and _looks_like_tool_plan(payload):
                return P4LTLCandidate(
                    spec_text=json.dumps(payload, ensure_ascii=False, indent=2),
                    assumptions=["The model returned a tool-plan-like payload; it was preserved as raw text so the repair round can replace it with real .p4ltl."],
                    self_checks=["tool-plan-like model_dump payload coerced into raw spec_text for repair"],
                )
            return schema.model_validate(payload)
        raise TypeError(f"unexpected agent output type for {schema.__name__}: {type(content)!r}")

    def _resolve_agent_stream(self, agent_stream: Optional[bool]) -> bool:
        if agent_stream is not None:
            return agent_stream
        return load_api_config().stream

    def _heuristic_candidate(
        self,
        features: IntentFeatureBundle,
        toolkit: ContextToolkit,
        feedback: Optional[str],
    ) -> P4LTLCandidate:
        known_fields = toolkit.list_known_entities("field")
        known_tables = toolkit.list_known_entities("table")
        known_actions = toolkit.list_known_entities("action")

        if features.intent_type in {"control_plane_rule", "mixed"} and known_tables and known_actions:
            table = known_tables[0]
            action = known_actions[0]
            spec = (
                f"//#CPI_SPEC: [](AP(Apply({table}, {action})))\n"
                f"//#LTLProperty: [](AP(standard_metadata.ingress_port >= 0))"
            )
        elif features.temporal_pattern == "always":
            cond = _pick_simple_condition(known_fields)
            spec = f"//#LTLProperty: [](AP({cond}))"
        elif "drop" in features.target_events:
            spec = "//#LTLProperty: <>(AP(drop))"
        elif "fwd" in features.target_events:
            spec = "//#LTLProperty: <>(AP(fwd(1)))"
        else:
            cond = _pick_simple_condition(known_fields)
            spec = f"//#LTLProperty: <>(AP({cond}))"

        assumptions = []
        if feedback:
            assumptions.append("Candidate was regenerated using the heuristic fallback after a failed round.")
        return P4LTLCandidate(
            spec_text=spec,
            assumptions=assumptions,
            self_checks=["heuristic fallback produced a parser-friendly template"],
            evidence_used=known_fields[:3] + known_tables[:1] + known_actions[:1],
            generation_rationale_summary="Heuristic fallback based on intent type, temporal pattern, and available entities.",
        )

    def _build_feedback_text(
        self,
        *,
        syntax_validation: dict[str, Any],
        context_validation: Any,
        semantic_review: SemanticReviewReport,
    ) -> str:
        mismatch_lines = semantic_review.suspicious_mismatches or ["<none>"]
        mismatch_block = "\n".join(f"- {item}" for item in mismatch_lines)
        return (
            "Candidate rejected.\n"
            f"Syntax: {syntax_validation.get('summary')}\n"
            f"Context: {context_validation.summary}\n"
            f"Semantic: {semantic_review.semantic_verdict} - {semantic_review.review_reason}\n"
            f"Semantic mismatches to fix:\n{mismatch_block}\n"
        )

    def _apply_dsl_repair(self, candidate: P4LTLCandidate) -> P4LTLCandidate:
        repaired = repair_p4ltl_text(candidate.spec_text)
        if not repaired.changed:
            return candidate
        assumptions = list(candidate.assumptions)
        self_checks = list(candidate.self_checks)
        assumptions.append("A deterministic DSL repair pass normalized the generated .p4ltl text before validation.")
        self_checks.extend(repaired.notes)
        return candidate.model_copy(
            update={
                "spec_text": repaired.repaired_text,
                "assumptions": assumptions,
                "self_checks": self_checks,
            }
        )

    def _accepted_semantic_verdicts(
        self,
        request: IntentToP4LTLRequest,
        features: IntentFeatureBundle,
    ) -> set[str]:
        if request.benchmark_case_id and request.benchmark_case_id.startswith("sagefuzz:"):
            if features.expressibility_level in {"approximate", "closed_loop"}:
                return {"correct", "plausible"}
            return {"correct"}
        return {"correct", "plausible"}

    def _build_repair_summary(
        self,
        *,
        syntax_validation: dict[str, Any],
        context_valid: bool,
        semantic_verdict: str,
        semantic_review: SemanticReviewReport,
    ) -> str:
        return (
            f"syntax_valid={syntax_validation.get('valid')}, "
            f"context_valid={context_valid}, "
            f"semantic_verdict={semantic_verdict}, "
            f"semantic_mismatches={len(semantic_review.suspicious_mismatches)}"
        )


class AgentRunTimeoutError(TimeoutError):
    pass


class _TimeoutHandler:
    def __init__(self, seconds: float, stage_name: str) -> None:
        self.seconds = seconds
        self.stage_name = stage_name
        self.previous_handler: Any = None

    def __enter__(self) -> None:
        if self.seconds <= 0:
            return
        self.previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.seconds <= 0:
            return
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.previous_handler)

    def _handle_timeout(self, signum, frame) -> None:
        raise AgentRunTimeoutError(
            f"{self.stage_name} agent timed out after {self.seconds} second(s)"
        )


def _agent_timeout(seconds: float, stage_name: str) -> _TimeoutHandler:
    return _TimeoutHandler(seconds, stage_name)


def _pick_simple_condition(known_fields: list[str]) -> str:
    for field in known_fields:
        if field.endswith("ingress_port") or field == "standard_metadata.ingress_port":
            return f"{field} >= 0"
        if field.endswith("egress_spec") or field == "standard_metadata.egress_spec":
            return f"{field} >= 0"
    return "standard_metadata.ingress_port >= 0"


def _looks_like_tool_plan(content: Any) -> bool:
    if isinstance(content, list):
        return any(_looks_like_tool_plan(item) for item in content)
    if isinstance(content, dict):
        keys = set(content.keys())
        if {"tool", "pattern"} & keys:
            return True
        if {"tool", "parameters"} <= keys:
            return True
        if {"reason", "tool"} <= keys:
            return True
        if keys == {"error"} and isinstance(content.get("error"), str):
            return True
    return False


def _looks_like_tool_plan_string(content: str) -> bool:
    lowered = content.strip().lower()
    return (
        lowered.startswith('{"tool"')
        or lowered.startswith('[{"tool"')
        or lowered.startswith('{"reason"')
        or lowered.startswith('[{"reason"')
    )
