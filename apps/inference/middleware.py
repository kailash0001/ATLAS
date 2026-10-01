import logging
import re
import time
from uuid import uuid4

from starlette.responses import JSONResponse

logger = logging.getLogger("aegis.http")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class RequestMiddleware:
    """Bounded body buffering, correlation, redacted errors and bounded metric labels."""

    def __init__(self, app, metrics, max_bytes: int):
        self.app, self.metrics, self.max_bytes = app, metrics, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        request_id = supplied if SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.perf_counter()
        status = 500
        response_started = False

        async def observed_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        async def fail(code, message, http_status):
            response = JSONResponse(
                {"error": {"code": code, "message": message, "request_id": request_id}},
                status_code=http_status,
            )
            await response(scope, receive, observed_send)

        try:
            receiver = receive
            if scope["method"] in {"POST", "PUT", "PATCH"}:
                chunks, size = [], 0
                while True:
                    chunk = await receive()
                    if chunk["type"] == "http.disconnect":
                        return
                    body = chunk.get("body", b"")
                    size += len(body)
                    if size > self.max_bytes:
                        await fail(
                            "PAYLOAD_TOO_LARGE", "Request body exceeds configured limit", 413
                        )
                        return
                    chunks.append(body)
                    if not chunk.get("more_body", False):
                        break
                buffered = b"".join(chunks)
                sent = False

                async def replay():
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {"type": "http.request", "body": buffered, "more_body": False}
                    return await receive()

                receiver = replay
            await self.app(scope, receiver, observed_send)
        except Exception as exc:
            logger.error(
                "request_failed",
                extra={"context": {"request_id": request_id, "error_type": type(exc).__name__}},
            )
            if response_started:
                raise
            await fail("INTERNAL_ERROR", "Request could not be completed", 500)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            method = (
                scope["method"]
                if scope["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
                else "OTHER"
            )
            elapsed = time.perf_counter() - start
            self.metrics.requests.labels(method, route, str(status)).inc()
            self.metrics.latency.labels(method, route).observe(elapsed)
            logger.info(
                "http_request",
                extra={
                    "context": {
                        "request_id": request_id,
                        "method": method,
                        "route": route,
                        "status": status,
                        "duration_ms": elapsed * 1000,
                    }
                },
            )
