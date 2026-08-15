from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from canvas_gpt.errors import CanvasGPTError, NotInitializedError
from canvas_gpt.models import Config
from canvas_gpt.service import GraphService
from canvas_gpt.storage import Workspace


class WorkspaceTests(unittest.TestCase):
    def test_round_trip_and_no_credentials_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            config = Config(provider="anthropic", model="claude-sonnet-5", max_output_tokens=999)
            workspace.initialize(config)

            loaded = workspace.load_config()
            raw = workspace.config_path.read_text(encoding="utf-8")

            self.assertEqual(loaded, config)
            self.assertNotIn("api_key", raw.lower())
            self.assertEqual(json.loads(raw)["provider"], "anthropic")

    def test_v1_graph_migrates_copied_branch_history_to_local_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.initialize(Config())
            v1_graph = {
                "version": 1,
                "nodes": {
                    "n1": {
                        "id": "n1",
                        "title": "Root",
                        "messages": [
                            {"role": "user", "content": "Shared question"},
                            {"role": "assistant", "content": "Shared answer"},
                            {"role": "user", "content": "Root continuation"},
                        ],
                    },
                    "n2": {
                        "id": "n2",
                        "title": "Branch",
                        "messages": [
                            {"role": "user", "content": "Shared question"},
                            {"role": "assistant", "content": "Shared answer"},
                            {"role": "user", "content": "Branch continuation"},
                            {"role": "assistant", "content": "Branch answer"},
                        ],
                    },
                },
                "edges": [{"source": "n1", "target": "n2", "type": "branch"}],
            }
            workspace.graph_path.write_text(json.dumps(v1_graph), encoding="utf-8")

            graph = workspace.load_graph()

            self.assertEqual(graph.version, 2)
            self.assertEqual(
                [message.content for message in graph.nodes["n2"].local_messages],
                ["Branch continuation", "Branch answer"],
            )
            self.assertEqual(graph.edges[0].context_message_count, 2)
            self.assertEqual(
                [
                    message.content
                    for message in GraphService(workspace).context_messages("n2")
                ],
                [
                    "Shared question",
                    "Shared answer",
                    "Branch continuation",
                    "Branch answer",
                ],
            )
            migrated_raw = json.loads(workspace.graph_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated_raw["version"], 2)
            self.assertIn("local_messages", migrated_raw["nodes"]["n2"])
            self.assertNotIn("messages", migrated_raw["nodes"]["n2"])

    def test_uninitialized_workspace_raises_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            with self.assertRaises(NotInitializedError):
                workspace.load_graph()

    def test_corrupt_and_malformed_graphs_raise_clean_errors(self) -> None:
        cases = [
            ("{not-json", "Could not read"),
            ("[]", "Expected a JSON object"),
            (json.dumps({"version": 2, "nodes": [], "edges": []}), "Invalid graph schema"),
            (
                json.dumps(
                    {
                        "version": 2,
                        "nodes": {"n1": {"id": "n1", "local_messages": []}},
                        "edges": [],
                    }
                ),
                "Invalid graph schema",
            ),
        ]
        for raw_graph, expected_error in cases:
            with self.subTest(raw_graph=raw_graph), tempfile.TemporaryDirectory() as directory:
                workspace = Workspace(Path(directory))
                workspace.initialize(Config())
                workspace.graph_path.write_text(raw_graph, encoding="utf-8")

                with self.assertRaisesRegex(CanvasGPTError, expected_error):
                    workspace.load_graph()

    def test_future_graph_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.initialize(Config())
            workspace.graph_path.write_text(
                json.dumps({"version": 999, "nodes": {}, "edges": []}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(CanvasGPTError, "newer than the supported version"):
                workspace.load_graph()

    def test_invalid_config_schema_raises_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.initialize(Config())
            workspace.config_path.write_text(
                json.dumps({"max_output_tokens": "not-a-number"}), encoding="utf-8"
            )

            with self.assertRaisesRegex(CanvasGPTError, "Invalid config schema"):
                workspace.load_config()

    def test_initialize_refuses_to_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.initialize(Config())
            with self.assertRaises(CanvasGPTError):
                workspace.initialize(Config())

    def test_force_initialize_resets_graph_and_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.initialize(Config())
            GraphService(workspace).new_node("Will be reset")

            replacement = Config(provider="anthropic", model="claude-test")
            workspace.initialize(replacement, force=True)

            self.assertEqual(workspace.load_config(), replacement)
            self.assertEqual(workspace.load_graph().nodes, {})
            self.assertEqual(workspace.load_graph().edges, [])

    def test_failed_atomic_replace_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.initialize(Config())
            original = workspace.config_path.read_text(encoding="utf-8")

            with patch("canvas_gpt.storage.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    workspace.save_config(Config(provider="anthropic", model="claude-test"))

            self.assertEqual(workspace.config_path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(workspace.data_dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
