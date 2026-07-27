"""Constants for the Zaehlerfreunde integration."""

PARTNER_ID = "zaehlerfreunde"
PLATFORMS = ["sensor"]
DEFAULT_NAME = "Zählerfreunde"

CONF_INVERTERS = "inverters"
CONF_GRID_METERS = "grid_meters"
CONF_BATTERY_STORAGES = "battery_storages"
CONF_HEAT_PUMPS = "heat_pumps"
CONF_CAR_CHARGERS = "car_chargers"

DEVICE_SELECTION_KEYS = [
	CONF_INVERTERS,
	CONF_GRID_METERS,
	CONF_BATTERY_STORAGES,
	CONF_HEAT_PUMPS,
	CONF_CAR_CHARGERS,
]

BACKEND_URL = "https://external.prod.zaehlerfreunde.com"
INGEST_URL = "https://external.prod.zaehlerfreunde.com"
APP_URL = "https://app.zaehlerfreunde.com"
LINK_POLLING_INTERVAL_SECONDS = 2
LINK_POLLING_TIMEOUT_SECONDS = 600

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_SETUP_CODE = "setup_code"
CONF_ENTITY_ROLES = "entry_entity_roles"

LAST_UPLOAD_SENSOR_KEY = "last_upload_sensor"

# Inverter sensor roles
CONF_SOLAR_POWER = "solar_power"
CONF_SOLAR_YIELD_TOTAL = "solar_yield_total"
CONF_GRID_POWER = "grid_power"
CONF_BATTERY_POWER = "battery_power"
CONF_BATTERY_SOC = "battery_soc"
CONF_CONSUMPTION_POWER = "consumption_power"

INVERTER_ROLES: list[str] = [
    CONF_SOLAR_POWER,
    CONF_SOLAR_YIELD_TOTAL,
]

# Roles per category: list of (config_key, display_label) tuples.
# Only categories with at least one role are shown in the config flow.
CATEGORY_ROLES: dict[str, list[str]] = {
    CONF_INVERTERS: INVERTER_ROLES,
    CONF_GRID_METERS: [CONF_GRID_POWER],
    CONF_BATTERY_STORAGES: [CONF_BATTERY_POWER, CONF_BATTERY_SOC],
    CONF_HEAT_PUMPS: [CONF_CONSUMPTION_POWER],
    CONF_CAR_CHARGERS: [CONF_BATTERY_POWER, CONF_BATTERY_SOC],
}
