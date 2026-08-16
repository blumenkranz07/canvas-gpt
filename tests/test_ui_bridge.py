from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from canvas_gpt.models import Config, Message
from canvas_gpt.service import GraphService
from canvas_gpt.storage import Workspace
from canvas_gpt.ui_bridge import DesktopAPI


class DesktopAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.api = DesktopAPI(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_initialize_without_api_key_keeps_offline_canvas_available(self) -> None:
        before = self.api.bootstrap()
        self.assertTrue(before["ok"])
        self.assertFalse(before["data"]["initialized"])

        with patch.dict("os.environ", {}, clear=True):
            initialized = self.api.initialize_workspace()

        self.assertTrue(initialized["ok"])
        self.assertTrue(initialized["data"]["initialized"])
        self.assertFalse(initialized["data"]["config"]["api_key_configured"])
        self.assertEqual(initialized["data"]["config"]["api_key_environment"], "OPENAI_API_KEY")

        created = self.api.create_node()
        self.assertTrue(created["ok"])
        self.assertEqual(created["data"]["title_source"], "placeholder")

    def test_missing_api_key_returns_error_only_for_chat(self) -> None:
        self.api.initialize_workspace()
        node_id = self.api.create_node()["data"]["id"]

        with patch.dict("os.environ", {}, clear=True):
            result = self.api.chat(node_id, "Hello")

        self.assertFalse(result["ok"])
        self.assertIn("OPENAI_API_KEY", result["error"])
        snapshot = self.api.bootstrap()["data"]
        self.assertEqual(len(snapshot["nodes"]), 1)
        self.assertEqual(snapshot["nodes"][0]["local_message_count"], 0)

    def test_create_rename_branch_and_save_layout(self) -> None:
        workspace = Workspace(self.root)
        workspace.initialize(Config())
        service = GraphService(workspace)
        parent = service.new_node("Parent")
        graph = workspace.load_graph()
        graph.nodes[parent.id].local_messages.extend(
            [
                Message(role="user", content="Parent context"),
                Message(role="assistant", content="Parent answer"),
            ]
        )
        workspace.save_graph(graph)

        child = self.api.create_node()["data"]
        renamed = self.api.rename_node(child["id"], "Draft child")
        connected = self.api.set_branch_parent(child["id"], parent.id)
        saved = self.api.save_ui_state(
            {child["id"]: {"x": 120.5, "y": 240.25}}, 0.61
        )

        self.assertTrue(renamed["ok"])
        self.assertEqual(renamed["data"]["title_source"], "manual")
        self.assertTrue(connected["ok"])
        self.assertEqual(connected["data"]["source"], parent.id)
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["data"]["split_ratio"], 0.61)

    def test_new_graph_clears_nodes_but_preserves_config(self) -> None:
        self.api.initialize_workspace()
        self.api.create_node()

        result = self.api.new_graph()

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["nodes"], [])
        self.assertEqual(result["data"]["config"]["provider"], "openai")


if __name__ == "__main__":
    unittest.main()
