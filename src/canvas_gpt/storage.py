from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import CanvasGPTError, NotInitializedError
from .models import CURRENT_GRAPH_VERSION, Config, Graph


class Workspace:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.data_dir = self.root / ".canvas-gpt"
        self.config_path = self.data_dir / "config.json"
        self.graph_path = self.data_dir / "graph.json"
        self.ui_path = self.data_dir / "ui.json"

    @property
    def initialized(self) -> bool:
        return self.config_path.is_file() and self.graph_path.is_file()

    def initialize(self, config: Config, *, force: bool = False) -> None:
        if self.initialized and not force:
            raise CanvasGPTError(
                f"Workspace is already initialized at {self.data_dir}. Use --force to reset it."
            )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.config_path, config.to_dict())
        self._write_json(self.graph_path, Graph().to_dict())

    def require_initialized(self) -> None:
        if not self.initialized:
            raise NotInitializedError(
                "This folder is not initialized. Run `canvas-gpt init` first."
            )

    def load_config(self) -> Config:
        self.require_initialized()
        raw_config = self._read_json(self.config_path)
        try:
            return Config.from_dict(raw_config)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanvasGPTError(f"Invalid config schema in {self.config_path}: {exc}") from exc

    def save_config(self, config: Config) -> None:
        self.require_initialized()
        self._write_json(self.config_path, config.to_dict())

    def load_graph(self) -> Graph:
        self.require_initialized()
        raw_graph = self._read_json(self.graph_path)
        try:
            source_version = int(raw_graph.get("version", 1))
        except (TypeError, ValueError) as exc:
            raise CanvasGPTError(
                f"Invalid graph schema version in {self.graph_path}."
            ) from exc
        if source_version > CURRENT_GRAPH_VERSION:
            raise CanvasGPTError(
                f"Graph schema version {source_version} is newer than the supported "
                f"version {CURRENT_GRAPH_VERSION}. Upgrade Canvas GPT before opening it."
            )
        try:
            graph = Graph.from_dict(raw_graph)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise CanvasGPTError(f"Invalid graph schema in {self.graph_path}: {exc}") from exc
        if int(raw_graph.get("version", 1)) < graph.version:
            self._write_json(self.graph_path, graph.to_dict())
        return graph

    def save_graph(self, graph: Graph) -> None:
        self.require_initialized()
        self._write_json(self.graph_path, graph.to_dict())

    def load_ui_state(self) -> dict[str, Any]:
        self.require_initialized()
        if not self.ui_path.is_file():
            return {}
        return self._read_json(self.ui_path)

    def save_ui_state(self, state: dict[str, Any]) -> None:
        self.require_initialized()
        self._write_json(self.ui_path, state)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise CanvasGPTError(f"Could not read {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise CanvasGPTError(f"Expected a JSON object in {path}.")
        return value

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary_path, path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
