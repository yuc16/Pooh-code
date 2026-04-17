from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import InboundMessage


class Channel(ABC):
    @abstractmethod
    def receive(self) -> InboundMessage | None:
        raise NotImplementedError

    @abstractmethod
    def send(self, peer_id: str, text: str, **kwargs) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        return None
