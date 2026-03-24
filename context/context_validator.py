from __future__ import annotations

import re

from .context_store import LoadedContext
from ..pipeline.models import ContextValidationIssue, ContextValidationReport


FIELD_REF_RE = re.compile(
    r"\b(?:hdr|meta|standard_metadata)\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)
APPLY_RE = re.compile(r"Apply\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(?:,\s*([A-Za-z_][A-Za-z0-9_.]*))?\s*\)")
KEY_RE = re.compile(r"Key\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*,\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)")
ARRAY_BASE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\[")

BUILTIN_REGISTER_LIKE = {
    "hdr",
    "meta",
    "standard_metadata",
    "old",
    "drop",
    "fwd",
    "valid",
    "Apply",
    "Key",
    "AP",
    "true",
    "false",
}


def validate_context_alignment(spec_text: str, context: LoadedContext) -> ContextValidationReport:
    fields = sorted(set(FIELD_REF_RE.findall(spec_text)))
    tables: set[str] = set()
    actions: set[str] = set()
    keys: set[str] = set()
    registers: set[str] = set()

    errors: list[ContextValidationIssue] = []
    warnings: list[ContextValidationIssue] = []

    for table, action in APPLY_RE.findall(spec_text):
        tables.add(table)
        if action:
            actions.add(action)

    for table, key in KEY_RE.findall(spec_text):
        tables.add(table)
        keys.add(key)

    for base in ARRAY_BASE_RE.findall(spec_text):
        if base not in BUILTIN_REGISTER_LIKE and "." not in base:
            registers.add(base)

    for field in fields:
        if field not in context.known_fields:
            errors.append(
                ContextValidationIssue(
                    severity="error",
                    message=f"unknown field reference: {field}",
                    entity_type="field",
                    entity_value=field,
                )
            )

    for table in sorted(tables):
        if not _is_known_with_suffix(table, context.known_tables):
            errors.append(
                ContextValidationIssue(
                    severity="error",
                    message=f"unknown table reference: {table}",
                    entity_type="table",
                    entity_value=table,
                )
            )

    for action in sorted(actions):
        if not _is_known_with_suffix(action, context.known_actions):
            errors.append(
                ContextValidationIssue(
                    severity="error",
                    message=f"unknown action reference: {action}",
                    entity_type="action",
                    entity_value=action,
                )
            )

    for key in sorted(keys):
        if key not in context.known_keys and key not in context.known_fields:
            warnings.append(
                ContextValidationIssue(
                    severity="warning",
                    message=f"unresolved key expression: {key}",
                    entity_type="key",
                    entity_value=key,
                )
            )

    for register in sorted(registers):
        if register not in context.known_registers:
            warnings.append(
                ContextValidationIssue(
                    severity="warning",
                    message=f"unresolved array/register reference: {register}",
                    entity_type="register",
                    entity_value=register,
                )
            )

    valid = not errors
    summary = "context alignment passed" if valid else f"context alignment failed with {len(errors)} error(s)"
    return ContextValidationReport(
        valid=valid,
        summary=summary,
        errors=errors,
        warnings=warnings,
        referenced_fields=fields,
        referenced_tables=sorted(tables),
        referenced_actions=sorted(actions),
        referenced_registers=sorted(registers),
        referenced_keys=sorted(keys),
    )


def _is_known_with_suffix(name: str, known_values: set[str]) -> bool:
    if name in known_values:
        return True
    base = re.sub(r"_[0-9]+$", "", name)
    return base in known_values
