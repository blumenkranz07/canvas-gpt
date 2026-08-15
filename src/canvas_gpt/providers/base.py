from __future__ import annotations

from typing import Protocol, Sequence

from ..models import Message


class Provider(Protocol):
    def generate(self, messages: Sequence[Message], *, system_prompt: str) -> str:
        """Generate one assistant response for the supplied conversation."""

