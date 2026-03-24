from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .context_store import LoadedContext


class ContextToolkit:
    def __init__(self, context: LoadedContext, max_snippet_lines: int = 40) -> None:
        self.context = context
        self.max_snippet_lines = max_snippet_lines

    def search_code(self, pattern: str, scope: Optional[str] = None) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for doc in self.context.documents:
            if doc.kind != "p4":
                continue
            if scope and scope not in doc.path:
                continue
            for idx, line in enumerate(doc.content.splitlines(), start=1):
                if pattern in line:
                    hits.append({"path": doc.path, "line_no": idx, "line": line.strip()})
        return hits[:50]

    def read_code_snippet(self, path: str, start_line: int, end_line: int) -> dict[str, Any]:
        doc = self._get_document(path)
        if doc is None:
            return {"path": path, "error": "document not found"}
        if doc.kind != "p4":
            return {"path": path, "error": "document is not a P4 source file"}

        start = max(1, start_line)
        stop = min(end_line, start + self.max_snippet_lines - 1)
        lines = doc.content.splitlines()
        snippet = "\n".join(lines[start - 1 : stop])
        return {"path": path, "start_line": start, "end_line": stop, "snippet": snippet}

    def query_artifact_json(self, path: str, selector: str) -> dict[str, Any]:
        doc = self._get_document(path)
        if doc is None:
            return {"path": path, "selector": selector, "matches": [], "error": "document not found"}
        if doc.parsed_json is None:
            return {"path": path, "selector": selector, "matches": [], "error": "not a parsed JSON document"}

        matches: list[Any] = []
        self._search_json(doc.parsed_json, selector, matches)
        return {"path": path, "selector": selector, "matches": matches[:50]}

    def read_artifact_json_snippet(self, path: str, selector: str) -> dict[str, Any]:
        result = self.query_artifact_json(path, selector)
        matches = result.get("matches", [])
        return {"path": path, "selector": selector, "matches": matches[:10]}

    def query_context_graph(
        self,
        node: Optional[str] = None,
        relation: Optional[str] = None,
        target_kind: Optional[str] = None,
        pattern: Optional[str] = None,
    ) -> dict[str, Any]:
        result = self.context.graph.query(
            node=node,
            relation=relation,
            target_kind=target_kind,
            pattern=pattern,
        )
        return result.model_dump()

    def list_known_entities(self, entity_type: str) -> list[str]:
        mapping = {
            "field": sorted(self.context.known_fields),
            "table": sorted(self.context.known_tables),
            "action": sorted(self.context.known_actions),
            "register": sorted(self.context.known_registers),
            "key": sorted(self.context.known_keys),
        }
        return mapping.get(entity_type, [])

    def summarize_context(self) -> dict[str, Any]:
        return self.context.summary().model_dump()

    def _get_document(self, path: str):
        for doc in self.context.documents:
            if doc.path == path or Path(doc.path).name == Path(path).name:
                return doc
        return None

    def _search_json(self, value: Any, selector: str, matches: list[Any], path: str = "$") -> None:
        if len(matches) >= 100:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                next_path = f"{path}.{key}"
                if selector in key:
                    matches.append({"path": next_path, "value": item})
                self._search_json(item, selector, matches, next_path)
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                next_path = f"{path}[{idx}]"
                self._search_json(item, selector, matches, next_path)
        elif isinstance(value, str):
            if selector in value:
                matches.append({"path": path, "value": value})
