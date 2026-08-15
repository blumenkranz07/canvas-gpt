from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from collections.abc import Sequence

from canvas_gpt.errors import CanvasGPTError, NodeNotFoundError, ProviderError
from canvas_gpt.models import Config, Message
from canvas_gpt.service import GraphService
from canvas_gpt.storage import Workspace


class FakeProvider:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or ["fake response"]
        self.calls: list[tuple[list[Message], str]] = []

    def generate(self, messages: Sequence[Message], *, system_prompt: str) -> str:
        self.calls.append((list(messages), system_prompt))
        return self.responses.pop(0)


class FailingProvider:
    def __init__(self, message: str = "simulated failure") -> None:
        self.message = message

    def generate(self, messages: Sequence[Message], *, system_prompt: str) -> str:
        raise ProviderError(self.message)


class GraphServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = Workspace(Path(self.temporary_directory.name))
        self.workspace.initialize(Config())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_create_chat_branch_and_merge(self) -> None:
        provider = FakeProvider(
            ["First answer", "Later root answer", "Branch answer", "Merged synthesis"]
        )
        service = GraphService(self.workspace, provider)

        root = service.new_node("Root question")
        answer = service.chat(root.id, "Explore option A")
        branch = service.branch(root.id, "Alternative path")
        service.chat(root.id, "Continue only on root")
        branch_answer = service.chat(branch.id, "Explore option B")
        merged, synthesis = service.merge([root.id, branch.id], title="Unified result")
        updated_root = service.get_node(root.id)
        updated_branch = service.get_node(branch.id)

        self.assertEqual(answer, "First answer")
        self.assertEqual(branch_answer, "Branch answer")
        self.assertEqual(synthesis, "Merged synthesis")
        self.assertEqual(len(updated_root.local_messages), 4)
        self.assertEqual(len(updated_branch.local_messages), 2)
        branch_call_messages = provider.calls[2][0]
        self.assertEqual(
            [message.content for message in branch_call_messages],
            ["Explore option A", "First answer", "Explore option B"],
        )
        merge_prompt = provider.calls[3][0][0].content
        self.assertEqual(merge_prompt.count("First answer"), 1)
        self.assertEqual(merge_prompt.count("Branch answer"), 1)
        self.assertIn("Source n2 (Alternative path): n1[:2] -> n2[:2]", merge_prompt)
        self.assertEqual(merged.kind, "merge")
        self.assertEqual(merged.local_messages[-1].content, "Merged synthesis")

        graph = self.workspace.load_graph()
        edge_values = {(edge.source, edge.target, edge.type) for edge in graph.edges}
        self.assertIn((root.id, branch.id, "branch"), edge_values)
        self.assertIn((root.id, merged.id, "merge"), edge_values)
        self.assertIn((branch.id, merged.id, "merge"), edge_values)

    def test_chat_failure_does_not_modify_node(self) -> None:
        service = GraphService(self.workspace, FailingProvider())
        node = service.new_node("Safe write")

        with self.assertRaises(ProviderError):
            service.chat(node.id, "This request fails")

        self.assertEqual(service.get_node(node.id).local_messages, [])

    def test_merge_requires_two_distinct_nodes(self) -> None:
        service = GraphService(self.workspace, FakeProvider())
        node = service.new_node("Only node")
        with self.assertRaises(CanvasGPTError):
            service.merge([node.id, node.id])

    def test_empty_titles_messages_and_merge_instruction_are_rejected(self) -> None:
        service = GraphService(self.workspace, FakeProvider())
        first = service.new_node("First")
        second = service.new_node("Second")

        with self.assertRaisesRegex(CanvasGPTError, "Title cannot be empty"):
            service.new_node("   ")
        with self.assertRaisesRegex(CanvasGPTError, "Title cannot be empty"):
            service.branch(first.id, "   ")
        with self.assertRaisesRegex(CanvasGPTError, "Message cannot be empty"):
            service.chat(first.id, "   ")
        with self.assertRaisesRegex(CanvasGPTError, "instruction cannot be empty"):
            service.merge([first.id, second.id], instruction="   ")
        with self.assertRaisesRegex(CanvasGPTError, "Title cannot be empty"):
            service.merge([first.id, second.id], title="   ")

    def test_missing_node_ids_raise_clean_errors(self) -> None:
        service = GraphService(self.workspace, FakeProvider(["unused"]))
        existing = service.new_node("Existing")
        operations = {
            "get": lambda: service.get_node("missing"),
            "context": lambda: service.context_messages("missing"),
            "chat": lambda: service.chat("missing", "Hello"),
            "branch": lambda: service.branch("missing", "Branch"),
            "connect source": lambda: service.connect("missing", existing.id, "reference"),
            "connect target": lambda: service.connect(existing.id, "missing", "reference"),
            "merge": lambda: service.merge([existing.id, "missing"]),
        }
        for name, operation in operations.items():
            with self.subTest(operation=name), self.assertRaises(NodeNotFoundError):
                operation()

    def test_failed_merge_does_not_create_node_or_edges(self) -> None:
        service = GraphService(self.workspace, FailingProvider("context length exceeded"))
        first = service.new_node("First")
        second = service.new_node("Second")
        before = self.workspace.load_graph().to_dict()

        with self.assertRaisesRegex(ProviderError, "context length exceeded"):
            service.merge([first.id, second.id])

        self.assertEqual(self.workspace.load_graph().to_dict(), before)

    def test_connect_arbitrary_nodes(self) -> None:
        service = GraphService(self.workspace)
        first = service.new_node("First")
        second = service.new_node("Second")

        edge = service.connect(first.id, second.id, "supports")

        self.assertEqual(edge.type, "supports")
        with self.assertRaises(CanvasGPTError):
            service.connect(first.id, second.id, "supports")
        with self.assertRaises(CanvasGPTError):
            service.connect(first.id, first.id, "reference")
        with self.assertRaises(CanvasGPTError):
            service.connect(first.id, second.id, "branch")

    def test_branch_cycle_is_rejected_when_loading_context(self) -> None:
        from canvas_gpt.models import Edge

        service = GraphService(self.workspace)
        first = service.new_node("First")
        second = service.branch(first.id, "Second")
        graph = self.workspace.load_graph()
        graph.edges.append(
            Edge(
                source=second.id,
                target=first.id,
                type="branch",
                context_message_count=0,
            )
        )
        self.workspace.save_graph(graph)

        with self.assertRaisesRegex(CanvasGPTError, "cycle"):
            service.context_messages(second.id)

    def test_multiple_branch_parents_are_rejected(self) -> None:
        from canvas_gpt.models import Edge

        service = GraphService(self.workspace)
        first = service.new_node("First")
        second = service.new_node("Second")
        child = service.branch(first.id, "Child")
        graph = self.workspace.load_graph()
        graph.edges.append(
            Edge(
                source=second.id,
                target=child.id,
                type="branch",
                context_message_count=0,
            )
        )
        self.workspace.save_graph(graph)

        with self.assertRaisesRegex(CanvasGPTError, "multiple branch parents"):
            service.context_messages(child.id)

    def test_invalid_branch_context_boundaries_are_rejected(self) -> None:
        from canvas_gpt.models import Edge

        for boundary, expected_error in [
            (-1, "cannot be negative"),
            (1, "exceeds the parent conversation length"),
        ]:
            with self.subTest(boundary=boundary):
                graph = self.workspace.load_graph()
                graph.nodes.clear()
                graph.edges.clear()
                self.workspace.save_graph(graph)
                parent = GraphService(self.workspace).new_node("Parent")
                child = GraphService(self.workspace).new_node("Child")
                graph = self.workspace.load_graph()
                graph.edges.append(
                    Edge(
                        source=parent.id,
                        target=child.id,
                        type="branch",
                        context_message_count=boundary,
                    )
                )
                self.workspace.save_graph(graph)

                with self.assertRaisesRegex(CanvasGPTError, expected_error):
                    GraphService(self.workspace).context_messages(child.id)

    def test_missing_branch_context_boundary_is_rejected(self) -> None:
        from canvas_gpt.models import Edge

        service = GraphService(self.workspace)
        parent = service.new_node("Parent")
        child = service.new_node("Child")
        graph = self.workspace.load_graph()
        graph.edges.append(Edge(source=parent.id, target=child.id, type="branch"))
        self.workspace.save_graph(graph)

        with self.assertRaisesRegex(CanvasGPTError, "no context boundary"):
            service.context_messages(child.id)


if __name__ == "__main__":
    unittest.main()
