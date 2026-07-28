"""HEMS command executor for Zaehlerfreunde."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    BATTERY_MODES,
    COMMAND_SET_BATTERY_MODE,
    COMMAND_SET_CHARGING_RATE,
    COMMAND_SET_HEAT_PUMP_MODE,
    COMMAND_START_CHARGING,
    COMMAND_STOP_CHARGING,
    CONF_BATTERY_MODE,
    CONF_BATTERY_MODE_MAPPINGS,
    CONF_CHARGING_RATE,
    CONF_CHARGING_SWITCH,
    CONF_HEAT_PUMP_MODE,
    CONF_HEAT_PUMP_MODE_MAPPINGS,
    HEAT_PUMP_MODES,
)

_LOGGER = logging.getLogger(__name__)

# Maps each command type to the control role whose entity it targets.
_COMMAND_ROLE: dict[str, str] = {
    COMMAND_START_CHARGING: CONF_CHARGING_SWITCH,
    COMMAND_STOP_CHARGING: CONF_CHARGING_SWITCH,
    COMMAND_SET_CHARGING_RATE: CONF_CHARGING_RATE,
    COMMAND_SET_BATTERY_MODE: CONF_BATTERY_MODE,
    COMMAND_SET_HEAT_PUMP_MODE: CONF_HEAT_PUMP_MODE,
}


async def async_execute_command(
    hass: HomeAssistant,
    entity_roles: dict[str, str],
    command: dict[str, Any],
    battery_mode_mappings: dict[str, str] | None = None,
    heat_pump_mode_mappings: dict[str, str] | None = None,
) -> tuple[bool, str | None]:
    """Execute a HEMS command; return (success, error_message)."""
    command_id = command.get("command_id", "<unknown>")
    command_type = command.get("type")
    params = command.get("params", {})

    _LOGGER.debug(
        "Executing command %s (type=%s, params=%s)", command_id, command_type, params
    )

    if command_type not in _COMMAND_ROLE:
        msg = f"Unknown command type: {command_type}"
        _LOGGER.warning(msg)
        return False, msg

    target_role = _COMMAND_ROLE[command_type]
    # entity_roles maps entity_id → role; invert to find entity for a given role.
    role_to_entity = {role: entity_id for entity_id, role in entity_roles.items()}
    entity_id = role_to_entity.get(target_role)

    if entity_id is None:
        msg = f"No entity mapped for role '{target_role}' (command: {command_type})"
        _LOGGER.warning(msg)
        return False, msg

    # Derive the HA domain from the entity_id (e.g. "switch.wallbox" → "switch").
    # This makes the executor work with any compatible entity type across brands.
    entity_domain = entity_id.split(".")[0]

    try:
        if command_type == COMMAND_START_CHARGING:
            await _call_service(hass, entity_domain, "turn_on", entity_id, {})

        elif command_type == COMMAND_STOP_CHARGING:
            await _call_service(hass, entity_domain, "turn_off", entity_id, {})

        elif command_type == COMMAND_SET_CHARGING_RATE:
            rate = params.get("rate_kw")
            if rate is None:
                return False, "Missing param: rate_kw"
            await _call_service(hass, entity_domain, "set_value", entity_id, {"value": rate})

        elif command_type == COMMAND_SET_BATTERY_MODE:
            mode = params.get("mode")
            if mode not in BATTERY_MODES:
                return False, f"Invalid battery mode: {mode!r}"
            native = (battery_mode_mappings or {}).get(mode)
            if not native:
                return False, f"No option mapped for battery mode '{mode}'"
            await _call_service(hass, entity_domain, "select_option", entity_id, {"option": native})

        elif command_type == COMMAND_SET_HEAT_PUMP_MODE:
            mode = params.get("mode")
            if mode not in HEAT_PUMP_MODES:
                return False, f"Invalid heat pump mode: {mode!r} (expected: boost, normal)"
            native = (heat_pump_mode_mappings or {}).get(mode)
            if not native:
                return False, f"No option mapped for heat pump mode '{mode}'"
            await _call_service(hass, entity_domain, "select_option", entity_id, {"option": native})

        _LOGGER.debug("Command %s executed successfully on %s", command_id, entity_id)
        return True, None

    except Exception as err:
        msg = f"Failed to execute {command_type} on {entity_id}: {err}"
        _LOGGER.error(msg)
        return False, msg


async def _call_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    entity_id: str,
    service_data: dict[str, Any],
) -> None:
    """Call a Home Assistant service targeting a single entity."""
    await hass.services.async_call(
        domain,
        service,
        {"entity_id": entity_id, **service_data},
        blocking=True,
    )
