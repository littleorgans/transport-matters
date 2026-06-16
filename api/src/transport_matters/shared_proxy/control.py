"""Unix-domain-socket control channel for the shared proxy subprocess."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

from transport_matters.shared_proxy.models import (
    REQUEST_ADAPTER,
    RESPONSE_ADAPTER,
    PingRequest,
    SharedProxyControlAck,
    SharedProxyControlErrorResponse,
    SharedProxyControlRequest,
    request_to_json_bytes,
    response_to_json_bytes,
)

LOGGER = logging.getLogger(__name__)
CONTROL_SOCKET_LIMIT = 1_048_576


class SharedProxyControlError(RuntimeError):
    """Control channel failure with a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SharedProxyControlClient:
    """Client for one-request-per-connection UDS control messages."""

    def __init__(self, socket_path: Path, *, request_timeout_s: float = 5.0) -> None:
        self.socket_path = socket_path
        self.request_timeout_s = request_timeout_s

    async def ping(self) -> SharedProxyControlAck:
        return await self.request(PingRequest())

    async def request(self, request: SharedProxyControlRequest) -> SharedProxyControlAck:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self.socket_path), limit=CONTROL_SOCKET_LIMIT),
                timeout=self.request_timeout_s,
            )
        except OSError as exc:
            raise SharedProxyControlError("control_unavailable", str(exc)) from exc
        except TimeoutError as exc:
            msg = "shared proxy control socket did not accept a connection before timeout"
            raise SharedProxyControlError("control_connect_timeout", msg) from exc

        try:
            writer.write(request_to_json_bytes(request))
            await asyncio.wait_for(writer.drain(), timeout=self.request_timeout_s)
            raw = await asyncio.wait_for(reader.readline(), timeout=self.request_timeout_s)
        except TimeoutError as exc:
            msg = "shared proxy control request timed out"
            raise SharedProxyControlError("control_request_timeout", msg) from exc
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

        if not raw:
            msg = "shared proxy control socket closed without a response"
            raise SharedProxyControlError("control_closed", msg)
        try:
            response = RESPONSE_ADAPTER.validate_json(raw)
        except ValidationError as exc:
            msg = "shared proxy control response failed validation"
            raise SharedProxyControlError("invalid_control_response", msg) from exc
        if isinstance(response, SharedProxyControlErrorResponse):
            raise SharedProxyControlError(response.code, response.message)
        return response

    async def wait_until_ready(self, *, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        last_error: SharedProxyControlError | None = None
        while time.monotonic() < deadline:
            try:
                await self.ping()
                return
            except SharedProxyControlError as exc:
                last_error = exc
                await asyncio.sleep(0.05)
        detail = f": {last_error.message}" if last_error is not None else ""
        msg = f"shared proxy control socket was not ready before timeout{detail}"
        raise SharedProxyControlError("control_ready_timeout", msg)


RequestHandler = Callable[[SharedProxyControlRequest], Awaitable[SharedProxyControlAck]]


class SharedProxyControlServer:
    """Local UDS server for typed shared proxy control messages."""

    def __init__(self, socket_path: Path, handler: RequestHandler) -> None:
        self.socket_path = socket_path
        self._handler = handler
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.socket_path.parent.chmod(0o700)
        with contextlib.suppress(FileNotFoundError):
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(self.socket_path),
            limit=CONTROL_SOCKET_LIMIT,
        )
        self.socket_path.chmod(0o600)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        with contextlib.suppress(FileNotFoundError):
            self.socket_path.unlink()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.readline()
            response = await self._dispatch(raw)
            writer.write(response_to_json_bytes(response))
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _dispatch(
        self,
        raw: bytes,
    ) -> SharedProxyControlAck | SharedProxyControlErrorResponse:
        if not raw:
            return SharedProxyControlErrorResponse(
                code="empty_control_request",
                message="control request was empty",
            )
        try:
            request = REQUEST_ADAPTER.validate_json(raw)
        except ValidationError:
            return SharedProxyControlErrorResponse(
                code="invalid_control_request",
                message="control request failed validation",
            )
        try:
            return await self._handler(request)
        except SharedProxyControlError as exc:
            return SharedProxyControlErrorResponse(code=exc.code, message=exc.message)
        except Exception:
            LOGGER.exception("shared proxy control handler failed")
            return SharedProxyControlErrorResponse(
                code="control_handler_error",
                message="shared proxy control handler failed",
            )
