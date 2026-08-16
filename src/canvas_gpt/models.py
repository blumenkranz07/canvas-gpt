from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


CURRENT_GRAPH_VERSION = 3
TITLE_SOURCES = ("manual", "placeholder", "auto")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Message:
    role: str
    content: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Message:
        return cls(role=str(value["role"]), content=str(value["content"]))


@dataclass(slots=True)
class Node:
    id: str
    title: str
    title_source: str = "manual"
    local_messages: list[Message] = field(default_factory=list)
    kind: str = "conversation"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, legacy_messages: bool = False) -> Node:
        message_key = "messages" if legacy_messages else "local_messages"
        title_source = str(value.get("title_source", "manual"))
        if title_source not in TITLE_SOURCES:
            raise ValueError(f"Unknown title source '{title_source}'.")
        return cls(
            id=str(value["id"]),
            title=str(value["title"]),
            title_source=title_source,
            local_messages=[
                Message.from_dict(item)
                for item in value.get(message_key, value.get("messages", []))
            ],
            kind=str(value.get("kind", "conversation")),
            created_at=str(value.get("created_at", utc_now())),
            updated_at=str(value.get("updated_at", utc_now())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "title_source": self.title_source,
            "local_messages": [asdict(message) for message in self.local_messages],
            "kind": self.kind,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True, frozen=True)
class Edge:
    source: str
    target: str
    type: str
    context_message_count: int | None = None
    context_path: tuple[tuple[str, int], ...] | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Edge:
        raw_count = value.get("context_message_count")
        raw_path = value.get("context_path")
        return cls(
            source=str(value["source"]),
            target=str(value["target"]),
            type=str(value["type"]),
            context_message_count=int(raw_count) if raw_count is not None else None,
            context_path=(
                tuple((str(node_id), int(message_count)) for node_id, message_count in raw_path)
                if raw_path is not None
                else None
            ),
        )


@dataclass(slots=True)
class Graph:
    version: int = CURRENT_GRAPH_VERSION
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Graph:
        source_version = int(value.get("version", 1))
        graph = cls(
            version=source_version,
            nodes={
                key: Node.from_dict(node, legacy_messages=source_version < 2)
                for key, node in value.get("nodes", {}).items()
            },
            edges=[Edge.from_dict(edge) for edge in value.get("edges", [])],
        )
        if source_version < CURRENT_GRAPH_VERSION:
            if source_version < 2:
                graph._migrate_v1_messages()
            graph.version = CURRENT_GRAPH_VERSION
        return graph

    def _migrate_v1_messages(self) -> None:
        raw_messages = {
            node_id: list(node.local_messages) for node_id, node in self.nodes.items()
        }
        branch_edges_by_child: dict[str, list[Edge]] = {}
        for edge in self.edges:
            if edge.type == "branch":
                branch_edges_by_child.setdefault(edge.target, []).append(edge)

        boundaries: dict[tuple[str, str], int] = {}
        for child_id, branch_edges in branch_edges_by_child.items():
            if len(branch_edges) != 1 or child_id not in self.nodes:
                continue
            edge = branch_edges[0]
            parent_messages = raw_messages.get(edge.source, [])
            child_messages = raw_messages.get(child_id, [])
            prefix_length = _common_prefix_length(parent_messages, child_messages)
            self.nodes[child_id].local_messages = child_messages[prefix_length:]
            boundaries[(edge.source, edge.target)] = prefix_length

        self.edges = [
            Edge(
                source=edge.source,
                target=edge.target,
                type=edge.type,
                context_message_count=boundaries.get((edge.source, edge.target)),
            )
            if edge.type == "branch"
            else edge
            for edge in self.edges
        ]
        self.version = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nodes": {key: node.to_dict() for key, node in self.nodes.items()},
            "edges": [asdict(edge) for edge in self.edges],
        }


def _common_prefix_length(left: list[Message], right: list[Message]) -> int:
    length = 0
    for left_message, right_message in zip(left, right):
        if left_message != right_message:
            break
        length += 1
    return length


DEFAULT_MODELS = {
    "openai": "gpt-5.6-terra",
    "anthropic": "claude-sonnet-5",
}


@dataclass(slots=True)
class Config:
    provider: str = "openai"
    model: str = DEFAULT_MODELS["openai"]
    max_output_tokens: int = 2048

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Config:
        return cls(
            provider=str(value.get("provider", "openai")),
            model=str(value.get("model", DEFAULT_MODELS["openai"])),
            max_output_tokens=int(value.get("max_output_tokens", 2048)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
