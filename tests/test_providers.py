from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from canvas_gpt.errors import ProviderError
from canvas_gpt.models import Config, Message
from canvas_gpt.providers.anthropic_provider import AnthropicProvider
from canvas_gpt.providers.openai_provider import OpenAIProvider


class RecordingEndpoint:
    def __init__(self, response: object) -> None:
        self.response = response
        self.kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return self.response


class RaisingEndpoint:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create(self, **kwargs: object) -> object:
        raise self.error


class ProviderTests(unittest.TestCase):
    def test_openai_provider_uses_responses_api_payload(self) -> None:
        endpoint = RecordingEndpoint(SimpleNamespace(output_text=" OpenAI answer "))
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.client = SimpleNamespace(responses=endpoint)
        provider.model = "gpt-test"
        provider.max_output_tokens = 123

        result = provider.generate([Message("user", "Hello")], system_prompt="System")

        self.assertEqual(result, "OpenAI answer")
        self.assertEqual(endpoint.kwargs["model"], "gpt-test")
        self.assertEqual(endpoint.kwargs["instructions"], "System")
        self.assertEqual(endpoint.kwargs["input"], [{"role": "user", "content": "Hello"}])

    def test_anthropic_provider_uses_messages_api_payload(self) -> None:
        response = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="Claude "),
                SimpleNamespace(type="tool_use"),
                SimpleNamespace(type="text", text="answer"),
            ]
        )
        endpoint = RecordingEndpoint(response)
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.client = SimpleNamespace(messages=endpoint)
        provider.model = "claude-test"
        provider.max_output_tokens = 456

        result = provider.generate([Message("user", "Hello")], system_prompt="System")

        self.assertEqual(result, "Claude answer")
        self.assertEqual(endpoint.kwargs["model"], "claude-test")
        self.assertEqual(endpoint.kwargs["system"], "System")
        self.assertEqual(endpoint.kwargs["messages"], [{"role": "user", "content": "Hello"}])

    def test_missing_keys_fail_before_a_request(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderError):
                OpenAIProvider(Config())
            with self.assertRaises(ProviderError):
                AnthropicProvider(Config(provider="anthropic", model="claude-test"))

    def test_empty_provider_responses_are_rejected(self) -> None:
        openai_provider = OpenAIProvider.__new__(OpenAIProvider)
        openai_provider.client = SimpleNamespace(
            responses=RecordingEndpoint(SimpleNamespace(output_text="   "))
        )
        openai_provider.model = "gpt-test"
        openai_provider.max_output_tokens = 10

        anthropic_provider = AnthropicProvider.__new__(AnthropicProvider)
        anthropic_provider.client = SimpleNamespace(
            messages=RecordingEndpoint(
                SimpleNamespace(content=[SimpleNamespace(type="text", text="   ")])
            )
        )
        anthropic_provider.model = "claude-test"
        anthropic_provider.max_output_tokens = 10

        with self.assertRaisesRegex(ProviderError, "empty text response"):
            openai_provider.generate([Message("user", "Hello")], system_prompt="System")
        with self.assertRaisesRegex(ProviderError, "empty text response"):
            anthropic_provider.generate([Message("user", "Hello")], system_prompt="System")

    def test_sdk_errors_are_wrapped_as_provider_errors(self) -> None:
        openai_provider = OpenAIProvider.__new__(OpenAIProvider)
        openai_provider.client = SimpleNamespace(
            responses=RaisingEndpoint(TimeoutError("request timed out"))
        )
        openai_provider.model = "gpt-test"
        openai_provider.max_output_tokens = 10

        anthropic_provider = AnthropicProvider.__new__(AnthropicProvider)
        anthropic_provider.client = SimpleNamespace(
            messages=RaisingEndpoint(RuntimeError("rate limited"))
        )
        anthropic_provider.model = "claude-test"
        anthropic_provider.max_output_tokens = 10

        with self.assertRaisesRegex(ProviderError, "OpenAI request failed.*timed out"):
            openai_provider.generate([Message("user", "Hello")], system_prompt="System")
        with self.assertRaisesRegex(ProviderError, "Anthropic request failed.*rate limited"):
            anthropic_provider.generate([Message("user", "Hello")], system_prompt="System")


if __name__ == "__main__":
    unittest.main()
