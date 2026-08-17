from __future__ import annotations

import math
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from .errors import CanvasGPTError
from .models import DEFAULT_MODELS, Config, Graph
from .providers import build_provider
from .service import (
    MAX_NODE_CHILDREN,
    GraphService,
    STRUCTURAL_EDGE_TYPES,
)
from .storage import Workspace


T = TypeVar("T")
API_KEY_ENVIRONMENTS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "fake": "Fake context",
}
FAKE_MODEL = "dev-context-echo"


class DesktopAPI:
    def __init__(self, root: Path | str, *, allow_fake_provider: bool = False) -> None:
        self.workspace = Workspace(root)
        self.allow_fake_provider = allow_fake_provider
        self._window: Any | None = None
        self._window_is_maximized = False

    def _attach_window(self, window: Any) -> None:
        self._window = window

        def maximized(*_: Any) -> None:
            self._window_is_maximized = True

        def restored(*_: Any) -> None:
            self._window_is_maximized = False

        window.events.maximized += maximized
        window.events.restored += restored

    def minimize_window(self) -> dict[str, Any]:
        return self._result(lambda: self._run_window_action("minimize"))

    def toggle_maximize_window(self) -> dict[str, Any]:
        def toggle() -> bool:
            if self._window is None:
                raise CanvasGPTError("Desktop window is not ready.")
            if self._window_is_maximized:
                self._window.restore()
                self._window_is_maximized = False
            else:
                self._window.maximize()
                self._window_is_maximized = True
            return self._window_is_maximized

        return self._result(toggle)

    def close_window(self) -> dict[str, Any]:
        return self._result(lambda: self._run_window_action("destroy"))

    def resize_window(self, width: float, height: float, anchor: str) -> dict[str, Any]:
        def resize() -> bool:
            if self._window is None:
                raise CanvasGPTError("Desktop window is not ready.")
            from webview.window import FixPoint

            fix_points = {
                "north-west": FixPoint.NORTH | FixPoint.WEST,
                "north-east": FixPoint.NORTH | FixPoint.EAST,
                "south-west": FixPoint.SOUTH | FixPoint.WEST,
                "south-east": FixPoint.SOUTH | FixPoint.EAST,
            }
            if anchor not in fix_points:
                raise CanvasGPTError("Invalid window resize anchor.")
            self._window.resize(
                max(900, int(width)),
                max(600, int(height)),
                fix_points[anchor],
            )
            return True

        return self._result(resize)

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

    def update_provider(self, provider: str) -> dict[str, Any]:
        def update() -> dict[str, Any]:
            allowed = {"openai", "anthropic"}
            if self.allow_fake_provider:
                allowed.add("fake")
            if provider not in allowed:
                raise CanvasGPTError(f"Provider '{provider}' is not available in this build.")
            config = self.workspace.load_config()
            config.provider = provider
            config.model = FAKE_MODEL if provider == "fake" else DEFAULT_MODELS[provider]
            self.workspace.save_config(config)
            return self._snapshot()

        return self._result(update)

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
            return self._edge_payload(edge)

        return self._result(set_parent)

    def add_draft_parent(self, child_id: str, parent_id: str) -> dict[str, Any]:
        def add_parent() -> dict[str, Any]:
            edge = GraphService(self.workspace).add_draft_parent(child_id, parent_id)
            return self._edge_payload(edge)

        return self._result(add_parent)

    def attach_parent(self, child_id: str, parent_id: str) -> dict[str, Any]:
        def attach() -> dict[str, Any]:
            edge = GraphService(self.workspace).attach_parent(child_id, parent_id)
            return self._edge_payload(edge)

        return self._result(attach)

    def create_merge_draft(self, source_ids: list[str]) -> dict[str, Any]:
        return self._result(
            lambda: self._node_payload(
                GraphService(self.workspace).new_merge_draft(source_ids)
            )
        )

    def remove_draft_parent(self, child_id: str, parent_id: str) -> dict[str, Any]:
        def remove_parent() -> dict[str, Any]:
            remaining = GraphService(self.workspace).remove_draft_parent(
                child_id, parent_id
            )
            return {"parent_ids": [edge.source for edge in remaining]}

        return self._result(remove_parent)

    def rename_node(self, node_id: str, title: str) -> dict[str, Any]:
        return self._result(
            lambda: self._node_payload(
                GraphService(self.workspace).rename_node(node_id, title)
            )
        )

    def delete_node(self, node_id: str) -> dict[str, Any]:
        return self._result(
            lambda: self._node_payload(
                GraphService(self.workspace).delete_node(node_id)
            )
        )

    def delete_edge(
        self, source_id: str, target_id: str, edge_type: str
    ) -> dict[str, Any]:
        return self._result(
            lambda: self._edge_payload(
                GraphService(self.workspace).delete_edge(
                    source_id, target_id, edge_type
                )
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
            service = GraphService(
                self.workspace,
                build_provider(config, allow_fake=self.allow_fake_provider),
            )
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
                "platform": self._platform_name(),
            }
        graph = self.workspace.load_graph()
        config = self.workspace.load_config()
        service = GraphService(self.workspace)
        environment = API_KEY_ENVIRONMENTS.get(config.provider, "")
        available_provider_ids = ["openai", "anthropic"]
        if self.allow_fake_provider:
            available_provider_ids.append("fake")
        child_counts = {
            node_id: sum(
                1
                for edge in graph.edges
                if edge.source == node_id and edge.type in STRUCTURAL_EDGE_TYPES
            )
            for node_id in graph.nodes
        }
        return {
            "initialized": True,
            "workspace_name": self.workspace.root.name,
            "platform": self._platform_name(),
            "config": {
                "provider": config.provider,
                "model": config.model,
                "api_key_environment": environment,
                "api_key_configured": (
                    config.provider == "fake" and self.allow_fake_provider
                ) or bool(environment and os.environ.get(environment)),
                "available_providers": [
                    {
                        "id": provider_id,
                        "label": PROVIDER_LABELS[provider_id],
                        "model": (
                            FAKE_MODEL
                            if provider_id == "fake"
                            else DEFAULT_MODELS[provider_id]
                        ),
                        "is_dev": provider_id == "fake",
                    }
                    for provider_id in available_provider_ids
                ],
            },
            "nodes": [
                {
                    **self._node_payload(node),
                    "message_count": len(service.context_messages(node.id)),
                    "deletable": not node.local_messages,
                    "frozen": child_counts[node.id] > 0,
                    "child_count": child_counts[node.id],
                    "max_children": MAX_NODE_CHILDREN,
                    "parent_ids": [
                        edge.source
                        for edge in graph.edges
                        if edge.target == node.id
                        and edge.type in STRUCTURAL_EDGE_TYPES
                    ],
                }
                for node in sorted(graph.nodes.values(), key=self._node_sort_key)
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "type": edge.type,
                    "context_message_count": edge.context_message_count,
                    "deletable": (
                        edge.type not in STRUCTURAL_EDGE_TYPES
                        or (
                            graph.nodes[edge.target].kind == "conversation"
                            and not graph.nodes[edge.target].local_messages
                        )
                    ),
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
    def _edge_payload(edge: Any) -> dict[str, Any]:
        return {
            "source": edge.source,
            "target": edge.target,
            "type": edge.type,
            "context_message_count": edge.context_message_count,
        }

    @staticmethod
    def _node_sort_key(node: Any) -> tuple[int, str]:
        if node.id.startswith("n") and node.id[1:].isdigit():
            return (int(node.id[1:]), node.id)
        return (10**9, node.id)

    def _run_window_action(self, action: str) -> bool:
        if self._window is None:
            raise CanvasGPTError("Desktop window is not ready.")
        getattr(self._window, action)()
        return True

    @staticmethod
    def _platform_name() -> str:
        if sys.platform == "darwin":
            return "macos"
        if sys.platform == "win32":
            return "windows"
        return "linux"

    @staticmethod
    def _result(action: Callable[[], T]) -> dict[str, Any]:
        try:
            return {"ok": True, "data": action()}
        except CanvasGPTError as exc:
            return {"ok": False, "error": str(exc)}
        except (OSError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"Desktop operation failed: {exc}"}
