from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Protocol, Sequence

from .errors import ContextBudgetError
from .models import Config, Message


SAFETY_MARGIN_RATIO = 0.05
MINIMUM_SAFETY_MARGIN_TOKENS = 256
MESSAGE_OVERHEAD_TOKENS = 4
REQUEST_OVERHEAD_TOKENS = 3


class TokenEstimator(Protocol):
    def estimate_text(self, text: str) -> int:
        """Estimate the number of model input tokens in text."""


class PortableTokenEstimator:
    """Provider-neutral estimate that works without tokenizer dependencies.

    UTF-8 bytes divided by three is intentionally more conservative than the
    common four-ASCII-characters-per-token rule while remaining practical for
    CJK text. The context planner adds a separate safety margin because no
    provider-neutral heuristic can be exact for every model.
    """

    def estimate_text(self, text: str) -> int:
        if not text:
            return 0
        return ceil(len(text.encode("utf-8")) / 3)


@dataclass(slots=True, frozen=True)
class ContextBudget:
    context_window_tokens: int
    estimated_input_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int

    @property
    def available_input_tokens(self) -> int:
        return max(
            0,
            self.context_window_tokens
            - self.reserved_output_tokens
            - self.safety_margin_tokens,
        )

    @property
    def remaining_input_tokens(self) -> int:
        return self.available_input_tokens - self.estimated_input_tokens

    @property
    def fits(self) -> bool:
        return self.remaining_input_tokens >= 0

    @property
    def utilization(self) -> float:
        if self.available_input_tokens == 0:
            return 1.0
        return self.estimated_input_tokens / self.available_input_tokens


class ContextPlanner:
    def __init__(self, estimator: TokenEstimator | None = None) -> None:
        self.estimator = estimator or PortableTokenEstimator()

    def plan(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str,
        config: Config,
    ) -> ContextBudget:
        estimated_input_tokens = (
            self.estimator.estimate_text(system_prompt)
            + sum(
                self.estimator.estimate_text(message.role)
                + self.estimator.estimate_text(message.content)
                + MESSAGE_OVERHEAD_TOKENS
                for message in messages
            )
            + REQUEST_OVERHEAD_TOKENS
        )
        safety_margin_tokens = max(
            MINIMUM_SAFETY_MARGIN_TOKENS,
            ceil(config.context_window_tokens * SAFETY_MARGIN_RATIO),
        )
        return ContextBudget(
            context_window_tokens=config.context_window_tokens,
            estimated_input_tokens=estimated_input_tokens,
            reserved_output_tokens=config.max_output_tokens,
            safety_margin_tokens=safety_margin_tokens,
        )

    def require_fit(
        self,
        messages: Sequence[Message],
        *,
        system_prompt: str,
        config: Config,
    ) -> ContextBudget:
        budget = self.plan(messages, system_prompt=system_prompt, config=config)
        if not budget.fits:
            raise ContextBudgetError(
                "Context budget exceeded before provider request: "
                f"estimated input {budget.estimated_input_tokens} tokens, "
                f"available input {budget.available_input_tokens} tokens "
                f"(context window {budget.context_window_tokens} - "
                f"output reserve {budget.reserved_output_tokens} - "
                f"safety margin {budget.safety_margin_tokens}). "
                "Reduce the selected context, lower max output tokens, or increase "
                "the configured context window."
            )
        return budget
