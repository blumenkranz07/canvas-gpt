from __future__ import annotations

import io
import tempfile
import unittest
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from canvas_gpt.cli import main
from canvas_gpt.models import Config, Message


class FakeProvider:
    def generate(self, messages: Sequence[Message], *, system_prompt: str) -> str:
        return "CLI answer"


class CLITests(unittest.TestCase):
    def run_cli(self, root: Path, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()

        def provider_factory(config: Config) -> FakeProvider:
            return FakeProvider()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args, root=root, provider_factory=provider_factory)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_basic_cli_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, output, _ = self.run_cli(root, "init", "--provider", "openai")
            self.assertEqual(code, 0)
            self.assertIn("Initialized Canvas GPT", output)

            code, output, _ = self.run_cli(root, "new", "Research idea")
            self.assertEqual(code, 0)
            self.assertIn("Created n1", output)

            code, output, _ = self.run_cli(root, "chat", "n1", "Hello")
            self.assertEqual(code, 0)
            self.assertIn("CLI answer", output)

            code, output, _ = self.run_cli(root, "branch", "n1", "Alternative")
            self.assertEqual(code, 0)
            self.assertIn("Created n2 from n1", output)

            code, output, _ = self.run_cli(root, "rename", "n2", "Alternative path")
            self.assertEqual(code, 0)
            self.assertIn("Renamed n2: Alternative path", output)

            code, output, _ = self.run_cli(root, "chat", "n2", "Explore alternative")
            self.assertEqual(code, 0)
            self.assertIn("CLI answer", output)

            code, output, _ = self.run_cli(root, "merge", "n1", "n2")
            self.assertEqual(code, 0)
            self.assertIn("Created merge node n3", output)

            code, output, _ = self.run_cli(root, "graph")
            self.assertEqual(code, 0)
            self.assertIn("n1 --branch--> n2", output)
            self.assertIn("n1 --merge--> n3", output)

    def test_command_before_init_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, _, error = self.run_cli(Path(directory), "graph")
            self.assertEqual(code, 1)
            self.assertIn("canvas-gpt init", error)

    def test_missing_node_returns_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_cli(root, "init", "--provider", "openai")

            code, _, error = self.run_cli(root, "show", "missing")

            self.assertEqual(code, 1)
            self.assertIn("does not exist", error)

    def test_invalid_token_limits_return_cli_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, _, error = self.run_cli(
                root, "init", "--provider", "openai", "--max-output-tokens", "0"
            )
            self.assertEqual(code, 1)
            self.assertIn("greater than zero", error)

            self.run_cli(root, "init", "--provider", "openai")
            code, _, error = self.run_cli(root, "config", "--max-output-tokens", "-1")
            self.assertEqual(code, 1)
            self.assertIn("greater than zero", error)


if __name__ == "__main__":
    unittest.main()
