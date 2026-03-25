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

        fairness_needed = any(token in text for token in ["fairness", "公平", "持续出现", "持续到来", "反复", "无限次"])
        free_variables_needed = any(token in text for token in ["任意", "symbolic", "unknown", "变量"])

        target_events: list[str] = []
        if any(token in text for token in ["drop", "丢包", "阻断", "阻止"]):
            target_events.append("drop")
        if any(token in text for token in ["forward", "转发", "通过"]):
            target_events.append("fwd")
        if any(token in text for token in ["valid", "有效", "header", "头"]):
            target_events.append("valid")
        if any(token in text for token in ["apply", "action", "规则", "table"]):
            target_events.append("Apply")

        required_entities: list[str] = []
        if toolkit is not None:
            summary = toolkit.summarize_context()
            for entity in summary["known_fields"][:80]:
                if entity.lower() in text:
                    required_entities.append(entity)
            for entity in summary["known_tables"][:40]:
                if entity.lower() in text:
                    required_entities.append(entity)
            for entity in summary["known_actions"][:40]:
                if entity.lower() in text:
                    required_entities.append(entity)

        state_constraints: list[str] = []
        if any(token in text for token in ["old", "前态", "先", "已经"]):
            state_constraints.append("stateful relation expected")
        if any(token in text for token in ["threshold", "阈值", "计数", "linkstate", "backup", "primary"]):
            state_constraints.append("named state variable likely required")

        control_plane_constraints: list[str] = []
        if intent_type in {"control_plane_rule", "mixed"}:
            control_plane_constraints.append("control-plane relation expected")
        if any(token in text for token in ["通知", "notification", "rehash", "seed", "nhop"]):
            control_plane_constraints.append("action-selection evidence may be required")

        template_family, expressibility_level, template_guidance, required_slot_hints = _classify_template_family(
            text=text,
            temporal_pattern=temporal_pattern,
            fairness_needed=fairness_needed,
        )

        assumptions = []
        if not required_entities:
            assumptions.append(
                "No explicit program entity was recovered from the intent; generator must recover exact fields/tables from the aligned context summary."
            )
        if expressibility_level != "direct":
            assumptions.append(
                f"This intent is classified as {expressibility_level}; generation should prefer the closest sound local temporal proxy rather than an invented closed-loop proof."
            )

        return IntentFeatureBundle(
            intent_type=intent_type,
            temporal_pattern=temporal_pattern,
            template_family=template_family,
            expressibility_level=expressibility_level,
            template_guidance=template_guidance,
            required_slot_hints=required_slot_hints,
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
                f"template_family={template_family}, expressibility={expressibility_level}, "
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
{admin_description or '<none provided>'}

Use the available context tools to recover the exact fields, tables, actions, keys, and registers when needed.
Return only the structured feature bundle.
""".strip()
        output = self.agent.run(prompt, output_schema=IntentFeatureBundle)
        if isinstance(output.content, IntentFeatureBundle):
            return output.content
        if isinstance(output.content, dict):
            return IntentFeatureBundle.model_validate(output.content)
        raise TypeError("unexpected decomposer output content")


def _classify_template_family(
    *,
    text: str,
    temporal_pattern: str,
    fairness_needed: bool,
) -> tuple[str, str, list[str], list[str]]:
    if any(token in text for token in ["移除 telemetry", "去掉 telemetry", "remove telemetry", "恢复正常以太网", "ethernet type"]):
        return (
            "header_removed_before_exit",
            "direct",
            [
                "Use an always-style property tied to the host-facing exit condition.",
                "Require both telemetry removal and restoration of the normal Ethernet type when the packet leaves towards hosts.",
            ],
            ["host-facing exit condition", "telemetry header symbol", "EtherType field", "restored normal EtherType value"],
        )

    if any(token in text for token in ["failover", "备用", "backup", "lfa", "主下一跳故障", "链路故障"]):
        return (
            "state_selects_backup_action",
            "approximate",
            [
                "Use a failure-triggered property that selects the backup path on the next step or immediately.",
                "Prefer comparing the selected next-hop field against the exact backup next-hop entity instead of a generic forwarding action.",
            ],
            ["failure condition", "selected next-hop field", "backup next-hop entity"],
        )

    if any(token in text for token in ["主链路正常", "healthy", "primary path remains active", "继续使用主下一跳", "use primary"]):
        return (
            "state_selects_primary_action",
            "direct",
            [
                "Use an always-style implication from the healthy-state condition to the primary-path selection.",
                "Prefer exact next-hop equality or exact action selection over generic forwarding claims.",
            ],
            ["healthy-state condition", "selected next-hop field", "primary next-hop entity"],
        )

    if any(token in text for token in ["telemetry", "probe", "逐跳", "每跳", "per-hop", "queue depth", "利用率", "monitoring data"]):
        if any(token in text for token in ["deliver", "主机端", "host", "观测"]):
            return (
                "delivery_or_eventual_observability",
                "approximate",
                [
                    "Use an eventual-observation property instead of a local one-step invariant.",
                    "Do not reduce delivery to a weak proxy like hop count alone; include the carried monitoring field or telemetry validity at the observation point.",
                ],
                ["probe trigger", "observation-point condition", "carried monitoring field"],
            )
        return (
            "in_band_header_added_or_preserved",
            "approximate",
            [
                "Use an in-network trigger and assert telemetry or probe-header validity, or a monitored field change, while the packet is inside the network.",
                "Prefer the closest local proxy for hop-by-hop accumulation rather than inventing end-to-end claims that the current DSL cannot ground.",
            ],
            ["in-network condition", "telemetry/probe header symbol", "updated field witness"],
        )

    if any(token in text for token in ["reroute", "rehash", "迁移到其他路径", "notification", "update_flow_seed", "反馈通知"]):
        return (
            "eventual_control_reaction",
            "closed_loop",
            [
                "Use an always-trigger-implies-eventually-response structure.",
                "Prefer a concrete congestion-detected trigger and an explicit reroute action or seed-update action as the eventual reaction.",
            ],
            ["congestion trigger", "eventual reroute action or seed update", "optional old/new path witness"],
        )

    if any(token in text for token in ["allow", "允许", "通过", "正常转发", "return traffic", "not be dropped"]):
        return (
            "guarded_forward_or_not_drop",
            "stateful_local",
            [
                "Use an always-style implication from the trigger to !drop or an exact forwarding action.",
                "If the intent depends on prior state such as established connections, include the visible state-tracking condition explicitly.",
            ],
            ["trigger condition", "visible state-tracking condition if any", "forward or !drop consequence"],
        )

    if any(token in text for token in ["drop", "丢弃", "阻断", "block", "heavy hitter", "syn"]):
        return (
            "guarded_drop",
            "direct",
            [
                "Use an always-style implication from the exact trigger to drop or next-step drop.",
                "If the intent mentions a threshold, established state, or packet class, that condition must appear explicitly in the trigger.",
            ],
            ["trigger condition", "optional threshold or state condition", "drop timing (same-step or next-step)"],
        )

    if fairness_needed:
        return (
            "delivery_or_eventual_observability",
            "approximate",
            [
                "Use repeated eventuality only when the intent explicitly requires repeated observation or repeated hits.",
            ],
            ["goal observation condition"],
        )

    return (
        "generic_temporal_property",
        "direct",
        [
            "Choose the smallest repository-supported .p4ltl formula that matches the temporal pattern.",
            "Prefer exact local entities over generic standard_metadata placeholders whenever grounded entities are available.",
        ],
        ["trigger condition", "main consequence"],
    )
