from __future__ import annotations

from ..errors import CanvasGPTError
from ..models import Config
from .anthropic_provider import AnthropicProvider
from .base import Provider
from .openai_provider import OpenAIProvider


def build_provider(config: Config, *, allow_fake: bool = False) -> Provider:
    if config.provider == "openai":
        return OpenAIProvider(config)
    if config.provider == "anthropic":
        return AnthropicProvider(config)
    if config.provider == "fake" and allow_fake:
        from .fake_provider import FakeProvider

        return FakeProvider()
    raise CanvasGPTError(f"Unsupported provider: {config.provider}")


__all__ = ["Provider", "build_provider"]
