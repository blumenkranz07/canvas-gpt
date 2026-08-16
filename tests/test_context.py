from __future__ import annotations

import unittest

from canvas_gpt.context import ContextPlanner, PortableTokenEstimator
from canvas_gpt.errors import ContextBudgetError
from canvas_gpt.models import Config, Message


class ContextPlannerTests(unittest.TestCase):
    def test_portable_estimator_handles_ascii_and_cjk_without_dependencies(self) -> None:
        estimator = PortableTokenEstimator()

        self.assertEqual(estimator.estimate_text("abcdef"), 2)
        self.assertEqual(estimator.estimate_text("上下文"), 3)
        self.assertEqual(estimator.estimate_text(""), 0)

    def test_plan_reports_each_part_of_the_budget(self) -> None:
        planner = ContextPlanner()
        config = Config(max_output_tokens=100, context_window_tokens=1_000)

        budget = planner.plan(
            [Message(role="user", content="hello")],
            system_prompt="system",
            config=config,
        )

        self.assertEqual(budget.context_window_tokens, 1_000)
        self.assertEqual(budget.estimated_input_tokens, 13)
        self.assertEqual(budget.reserved_output_tokens, 100)
        self.assertEqual(budget.safety_margin_tokens, 256)
        self.assertEqual(budget.available_input_tokens, 644)
        self.assertEqual(budget.remaining_input_tokens, 631)
        self.assertTrue(budget.fits)

    def test_require_fit_raises_an_actionable_error(self) -> None:
        planner = ContextPlanner()
        config = Config(max_output_tokens=100, context_window_tokens=500)

        with self.assertRaisesRegex(
            ContextBudgetError,
            r"estimated input .* available input .*context window 500",
        ):
            planner.require_fit(
                [Message(role="user", content="x" * 1_000)],
                system_prompt="system",
                config=config,
            )


if __name__ == "__main__":
    unittest.main()
