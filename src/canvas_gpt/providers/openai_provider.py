from __future__ import annotations

import os
from typing import Sequence

from ..errors import ProviderError
from ..models import Config, Message


class OpenAIProvider:
    def __init__(self, config: Config) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError(
                "OPENAI_API_KEY is not set. Add it to your environment before using chat or merge."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError("OpenAI SDK is not installed. Run `pip install -e .`.") from exc
        self.client = OpenAI(api_key=api_key)
        self.model = config.model
        self.max_output_tokens = config.max_output_tokens

    def generate(self, messages: Sequence[Message], *, system_prompt: str) -> str:
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=[{"role": message.role, "content": message.content} for message in messages],
                max_output_tokens=self.max_output_tokens,
            )
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc
        text = response.output_text.strip()
        if not text:
            raise ProviderError("OpenAI returned an empty text response.")
        return text

