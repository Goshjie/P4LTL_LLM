from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .context_graph import SimpleContextGraph
from ..pipeline.models import AlignedContextSummary, ContextDocument, IntentToP4LTLRequest


FIELD_REF_RE = re.compile(
    r"\b(?:hdr|meta|standard_metadata)\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)
TABLE_RE = re.compile(r"\btable\s+([A-Za-z_][A-Za-z0-9_]*)")
ACTION_RE = re.compile(r"\baction\s+([A-Za-z_][A-Za-z0-9_]*)")
REGISTER_RE = re.compile(r"\bregister(?:<[^>]+>)?\s*\([^)]*\)\s*([A-Za-z_][A-Za-z0-9_]*)")
KEY_BLOCK_RE = re.compile(r"\bkey\s*=\s*\{(?P<body>.*?)\}", re.DOTALL)
KEY_FIELD_RE = re.compile(
    r"((?:hdr|meta|standard_metadata)\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*:"
)
P4INFO_TABLE_RE = re.compile(r'name:\s+"([^"]+)"')
RUNTIME_TABLE_RE = re.compile(r'"table"\s*:\s*"([^"]+)"')
RUNTIME_ACTION_RE = re.compile(r'"action_name"\s*:\s*"([^"]+)"')


@dataclass
class LoadedContext:
    guide_path: str
    guide_text: str
    documents: list[ContextDocument] = field(default_factory=list)
    control_plane_surface: str = ""
    artifact_summaries: list[str] = field(default_factory=list)
    known_fields: set[str] = field(default_factory=set)
    known_tables: set[str] = field(default_factory=set)
    known_actions: set[str] = field(default_factory=set)
    known_registers: set[str] = field(default_factory=set)
    known_keys: set[str] = field(default_factory=set)
    graph: SimpleContextGraph = field(default_factory=SimpleContextGraph)

    def summary(self) -> AlignedContextSummary:
        return AlignedContextSummary(
            program_paths=[doc.path for doc in self.documents if doc.kind == "p4"],
            artifact_paths=[doc.path for doc in self.documents if doc.kind == "artifact_json"],
            control_plane_paths=[
                doc.path for doc in self.documents if doc.kind in {"runtime_json", "p4info"}
            ],
            known_fields=sorted(self.known_fields),
            known_tables=sorted(self.known_tables),
            known_actions=sorted(self.known_actions),
            known_registers=sorted(self.known_registers),
            known_keys=sorted(self.known_keys),
            candidate_program_regions=self._candidate_regions(),
            artifact_evidence=self._artifact_evidence(),
            uncertain_entities=[],
        )

    def _candidate_regions(self) -> list[str]:
        ranked = []
        for doc in self.documents:
            if doc.kind in {"p4", "runtime_json", "artifact_json", "p4info"}:
                ranked.append(doc.path)
        return ranked[:20]

    def _artifact_evidence(self) -> list[str]:
        evidence: list[str] = []
        for doc in self.documents:
            if doc.kind == "artifact_json":
                evidence.append(f"{doc.path}: json artifact loaded")
            elif doc.kind == "runtime_json":
                evidence.append(f"{doc.path}: runtime entries loaded")
            elif doc.kind == "p4info":
                evidence.append(f"{doc.path}: p4info text loaded")
        return evidence[:20]


def load_context(request: IntentToP4LTLRequest) -> LoadedContext:
    guide_path = Path(request.guide_path)
    context = LoadedContext(
        guide_path=str(guide_path),
        guide_text=guide_path.read_text(encoding="utf-8"),
        control_plane_surface=request.control_plane_surface,
        artifact_summaries=list(request.artifact_summaries),
    )

    for idx, text in enumerate(request.p4_program_texts):
        virtual_path = f"<inline-p4-{idx}>"
        document = ContextDocument(path=virtual_path, kind="p4", content=text)
        context.documents.append(document)
        _index_p4_document(context, document)

    for path in request.p4_program_paths:
        _load_path_document(context, Path(path), kind_hint="p4")

    for path in request.artifact_paths:
        _load_path_document(context, Path(path), kind_hint=None)

    _index_control_plane_surface(context, request.control_plane_surface)
    for summary in request.artifact_summaries:
        _index_artifact_summary(context, summary)
    return context


def _load_path_document(context: LoadedContext, path: Path, kind_hint: Optional[str]) -> None:
    if not path.exists():
        return

    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file():
                _load_path_document(context, child, kind_hint=None)
        return

    kind = _classify_path(path, kind_hint)
    if kind is None:
        return

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")

    parsed_json = None
    if kind in {"artifact_json", "runtime_json"}:
        try:
            parsed_json = json.loads(text)
        except json.JSONDecodeError:
            parsed_json = None

    document = ContextDocument(path=str(path), kind=kind, content=text, parsed_json=parsed_json)
    context.documents.append(document)

    if kind == "p4":
        _index_p4_document(context, document)
    elif kind in {"artifact_json", "runtime_json"}:
        _index_json_document(context, document)
    elif kind == "p4info":
        _index_p4info_document(context, document)


def _classify_path(path: Path, kind_hint: Optional[str]) -> Optional[str]:
    if kind_hint == "p4":
        return "p4"
    name = path.name
    suffix = path.suffix.lower()
    if suffix == ".p4":
        return "p4"
    if suffix == ".json":
        if "runtime" in name or "topology" in name:
            return "runtime_json"
        return "artifact_json"
    if name.endswith(".p4info.txt") or name.endswith(".p4info.txtpb") or "p4info" in name:
        return "p4info"
    return None


def _index_p4_document(context: LoadedContext, document: ContextDocument) -> None:
    content = document.content
    file_node = f"file:{document.path}"
    context.graph.add_node(file_node, "file", path=document.path, document_kind=document.kind)

    for field in sorted(set(FIELD_REF_RE.findall(content))):
        context.known_fields.add(field)
        field_node = f"field:{field}"
        context.graph.add_node(field_node, "field", name=field)
        context.graph.add_edge(file_node, field_node, "references")

    for name in sorted(set(TABLE_RE.findall(content))):
        context.known_tables.add(name)
        table_node = f"table:{name}"
        context.graph.add_node(table_node, "table", name=name)
        context.graph.add_edge(file_node, table_node, "declares")

    for name in sorted(set(ACTION_RE.findall(content))):
        context.known_actions.add(name)
        action_node = f"action:{name}"
        context.graph.add_node(action_node, "action", name=name)
        context.graph.add_edge(file_node, action_node, "declares")

    for name in sorted(set(REGISTER_RE.findall(content))):
        context.known_registers.add(name)
        register_node = f"register:{name}"
        context.graph.add_node(register_node, "register", name=name)
        context.graph.add_edge(file_node, register_node, "declares")

    for key_block in KEY_BLOCK_RE.findall(content):
        for key in sorted(set(KEY_FIELD_RE.findall(key_block))):
            context.known_keys.add(key)
            key_node = f"key:{key}"
            context.graph.add_node(key_node, "key", name=key)
            context.graph.add_edge(file_node, key_node, "uses_key")


def _index_json_document(context: LoadedContext, document: ContextDocument) -> None:
    file_node = f"file:{document.path}"
    context.graph.add_node(file_node, "file", path=document.path, document_kind=document.kind)

    if document.parsed_json is None:
        return

    if isinstance(document.parsed_json, dict):
        for action in document.parsed_json.get("actions", []):
            if isinstance(action, dict) and isinstance(action.get("name"), str):
                action_name = action["name"]
                context.known_actions.add(action_name)
                action_node = f"action:{action_name}"
                context.graph.add_node(action_node, "action", name=action_name)
                context.graph.add_edge(file_node, action_node, "declares")

        for pipeline in document.parsed_json.get("pipelines", []):
            if not isinstance(pipeline, dict):
                continue
            for table in pipeline.get("tables", []):
                if not isinstance(table, dict):
                    continue
                table_name = table.get("name")
                if isinstance(table_name, str):
                    context.known_tables.add(table_name)
                    table_node = f"table:{table_name}"
                    context.graph.add_node(table_node, "table", name=table_name)
                    context.graph.add_edge(file_node, table_node, "declares")

                for key_item in table.get("key", []):
                    if not isinstance(key_item, dict):
                        continue
                    target = key_item.get("target")
                    if isinstance(target, list):
                        joined = ".".join(str(part) for part in target)
                        context.known_keys.add(joined)
                        context.known_fields.add(joined)
                        key_node = f"key:{joined}"
                        field_node = f"field:{joined}"
                        context.graph.add_node(key_node, "key", name=joined)
                        context.graph.add_node(field_node, "field", name=joined)
                        context.graph.add_edge(file_node, key_node, "uses_key")

                for action_name in table.get("actions", []):
                    if isinstance(action_name, str):
                        context.known_actions.add(action_name)
                        action_node = f"action:{action_name}"
                        context.graph.add_node(action_node, "action", name=action_name)
                        context.graph.add_edge(file_node, action_node, "declares")
                        if isinstance(table_name, str):
                            context.graph.add_edge(f"table:{table_name}", action_node, "has_action")

        header_types = document.parsed_json.get("header_types", [])
        for item in header_types:
            if not isinstance(item, dict):
                continue
            header_name = item.get("name")
            fields = item.get("fields", [])
            for field_item in fields:
                if isinstance(field_item, list) and field_item:
                    field_name = field_item[0]
                    if header_name and not field_name.startswith(("hdr.", "meta.", "standard_metadata.")):
                        if header_name == "standard_metadata":
                            full = f"standard_metadata.{field_name}"
                        else:
                            full = field_name
                    else:
                        full = field_name
                    context.known_fields.add(full)
                    field_node = f"field:{full}"
                    context.graph.add_node(field_node, "field", name=full)
                    context.graph.add_edge(file_node, field_node, "declares")

        for entry in document.parsed_json.get("table_entries", []):
            if not isinstance(entry, dict):
                continue
            table = entry.get("table")
            action = entry.get("action_name")
            if isinstance(table, str):
                context.known_tables.add(table)
                table_node = f"table:{table}"
                context.graph.add_node(table_node, "table", name=table)
                context.graph.add_edge(file_node, table_node, "declares")
            if isinstance(action, str):
                context.known_actions.add(action)
                action_node = f"action:{action}"
                context.graph.add_node(action_node, "action", name=action)
                context.graph.add_edge(file_node, action_node, "declares")
                if isinstance(table, str):
                    context.graph.add_edge(f"table:{table}", action_node, "has_action")
            match = entry.get("match")
            if isinstance(match, dict):
                for key in match.keys():
                    if isinstance(key, str):
                        context.known_keys.add(key)
                        context.known_fields.add(key)
                        key_node = f"key:{key}"
                        field_node = f"field:{key}"
                        context.graph.add_node(key_node, "key", name=key)
                        context.graph.add_node(field_node, "field", name=key)
                        context.graph.add_edge(file_node, key_node, "uses_key")


def _index_p4info_document(context: LoadedContext, document: ContextDocument) -> None:
    content = document.content
    file_node = f"file:{document.path}"
    context.graph.add_node(file_node, "file", path=document.path, document_kind=document.kind)

    lines = content.splitlines()
    current_section: Optional[str] = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("tables {"):
            current_section = "table"
            continue
        if stripped.startswith("actions {"):
            current_section = "action"
            continue
        if stripped.startswith("}"):
            current_section = None
            continue
        match = re.search(r'name:\s+"([^"]+)"', stripped)
        if not match:
            continue
        name = match.group(1)
        if current_section == "table":
            context.known_tables.add(name)
            table_node = f"table:{name}"
            context.graph.add_node(table_node, "table", name=name)
            context.graph.add_edge(file_node, table_node, "declares")
        elif current_section == "action":
            context.known_actions.add(name)
            action_node = f"action:{name}"
            context.graph.add_node(action_node, "action", name=name)
            context.graph.add_edge(file_node, action_node, "declares")
        elif "." in name:
            context.known_keys.add(name)
            context.known_fields.add(name)
            key_node = f"key:{name}"
            field_node = f"field:{name}"
            context.graph.add_node(key_node, "key", name=name)
            context.graph.add_node(field_node, "field", name=name)
            context.graph.add_edge(file_node, key_node, "declares")

    for table in RUNTIME_TABLE_RE.findall(content):
        context.known_tables.add(table)
    for action in RUNTIME_ACTION_RE.findall(content):
        context.known_actions.add(action)
    for field in FIELD_REF_RE.findall(content):
        context.known_fields.add(field)
        context.known_keys.add(field)


def _index_control_plane_surface(context: LoadedContext, surface: str) -> None:
    if not surface:
        return
    for table in RUNTIME_TABLE_RE.findall(surface):
        context.known_tables.add(table)
    for action in RUNTIME_ACTION_RE.findall(surface):
        context.known_actions.add(action)
    for field in FIELD_REF_RE.findall(surface):
        context.known_fields.add(field)
        context.known_keys.add(field)


def _index_artifact_summary(context: LoadedContext, summary: str) -> None:
    if not summary:
        return
    for field in FIELD_REF_RE.findall(summary):
        context.known_fields.add(field)
        context.known_keys.add(field)
    for table in re.findall(r"\b[A-Za-z_][A-Za-z0-9_.]*\b", summary):
        if ".table" in table:
            context.known_tables.add(table)


def discover_p4_files(root: str | Path) -> list[str]:
    base = Path(root)
    paths: list[str] = []
    for path in sorted(base.rglob("*.p4")):
        if _skip_benchmark_path(path):
            continue
        paths.append(str(path))
    return paths


def discover_artifact_files(root: str | Path) -> list[str]:
    base = Path(root)
    paths: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if _skip_benchmark_path(path):
            continue
        if path.suffix.lower() == ".json" or "p4info" in path.name:
            paths.append(str(path))
    return paths


def _skip_benchmark_path(path: Path) -> bool:
    parts = set(path.parts)
    return "bak" in parts
