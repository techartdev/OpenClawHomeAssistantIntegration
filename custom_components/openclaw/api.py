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
    API_TOOLS_INVOKE,
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
        verify_ssl: bool = True,
        session: aiohttp.ClientSession | None = None,
        agent_id: str = "main",
    ) -> None:
        """Initialize the API client.

        Args:
            host: Gateway hostname or IP.
            port: Gateway port number.
            token: Authentication token from openclaw.json.
            use_ssl: Use HTTPS instead of HTTP.
            verify_ssl: Verify SSL certificates (set False for self-signed certs).
            session: Optional aiohttp session (reused from HA).
            agent_id: Target OpenClaw agent ID (default: "main").
        """
        self._host = host
        self._port = port
        self._token = token
        self._use_ssl = use_ssl
        self._verify_ssl = verify_ssl
        self._session = session
        self._agent_id = agent_id
        self._base_url = f"{'https' if use_ssl else 'http'}://{host}:{port}"
        # ssl=False disables cert verification for self-signed certs;
        # ssl=None uses default verification.
        self._ssl_param: bool | None = False if (use_ssl and not verify_ssl) else None

    @property
    def base_url(self) -> str:
        """Return the base URL of the gateway."""
        return self._base_url

    def update_token(self, token: str) -> None:
        """Update the authentication token (e.g., after addon restart)."""
        self._token = token

    def _headers(self, agent_id: str | None = None) -> dict[str, str]:
        """Build request headers with auth token and agent ID.

        Args:
            agent_id: Per-call agent ID override. Falls back to the
                      client-level ``agent_id`` set in the constructor.
        """
        effective_agent = agent_id or self._agent_id or "main"
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "x-openclaw-agent-id": effective_agent,
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
                ssl=self._ssl_param,
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

        except aiohttp.ClientConnectorCertificateError as err:
            raise OpenClawConnectionError(
                f"SSL certificate verification failed for {url}. "
                f"If using self-signed certificates (e.g. lan_https mode), "
                f"disable 'Verify SSL certificate' in the integration config. "
                f"Error: {err}"
            ) from err
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
        system_prompt: str | None = None,
        stream: bool = False,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat message (non-streaming).

        Args:
            message: The user message text.
            session_id: Optional session/conversation ID.
            model: Optional model override.
            stream: If True, raises ValueError (use async_stream_message).
            agent_id: Optional per-call agent ID override (overrides the
                      client-level default set in the constructor).

        Returns:
            Complete chat completion response.
        """
        if stream:
            raise ValueError("Use async_stream_message() for streaming")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload: dict[str, Any] = {
            "messages": messages,
            "stream": False,
        }
        if session_id:
            payload["session_id"] = session_id
            payload["user"] = session_id
        if model:
            payload["model"] = model

        # Pass session_id as a custom header or param if supported by gateway
        headers = self._headers(agent_id=agent_id)
        if session_id:
            headers["X-Session-Id"] = session_id
            headers["x-openclaw-session-key"] = session_id

        session = await self._get_session()
        url = f"{self._base_url}{API_CHAT_COMPLETIONS}"

        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=STREAM_TIMEOUT,
                ssl=self._ssl_param,
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
        system_prompt: str | None = None,
        agent_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Send a chat message and stream the response via SSE.

        Yields delta content strings as they arrive from the gateway.

        Args:
            message: The user message text.
            session_id: Optional session/conversation ID.
            model: Optional model override.
            agent_id: Optional per-call agent ID override (overrides the
                      client-level default set in the constructor).

        Yields:
            Content delta strings from the streaming response.
        """
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload: dict[str, Any] = {
            "messages": messages,
            "stream": True,
        }
        if session_id:
            payload["session_id"] = session_id
            payload["user"] = session_id
        if model:
            payload["model"] = model

        headers = self._headers(agent_id=agent_id)
        if session_id:
            headers["X-Session-Id"] = session_id
            headers["x-openclaw-session-key"] = session_id

        session = await self._get_session()
        url = f"{self._base_url}{API_CHAT_COMPLETIONS}"

        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=STREAM_TIMEOUT,
                ssl=self._ssl_param,
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
        """Check if the gateway is reachable, API is enabled, and auth works.

        The OpenClaw gateway only implements /v1/chat/completions (not
        /v1/models). We send a POST with an empty messages list — the gateway
        auth middleware validates the token first, then the endpoint returns a
        400 (or similar) for the invalid body. This proves:
          - Server is reachable.
          - The OpenAI-compatible API layer is enabled (enable_openai_api).
          - The auth token is accepted.

        If the route is not registered (API disabled) the SPA catch-all
        returns 200 text/html — detected via content-type check.

        Returns:
            True if connected and authenticated.

        Raises:
            OpenClawAuthError: If authentication fails.
            OpenClawApiError: If the gateway returns HTML (API not enabled).
            OpenClawConnectionError: If the gateway is unreachable.
        """
        session = await self._get_session()
        url = f"{self._base_url}{API_CHAT_COMPLETIONS}"

        try:
            async with session.post(
                url,
                headers=self._headers(),
                json={"messages": [], "stream": False},
                timeout=API_TIMEOUT,
                ssl=self._ssl_param,
            ) as resp:
                if resp.status in (401, 403):
                    raise OpenClawAuthError(
                        "Authentication failed — check gateway token"
                    )

                content_type = resp.content_type or ""
                if "json" not in content_type:
                    text = await resp.text()
                    raise OpenClawApiError(
                        f"Gateway returned '{content_type}' instead of JSON. "
                        "The OpenAI-compatible API is likely not enabled. "
                        "Enable 'enable_openai_api' in the addon settings "
                        f"and restart. Response: {text[:200]}"
                    )

                # Any JSON response (200, 400, 422, etc.) means the
                # endpoint exists, auth passed, and the API layer is active.
                return True

        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, asyncio.TimeoutError) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway at {url}: {err}"
            ) from err

    async def async_check_alive(self) -> bool:
        """Lightweight connectivity check — is the gateway process running?

        Sends a GET to the base URL. The SPA catch-all returns 200 HTML for
        any route, so any non-error HTTP response means the server is alive.
        Auth is NOT verified here (the SPA ignores tokens).

        Returns:
            True if the gateway HTTP server is responding.

        Raises:
            OpenClawConnectionError: If the gateway is unreachable.
        """
        session = await self._get_session()
        try:
            async with session.get(
                self._base_url,
                timeout=API_TIMEOUT,
                ssl=self._ssl_param,
            ) as resp:
                return resp.status < 500
        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, asyncio.TimeoutError) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway: {err}"
            ) from err

    async def async_invoke_tool(
        self,
        tool: str,
        action: str | None = None,
        args: dict[str, Any] | None = None,
        session_key: str | None = None,
        dry_run: bool = False,
        message_channel: str | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a single OpenClaw tool via gateway HTTP endpoint."""
        payload: dict[str, Any] = {
            "tool": tool,
            "args": args or {},
            "dryRun": bool(dry_run),
        }
        if action:
            payload["action"] = action
        if session_key:
            payload["sessionKey"] = session_key

        headers = self._headers()
        if message_channel:
            headers["x-openclaw-message-channel"] = message_channel
        if account_id:
            headers["x-openclaw-account-id"] = account_id

        session = await self._get_session()
        url = f"{self._base_url}{API_TOOLS_INVOKE}"

        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=STREAM_TIMEOUT,
                ssl=self._ssl_param,
            ) as resp:
                if resp.status == 401:
                    raise OpenClawAuthError("Authentication failed")
                if resp.status >= 400:
                    text = await resp.text()
                    raise OpenClawApiError(f"Tool invoke error {resp.status}: {text[:300]}")

                content_type = resp.content_type or ""
                if "json" not in content_type:
                    text = await resp.text()
                    raise OpenClawApiError(
                        f"Unexpected tool response content type '{content_type}': {text[:300]}"
                    )
                return await resp.json()

        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, asyncio.TimeoutError) as err:
            raise OpenClawConnectionError(
                f"Cannot connect to OpenClaw gateway: {err}"
            ) from err

    async def async_close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
