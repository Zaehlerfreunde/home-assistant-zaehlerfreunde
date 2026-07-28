"""Sensor platform for Zaehlerfreunde."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CATEGORY_COMMAND_TYPES,
    LAST_COMMAND_SENSOR_KEY,
    LAST_POLL_SENSOR_KEY,
    LAST_UPLOAD_SENSOR_KEY,
    PARTNER_ID,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zaehlerfreunde sensors from a config entry."""
    upload_sensor = ZaehlerfreundeLastUploadSensor(entry)
    hass.data[PARTNER_ID][entry.entry_id][LAST_UPLOAD_SENSOR_KEY] = upload_sensor

    entities: list[SensorEntity] = [upload_sensor]

    device_type = entry.data.get("entry_device_type")
    if CATEGORY_COMMAND_TYPES.get(device_type):
        cmd_sensor = ZaehlerfreundeLastCommandSensor(entry)
        hass.data[PARTNER_ID][entry.entry_id][LAST_COMMAND_SENSOR_KEY] = cmd_sensor
        entities.append(cmd_sensor)

        poll_sensor = ZaehlerfreundeLastPollSensor(entry)
        hass.data[PARTNER_ID][entry.entry_id][LAST_POLL_SENSOR_KEY] = poll_sensor
        entities.append(poll_sensor)

    async_add_entities(entities)


class ZaehlerfreundeLastUploadSensor(SensorEntity):
    """Sensor showing the last time data was successfully uploaded for this entry."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False
    _attr_native_value: datetime | None = None

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._attr_unique_id = f"{entry.entry_id}_last_upload"
        self._attr_name = "Last upload"
        self._attr_device_info = DeviceInfo(
            identifiers={(PARTNER_ID, entry.entry_id)},
            name=entry.title,
            manufacturer="Zählerfreunde",
        )
        self._last_error: str | None = None
        self._last_error_at: datetime | None = None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the latest error as an attribute."""
        return {
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
        }

    def record_upload(self) -> None:
        """Record a successful upload and clear any previous error."""
        self._attr_native_value = datetime.now(timezone.utc)
        self._last_error = None
        self._last_error_at = None
        self.async_write_ha_state()

    def record_error(self, message: str) -> None:
        """Record a failed upload with error details."""
        self._last_error = message
        self._last_error_at = datetime.now(timezone.utc)
        self.async_write_ha_state()


class ZaehlerfreundeLastCommandSensor(SensorEntity):
    """Sensor showing a description of the last HEMS command executed on this entry."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_value: str | None = None

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._attr_unique_id = f"{entry.entry_id}_last_command"
        self._attr_name = "Last command"
        self._attr_device_info = DeviceInfo(
            identifiers={(PARTNER_ID, entry.entry_id)},
            name=entry.title,
            manufacturer="Zählerfreunde",
        )
        self._command: str | None = None
        self._params: dict = {}
        self._executed_at: datetime | None = None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose command type, parameters, and when it was executed."""
        return {
            "command": self._command,
            "params": self._params,
            "executed_at": self._executed_at.isoformat() if self._executed_at else None,
        }

    def record_execution(self, command_type: str, params: dict) -> None:
        """Record a successful command execution."""
        self._command = command_type
        self._params = params
        self._executed_at = datetime.now(timezone.utc)
        self._attr_native_value = _command_description(command_type, params)
        self.async_write_ha_state()


def _command_description(command_type: str, params: dict) -> str:
    """Build a short human-readable description for a command."""
    if command_type == "start_charging":
        return "Charging started"
    if command_type == "stop_charging":
        return "Charging stopped"
    if command_type == "set_charging_rate":
        rate = params.get("rate_kw")
        return f"Charging rate set to {rate} kW" if rate is not None else "Charging rate updated"
    if command_type == "set_battery_mode":
        mode = params.get("mode", "unknown")
        return f"Battery mode: {mode}"
    if command_type == "set_heat_pump_mode":
        mode = params.get("mode", "unknown")
        return f"Heat pump mode: {mode}"
    return command_type


class ZaehlerfreundeLastPollSensor(SensorEntity):
    """Sensor showing the last time this entry polled the backend for commands."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False
    _attr_native_value: datetime | None = None

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._attr_unique_id = f"{entry.entry_id}_last_poll"
        self._attr_name = "Last command poll"
        self._attr_device_info = DeviceInfo(
            identifiers={(PARTNER_ID, entry.entry_id)},
            name=entry.title,
            manufacturer="Zählerfreunde",
        )

    def record_poll(self) -> None:
        """Record that a poll attempt was made."""
        self._attr_native_value = datetime.now(timezone.utc)
        self.async_write_ha_state()
