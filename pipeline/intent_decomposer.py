from __future__ import annotations

from typing import Any, Optional

from ..context.context_tools import ContextToolkit
from .models import IntentFeatureBundle


class HeuristicIntentDecompiler:
    def decompose(
        self,
        intent: str,
        admin_description: str,
        toolkit: Optional[ContextToolkit] = None,
    ) -> IntentFeatureBundle:
        text = f"{intent}\n{admin_description}".lower()

        temporal_pattern = "eventually"
        if any(token in text for token in ["一直", "始终", "永远", "always", "globally"]):
            temporal_pattern = "always"
        elif any(token in text for token in ["下一步", "下一拍", "next"]):
            temporal_pattern = "next"
        elif any(token in text for token in ["直到", "until", "在", "之前一直"]):
            temporal_pattern = "weak_until"
        elif any(token in text for token in ["release"]):
            temporal_pattern = "release"

        intent_type = "packet_behavior"
        if any(token in text for token in ["table", "action", "规则", "control plane", "cpi"]):
            intent_type = "control_plane_rule"
        if any(token in text for token in ["mixed", "同时", "both"]):
            intent_type = "mixed"

        fairness_needed = any(token in text for token in ["fairness", "公平", "持续出现", "持续到来"])
        free_variables_needed = any(token in text for token in ["任意", "symbolic", "unknown", "变量"])

        target_events: list[str] = []
        if any(token in text for token in ["drop", "丢包"]):
            target_events.append("drop")
        if any(token in text for token in ["forward", "转发", "端口"]):
            target_events.append("fwd")
        if any(token in text for token in ["valid", "有效"]):
            target_events.append("valid")
        if any(token in text for token in ["apply", "action", "规则", "table"]):
            target_events.append("Apply")

        required_entities: list[str] = []
        if toolkit is not None:
            summary = toolkit.summarize_context()
            for entity in summary["known_fields"][:40]:
                if entity.lower() in text:
                    required_entities.append(entity)
            for entity in summary["known_tables"][:20]:
                if entity.lower() in text:
                    required_entities.append(entity)
            for entity in summary["known_actions"][:20]:
                if entity.lower() in text:
                    required_entities.append(entity)

        state_constraints: list[str] = []
        if "old" in text or "前态" in text:
            state_constraints.append("old-state comparison")

        control_plane_constraints: list[str] = []
        if intent_type in {"control_plane_rule", "mixed"}:
            control_plane_constraints.append("control-plane relation expected")

        assumptions = []
        if not required_entities:
            assumptions.append("No explicit program entity was recovered from the intent; generator may rely on generic standard_metadata entities.")

        return IntentFeatureBundle(
            intent_type=intent_type,
            temporal_pattern=temporal_pattern,
            trigger_conditions=[],
            target_events=target_events,
            state_constraints=state_constraints,
            fairness_needed=fairness_needed,
            free_variables_needed=free_variables_needed,
            control_plane_constraints=control_plane_constraints,
            required_entities=required_entities,
            assumptions=assumptions,
            decomposition_summary=(
                f"intent_type={intent_type}, temporal_pattern={temporal_pattern}, "
                f"targets={target_events or ['generic-condition']}"
            ),
        )


class DecomposerAgentAdapter:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def decompose(
        self,
        intent: str,
        admin_description: str,
        toolkit: ContextToolkit,
    ) -> IntentFeatureBundle:
        prompt = f"""
You are decomposing a natural-language verification intent into a structured feature bundle for a P4LTL generator.

Intent:
{intent}

Administrator description:
{admin_description or "<none provided>"}

Use the available context tools to recover the exact fields, tables, actions, keys, and registers when needed.
Return only the structured feature bundle.
""".strip()
        output = self.agent.run(prompt, output_schema=IntentFeatureBundle)
        if isinstance(output.content, IntentFeatureBundle):
            return output.content
        if isinstance(output.content, dict):
            return IntentFeatureBundle.model_validate(output.content)
        raise TypeError("unexpected decomposer output content")
