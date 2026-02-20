"""OpenClaw Gateway API client."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import aiohttp

from .const import (
    API_CHAT_COMPLETIONS,
    API_MODELS,
)

_LOGGER = logging.getLogger(__name__)

# Timeout for regular API calls (seconds)
API_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Timeout for streaming chat completions (long-running)
STREAM_TIMEOUT = aiohttp.ClientTimeout(total=300, sock_read=120)


class OpenClawApiError(Exception):
    """Base exception for OpenClaw API errors."""


class OpenClawConnectionError(OpenClawApiError):
    """Connection to OpenClaw gateway failed."""


class OpenClawAuthError(OpenClawApiError):
    """Authentication with OpenClaw gateway failed."""


class OpenClawApiClient:
    """HTTP client for the OpenClaw gateway API.

    Communicates with the OpenClaw gateway running inside the addon container.
    Supports both regular JSON API calls and SSE streaming for chat completions.
    """

    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        use_ssl: bool = False,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client.

        Args:
            host: Gateway hostname or IP.
            port: Gateway port number.
            token: Authentication token from openclaw.json.
            use_ssl: Use HTTPS instead of HTTP.
            session: Optional aiohttp session (reused from HA).
        """
        self._host = host
        self._port = port
        self._token = token
        self._use_ssl = use_ssl
        self._session = session
        self._base_url = f"{'https' if use_ssl else 'http'}://{host}:{port}"

    @property
    def base_url(self) -> str:
        """Return the base URL of the gateway."""
        return self._base_url

    def update_token(self, token: str) -> None:
        """Update the authentication token (e.g., after addon restart)."""
        self._token = token

    def _headers(self) -> dict[str, str]:
        """Build request headers with auth token."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        timeout: aiohttp.ClientTimeout = API_TIMEOUT,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an HTTP request to the gateway.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g., /api/status).
            timeout: Request timeout.
            **kwargs: Additional arguments passed to aiohttp request.

        Returns:
            Parsed JSON response.

        Raises:
            OpenClawConnectionError: If the gateway is unreachable.
            OpenClawAuthError: If authentication fails.
            OpenClawApiError: For other API errors.
        """
        session = await self._get_session()
        url = f"{self._base_url}{path}"

        try:
            async with session.request(
                method,
                url,
                headers=self._headers(),
                timeout=timeout,
                **kwargs,
            ) as resp:
                if resp.status == 401:
                    raise OpenClawAuthError(
                        "Authentication failed — check gateway token"
                    )
                if resp.status == 403:
                    raise OpenClawAuthError(
                        "Access forbidden — token may be invalid"
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise OpenClawApiError(
                        f"API error {resp.status}: {text[:200]}"
                    )
                content_type = resp.content_type or ""
                if "json" not in content_type:
                    text = await resp.text()
                    raise OpenClawApiError(
                        f"Unexpected response content type '{content_type}' (expected JSON). "
                        f"The host/port may be wrong or the gateway returned an error page. "
                        f"Response: {text[:200]}"
                    )
                return await resp.json()

        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, asyncio.TimeoutError) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway at {url}: {err}"
            ) from err

    # ─── Public API methods ────────────────────────────────────────────

    async def async_get_models(self) -> dict[str, Any]:
        """Get available models (OpenAI-compatible).

        Returns:
            Dict with 'data' containing model objects.
        """
        return await self._request("GET", API_MODELS)

    async def async_send_message(
        self,
        message: str,
        session_id: str | None = None,
        model: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Send a chat message (non-streaming).

        Args:
            message: The user message text.
            session_id: Optional session/conversation ID.
            model: Optional model override.
            stream: If True, raises ValueError (use async_stream_message).

        Returns:
            Complete chat completion response.
        """
        if stream:
            raise ValueError("Use async_stream_message() for streaming")

        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": message}],
            "stream": False,
        }
        if model:
            payload["model"] = model

        # Pass session_id as a custom header or param if supported by gateway
        headers = self._headers()
        if session_id:
            headers["X-Session-Id"] = session_id

        session = await self._get_session()
        url = f"{self._base_url}{API_CHAT_COMPLETIONS}"

        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=STREAM_TIMEOUT,
            ) as resp:
                if resp.status == 401:
                    raise OpenClawAuthError("Authentication failed")
                if resp.status >= 400:
                    text = await resp.text()
                    raise OpenClawApiError(f"Chat error {resp.status}: {text[:200]}")
                return await resp.json()

        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, asyncio.TimeoutError) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway: {err}"
            ) from err

    async def async_stream_message(
        self,
        message: str,
        session_id: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Send a chat message and stream the response via SSE.

        Yields delta content strings as they arrive from the gateway.

        Args:
            message: The user message text.
            session_id: Optional session/conversation ID.
            model: Optional model override.

        Yields:
            Content delta strings from the streaming response.
        """
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": message}],
            "stream": True,
        }
        if model:
            payload["model"] = model

        headers = self._headers()
        if session_id:
            headers["X-Session-Id"] = session_id

        session = await self._get_session()
        url = f"{self._base_url}{API_CHAT_COMPLETIONS}"

        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=STREAM_TIMEOUT,
            ) as resp:
                if resp.status == 401:
                    raise OpenClawAuthError("Authentication failed")
                if resp.status >= 400:
                    text = await resp.text()
                    raise OpenClawApiError(f"Chat error {resp.status}: {text[:200]}")

                # Parse SSE stream
                async for line in resp.content:
                    decoded = line.decode("utf-8").strip()
                    if not decoded or not decoded.startswith("data: "):
                        continue

                    data_str = decoded[6:]  # strip "data: " prefix
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        _LOGGER.debug("Skipping non-JSON SSE line: %s", data_str[:100])

        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, asyncio.TimeoutError) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway: {err}"
            ) from err

    async def async_check_connection(self) -> bool:
        """Check if the gateway is reachable and authenticated.

        Uses the /v1/models endpoint as a lightweight probe — the only
        consistently available GET endpoint on the OpenClaw gateway.

        Returns:
            True if connected and authenticated.

        Raises:
            OpenClawAuthError: If authentication fails (re-raised so callers
                can distinguish bad tokens from unreachable gateways).
        """
        try:
            await self.async_get_models()
            return True
        except OpenClawAuthError:
            raise
        except OpenClawApiError:
            return False

    async def async_close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
