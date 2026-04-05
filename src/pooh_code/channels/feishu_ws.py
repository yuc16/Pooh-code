from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any

import httpx
import lark_oapi as lark
from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1

from ..config import FeishuConfig
from ..models import InboundMessage


class FeishuWebSocketChannel:
    def __init__(self, config: FeishuConfig) -> None:
        self.config = config
        self._queue: "queue.Queue[InboundMessage]" = queue.Queue()
        self._http = httpx.Client(timeout=20.0)
        self._tenant_token = ""
        self._token_expires_at = 0.0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )
        domain = (
            lark.core.const.LARK_DOMAIN
            if self.config.domain.lower() == "lark"
            else lark.core.const.FEISHU_DOMAIN
        )
        client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=handler,
            domain=domain,
        )
        self._thread = threading.Thread(target=client.start, daemon=True, name="feishu-ws")
        self._thread.start()

    def receive(self, timeout: float = 1.0) -> InboundMessage | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _on_message(self, data: P2ImMessageReceiveV1) -> None:
        event = data.event
        if event is None or event.message is None or event.sender is None:
            return
        message = event.message
        sender = event.sender
        sender_id = ""
        if sender.sender_id is not None:
            sender_id = (
                sender.sender_id.open_id
                or sender.sender_id.user_id
                or sender.sender_id.union_id
                or ""
            )
        if sender.sender_type and sender.sender_type.lower() == "app":
            return

        text = self._parse_message_content(message.message_type or "text", message.content or "{}")
        if not text:
            return
        if message.chat_type == "group" and self.config.bot_open_id:
            mentioned = any(
                (mention.id and mention.id.open_id == self.config.bot_open_id)
                or mention.key == self.config.bot_open_id
                for mention in (message.mentions or [])
            )
            if not mentioned:
                return

        inbound = InboundMessage(
            text=text,
            sender_id=sender_id or "unknown",
            channel="feishu",
            account_id=self.config.app_id,
            peer_id=message.chat_id or sender_id or "unknown",
            chat_id=message.chat_id or sender_id or "unknown",
            is_group=message.chat_type == "group",
            raw={"message_id": message.message_id},
        )
        self._queue.put(inbound)

    def _parse_message_content(self, message_type: str, content: str) -> str:
        try:
            payload = json.loads(content)
        except Exception:
            return ""
        if message_type == "text":
            return (payload.get("text") or "").strip()
        if message_type == "post":
            lines = []
            for value in payload.values():
                if not isinstance(value, dict):
                    continue
                title = value.get("title")
                if title:
                    lines.append(title)
                for paragraph in value.get("content", []):
                    for node in paragraph:
                        if node.get("tag") == "text":
                            lines.append(node.get("text", ""))
            return "\n".join(line for line in lines if line).strip()
        return ""

    def _refresh_token(self) -> str:
        if self._tenant_token and time.time() < self._token_expires_at:
            return self._tenant_token
        api_base = (
            "https://open.larksuite.com/open-apis"
            if self.config.domain.lower() == "lark"
            else "https://open.feishu.cn/open-apis"
        )
        response = self._http.post(
            f"{api_base}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("msg", "failed to refresh tenant token"))
        self._tenant_token = payload.get("tenant_access_token", "")
        self._token_expires_at = time.time() + int(payload.get("expire", 7200)) - 300
        return self._tenant_token

    def send(self, peer_id: str, text: str, **kwargs: Any) -> bool:
        _ = kwargs
        token = self._refresh_token()
        api_base = (
            "https://open.larksuite.com/open-apis"
            if self.config.domain.lower() == "lark"
            else "https://open.feishu.cn/open-apis"
        )
        response = self._http.post(
            f"{api_base}/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": peer_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("code") == 0

    def close(self) -> None:
        self._http.close()
