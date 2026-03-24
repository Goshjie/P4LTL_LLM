from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .checker import (
    FormulaValidationResult,
    ValidationReport,
    validate_formula_text,
    validate_p4ltl_file,
    validate_p4ltl_text,
)


@dataclass
class AgentIssue:
    line: Optional[int]
    marker: Optional[str]
    message: str
    original: Optional[str] = None
    checked_formula: Optional[str] = None


@dataclass
class AgentValidationResponse:
    valid: bool
    summary: str
    errors: list[AgentIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized_formulas: list[dict] = field(default_factory=list)
    feedback_for_agent: str = ""
    raw_report: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "summary": self.summary,
            "errors": [asdict(item) for item in self.errors],
            "warnings": self.warnings,
            "normalized_formulas": self.normalized_formulas,
            "feedback_for_agent": self.feedback_for_agent,
            "raw_report": self.raw_report,
        }


class P4LTLAgentSyntaxInterface:
    """
    Stable Python-facing interface for agent frameworks.

    Typical use:
        checker = P4LTLAgentSyntaxInterface(strict=True)
        result = checker.validate_spec_text(candidate_text)
        if not result.valid:
            retry_prompt = result.feedback_for_agent
    """

    def __init__(
        self,
        checker_bin: Optional[str | Path] = None,
        strict: bool = False,
    ) -> None:
        self.checker_bin = Path(checker_bin) if checker_bin else None
        self.strict = strict

    def validate_formula(self, formula: str) -> AgentValidationResponse:
        ok, normalized, error = validate_formula_text(
            formula,
            checker_bin=self.checker_bin,
        )
        if ok:
            return AgentValidationResponse(
                valid=True,
                summary="formula passes the current P4LTL parser",
                normalized_formulas=[
                    {
                        "marker": None,
                        "line": None,
                        "original": formula,
                        "checked_formula": formula,
                        "normalized": normalized,
                    }
                ],
                feedback_for_agent=(
                    "The formula is already accepted by the current P4LTL parser."
                ),
                raw_report={
                    "ok": True,
                    "normalized": normalized,
                    "error": None,
                },
            )

        issue = AgentIssue(
            line=None,
            marker=None,
            message=error or "unknown parser error",
            original=formula,
            checked_formula=formula,
        )
        return AgentValidationResponse(
            valid=False,
            summary="formula does not pass the current P4LTL parser",
            errors=[issue],
            feedback_for_agent=self._build_formula_feedback(formula, issue.message),
            raw_report={
                "ok": False,
                "normalized": None,
                "error": issue.message,
            },
        )

    def validate_spec_text(self, text: str) -> AgentValidationResponse:
        report = validate_p4ltl_text(
            text,
            checker_bin=self.checker_bin,
            strict=self.strict,
        )
        return self._convert_report(report)

    def validate_spec_file(self, path: str | Path) -> AgentValidationResponse:
        report = validate_p4ltl_file(
            path,
            checker_bin=self.checker_bin,
            strict=self.strict,
        )
        return self._convert_report(report)

    def validate_candidates(self, candidates: list[str]) -> list[AgentValidationResponse]:
        return [self.validate_spec_text(candidate) for candidate in candidates]

    def first_valid_candidate(self, candidates: list[str]) -> Optional[AgentValidationResponse]:
        for candidate in candidates:
            result = self.validate_spec_text(candidate)
            if result.valid:
                return result
        return None

    def _convert_report(self, report: ValidationReport) -> AgentValidationResponse:
        issues = self._build_issues(report)
        normalized_formulas = self._normalized_formulas(report.formulas)
        summary = self._build_summary(report)
        feedback = self._build_spec_feedback(report, issues)
        return AgentValidationResponse(
            valid=report.ok,
            summary=summary,
            errors=issues,
            warnings=report.warnings,
            normalized_formulas=normalized_formulas,
            feedback_for_agent=feedback,
            raw_report=report.to_dict(),
        )

    def _build_issues(self, report: ValidationReport) -> list[AgentIssue]:
        issues: list[AgentIssue] = []
        formula_by_line = {formula.line: formula for formula in report.formulas}

        for error in report.errors:
            line = self._extract_line_number(error)
            formula = formula_by_line.get(line)
            marker = formula.marker if formula else None
            issues.append(
                AgentIssue(
                    line=line,
                    marker=marker,
                    message=error,
                    original=formula.original if formula else None,
                    checked_formula=formula.checked_formula if formula else None,
                )
            )
        return issues

    def _normalized_formulas(
        self,
        formulas: list[FormulaValidationResult],
    ) -> list[dict]:
        result: list[dict] = []
        for formula in formulas:
            if not formula.ok:
                continue
            result.append(
                {
                    "marker": formula.marker,
                    "line": formula.line,
                    "original": formula.original,
                    "checked_formula": formula.checked_formula,
                    "normalized": formula.normalized,
                }
            )
        return result

    def _build_summary(self, report: ValidationReport) -> str:
        if report.ok:
            return (
                f"spec passes validation: {len(report.formulas)} formula line(s) accepted"
            )
        return (
            f"spec fails validation: {len(report.errors)} error(s), "
            f"{len(report.warnings)} warning(s)"
        )

    def _build_formula_feedback(self, formula: str, error: str) -> str:
        return (
            "The candidate formula is rejected by the current P4LTL parser.\n"
            f"Formula:\n{formula}\n\n"
            f"Parser error:\n{error}\n\n"
            "Rewrite the formula so it uses the exact current syntax.\n"
            "Keep these constraints:\n"
            "- Use only [] <> X U W R ! && || ==> at the temporal level.\n"
            "- Atomic propositions must be wrapped as AP(...).\n"
            "- Inside AP(...), use only drop, fwd(...), valid(...), Apply(...), comparisons, and predicate boolean operators.\n"
            "- Do not use G/F, <==>, quantifiers, custom functions, or AP(true).\n"
        )

    def _build_spec_feedback(
        self,
        report: ValidationReport,
        issues: list[AgentIssue],
    ) -> str:
        if report.ok:
            normalized_lines = []
            for item in self._normalized_formulas(report.formulas):
                marker = item["marker"] or "<formula>"
                normalized = item["normalized"]
                normalized_lines.append(f"{marker} {normalized}")

            body = "\n".join(normalized_lines) if normalized_lines else "<none>"
            return (
                "The candidate .p4ltl text is accepted by the current checker.\n"
                "Accepted normalized formulas:\n"
                f"{body}\n"
            )

        lines = []
        for issue in issues:
            loc = f"line {issue.line}" if issue.line is not None else "global"
            marker = issue.marker or "<unknown>"
            lines.append(f"- {loc} {marker}: {issue.message}")
            if issue.original:
                lines.append(f"  original: {issue.original}")

        warning_block = ""
        if report.warnings:
            warning_block = "Warnings:\n" + "\n".join(f"- {item}" for item in report.warnings) + "\n\n"

        issue_block = "\n".join(lines) if lines else "- no structured issues extracted"
        return (
            "The candidate .p4ltl text is rejected by the current checker.\n\n"
            f"{warning_block}"
            "Fix the following problems and regenerate the full .p4ltl text:\n"
            f"{issue_block}\n\n"
            "Regeneration constraints:\n"
            "- Keep exactly one //#LTLProperty line unless you intentionally want guide-level warnings.\n"
            "- If free variables are used, declare them with //#LTLVariables using only bool, int, or bvN.\n"
            "- For //#CPI_SIMP, separate each condition and the final action with semicolons.\n"
            "- Only use the current parser-supported P4LTL syntax.\n"
            "- Reuse the user's field names instead of inventing new identifiers.\n"
        )

    def _extract_line_number(self, error: str) -> Optional[int]:
        prefix = "line "
        if not error.startswith(prefix):
            return None
        remain = error[len(prefix):]
        digits = []
        for ch in remain:
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if not digits:
            return None
        return int("".join(digits))
