"""API client for Zaehlerfreunde backend linking."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import ssl

from .const import BACKEND_URL, INGEST_URL

_LOGGER = logging.getLogger(__name__)


class LinkSessionError(Exception):
    """Error during link session operations."""


class TokenExpiredError(LinkSessionError):
    """Raised when the access token has expired (HTTP 403)."""


async def async_start_link_session(
    instance_id: str,
    category: str | None = None,
    device_name: str | None = None,
) -> dict[str, Any]:
    """Start a new link session with the backend.

    Args:
        instance_id: The Home Assistant instance ID.
        category: The device category being linked (e.g. 'inverters').
        device_name: The display name of the selected HA device.

    Returns:
        Dictionary with 'setup_code' and 'verification_url' keys.

    Raises:
        LinkSessionError: If the request fails.
    """
    _LOGGER.debug(
        "Starting link session for instance %s (category=%s, device=%s)",
        instance_id,
        category,
        device_name,
    )
    try:
        payload: dict[str, Any] = {"instance_id": instance_id}
        if category is not None:
            payload["category"] = category
        if device_name is not None:
            payload["device_name"] = device_name

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BACKEND_URL}/ha/link/start",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise LinkSessionError(f"Failed to start link session: {resp.status}")
                data = await resp.json()
                _LOGGER.debug("Link session started, verification_url=%s", data.get("verification_url"))
                return {
                    "setup_code": data.get("setup_code"),
                    "verification_url": data.get("verification_url"),
                }
    except aiohttp.ClientError as err:
        raise LinkSessionError(f"Connection error: {err}") from err
    except Exception as err:
        raise LinkSessionError(f"Unexpected error: {err}") from err


async def async_check_link_status(setup_code: str) -> bool:
    """Check if the link session has been authorized.

    Args:
        setup_code: The setup code from the link session.

    Returns:
        True if authorization is complete, False otherwise.

    Raises:
        LinkSessionError: If the request fails.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BACKEND_URL}/ha/link/status",
                params={"setup_code": setup_code},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                _LOGGER.debug("Link status check responded with HTTP %s", resp.status)
                if resp.status != 200:
                    raise LinkSessionError(f"Failed to check link status: {resp.status}")
                data = await resp.json()
                approved = data.get("approved", False)
                _LOGGER.debug("Link session approved=%s for setup_code=%s", approved, setup_code)
                return approved
    except aiohttp.ClientError as err:
        raise LinkSessionError(f"Connection error: {err}") from err
    except Exception as err:
        raise LinkSessionError(f"Unexpected error: {err}") from err


async def async_get_link_tokens(setup_code: str) -> dict[str, str]:
    """Fetch access and refresh tokens for a completed link session.

    Args:
        setup_code: The setup code from the link session.

    Returns:
        Dictionary with 'access_token' and 'refresh_token' keys.

    Raises:
        LinkSessionError: If the request fails.
    """
    _LOGGER.debug("Fetching link tokens for setup_code=%s", setup_code)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BACKEND_URL}/ha/link/tokens",
                params={"setup_code": setup_code},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise LinkSessionError(f"Failed to fetch tokens: {resp.status}")
                data = await resp.json()
                _LOGGER.debug("Successfully fetched link tokens for setup_code=%s", setup_code)
                return {
                    "access_token": data.get("access_token"),
                    "refresh_token": data.get("refresh_token"),
                }
    except aiohttp.ClientError as err:
        raise LinkSessionError(f"Connection error: {err}") from err
    except Exception as err:
        raise LinkSessionError(f"Unexpected error: {err}") from err


async def async_refresh_tokens(refresh_token: str) -> dict[str, str]:
    """Exchange a refresh token for a new access token.

    Args:
        refresh_token: The refresh token from the stored config entry.

    Returns:
        Dictionary with 'access_token' and 'refresh_token' keys.

    Raises:
        LinkSessionError: If the request fails.
    """
    _LOGGER.debug("Refreshing access token")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BACKEND_URL}/ha/link/token/refresh",
                json={"refresh_token": refresh_token},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise LinkSessionError(f"Failed to refresh token: {resp.status}")
                data = await resp.json()
                _LOGGER.debug("Successfully refreshed access token")
                return {
                    "access_token": data.get("access_token", ""),
                    "refresh_token": data.get("refresh_token", refresh_token),
                }
    except aiohttp.ClientError as err:
        raise LinkSessionError(f"Connection error: {err}") from err
    except LinkSessionError:
        raise
    except Exception as err:
        raise LinkSessionError(f"Unexpected error: {err}") from err


async def async_send_sensor_value(
    access_token: str,
    entity_id: str,
    role: str,
    state: str,
    attributes: dict[str, Any],
    time_fired: Any = None,
) -> None:
    """Send a sensor state update to the backend.

    Args:
        access_token: Bearer token for the entry.
        entity_id: The Home Assistant entity ID.
        category: The device category (e.g. 'inverters').
        role: The sensor role within the category (e.g. 'solar_power').
        state: The new state string.
        unit: Optional unit of measurement.
        attributes: Full entity attributes dict.

    Raises:
        LinkSessionError: If the request fails.
    """
    payload: dict[str, Any] = {
        "entity_id": entity_id,
        "role": role,
        "state": state,
        "attributes": attributes,
        "time_fired": int(time_fired.timestamp()) if time_fired is not None else None,
    }
    _LOGGER.debug(
        "Sending sensor value to backend: entity_id=%s, role=%s, state=%s, access_token=%s",
        entity_id,
        role,
        state,
        access_token
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{INGEST_URL}/ha/sensors/values",
                json=payload,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    data = await resp.text()
                    raise TokenExpiredError("Access token expired %s", data)
                if resp.status not in (200, 201, 204):
                    data = await resp.text()
                    raise LinkSessionError(
                        f"Failed to send sensor value: {resp.status} {data}"
                    )
                _LOGGER.debug(
                    "Successfully sent sensor value for entity %s (HTTP %s)",
                    entity_id,
                    resp.status,
                )
    except aiohttp.ClientError as err:
        raise LinkSessionError(f"Connection error: {err}") from err
    except LinkSessionError:
        raise
    except Exception as err:
        raise LinkSessionError(f"Unexpected error: {err}") from err
