"""Sensor platform for Zaehlerfreunde."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PARTNER_ID, LAST_UPLOAD_SENSOR_KEY


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zaehlerfreunde sensors from a config entry."""
    sensor = ZaehlerfreundeLastUploadSensor(entry)
    async_add_entities([sensor])
    hass.data[PARTNER_ID][entry.entry_id][LAST_UPLOAD_SENSOR_KEY] = sensor


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
