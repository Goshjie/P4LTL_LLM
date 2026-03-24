from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..pipeline.models import GraphQueryResult


@dataclass
class GraphNode:
    node_id: str
    kind: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    src: str
    dst: str
    relation: str
    attrs: dict[str, Any] = field(default_factory=dict)


class SimpleContextGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []

    def add_node(self, node_id: str, kind: str, **attrs: Any) -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = GraphNode(node_id=node_id, kind=kind, attrs=dict(attrs))
            return
        self.nodes[node_id].attrs.update(attrs)

    def add_edge(self, src: str, dst: str, relation: str, **attrs: Any) -> None:
        self.edges.append(GraphEdge(src=src, dst=dst, relation=relation, attrs=dict(attrs)))

    def query(
        self,
        node: Optional[str] = None,
        relation: Optional[str] = None,
        target_kind: Optional[str] = None,
        pattern: Optional[str] = None,
    ) -> GraphQueryResult:
        matches: list[dict[str, Any]] = []
        for edge in self.edges:
            if node is not None and edge.src != node and edge.dst != node:
                continue
            if relation is not None and edge.relation != relation:
                continue

            src_node = self.nodes.get(edge.src)
            dst_node = self.nodes.get(edge.dst)
            if target_kind is not None:
                dst_kind = dst_node.kind if dst_node else None
                src_kind = src_node.kind if src_node else None
                if target_kind not in {src_kind, dst_kind}:
                    continue

            if pattern is not None:
                haystacks = [
                    edge.src,
                    edge.dst,
                    edge.relation,
                    src_node.kind if src_node else "",
                    dst_node.kind if dst_node else "",
                ]
                if not any(pattern in item for item in haystacks):
                    continue

            matches.append(
                {
                    "src": edge.src,
                    "src_kind": src_node.kind if src_node else None,
                    "dst": edge.dst,
                    "dst_kind": dst_node.kind if dst_node else None,
                    "relation": edge.relation,
                    "attrs": edge.attrs,
                }
            )
        return GraphQueryResult(node=node, relation=relation, matches=matches)

    def neighbors(self, node_id: str, relation: Optional[str] = None) -> list[dict[str, Any]]:
        result = self.query(node=node_id, relation=relation).matches
        return result

    def to_networkx(self) -> Any:
        try:
            import networkx as nx  # type: ignore
        except ImportError as exc:
            raise RuntimeError("networkx is not installed in this environment") from exc

        graph = nx.MultiDiGraph()
        for node_id, node in self.nodes.items():
            graph.add_node(node_id, kind=node.kind, **node.attrs)
        for edge in self.edges:
            graph.add_edge(edge.src, edge.dst, relation=edge.relation, **edge.attrs)
        return graph
