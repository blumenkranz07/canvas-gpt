from __future__ import annotations

from ..errors import CanvasGPTError
from ..models import Config
from .anthropic_provider import AnthropicProvider
from .base import Provider
from .openai_provider import OpenAIProvider


def build_provider(config: Config) -> Provider:
    if config.provider == "openai":
        return OpenAIProvider(config)
    if config.provider == "anthropic":
        return AnthropicProvider(config)
    raise CanvasGPTError(f"Unsupported provider: {config.provider}")


__all__ = ["Provider", "build_provider"]
