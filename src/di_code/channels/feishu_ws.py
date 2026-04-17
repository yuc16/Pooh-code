from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from typing import Any

import httpx
import lark_oapi as lark
from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1

from ..config import FeishuConfig
from ..models import InboundMessage
from ..paths import LOGS_DIR
from ..time_utils import shanghai_now, shanghai_now_iso


class FeishuWebSocketChannel:
    def __init__(self, config: FeishuConfig) -> None:
        self.config = config
        self._queue: "queue.Queue[InboundMessage]" = queue.Queue()
        self._http = httpx.Client(timeout=20.0)
        self._tenant_token = ""
        self._token_expires_at = 0.0
        self._thread: threading.Thread | None = None
        self._log_path = LOGS_DIR / "feishu_send.jsonl"
        self._log_lock = threading.RLock()

    def _configure_logging(self) -> None:
        logger = logging.getLogger("Lark")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)
        logger.disabled = True

    def _write_send_log(self, record: dict[str, Any]) -> None:
        payload = {"ts": shanghai_now_iso(), **record}
        acquired = self._log_lock.acquire(timeout=0.2)
        if not acquired:
            return
        try:
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception:
            return
        finally:
            self._log_lock.release()

    def start(self) -> None:
        self._configure_logging()
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
        self._configure_logging()

        def _run_client() -> None:
            self._configure_logging()
            client.start()

        self._thread = threading.Thread(target=_run_client, daemon=True, name="feishu-ws")
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
        sender_open_id = ""
        sender_user_id = ""
        sender_id = ""
        if sender.sender_id is not None:
            sender_open_id = sender.sender_id.open_id or ""
            sender_user_id = sender.sender_id.user_id or ""
            sender_id = sender_open_id or sender_user_id or sender.sender_id.union_id or ""
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

        reply_target_type = "chat_id"
        reply_target_id = message.chat_id or sender_id or "unknown"
        if not message.chat_id:
            if sender_open_id:
                reply_target_type = "open_id"
                reply_target_id = sender_open_id
            elif sender_user_id:
                reply_target_type = "user_id"
                reply_target_id = sender_user_id

        inbound = InboundMessage(
            text=text,
            sender_id=sender_id or "unknown",
            channel="feishu",
            account_id=self.config.app_id,
            peer_id=message.chat_id or sender_id or "unknown",
            chat_id=message.chat_id or sender_id or "unknown",
            is_group=message.chat_type == "group",
            reply_target_id=reply_target_id,
            reply_target_type=reply_target_type,
            raw={
                "message_id": message.message_id,
                "chat_type": message.chat_type,
                "thread_id": message.thread_id,
            },
        )
        self._write_send_log(
            {
                "event": "feishu_receive",
                "sender_id": inbound.sender_id,
                "chat_id": inbound.chat_id,
                "peer_id": inbound.peer_id,
                "reply_target_id": inbound.reply_target_id,
                "reply_target_type": inbound.reply_target_type,
                "text": inbound.text,
                "raw": inbound.raw,
            }
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
        if self._tenant_token and shanghai_now().timestamp() < self._token_expires_at:
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
        self._token_expires_at = shanghai_now().timestamp() + int(payload.get("expire", 7200)) - 300
        return self._tenant_token

    def send(self, peer_id: str, text: str, **kwargs: Any) -> bool:
        receive_id_type = kwargs.get("receive_id_type") or "chat_id"
        reply_to_message_id = kwargs.get("reply_to_message_id")
        request_body = {
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
            "uuid": uuid.uuid4().hex,
        }
        request_json = {"receive_id": peer_id, **request_body}
        request_meta = {
            "event": "feishu_send",
            "receive_id_type": receive_id_type,
            "receive_id": peer_id,
            "reply_to_message_id": reply_to_message_id or "",
            "request_json": request_json,
        }
        self._write_send_log({**request_meta, "stage": "begin"})
        try:
            token = self._refresh_token()
        except Exception as exc:
            self._write_send_log({**request_meta, "stage": "refresh_token_error", "error": str(exc)})
            raise
        api_base = (
            "https://open.larksuite.com/open-apis"
            if self.config.domain.lower() == "lark"
            else "https://open.feishu.cn/open-apis"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        request_meta = {
            **request_meta,
            "api_base": api_base,
            "endpoint": "/im/v1/messages",
        }
        try:
            response = self._http.post(
                f"{api_base}/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers=headers,
                json=request_json,
            )
            payload = self._decode_payload(response)
            self._write_send_log(
                {
                    **request_meta,
                    "http_status": response.status_code,
                    "response_headers": dict(response.headers),
                    "response_json": payload,
                }
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    "feishu send http failed: "
                    f"status={response.status_code} "
                    f"receive_id_type={receive_id_type} "
                    f"receive_id={peer_id} "
                    f"reply_to_message_id={reply_to_message_id or ''} "
                    f"payload={json.dumps(payload, ensure_ascii=False)}"
                )
            if payload.get("code") != 0:
                raise RuntimeError(
                    "feishu send failed: "
                    f"receive_id_type={receive_id_type} "
                    f"receive_id={peer_id} "
                    f"reply_to_message_id={reply_to_message_id or ''} "
                    f"code={payload.get('code')} "
                    f"msg={payload.get('msg')} "
                    f"payload={json.dumps(payload, ensure_ascii=False)}"
                )
            return True
        except Exception as exc:
            self._write_send_log(
                {
                    **request_meta,
                    "stage": "request_error",
                    "error": str(exc),
                }
            )
            raise

    def _decode_payload(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            payload = {"raw_text": response.text}
        if isinstance(payload, dict):
            return payload
        return {"raw_payload": payload}

    def close(self) -> None:
        self._http.close()
