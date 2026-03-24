from __future__ import annotations

import re
from dataclasses import dataclass, field


TEMPORAL_AP_RE = re.compile(r"(\[\]|<>|X)\s+AP\(")
VALID_SUFFIX_RE = re.compile(r"AP\(\s*([A-Za-z_][A-Za-z0-9_.]*)\.isValid\s*\)")
VALID_CALL_RE = re.compile(r"([!]?)([A-Za-z_][A-Za-z0-9_.]*)\.isValid\(\)")
TEMPORAL_ALIAS_REPLACEMENTS = {
    "G (": "[](",
    "G(": "[](",
    "F (": "<>(",
    "F(": "<>(",
}
UNSUPPORTED_MARKER_PREFIXES = (
    "//#Description:",
    "//#Pattern:",
    "//#Trigger:",
    "//#Condition:",
    "//#Entities:",
)
FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\n|\n```$", re.MULTILINE)
NEGATED_BARE_FIELD_AP_RE = re.compile(r"AP\(\s*!((?:hdr|meta|standard_metadata)\.[A-Za-z_][A-Za-z0-9_.]*)\s*\)")
BARE_FIELD_AP_RE = re.compile(r"AP\(\s*((?:hdr|meta|standard_metadata)\.[A-Za-z_][A-Za-z0-9_.]*)\s*\)")


@dataclass
class DSLRepairResult:
    repaired_text: str
    changed: bool
    notes: list[str] = field(default_factory=list)


def repair_p4ltl_text(raw_text: str) -> DSLRepairResult:
    text = raw_text.strip()
    notes: list[str] = []

    original = text
    text = FENCE_RE.sub("", text).strip()
    if text != original:
        notes.append("removed markdown fences")

    repaired = text

    before = repaired
    repaired = repaired.replace("[] (", "[](")
    repaired = repaired.replace("<> (", "<>(")
    repaired = repaired.replace("X (", "X(")
    if repaired != before:
        notes.append("collapsed spaces between temporal operators and parentheses")

    before = repaired
    for src, dst in TEMPORAL_ALIAS_REPLACEMENTS.items():
        repaired = repaired.replace(src, dst)
    repaired = repaired.replace(" -> ", " ==> ")
    if repaired != before:
        notes.append("rewrote temporal aliases and implication syntax")

    before = repaired
    repaired = TEMPORAL_AP_RE.sub(r"\1(AP(", repaired)
    if repaired != before:
        notes.append("wrapped temporal operator operands with parentheses")

    before = repaired
    repaired = VALID_SUFFIX_RE.sub(r"AP(valid(\1))", repaired)
    repaired = VALID_CALL_RE.sub(lambda m: f"{m.group(1)}valid({m.group(2)})", repaired)
    if repaired != before:
        notes.append("rewrote .isValid suffix to valid(...) predicate")

    before = repaired
    repaired = NEGATED_BARE_FIELD_AP_RE.sub(r"AP(\1 == 0)", repaired)
    repaired = BARE_FIELD_AP_RE.sub(r"AP(\1 != 0)", repaired)
    if repaired != before:
        notes.append("rewrote bare field predicates into explicit comparisons")

    if not _has_known_marker(repaired):
        if _looks_like_formula(repaired):
            repaired = f"//#LTLProperty: {repaired}"
            notes.append("inserted missing //#LTLProperty marker")

    before = repaired
    repaired_lines = []
    for line in repaired.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(prefix) for prefix in UNSUPPORTED_MARKER_PREFIXES):
            continue
        repaired_lines.append(line)
    repaired = "\n".join(repaired_lines)
    if repaired != before:
        notes.append("removed unsupported //# metadata lines")

    repaired = _balance_marker_lines(repaired, notes)
    return DSLRepairResult(
        repaired_text=repaired,
        changed=repaired != original,
        notes=notes,
    )


def _has_known_marker(text: str) -> bool:
    return any(
        line.strip().startswith("//#")
        for line in text.splitlines()
    )


def _looks_like_formula(text: str) -> bool:
    tokens = ["AP(", "[]", "<>", "X(", " U ", " W ", " R ", "drop", "fwd(", "Apply(", "valid("]
    return any(token in text for token in tokens)


def _balance_marker_lines(text: str, notes: list[str]) -> str:
    lines = text.splitlines()
    repaired_lines: list[str] = []
    changed = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("//#"):
            balanced = _balance_parentheses(stripped)
            if balanced != stripped:
                changed = True
            repaired_lines.append(balanced)
        else:
            repaired_lines.append(line)

    if changed:
        notes.append("balanced parentheses on //# marker lines")
    return "\n".join(repaired_lines)


def _balance_parentheses(text: str) -> str:
    balance = 0
    for ch in text:
        if ch == "(":
            balance += 1
        elif ch == ")":
            balance -= 1
    if balance > 0:
        return text + (")" * balance)
    return text
