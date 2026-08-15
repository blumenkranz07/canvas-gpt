from __future__ import annotations

import os
from typing import Sequence

from ..errors import ProviderError
from ..models import Config, Message


class AnthropicProvider:
    def __init__(self, config: Config) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Add it to your environment before using chat or merge."
            )
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderError("Anthropic SDK is not installed. Run `pip install -e .`.") from exc
        self.client = Anthropic(api_key=api_key)
        self.model = config.model
        self.max_output_tokens = config.max_output_tokens

    def generate(self, messages: Sequence[Message], *, system_prompt: str) -> str:
        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                max_tokens=self.max_output_tokens,
                messages=[{"role": message.role, "content": message.content} for message in messages],
            )
        except Exception as exc:
            raise ProviderError(f"Anthropic request failed: {exc}") from exc
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise ProviderError("Anthropic returned an empty text response.")
        return text

