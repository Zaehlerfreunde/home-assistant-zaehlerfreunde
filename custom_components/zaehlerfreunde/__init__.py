"""The Zaehlerfreunde integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event, async_track_state_report_event, async_track_time_interval

from .api_client import (
    LinkSessionError,
    TokenExpiredError,
    async_fetch_pending_commands,
    async_refresh_tokens,
    async_report_command_result,
    async_send_sensor_value,
)
from .command_executor import async_execute_command
from .const import (
    COMMAND_POLLING_INTERVAL_SECONDS,
    LAST_COMMAND_SENSOR_KEY,
    LAST_POLL_SENSOR_KEY,
    CONF_ACCESS_TOKEN,
    CONF_BATTERY_MODE,
    CONF_BATTERY_MODE_MAPPINGS,
    CONF_ENTITY_ROLES,
    CONF_HEAT_PUMP_MODE,
    CONF_HEAT_PUMP_MODE_MAPPINGS,
    CONF_REFRESH_TOKEN,
    LAST_UPLOAD_SENSOR_KEY,
    PARTNER_ID,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

type ZaehlerfreundeConfigEntry = ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration via YAML (no-op)."""
    hass.data.setdefault(PARTNER_ID, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ZaehlerfreundeConfigEntry) -> bool:
    """Set up Zaehlerfreunde from a config entry."""
    hass.data.setdefault(PARTNER_ID, {})

    entity_roles = entry.data.get(CONF_ENTITY_ROLES, {})

    _LOGGER.debug(
        "Setting up Zaehlerfreunde entry %s with %d tracked entit%s",
        entry.entry_id,
        len(entity_roles),
        "y" if len(entity_roles) == 1 else "ies",
    )

    access_token: str = entry.data.get(CONF_ACCESS_TOKEN, "")

    @callback
    def _on_state_change(event: Event) -> None:
        """Forward a state-reported event to the backend."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            _LOGGER.debug(
                "Skipping state change for %s: state is '%s'",
                event.data.get("entity_id"),
                new_state.state if new_state is not None else "None",
            )
            return

        entity_id: str = new_state.entity_id
        role = entity_roles.get(entity_id, "")
        _LOGGER.debug(
            "Forwarding state change for entity %s (role=%s): %s",
            entity_id,
            role,
            new_state.state,
        )
        current_access_token: str = hass.data[PARTNER_ID][entry.entry_id].get(CONF_ACCESS_TOKEN, "")

        hass.async_create_task(
            _async_forward_sensor_value(
                hass,
                entry,
                current_access_token,
                entity_id,
                role,
                new_state.state,
                dict(new_state.attributes),
                event.time_fired,
            )
        )

    tracked_entities = list(entity_roles.keys())
    unsub_state_report_listener = (
        async_track_state_report_event(hass, tracked_entities, _on_state_change)
        if tracked_entities
        else lambda: None
    )
    unsub_state_change_listener = (
        async_track_state_change_event(hass, tracked_entities, _on_state_change)
        if tracked_entities
        else lambda: None
    )

    @callback
    def _on_command_poll_interval(now) -> None:
        hass.async_create_task(_async_poll_commands(hass, entry))

    unsub_command_listener = async_track_time_interval(
        hass,
        _on_command_poll_interval,
        timedelta(seconds=COMMAND_POLLING_INTERVAL_SECONDS),
    )

    hass.data[PARTNER_ID][entry.entry_id] = {
        CONF_ACCESS_TOKEN: access_token,
        CONF_ENTITY_ROLES: entity_roles,
        "unsub_options_update_listener": entry.add_update_listener(_async_options_updated),
        "unsub_state_report_listener": unsub_state_report_listener,
        "unsub_state_change_listener": unsub_state_change_listener,
        "unsub_command_listener": unsub_command_listener,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_forward_sensor_value(
    hass: HomeAssistant,
    entry: ZaehlerfreundeConfigEntry,
    access_token: str,
    entity_id: str,
    role: str,
    state: str,
    attributes: dict,
    time_fired: datetime,
) -> None:
    """Send a single sensor value to the backend, refreshing the token on 403."""
    if role == CONF_BATTERY_MODE:
        mappings: dict[str, str] = entry.data.get(CONF_BATTERY_MODE_MAPPINGS, {})
        native_to_canonical = {v: k for k, v in mappings.items()}
        canonical = native_to_canonical.get(state)
        if canonical is None:
            _LOGGER.warning(
                "No battery mode mapping found for native value '%s' on entity %s; skipping upload",
                state,
                entity_id,
            )
            return
        state = canonical
    elif role == CONF_HEAT_PUMP_MODE:
        mappings = entry.data.get(CONF_HEAT_PUMP_MODE_MAPPINGS, {})
        native_to_canonical = {v: k for k, v in mappings.items()}
        canonical = native_to_canonical.get(state)
        if canonical is None:
            _LOGGER.warning(
                "No heat pump mode mapping found for native value '%s' on entity %s; skipping upload",
                state,
                entity_id,
            )
            return
        state = canonical

    try:
        _LOGGER.debug(
            "Sending sensor value for entity %s (role=%s): state=%s, attributes=%s",
            entity_id,
            role,
            state,
            attributes,
        )
        await async_send_sensor_value(access_token, entity_id, role, state, attributes, time_fired)
        _LOGGER.debug("Successfully sent sensor value for entity %s", entity_id)
        _record_last_upload(hass, entry)
    except TokenExpiredError:
        _LOGGER.warning("Access token expired, refreshing for entry %s", entry.entry_id)
        refresh_token: str = entry.data.get(CONF_REFRESH_TOKEN, "")
        try:
            new_tokens = await async_refresh_tokens(refresh_token)
        except LinkSessionError as err:
            _LOGGER.error("Token refresh failed for entry %s: %s", entry.entry_id, err)
            _record_upload_error(hass, entry, f"Token refresh failed: {err}")
            return
        new_access_token: str = new_tokens.get("access_token", "")
        new_refresh_token: str = new_tokens.get("refresh_token", refresh_token)
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: new_access_token,
                CONF_REFRESH_TOKEN: new_refresh_token,
            },
        )
        entry_data = hass.data[PARTNER_ID].get(entry.entry_id)
        if entry_data is not None:
            entry_data[CONF_ACCESS_TOKEN] = new_access_token
        try:
            await async_send_sensor_value(new_access_token, entity_id, role, state, attributes, time_fired)
            _record_last_upload(hass, entry)
        except LinkSessionError as err:
            _LOGGER.error(
                "Failed to send sensor value for %s after token refresh: %s", entity_id, err
            )
            _record_upload_error(hass, entry, f"Send failed after token refresh: {err}")
    except LinkSessionError as err:
        _LOGGER.error("Failed to send sensor value for %s: %s", entity_id, err)
        _record_upload_error(hass, entry, str(err))
    except Exception as err:
        _LOGGER.exception("Unexpected error sending sensor value for %s", entity_id)
        _record_upload_error(hass, entry, f"Unexpected error: {err}")


def _record_last_upload(hass: HomeAssistant, entry: ZaehlerfreundeConfigEntry) -> None:
    """Clear the repair issue and update the sensor on a successful upload."""
    ir.async_delete_issue(hass, PARTNER_ID, f"upload_failed_{entry.entry_id}")
    entry_data = hass.data[PARTNER_ID].get(entry.entry_id)
    if entry_data is None:
        return
    sensor = entry_data.get(LAST_UPLOAD_SENSOR_KEY)
    if sensor is not None:
        sensor.record_upload()


def _record_upload_error(hass: HomeAssistant, entry: ZaehlerfreundeConfigEntry, message: str) -> None:
    """Create a repair issue and update the sensor on a failed upload."""
    ir.async_create_issue(
        hass,
        PARTNER_ID,
        f"upload_failed_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="upload_failed",
        translation_placeholders={
            "entry_title": entry.title,
            "error": message,
        },
    )
    entry_data = hass.data[PARTNER_ID].get(entry.entry_id)
    if entry_data is None:
        return
    sensor = entry_data.get(LAST_UPLOAD_SENSOR_KEY)
    if sensor is not None:
        sensor.record_error(message)


def _clear_command_poll_issue(hass: HomeAssistant, entry: ZaehlerfreundeConfigEntry) -> None:
    """Clear any active command poll repair issue."""
    ir.async_delete_issue(hass, PARTNER_ID, f"command_poll_failed_{entry.entry_id}")


def _record_command_poll_error(hass: HomeAssistant, entry: ZaehlerfreundeConfigEntry, message: str) -> None:
    """Create a repair issue when command polling fails persistently."""
    ir.async_create_issue(
        hass,
        PARTNER_ID,
        f"command_poll_failed_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="command_poll_failed",
        translation_placeholders={
            "entry_title": entry.title,
            "error": message,
        },
    )


async def async_unload_entry(hass: HomeAssistant, entry: ZaehlerfreundeConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Zaehlerfreunde entry %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[PARTNER_ID].get(entry.entry_id)
        if entry_data:
            entry_data["unsub_options_update_listener"]()
            entry_data["unsub_state_report_listener"]()
            entry_data["unsub_state_change_listener"]()
            entry_data["unsub_command_listener"]()
        hass.data[PARTNER_ID].pop(entry.entry_id, None)
        _LOGGER.debug("Successfully unloaded Zaehlerfreunde entry %s", entry.entry_id)
    else:
        _LOGGER.warning("Failed to unload platforms for Zaehlerfreunde entry %s", entry.entry_id)
    return unload_ok


async def _async_poll_commands(hass: HomeAssistant, entry: ZaehlerfreundeConfigEntry) -> None:
    """Poll the backend for pending HEMS commands and execute them."""
    entry_data = hass.data[PARTNER_ID].get(entry.entry_id)
    if entry_data is None:
        return

    access_token: str = entry_data.get(CONF_ACCESS_TOKEN, "")
    entity_roles: dict = entry_data.get(CONF_ENTITY_ROLES, {})

    poll_sensor = entry_data.get(LAST_POLL_SENSOR_KEY)
    if poll_sensor is not None:
        poll_sensor.record_poll()

    try:
        commands = await async_fetch_pending_commands(access_token, entry.entry_id)
    except TokenExpiredError:
        _LOGGER.warning("Access token expired during command poll, refreshing for entry %s", entry.entry_id)
        refresh_token: str = entry.data.get(CONF_REFRESH_TOKEN, "")
        try:
            new_tokens = await async_refresh_tokens(refresh_token)
        except LinkSessionError as err:
            _LOGGER.error("Token refresh failed during command poll for entry %s: %s", entry.entry_id, err)
            _record_command_poll_error(hass, entry, f"Token refresh failed: {err}")
            return
        access_token = new_tokens.get("access_token", "")
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: access_token,
                CONF_REFRESH_TOKEN: new_tokens.get("refresh_token", refresh_token),
            },
        )
        entry_data[CONF_ACCESS_TOKEN] = access_token
        try:
            commands = await async_fetch_pending_commands(access_token, entry.entry_id)
        except LinkSessionError as err:
            _LOGGER.error("Failed to fetch commands after token refresh for entry %s: %s", entry.entry_id, err)
            _record_command_poll_error(hass, entry, f"Failed after token refresh: {err}")
            return
    except LinkSessionError as err:
        _LOGGER.warning("Failed to fetch pending commands for entry %s: %s", entry.entry_id, err)
        _record_command_poll_error(hass, entry, str(err))
        return

    _clear_command_poll_issue(hass, entry)

    for command in commands:
        command_id = command.get("command_id", "<unknown>")
        success, error = await async_execute_command(
            hass,
            entity_roles,
            command,
            battery_mode_mappings=entry.data.get(CONF_BATTERY_MODE_MAPPINGS),
            heat_pump_mode_mappings=entry.data.get(CONF_HEAT_PUMP_MODE_MAPPINGS),
        )
        try:
            await async_report_command_result(access_token, command_id, success, error)
        except LinkSessionError as err:
            _LOGGER.error("Failed to report result for command %s: %s", command_id, err)

        if success:
            entry_data = hass.data[PARTNER_ID].get(entry.entry_id)
            if entry_data is not None:
                cmd_sensor = entry_data.get(LAST_COMMAND_SENSOR_KEY)
                if cmd_sensor is not None:
                    cmd_sensor.record_execution(command.get("type"), command.get("params", {}))


async def _async_options_updated(hass: HomeAssistant, entry: ZaehlerfreundeConfigEntry) -> None:
    """Reload the entry when options are updated."""
    _LOGGER.debug("Options updated for entry %s, reloading", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
