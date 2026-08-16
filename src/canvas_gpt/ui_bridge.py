from __future__ import annotations

import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from .errors import CanvasGPTError
from .models import Config, Graph
from .providers import build_provider
from .service import GraphService
from .storage import Workspace


T = TypeVar("T")
API_KEY_ENVIRONMENTS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class DesktopAPI:
    def __init__(self, root: Path | str) -> None:
        self.workspace = Workspace(root)

    def bootstrap(self) -> dict[str, Any]:
        return self._result(self._snapshot)

    def initialize_workspace(self) -> dict[str, Any]:
        def initialize() -> dict[str, Any]:
            if not self.workspace.initialized:
                self.workspace.initialize(Config())
            return self._snapshot()

        return self._result(initialize)

    def new_graph(self) -> dict[str, Any]:
        def reset() -> dict[str, Any]:
            self.workspace.require_initialized()
            self.workspace.save_graph(Graph())
            self.workspace.save_ui_state({})
            return self._snapshot()

        return self._result(reset)

    def create_node(self) -> dict[str, Any]:
        return self._result(
            lambda: self._node_payload(
                GraphService(self.workspace).new_node(
                    "Untitled", title_source="placeholder"
                )
            )
        )

    def branch_node(self, source_id: str) -> dict[str, Any]:
        return self._result(
            lambda: self._node_payload(
                GraphService(self.workspace).branch(
                    source_id, "New branch", title_source="placeholder"
                )
            )
        )

    def set_branch_parent(self, child_id: str, parent_id: str) -> dict[str, Any]:
        def set_parent() -> dict[str, Any]:
            edge = GraphService(self.workspace).set_branch_parent(child_id, parent_id)
            return {
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "context_message_count": edge.context_message_count,
            }

        return self._result(set_parent)

    def rename_node(self, node_id: str, title: str) -> dict[str, Any]:
        return self._result(
            lambda: self._node_payload(
                GraphService(self.workspace).rename_node(node_id, title)
            )
        )

    def get_conversation(self, node_id: str) -> dict[str, Any]:
        def conversation() -> dict[str, Any]:
            service = GraphService(self.workspace)
            node = service.get_node(node_id)
            return {
                "node": self._node_payload(node),
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in service.context_messages(node_id)
                ],
            }

        return self._result(conversation)

    def chat(self, node_id: str, message: str) -> dict[str, Any]:
        def send() -> dict[str, Any]:
            config = self.workspace.load_config()
            service = GraphService(self.workspace, build_provider(config))
            response = service.chat(node_id, message)
            return {
                "response": response,
                "snapshot": self._snapshot(),
            }

        return self._result(send)

    def save_ui_state(
        self, positions: dict[str, dict[str, float]], split_ratio: float
    ) -> dict[str, Any]:
        def save() -> dict[str, Any]:
            graph = self.workspace.load_graph()
            clean_positions: dict[str, dict[str, float]] = {}
            for node_id, position in positions.items():
                if node_id not in graph.nodes or not isinstance(position, dict):
                    continue
                x = float(position.get("x", 0))
                y = float(position.get("y", 0))
                if math.isfinite(x) and math.isfinite(y):
                    clean_positions[node_id] = {"x": x, "y": y}
            ratio = float(split_ratio)
            if not math.isfinite(ratio) or not 0.3 <= ratio <= 0.78:
                raise CanvasGPTError("Split ratio must be between 0.3 and 0.78.")
            state = {"positions": clean_positions, "split_ratio": ratio}
            self.workspace.save_ui_state(state)
            return state

        return self._result(save)

    def _snapshot(self) -> dict[str, Any]:
        if not self.workspace.initialized:
            return {
                "initialized": False,
                "workspace_name": self.workspace.root.name,
            }
        graph = self.workspace.load_graph()
        config = self.workspace.load_config()
        service = GraphService(self.workspace)
        environment = API_KEY_ENVIRONMENTS.get(config.provider, "")
        return {
            "initialized": True,
            "workspace_name": self.workspace.root.name,
            "config": {
                "provider": config.provider,
                "model": config.model,
                "api_key_environment": environment,
                "api_key_configured": bool(environment and os.environ.get(environment)),
            },
            "nodes": [
                {
                    **self._node_payload(node),
                    "message_count": len(service.context_messages(node.id)),
                }
                for node in sorted(graph.nodes.values(), key=self._node_sort_key)
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "type": edge.type,
                    "context_message_count": edge.context_message_count,
                }
                for edge in graph.edges
            ],
            "ui": self.workspace.load_ui_state(),
        }

    @staticmethod
    def _node_payload(node: Any) -> dict[str, Any]:
        return {
            "id": node.id,
            "title": node.title,
            "title_source": node.title_source,
            "kind": node.kind,
            "local_message_count": len(node.local_messages),
            "created_at": node.created_at,
            "updated_at": node.updated_at,
        }

    @staticmethod
    def _node_sort_key(node: Any) -> tuple[int, str]:
        if node.id.startswith("n") and node.id[1:].isdigit():
            return (int(node.id[1:]), node.id)
        return (10**9, node.id)

    @staticmethod
    def _result(action: Callable[[], T]) -> dict[str, Any]:
        try:
            return {"ok": True, "data": action()}
        except CanvasGPTError as exc:
            return {"ok": False, "error": str(exc)}
        except (OSError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"Desktop operation failed: {exc}"}
