"""DataUpdateCoordinator for the OpenClaw integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    OpenClawApiClient,
    OpenClawApiError,
    OpenClawAuthError,
    OpenClawConnectionError,
)
from .const import (
    DATA_CONNECTED,
    DATA_CONTEXT_WINDOW,
    DATA_GATEWAY_VERSION,
    DATA_LAST_ACTIVITY,
    DATA_MODEL,
    DATA_PROVIDER,
    DATA_SESSION_COUNT,
    DATA_SESSIONS,
    DATA_STATUS,
    DATA_UPTIME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class OpenClawCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the OpenClaw gateway for status updates.

    Fetches status, session info, and model info on a regular interval
    and makes the data available to sensor/binary_sensor entities.

    Handles:
    - Transient connection failures (returns offline data, no UpdateFailed)
    - Auth failures (triggers filesystem token re-read)
    - Model info cached separately with a longer poll interval
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: OpenClawApiClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self._last_activity: datetime | None = None
        self._model_cache: dict[str, Any] = {}
        self._consecutive_failures = 0

    def _offline_data(self) -> dict[str, Any]:
        """Return a data dict representing the offline state."""
        return {
            DATA_STATUS: "offline",
            DATA_CONNECTED: False,
            DATA_SESSION_COUNT: 0,
            DATA_SESSIONS: [],
            DATA_MODEL: self._model_cache.get(DATA_MODEL),
            DATA_LAST_ACTIVITY: self._last_activity,
            DATA_GATEWAY_VERSION: None,
            DATA_UPTIME: None,
            DATA_PROVIDER: self._model_cache.get(DATA_PROVIDER),
            DATA_CONTEXT_WINDOW: self._model_cache.get(DATA_CONTEXT_WINDOW),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the OpenClaw gateway.

        The OpenClaw gateway only exposes OpenAI-compatible endpoints.
        /v1/models is used as both the connectivity probe and the model
        data source; /api/status and /api/sessions do not exist on the
        gateway — it returns its SPA home page for unknown routes.

        Returns:
            Aggregated data dict for all entities.
        """
        data = self._offline_data()

        try:
            models_resp = await self.client.async_get_models()
            models = models_resp.get("data", [])

            data[DATA_STATUS] = "online"
            data[DATA_CONNECTED] = True
            data[DATA_GATEWAY_VERSION] = None  # Not exposed by gateway API
            data[DATA_UPTIME] = None           # Not exposed by gateway API
            data[DATA_SESSION_COUNT] = 0       # Sessions API does not exist
            data[DATA_SESSIONS] = []           # Sessions API does not exist
            data[DATA_LAST_ACTIVITY] = self._last_activity
            self._consecutive_failures = 0

            if models:
                current = models[0]
                self._model_cache = {
                    DATA_MODEL: current.get("id", "unknown"),
                    DATA_PROVIDER: current.get("owned_by"),
                    DATA_CONTEXT_WINDOW: current.get("context_window"),
                }

        except OpenClawAuthError as err:
            _LOGGER.warning("Gateway auth failed during poll: %s", err)
            await self._try_refresh_token()
            return data

        except OpenClawConnectionError:
            self._consecutive_failures += 1
            if self._consecutive_failures <= 3:
                _LOGGER.debug("Gateway unreachable (attempt %d)", self._consecutive_failures)
            elif self._consecutive_failures == 4:
                _LOGGER.warning(
                    "Gateway has been unreachable for %d consecutive polls",
                    self._consecutive_failures,
                )
            return data

        except OpenClawApiError as err:
            _LOGGER.warning("Error fetching gateway models: %s", err)
            return data

        data.update(self._model_cache)
        return data

    async def _try_refresh_token(self) -> None:
        """Attempt to re-read the gateway token via the refresh callback."""
        entry_data = self.hass.data.get(DOMAIN, {})
        for eid, ed in entry_data.items():
            if isinstance(ed, dict) and "refresh_token" in ed:
                refresh_fn = ed["refresh_token"]
                if await refresh_fn():
                    _LOGGER.info("Token refreshed successfully — next poll should succeed")
                    return
        _LOGGER.debug("No token refresh callback available")

    def update_last_activity(self) -> None:
        """Update the last activity timestamp to now.

        Called when a message is sent/received through the integration.
        """
        self._last_activity = datetime.now(timezone.utc)
