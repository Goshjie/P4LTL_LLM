from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Optional


def _bootstrap_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_bootstrap_import_path()

try:
    from .benchmark_specs import load_default_benchmark_cases
    from ..context.context_store import load_context
    from ..context.context_validator import validate_context_alignment
    from ..pipeline.intent_decomposer import HeuristicIntentDecompiler
    from ..pipeline.models import (
        BenchmarkCase,
        BenchmarkRunRecord,
        BenchmarkSuiteResult,
        IntentToP4LTLRequest,
    )
    from ..pipeline.pipeline_protocol import DEFAULT_GUIDE_PATH, IntentToP4LTLPipeline
    from ..pipeline.semantic_reviewer import review_semantics
    from ..syntax_checker import P4LTLAgentSyntaxInterface
except ImportError:
    from P4LTL_LLM.benchmarks.benchmark_specs import load_default_benchmark_cases
    from P4LTL_LLM.context.context_store import load_context
    from P4LTL_LLM.context.context_validator import validate_context_alignment
    from P4LTL_LLM.pipeline.intent_decomposer import HeuristicIntentDecompiler
    from P4LTL_LLM.pipeline.models import (
        BenchmarkCase,
        BenchmarkRunRecord,
        BenchmarkSuiteResult,
        IntentToP4LTLRequest,
    )
    from P4LTL_LLM.pipeline.pipeline_protocol import DEFAULT_GUIDE_PATH, IntentToP4LTLPipeline
    from P4LTL_LLM.pipeline.semantic_reviewer import review_semantics
    from P4LTL_LLM.syntax_checker import P4LTLAgentSyntaxInterface


class BenchmarkRunner:
    def __init__(self, *, strict_validation: bool = True) -> None:
        self.syntax = P4LTLAgentSyntaxInterface(strict=strict_validation)
        self.heuristic = HeuristicIntentDecompiler()

    def load_cases(self) -> list[BenchmarkCase]:
        return load_default_benchmark_cases()

    def validate_reference_cases(
        self,
        cases: Optional[Iterable[BenchmarkCase]] = None,
    ) -> BenchmarkSuiteResult:
        records: list[BenchmarkRunRecord] = []
        selected = list(cases) if cases is not None else self.load_cases()
        for case in selected:
            specs = self._reference_specs(case)
            for spec_text in specs:
                request = IntentToP4LTLRequest(
                    intent=case.intent,
                    admin_description=case.admin_description,
                    p4_program_paths=case.p4_program_paths,
                    artifact_paths=case.artifact_paths + case.control_plane_paths,
                    control_plane_surface="\n".join(case.control_plane_paths),
                    extra_constraints=case.extra_constraints,
                    guide_path=str(DEFAULT_GUIDE_PATH),
                    benchmark_case_id=case.case_id,
                )
                context = load_context(request)
                features = self.heuristic.decompose(case.intent, case.admin_description, None)
                syntax = self.syntax.validate_spec_text(spec_text)
                context_report = validate_context_alignment(spec_text, context)
                semantic = review_semantics(
                    case.intent,
                    features,
                    spec_text,
                    context_report,
                    aligned_context_summary=context.summary(),
                )
                notes = []
                if case.gold_spec_paths:
                    notes.append(f"gold_refs={len(case.gold_spec_paths)}")
                records.append(
                    BenchmarkRunRecord(
                        case=case,
                        reference_spec_text=spec_text,
                        syntax_valid=syntax.valid,
                        context_valid=context_report.valid,
                        semantic_verdict=semantic.semantic_verdict,
                        notes=notes + semantic.suspicious_mismatches,
                    )
                )
        return self._summarize(records)

    def run_pipeline(
        self,
        pipeline: IntentToP4LTLPipeline,
        cases: Optional[Iterable[BenchmarkCase]] = None,
    ) -> BenchmarkSuiteResult:
        records: list[BenchmarkRunRecord] = []
        selected = list(cases) if cases is not None else self.load_cases()
        for case in selected:
            request = IntentToP4LTLRequest(
                intent=case.intent,
                admin_description=case.admin_description,
                p4_program_paths=case.p4_program_paths,
                artifact_paths=case.artifact_paths + case.control_plane_paths,
                control_plane_surface="\n".join(case.control_plane_paths),
                extra_constraints=case.extra_constraints,
                guide_path=str(DEFAULT_GUIDE_PATH),
                benchmark_case_id=case.case_id,
            )
            result = pipeline.generate_and_validate(request)
            semantic_verdict = result.final_validation.get("semantic", {}).get("semantic_verdict", "incorrect")
            syntax_valid = result.final_validation.get("syntax", {}).get("valid", False)
            context_valid = result.final_validation.get("context", {}).get("valid", False)
            notes = []
            if not result.ok:
                notes.append(result.final_feedback_for_agent)
            records.append(
                BenchmarkRunRecord(
                    case=case,
                    reference_spec_text=result.final_spec_text or "",
                    syntax_valid=syntax_valid,
                    context_valid=context_valid,
                    semantic_verdict=semantic_verdict,
                    notes=notes,
                )
            )
        return self._summarize(records)

    def _reference_specs(self, case: BenchmarkCase) -> list[str]:
        specs = list(case.reference_spec_texts)
        for path in case.gold_spec_paths:
            specs.append(Path(path).read_text(encoding="utf-8"))
        return specs

    def _summarize(self, records: list[BenchmarkRunRecord]) -> BenchmarkSuiteResult:
        syntax_pass = sum(1 for record in records if record.syntax_valid)
        context_pass = sum(1 for record in records if record.context_valid)
        semantic_pass = sum(1 for record in records if record.semantic_verdict in {"correct", "plausible"})
        accepted = sum(
            1
            for record in records
            if record.syntax_valid and record.context_valid and record.semantic_verdict in {"correct", "plausible"}
        )
        return BenchmarkSuiteResult(
            total_cases=len(records),
            syntax_pass=syntax_pass,
            context_pass=context_pass,
            semantic_pass=semantic_pass,
            accepted=accepted,
            records=records,
        )


def main() -> None:
    runner = BenchmarkRunner()
    result = runner.validate_reference_cases()
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
