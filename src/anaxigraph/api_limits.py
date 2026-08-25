"""Hard request-size boundary shared by REST and mounted MCP traffic."""

from __future__ import annotations

import json
from typing import Any

MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024


class RequestBodyLimitMiddleware:
    def __init__(self, app: Any, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") not in {
            "POST",
            "PUT",
            "PATCH",
        }:
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _reject(send, self.max_bytes)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                await self.app(scope, _single_message(message), send)
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await _reject(send, self.max_bytes)
                return
            if not message.get("more_body", False):
                break
        await self.app(scope, _body_receiver(bytes(body)), send)


def _content_length(scope: dict[str, Any]) -> int | None:
    for key, value in scope.get("headers") or ():
        if key.lower() == b"content-length":
            try:
                return max(0, int(value))
            except ValueError:
                return None
    return None


def _body_receiver(body: bytes):
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _single_message(message: dict[str, Any]):
    async def receive() -> dict[str, Any]:
        return message

    return receive


async def _reject(send: Any, max_bytes: int) -> None:
    payload = json.dumps({"detail": f"Request body exceeds the {max_bytes}-byte limit"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
