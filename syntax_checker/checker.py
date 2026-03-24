#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


MARKER_VARIABLES = "//#LTLVariables:"
MARKER_PROPERTY = "//#LTLProperty:"
MARKER_FAIRNESS = "//#LTLFairness:"
MARKER_CPI = "//#CPI:"
MARKER_CPI_SPEC = "//#CPI_SPEC:"
MARKER_CPI_SIMP = "//#CPI_SIMP:"
MARKER_CPI_MODEL = "//#CPI_MODEL:"
MARKER_REGISTER_WRITE = "//#register_write"

KNOWN_MARKERS = [
    MARKER_VARIABLES,
    MARKER_PROPERTY,
    MARKER_FAIRNESS,
    MARKER_CPI,
    MARKER_CPI_MODEL,
    MARKER_CPI_SPEC,
    MARKER_CPI_SIMP,
    MARKER_REGISTER_WRITE,
]

IDENTIFIER_RE = re.compile(r"[_a-zA-Z~][a-zA-Z0-9_~#\.]*$")
BV_TYPE_RE = re.compile(r"bv[0-9]+$")


@dataclass
class FormulaValidationResult:
    marker: str
    line: int
    original: str
    checked_formula: str
    ok: bool
    normalized: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    formulas: list[FormulaValidationResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "formulas": [asdict(item) for item in self.formulas],
        }


def _module_dir() -> Path:
    return Path(__file__).resolve().parent


def _build_script() -> Path:
    return _module_dir() / "build_checker.sh"


def _default_checker_bin() -> Path:
    return _module_dir() / "bin" / "p4ltl_formula_checker"


def _ensure_checker_binary(checker_bin: Optional[Path] = None) -> Path:
    binary = checker_bin or _default_checker_bin()
    if binary.exists():
        return binary

    subprocess.run([str(_build_script())], check=True)
    if not binary.exists():
        raise FileNotFoundError(f"checker binary was not created: {binary}")
    return binary


def _strip_spaces(value: str) -> str:
    return "".join(value.split())


def _validate_variables_decl(body: str) -> list[str]:
    errors: list[str] = []
    compact = _strip_spaces(body)
    if not compact:
        return ["empty //#LTLVariables declaration"]

    for item in compact.split(","):
        if not item:
            errors.append("empty variable item in //#LTLVariables")
            continue

        if ":" not in item:
            errors.append(f'free variable must use "name:type": {item}')
            continue

        name, var_type = item.split(":", 1)
        if not IDENTIFIER_RE.fullmatch(name):
            errors.append(f"invalid variable name in //#LTLVariables: {name}")

        if var_type not in {"bool", "int"} and not BV_TYPE_RE.fullmatch(var_type):
            errors.append(
                f'unsupported variable type "{var_type}" in //#LTLVariables '
                '(current implementation accepts bool, int, bvN)'
            )
    return errors


def _expand_cpi_simp(body: str) -> tuple[Optional[str], Optional[str]]:
    parts = [part.strip() for part in body.split(";")]
    if len(parts) < 2:
        return None, "//#CPI_SIMP requires at least one condition and one action"

    if any(not part for part in parts):
        return None, "//#CPI_SIMP contains an empty condition or action"

    action = parts[-1]
    constraints = parts[:-1]
    left = "true == true"
    for constraint in constraints:
        left += f" && {constraint}"
    return f"[](AP(({left}) ==> {action}))", None


def validate_formula_text(
    formula: str,
    checker_bin: Optional[Path] = None,
) -> tuple[bool, Optional[str], Optional[str]]:
    binary = _ensure_checker_binary(checker_bin)
    proc = subprocess.run(
        [str(binary), "--stdin"],
        input=formula,
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        return True, proc.stdout.strip(), None

    error = proc.stderr.strip() or proc.stdout.strip() or "unknown parser error"
    return False, None, error


def validate_p4ltl_text(
    text: str,
    checker_bin: Optional[Path] = None,
    strict: bool = False,
) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    formulas: list[FormulaValidationResult] = []

    property_lines = 0
    fairness_lines = 0

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue

        marker = next((item for item in KNOWN_MARKERS if stripped.startswith(item)), None)
        if marker is None:
            if stripped.startswith("//#"):
                errors.append(f"line {line_no}: unknown marker: {stripped}")
            continue

        body = stripped[len(marker):].strip()

        if marker == MARKER_PROPERTY:
            property_lines += 1
        elif marker == MARKER_FAIRNESS:
            fairness_lines += 1

        if marker == MARKER_VARIABLES:
            for error in _validate_variables_decl(body):
                errors.append(f"line {line_no}: {error}")
            continue

        if marker == MARKER_REGISTER_WRITE:
            continue

        checked_formula = body
        if marker == MARKER_CPI_SIMP:
            expanded, error = _expand_cpi_simp(body)
            if error is not None:
                formulas.append(
                    FormulaValidationResult(
                        marker=marker,
                        line=line_no,
                        original=body,
                        checked_formula=body,
                        ok=False,
                        error=error,
                    )
                )
                errors.append(f"line {line_no}: {error}")
                continue
            checked_formula = expanded

        ok, normalized, error = validate_formula_text(checked_formula, checker_bin=checker_bin)
        formulas.append(
            FormulaValidationResult(
                marker=marker,
                line=line_no,
                original=body,
                checked_formula=checked_formula,
                ok=ok,
                normalized=normalized,
                error=error,
            )
        )
        if not ok and error is not None:
            errors.append(f"line {line_no}: {error}")

    if property_lines == 0:
        errors.append("missing required //#LTLProperty line")
    elif property_lines > 1:
        message = "multiple //#LTLProperty lines found; current guide expects exactly one"
        if strict:
            errors.append(message)
        else:
            warnings.append(message)

    if fairness_lines > 1:
        message = "multiple //#LTLFairness lines found; current guide recommends at most one"
        if strict:
            errors.append(message)
        else:
            warnings.append(message)

    return ValidationReport(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        formulas=formulas,
    )


def validate_p4ltl_file(
    path: str | Path,
    checker_bin: Optional[Path] = None,
    strict: bool = False,
) -> ValidationReport:
    file_path = Path(path)
    return validate_p4ltl_text(
        file_path.read_text(encoding="utf-8"),
        checker_bin=checker_bin,
        strict=strict,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate whether a .p4ltl spec can pass the current P4LTL parser."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="Path to a .p4ltl file")
    group.add_argument("--stdin", action="store_true", help="Read a .p4ltl file body from stdin")
    group.add_argument("--formula", help="Validate a single raw formula")
    parser.add_argument(
        "--checker-bin",
        help="Path to a prebuilt p4ltl_formula_checker binary",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat guide-level structural issues as errors",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    checker_bin = Path(args.checker_bin) if args.checker_bin else None

    if args.formula is not None:
        ok, normalized, error = validate_formula_text(args.formula, checker_bin=checker_bin)
        payload = {
            "ok": ok,
            "normalized": normalized,
            "error": error,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=True, indent=2))
        else:
            if ok:
                print(f"OK: {normalized}")
            else:
                print(f"ERROR: {error}")
        return 0 if ok else 1

    if args.stdin:
        import sys

        text = sys.stdin.read()
    else:
        text = Path(args.file).read_text(encoding="utf-8")

    report = validate_p4ltl_text(text, checker_bin=checker_bin, strict=args.strict)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=True, indent=2))
    else:
        print("OK" if report.ok else "ERROR")
        for item in report.errors:
            print(f"- {item}")
        for item in report.warnings:
            print(f"- warning: {item}")
        for formula in report.formulas:
            status = "OK" if formula.ok else "ERROR"
            print(
                f"- [{status}] line {formula.line} {formula.marker} "
                f"{formula.normalized or formula.error}"
            )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
