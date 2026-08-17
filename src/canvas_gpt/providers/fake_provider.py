from __future__ import annotations

from typing import Sequence

from ..models import Message


class FakeProvider:
    """Development-only provider that echoes the exact request into the conversation."""

    def generate(self, messages: Sequence[Message], *, system_prompt: str) -> str:
        context = "\n\n".join(
            f"[{index}] {message.role.upper()}\n{message.content}"
            for index, message in enumerate(messages, start=1)
        )
        response = (
            "【FAKE · Request echo】\n\n"
            f"--- SYSTEM ---\n{system_prompt}\n\n"
            "--- MESSAGES ---\n"
            f"{context or '[No messages]'}"
        )
        print(response, flush=True)
        return response
