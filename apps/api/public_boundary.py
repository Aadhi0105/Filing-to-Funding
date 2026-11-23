"""Resource limits and response safeguards for the anonymous HTTP API."""

import asyncio
import math
import re
from time import monotonic

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_BODY_BYTES = 4096
MAX_QUERY_BYTES = 2048
MAX_PATH_CHARS = 512
BODY_TIMEOUT_SECONDS = 5
FUNDING_SCENARIO_PATH = "/api/v1/funding/scenario"
SIGNED_DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?\Z")
FORMULA_PREFIX = re.compile(r"^[\x00-\x20]*[=+@\-＝＋＠－]|^[ ]*[\t\n\r]")

RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def csv_cell(value):
    if isinstance(value, str) and FORMULA_PREFIX.search(value) and not SIGNED_DECIMAL.fullmatch(value):
        return "'" + value
    return value


class RejectedRequest(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


def check_request(scope: Scope, expects_json: bool):
    if len(scope["path"]) > MAX_PATH_CHARS or len(scope["query_string"]) > MAX_QUERY_BYTES:
        raise RejectedRequest(414, "Request URL is too long.")
    if not expects_json:
        return

    body_headers = {}
    for key, value in scope["headers"]:
        if key in (b"content-length", b"content-type", b"content-encoding"):
            if key in body_headers:
                raise RejectedRequest(400, "Request body headers are invalid.")
            body_headers[key] = value

    length = body_headers.get(b"content-length")
    if length is not None:
        if not length.isdigit():
            raise RejectedRequest(400, "Request body length is invalid.")
        if len(length) > 10 or int(length) > MAX_BODY_BYTES:
            raise RejectedRequest(413, "Request body is too large.")

    mime = body_headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
    encoding = body_headers.get(b"content-encoding", b"identity").strip().lower()
    if mime != b"application/json" or encoding != b"identity":
        raise RejectedRequest(415, "Use an uncompressed application/json request body.")


async def bounded_body(receive: Receive):
    body = bytearray()
    try:
        async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return None
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    raise RejectedRequest(413, "Request body is too large.")
                body.extend(chunk)
                if not message.get("more_body", False):
                    return bytes(body)
    except TimeoutError:
        raise RejectedRequest(408, "Request body timed out.") from None


class PublicBoundary:
    """Bound each API process independently of client-supplied proxy headers."""

    def __init__(self, app: ASGIApp, *, rate=20, burst=40, concurrent=4, clock=monotonic):
        self.app = app
        self.rate = rate
        self.burst = burst
        self.concurrent = concurrent
        self.clock = clock
        self.last_check = clock()
        self.tokens = burst
        self.in_flight = 0

    def admit(self):
        current = self.clock()
        self.tokens = min(self.burst, self.tokens + (current - self.last_check) * self.rate)
        self.last_check = current
        if self.in_flight >= self.concurrent:
            return 1
        if self.tokens < 1:
            return max(1, math.ceil((1 - self.tokens) / self.rate))
        self.tokens -= 1
        self.in_flight += 1
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in RESPONSE_HEADERS.items():
                    headers[key] = value
                if scope["path"].startswith("/api/"):
                    headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
            await send(message)

        async def reject(status, detail, headers=None):
            response = JSONResponse({"detail": detail}, status_code=status, headers=headers)
            await response(scope, receive, secure_send)

        expects_json = scope["method"] == "POST" and scope["path"] == FUNDING_SCENARIO_PATH
        try:
            check_request(scope, expects_json)
        except RejectedRequest as error:
            await reject(error.status, str(error))
            return

        retry_after = self.admit()
        if retry_after is not None:
            await reject(429, "The API is busy. Try again shortly.", {"Retry-After": str(retry_after)})
            return

        try:
            if not expects_json:
                await self.app(scope, receive, secure_send)
                return
            try:
                body = await bounded_body(receive)
            except RejectedRequest as error:
                await reject(error.status, str(error))
                return
            if body is None:
                return

            async def replay_body():
                nonlocal body
                if body is not None:
                    message = {"type": "http.request", "body": body, "more_body": False}
                    body = None
                    return message
                return await receive()

            await self.app(scope, replay_body, secure_send)
        finally:
            self.in_flight -= 1
