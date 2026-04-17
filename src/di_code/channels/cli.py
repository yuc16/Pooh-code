from __future__ import annotations

from .base import Channel
from ..models import InboundMessage


class CLIChannel(Channel):
    def receive(self, prompt_text: str = "You > ") -> InboundMessage | None:
        try:
            text = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not text:
            return None
        return InboundMessage(
            text=text,
            sender_id="cli-user",
            channel="cli",
            account_id="local",
            peer_id="cli-user",
            chat_id="cli-user",
            reply_target_id="cli-user",
            reply_target_type="peer_id",
        )

    def send(self, peer_id: str, text: str, **kwargs) -> bool:
        _ = peer_id, kwargs
        print(f"\ndi-code> {text}\n")
        return True
