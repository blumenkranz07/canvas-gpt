from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from collections.abc import Sequence

from canvas_gpt.errors import CanvasGPTError, NodeNotFoundError, ProviderError
from canvas_gpt.models import Config, Message
from canvas_gpt.providers.fake_provider import FakeProvider as DevFakeProvider
from canvas_gpt.service import (
    MAX_DRAFT_PARENTS,
    MAX_NODE_CHILDREN,
    GraphService,
)
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

    @staticmethod
    def _incoming_structural_edges(graph, node_id: str):
        return [
            edge
            for edge in graph.edges
            if edge.target == node_id and edge.type in ("branch", "merge")
        ]

    @staticmethod
    def _structural_children(graph, node_id: str):
        return [
            edge
            for edge in graph.edges
            if edge.source == node_id and edge.type in ("branch", "merge")
        ]

    def test_create_chat_branch_and_merge(self) -> None:
        provider = FakeProvider(["First answer", "Branch answer", "Merged synthesis"])
        service = GraphService(self.workspace, provider)

        root = service.new_node("Root question")
        answer = service.chat(root.id, "Explore option A")
        branch = service.branch(root.id, "Alternative path")
        with self.assertRaisesRegex(CanvasGPTError, "frozen because it has children"):
            service.chat(root.id, "Continue only on root")
        branch_answer = service.chat(branch.id, "Explore option B")
        merged, synthesis = service.merge([root.id, branch.id], title="Unified result")
        updated_root = service.get_node(root.id)
        updated_branch = service.get_node(branch.id)

        self.assertEqual(answer, "First answer")
        self.assertEqual(branch_answer, "Branch answer")
        self.assertEqual(synthesis, "Merged synthesis")
        self.assertEqual(len(updated_root.local_messages), 2)
        self.assertEqual(len(updated_branch.local_messages), 2)
        branch_call_messages = provider.calls[1][0]
        self.assertEqual(
            [message.content for message in branch_call_messages],
            ["Explore option A", "First answer", "Explore option B"],
        )
        merge_prompt = provider.calls[2][0][0].content
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

    def test_dev_fake_echoes_standard_chat_request_and_frozen_context(self) -> None:
        service = GraphService(self.workspace, DevFakeProvider())
        root = service.new_node("Root")
        graph = self.workspace.load_graph()
        graph.nodes[root.id].local_messages = [
            Message(role="user", content="Grandparent question"),
            Message(role="assistant", content="Grandparent answer"),
        ]
        self.workspace.save_graph(graph)
        parent = service.branch(root.id, "Parent")
        graph = self.workspace.load_graph()
        graph.nodes[parent.id].local_messages = [
            Message(role="user", content="Parent question"),
            Message(role="assistant", content="Parent answer"),
        ]
        self.workspace.save_graph(graph)
        child = service.branch(parent.id, "Child")
        graph = self.workspace.load_graph()
        graph.nodes[parent.id].local_messages.append(
            Message(role="user", content="Late parent message")
        )
        self.workspace.save_graph(graph)

        first = service.chat(child.id, "xx")
        second = service.chat(child.id, "yy")

        self.assertIn("【FAKE · Request echo】", first)
        self.assertIn("--- MESSAGES ---", first)
        self.assertNotIn("Current node", first)
        self.assertNotIn("Canvas GPT", first)
        self.assertIn("Grandparent question", first)
        self.assertIn("Grandparent answer", first)
        self.assertIn("Parent question", first)
        self.assertIn("Parent answer", first)
        self.assertIn("[5] USER\nxx", first)
        self.assertNotIn("Late parent message", first)
        self.assertIn("【FAKE · Request echo】", second)
        self.assertIn(first, second)
        self.assertIn("yy", second)

    def test_chat_failure_does_not_modify_node(self) -> None:
        service = GraphService(self.workspace, FailingProvider())
        node = service.new_node("Untitled", title_source="placeholder")

        with self.assertRaises(ProviderError):
            service.chat(node.id, "This request fails")

        self.assertEqual(service.get_node(node.id).local_messages, [])
        self.assertEqual(service.get_node(node.id).title, "Untitled")
        self.assertEqual(service.get_node(node.id).title_source, "placeholder")

    def test_placeholder_node_is_auto_titled_after_first_successful_chat(self) -> None:
        service = GraphService(self.workspace, FakeProvider())
        node = service.new_node("Untitled", title_source="placeholder")

        service.chat(node.id, "比较 Tauri 和 pywebview 的优缺点。后面内容不应进入标题")

        updated = service.get_node(node.id)
        self.assertEqual(updated.title, "比较 Tauri 和 pywebview 的优缺…")
        self.assertEqual(updated.title_source, "auto")

    def test_renaming_node_marks_title_manual_and_prevents_auto_title(self) -> None:
        service = GraphService(self.workspace, FakeProvider())
        node = service.new_node("Untitled", title_source="placeholder")

        renamed = service.rename_node(node.id, "Chosen title")
        service.chat(node.id, "This would otherwise become the title")

        self.assertEqual(renamed.title_source, "manual")
        self.assertEqual(service.get_node(node.id).title, "Chosen title")
        self.assertEqual(service.get_node(node.id).title_source, "manual")

    def test_auto_title_is_cleaned_and_truncated_locally(self) -> None:
        service = GraphService(self.workspace, FakeProvider())
        node = service.new_node("New branch", title_source="placeholder")

        service.chat(node.id, "# This is a deliberately long English title that should be truncated")

        self.assertEqual(
            service.get_node(node.id).title,
            "This is a deliberately long English title that sho…",
        )

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
        with self.assertRaisesRegex(CanvasGPTError, "Title cannot be empty"):
            service.rename_node(first.id, "   ")
        with self.assertRaisesRegex(CanvasGPTError, "Unknown title source"):
            service.new_node("Title", title_source="unknown")
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
            "rename": lambda: service.rename_node("missing", "Renamed"),
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
        graph = self.workspace.load_graph()
        graph.nodes[first.id].local_messages = [Message(role="user", content="First")]
        graph.nodes[second.id].local_messages = [Message(role="user", content="Second")]
        self.workspace.save_graph(graph)
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

    def test_empty_node_can_receive_and_replace_branch_parent(self) -> None:
        service = GraphService(self.workspace, FakeProvider(["First answer", "Second answer"]))
        first = service.new_node("First")
        second = service.new_node("Second")
        child = service.new_node("Untitled", title_source="placeholder")
        service.chat(first.id, "First context")
        service.chat(second.id, "Second context")

        edge = service.set_branch_parent(child.id, first.id)
        replacement = service.set_branch_parent(child.id, second.id)

        self.assertEqual((edge.source, edge.target), (first.id, child.id))
        self.assertEqual((replacement.source, replacement.target), (second.id, child.id))
        graph = self.workspace.load_graph()
        parent_edges = [
            item for item in graph.edges if item.target == child.id and item.type == "branch"
        ]
        self.assertEqual(len(parent_edges), 1)
        self.assertEqual(parent_edges[0].source, second.id)

    def test_draft_accepts_multiple_parents_and_normalizes_edge_types(self) -> None:
        service = GraphService(self.workspace)
        parents = [service.new_node(f"Parent {index}") for index in range(3)]
        child = service.new_node("Draft")
        graph = self.workspace.load_graph()
        for parent in parents:
            graph.nodes[parent.id].local_messages = [
                Message(role="user", content=f"Context from {parent.title}")
            ]
        self.workspace.save_graph(graph)

        first_edge = service.add_draft_parent(child.id, parents[0].id)
        second_edge = service.add_draft_parent(child.id, parents[1].id)
        third_edge = service.add_draft_parent(child.id, parents[2].id)

        self.assertEqual(first_edge.type, "branch")
        self.assertEqual(second_edge.type, "merge")
        self.assertEqual(third_edge.type, "merge")
        graph = self.workspace.load_graph()
        incoming = [edge for edge in graph.edges if edge.target == child.id]
        self.assertEqual([edge.source for edge in incoming], [node.id for node in parents])
        self.assertEqual({edge.type for edge in incoming}, {"merge"})
        self.assertTrue(all(edge.context_path for edge in incoming))

    def test_removing_draft_parents_restores_branch_then_plain_draft(self) -> None:
        service = GraphService(self.workspace)
        parents = [service.new_node(f"Parent {index}") for index in range(3)]
        child = service.new_node("Draft")
        graph = self.workspace.load_graph()
        for parent in parents:
            graph.nodes[parent.id].local_messages = [
                Message(role="user", content=f"Context from {parent.title}")
            ]
        self.workspace.save_graph(graph)
        for parent in parents:
            service.add_draft_parent(child.id, parent.id)

        remaining = service.remove_draft_parent(child.id, parents[1].id)
        self.assertEqual(len(remaining), 2)
        self.assertEqual({edge.type for edge in remaining}, {"merge"})

        remaining = service.remove_draft_parent(child.id, parents[2].id)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].type, "branch")

        remaining = service.remove_draft_parent(child.id, parents[0].id)
        self.assertEqual(remaining, [])

    def test_draft_parent_validation_rejects_duplicate_cycle_and_limit(self) -> None:
        service = GraphService(self.workspace)
        parents = [
            service.new_node(f"Parent {index}")
            for index in range(MAX_DRAFT_PARENTS + 1)
        ]
        child = service.new_node("Draft")
        graph = self.workspace.load_graph()
        for parent in parents:
            graph.nodes[parent.id].local_messages = [
                Message(role="user", content=f"Context from {parent.title}")
            ]
        self.workspace.save_graph(graph)
        service.add_draft_parent(child.id, parents[0].id)

        with self.assertRaisesRegex(CanvasGPTError, "already a parent"):
            service.add_draft_parent(child.id, parents[0].id)

        for parent in parents[1:MAX_DRAFT_PARENTS]:
            service.add_draft_parent(child.id, parent.id)
        with self.assertRaisesRegex(CanvasGPTError, "at most 8"):
            service.add_draft_parent(child.id, parents[-1].id)

    def test_child_limit_is_enforced_without_hiding_the_reason(self) -> None:
        service = GraphService(self.workspace)
        parent = service.new_node("Parent")
        graph = self.workspace.load_graph()
        graph.nodes[parent.id].local_messages = [Message(role="user", content="Parent")]
        self.workspace.save_graph(graph)

        for index in range(MAX_NODE_CHILDREN):
            service.branch(parent.id, f"Child {index}")

        with self.assertRaisesRegex(CanvasGPTError, "maximum of 50 children"):
            service.branch(parent.id, "One too many")

        graph = self.workspace.load_graph()
        self.assertEqual(len(self._structural_children(graph, parent.id)), MAX_NODE_CHILDREN)

    def test_first_message_commits_merge_draft_without_mutating_parents(self) -> None:
        provider = FakeProvider(["Merged answer"])
        service = GraphService(self.workspace, provider)
        first = service.new_node("First")
        second = service.new_node("Second")
        child = service.new_node("Untitled", title_source="placeholder")
        graph = self.workspace.load_graph()
        graph.nodes[first.id].local_messages = [
            Message(role="user", content="Frozen first context")
        ]
        graph.nodes[second.id].local_messages = [
            Message(role="user", content="Frozen second context")
        ]
        self.workspace.save_graph(graph)
        service.add_draft_parent(child.id, first.id)
        service.add_draft_parent(child.id, second.id)

        graph = self.workspace.load_graph()
        graph.nodes[first.id].local_messages.append(
            Message(role="user", content="Late parent change")
        )
        self.workspace.save_graph(graph)
        parents_before = {
            node_id: list(self.workspace.load_graph().nodes[node_id].local_messages)
            for node_id in (first.id, second.id)
        }

        response = service.chat(child.id, "Keep agreements and surface conflicts")

        self.assertEqual(response, "Merged answer")
        prompt = provider.calls[0][0][0].content
        self.assertIn("Frozen first context", prompt)
        self.assertIn("Frozen second context", prompt)
        self.assertNotIn("Late parent change", prompt)
        updated = service.get_node(child.id)
        self.assertEqual(updated.kind, "merge")
        self.assertEqual(updated.title, "Merge: First + Second")
        self.assertIn("Goal: Keep agreements and surface conflicts", updated.local_messages[0].content)
        graph = self.workspace.load_graph()
        self.assertEqual(
            {node_id: graph.nodes[node_id].local_messages for node_id in parents_before},
            parents_before,
        )
        with self.assertRaisesRegex(CanvasGPTError, "parents are locked"):
            service.remove_draft_parent(child.id, first.id)

    def test_failed_merge_draft_commit_preserves_node_and_wiring(self) -> None:
        service = GraphService(self.workspace, FailingProvider())
        first = service.new_node("First")
        second = service.new_node("Second")
        child = service.new_node("Draft")
        graph = self.workspace.load_graph()
        graph.nodes[first.id].local_messages = [Message(role="user", content="First")]
        graph.nodes[second.id].local_messages = [Message(role="user", content="Second")]
        self.workspace.save_graph(graph)
        service.add_draft_parent(child.id, first.id)
        service.add_draft_parent(child.id, second.id)
        before = self.workspace.load_graph().to_dict()

        with self.assertRaisesRegex(ProviderError, "simulated failure"):
            service.chat(child.id, "Merge these")

        self.assertEqual(self.workspace.load_graph().to_dict(), before)

    def test_draft_cannot_have_children(self) -> None:
        service = GraphService(self.workspace)
        draft = service.new_node("Draft")
        child = service.new_node("Child")

        with self.assertRaisesRegex(CanvasGPTError, "Draft cannot have children"):
            service.branch(draft.id, "Not allowed")
        with self.assertRaisesRegex(CanvasGPTError, "Draft cannot have children"):
            service.add_draft_parent(child.id, draft.id)

    def test_committed_parent_is_immutable_and_merge_draft_preserves_sources(self) -> None:
        service = GraphService(
            self.workspace,
            FakeProvider(["Old answer", "New answer", "Child answer"]),
        )
        old_parent = service.new_node("Old parent")
        new_parent = service.new_node("New parent")
        service.chat(old_parent.id, "Old context")
        service.chat(new_parent.id, "New context")
        child = service.branch(old_parent.id, "Child")
        service.chat(child.id, "Child context")

        before = service.context_messages(child.id)
        with self.assertRaisesRegex(CanvasGPTError, "cannot be replaced"):
            service.set_branch_parent(child.id, new_parent.id)
        with self.assertRaisesRegex(CanvasGPTError, "cannot be changed"):
            service.attach_parent(child.id, new_parent.id)

        successor = service.new_merge_draft([child.id, new_parent.id])

        self.assertEqual(service.context_messages(child.id), before)
        self.assertEqual(
            [message.content for message in service.get_node(child.id).local_messages],
            ["Child context", "Child answer"],
        )
        graph = self.workspace.load_graph()
        incoming = self._incoming_structural_edges(graph, successor.id)
        self.assertEqual({edge.source for edge in incoming}, {child.id, new_parent.id})
        self.assertTrue(all(edge.type == "merge" for edge in incoming))

    def test_empty_node_can_be_deleted_but_history_node_cannot(self) -> None:
        service = GraphService(self.workspace, FakeProvider(["Initial answer", "Later answer"]))
        parent = service.new_node("Parent")
        service.chat(parent.id, "Start parent")
        empty = service.branch(parent.id, "Accidental")
        related = service.new_node("Related")
        service.connect(empty.id, related.id, "reference")

        deleted = service.delete_node(empty.id)

        self.assertEqual(deleted.id, empty.id)
        graph = self.workspace.load_graph()
        self.assertNotIn(empty.id, graph.nodes)
        self.assertFalse(
            any(edge.source == empty.id or edge.target == empty.id for edge in graph.edges)
        )

        service.chat(parent.id, "Keep this")
        with self.assertRaisesRegex(CanvasGPTError, "history cannot be deleted"):
            service.delete_node(parent.id)

    def test_edge_delete_rules_keep_committed_parent_atomic(self) -> None:
        service = GraphService(self.workspace, FakeProvider(["Child answer"]))
        first = service.new_node("First")
        second = service.new_node("Second")
        draft = service.new_node("Draft")
        graph = self.workspace.load_graph()
        graph.nodes[first.id].local_messages = [Message(role="user", content="First")]
        graph.nodes[second.id].local_messages = [Message(role="user", content="Second")]
        self.workspace.save_graph(graph)
        service.add_draft_parent(draft.id, first.id)

        removed = service.delete_edge(first.id, draft.id, "branch")
        self.assertEqual(removed.type, "branch")
        self.assertEqual(service.context_messages(draft.id), [])

        service.add_draft_parent(draft.id, first.id)
        service.chat(draft.id, "Commit child")
        with self.assertRaisesRegex(CanvasGPTError, "cannot be deleted or replaced"):
            service.delete_edge(first.id, draft.id, "branch")

        with self.assertRaisesRegex(CanvasGPTError, "cannot be changed"):
            service.attach_parent(draft.id, second.id)
        successor = service.new_merge_draft([draft.id, second.id])
        graph = self.workspace.load_graph()
        incoming = self._incoming_structural_edges(graph, successor.id)
        self.assertEqual({edge.source for edge in incoming}, {draft.id, second.id})

    def test_empty_node_cannot_be_a_branch_parent(self) -> None:
        service = GraphService(self.workspace)
        parent = service.new_node("Empty parent")
        child = service.new_node("Empty child")

        with self.assertRaisesRegex(CanvasGPTError, "Draft cannot have children"):
            service.set_branch_parent(child.id, parent.id)

    def test_branch_cycle_is_rejected_when_loading_context(self) -> None:
        from canvas_gpt.models import Edge

        service = GraphService(self.workspace)
        first = service.new_node("First")
        graph = self.workspace.load_graph()
        graph.nodes[first.id].local_messages = [Message(role="user", content="First")]
        self.workspace.save_graph(graph)
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
        graph = self.workspace.load_graph()
        graph.nodes[first.id].local_messages = [Message(role="user", content="First")]
        self.workspace.save_graph(graph)
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
