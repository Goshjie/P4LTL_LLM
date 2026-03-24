from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ContextDocument(BaseModel):
    path: str
    kind: str
    content: str = ""
    parsed_json: Optional[Any] = None


class AlignedContextSummary(BaseModel):
    program_paths: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    control_plane_paths: list[str] = Field(default_factory=list)
    known_fields: list[str] = Field(default_factory=list)
    known_tables: list[str] = Field(default_factory=list)
    known_actions: list[str] = Field(default_factory=list)
    known_registers: list[str] = Field(default_factory=list)
    known_keys: list[str] = Field(default_factory=list)
    candidate_program_regions: list[str] = Field(default_factory=list)
    artifact_evidence: list[str] = Field(default_factory=list)
    uncertain_entities: list[str] = Field(default_factory=list)


class CodeSearchHit(BaseModel):
    path: str
    line_no: int
    line: str


class ArtifactQueryResult(BaseModel):
    path: str
    selector: str
    matches: list[Any] = Field(default_factory=list)


class GraphQueryResult(BaseModel):
    node: Optional[str] = None
    relation: Optional[str] = None
    matches: list[dict[str, Any]] = Field(default_factory=list)


class IntentFeatureBundle(BaseModel):
    intent_type: str = "packet_behavior"
    temporal_pattern: str = "eventually"
    trigger_conditions: list[str] = Field(default_factory=list)
    target_events: list[str] = Field(default_factory=list)
    state_constraints: list[str] = Field(default_factory=list)
    fairness_needed: bool = False
    free_variables_needed: bool = False
    control_plane_constraints: list[str] = Field(default_factory=list)
    required_entities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    decomposition_summary: str = ""


class P4LTLCandidate(BaseModel):
    spec_text: str = Field(
        description="Complete .p4ltl file text only, including //# markers."
    )
    assumptions: list[str] = Field(default_factory=list)
    self_checks: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    generation_rationale_summary: str = ""


class ContextValidationIssue(BaseModel):
    severity: str
    message: str
    entity_type: Optional[str] = None
    entity_value: Optional[str] = None


class ContextValidationReport(BaseModel):
    valid: bool
    summary: str
    errors: list[ContextValidationIssue] = Field(default_factory=list)
    warnings: list[ContextValidationIssue] = Field(default_factory=list)
    referenced_fields: list[str] = Field(default_factory=list)
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_actions: list[str] = Field(default_factory=list)
    referenced_registers: list[str] = Field(default_factory=list)
    referenced_keys: list[str] = Field(default_factory=list)


class SemanticReviewReport(BaseModel):
    semantic_verdict: str
    intent_coverage: list[str] = Field(default_factory=list)
    context_support: list[str] = Field(default_factory=list)
    suspicious_mismatches: list[str] = Field(default_factory=list)
    review_reason: str = ""


class IntentToP4LTLRequest(BaseModel):
    intent: str
    admin_description: str = ""
    p4_program_paths: list[str] = Field(default_factory=list)
    p4_program_texts: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    artifact_summaries: list[str] = Field(default_factory=list)
    control_plane_surface: str = ""
    extra_constraints: list[str] = Field(default_factory=list)
    guide_path: str
    benchmark_case_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    max_rounds: int = Field(default=3, ge=1, le=10)


class AttemptRecord(BaseModel):
    round_id: int
    candidate: P4LTLCandidate
    syntax_validation: dict[str, Any]
    context_validation: ContextValidationReport
    semantic_review: SemanticReviewReport
    repair_input_summary: str = ""


class IntentToP4LTLResult(BaseModel):
    ok: bool
    final_spec_text: Optional[str] = None
    aligned_context_summary: AlignedContextSummary
    intent_features: IntentFeatureBundle
    attempts: list[AttemptRecord] = Field(default_factory=list)
    final_validation: dict[str, Any] = Field(default_factory=dict)
    final_feedback_for_agent: str = ""


class BenchmarkCase(BaseModel):
    case_id: str
    suite: str
    intent: str
    admin_description: str = ""
    root_dir: str
    p4_program_paths: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    control_plane_paths: list[str] = Field(default_factory=list)
    gold_spec_paths: list[str] = Field(default_factory=list)
    reference_spec_texts: list[str] = Field(default_factory=list)
    extra_constraints: list[str] = Field(default_factory=list)


class BenchmarkRunRecord(BaseModel):
    case: BenchmarkCase
    reference_spec_text: str
    syntax_valid: bool
    context_valid: bool
    semantic_verdict: str
    notes: list[str] = Field(default_factory=list)


class BenchmarkSuiteResult(BaseModel):
    total_cases: int
    syntax_pass: int
    context_pass: int
    semantic_pass: int
    accepted: int
    records: list[BenchmarkRunRecord] = Field(default_factory=list)
