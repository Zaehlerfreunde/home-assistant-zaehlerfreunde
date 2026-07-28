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
HEMS_URL = "https://external.prod.zaehlerfreunde.com"
LINK_POLLING_INTERVAL_SECONDS = 2
LINK_POLLING_TIMEOUT_SECONDS = 600

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_SETUP_CODE = "setup_code"
CONF_ENTITY_ROLES = "entry_entity_roles"

LAST_UPLOAD_SENSOR_KEY = "last_upload_sensor"

COMMAND_POLLING_INTERVAL_SECONDS = 30

# Command types sent by the HEMS backend
COMMAND_START_CHARGING = "start_charging"
COMMAND_STOP_CHARGING = "stop_charging"
COMMAND_SET_CHARGING_RATE = "set_charging_rate"
COMMAND_SET_BATTERY_MODE = "set_battery_mode"
COMMAND_SET_HEAT_PUMP_MODE = "set_heat_pump_mode"

# Config keys for storing user-configured option mappings
CONF_BATTERY_MODE_MAPPINGS = "battery_mode_mappings"
CONF_HEAT_PUMP_MODE_MAPPINGS = "heat_pump_mode_mappings"

# Canonical semantic modes (keys the backend sends)
BATTERY_MODES = ["charge", "discharge", "idle"]
HEAT_PUMP_MODES = ["boost", "normal"]

# Inverter sensor roles
CONF_SOLAR_POWER = "solar_power"
CONF_SOLAR_YIELD_TOTAL = "solar_yield_total"
CONF_GRID_POWER = "grid_power"
CONF_BATTERY_POWER = "battery_power"
CONF_BATTERY_SOC = "battery_soc"
CONF_CONSUMPTION_POWER = "consumption_power"

# Control roles (for HEMS command execution)
CONF_CHARGING_SWITCH = "charging_switch"
CONF_CHARGING_RATE = "charging_rate"
CONF_BATTERY_MODE = "battery_mode"
CONF_HEAT_PUMP_MODE = "heat_pump_mode"

INVERTER_ROLES: list[str] = [
    CONF_SOLAR_POWER,
    CONF_SOLAR_YIELD_TOTAL,
]

# Roles per category: list of (config_key, display_label) tuples.
# Only categories with at least one role are shown in the config flow.
CATEGORY_ROLES: dict[str, list[str]] = {
    CONF_INVERTERS: INVERTER_ROLES,
    CONF_GRID_METERS: [CONF_GRID_POWER],
    CONF_BATTERY_STORAGES: [CONF_BATTERY_POWER, CONF_BATTERY_SOC, CONF_BATTERY_MODE],
    CONF_HEAT_PUMPS: [CONF_CONSUMPTION_POWER, CONF_HEAT_PUMP_MODE],
    CONF_CAR_CHARGERS: [CONF_BATTERY_POWER, CONF_BATTERY_SOC, CONF_CHARGING_SWITCH, CONF_CHARGING_RATE],
}

LAST_COMMAND_SENSOR_KEY = "last_command_sensor"
LAST_POLL_SENSOR_KEY = "last_poll_sensor"

# Command types relevant to each device category
CATEGORY_COMMAND_TYPES: dict[str, list[str]] = {
    CONF_CAR_CHARGERS: [COMMAND_START_CHARGING, COMMAND_STOP_CHARGING, COMMAND_SET_CHARGING_RATE],
    CONF_BATTERY_STORAGES: [COMMAND_SET_BATTERY_MODE],
    CONF_HEAT_PUMPS: [COMMAND_SET_HEAT_PUMP_MODE],
}
