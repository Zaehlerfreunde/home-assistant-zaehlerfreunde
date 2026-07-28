"""Config flow for Zaehlerfreunde."""

from __future__ import annotations

import asyncio
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers import instance_id

from .api_client import (
    LinkSessionError,
    async_check_link_status,
    async_get_link_tokens,
    async_start_link_session,
)
from .const import (
    BATTERY_MODES,
    CATEGORY_ROLES,
    CONF_ACCESS_TOKEN,
    CONF_BATTERY_MODE,
    CONF_BATTERY_MODE_MAPPINGS,
    CONF_BATTERY_STORAGES,
    CONF_CAR_CHARGERS,
    CONF_CHARGING_RATE,
    CONF_CHARGING_SWITCH,
    CONF_ENTITY_ROLES,
    CONF_GRID_METERS,
    CONF_HEAT_PUMP_MODE,
    CONF_HEAT_PUMP_MODE_MAPPINGS,
    CONF_HEAT_PUMPS,
    CONF_INVERTERS,
    CONF_REFRESH_TOKEN,
    CONF_SETUP_CODE,
    DEFAULT_NAME,
    DEVICE_SELECTION_KEYS,
    HEAT_PUMP_MODES,
    LINK_POLLING_INTERVAL_SECONDS,
    LINK_POLLING_TIMEOUT_SECONDS,
    PARTNER_ID,
)

CONF_ADD_MORE = "add_more"
CONF_CATEGORY = "category"
CONF_DEVICE_ID = "device_id"

_LOGGER = logging.getLogger(__name__)

_CATEGORY_LABELS = {
    CONF_INVERTERS: "inverter",
    CONF_GRID_METERS: "grid",
    CONF_BATTERY_STORAGES: "battery",
    CONF_HEAT_PUMPS: "heat pump",
    CONF_CAR_CHARGERS: "car charger",
}

_CATEGORY_OPTIONS: list[selector.SelectOptionDict] = [
    selector.SelectOptionDict(value=CONF_INVERTERS, label="inverters"),
    selector.SelectOptionDict(value=CONF_GRID_METERS, label="grid_meters"),
    selector.SelectOptionDict(value=CONF_BATTERY_STORAGES, label="battery_storages"),
    selector.SelectOptionDict(value=CONF_HEAT_PUMPS, label="heat_pumps"),
    selector.SelectOptionDict(value=CONF_CAR_CHARGERS, label="car_chargers"),
]


def _category_selector() -> selector.SelectSelector:
    """Build category selector, limited to categories with defined roles."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[opt for opt in _CATEGORY_OPTIONS if CATEGORY_ROLES.get(opt["value"])],
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="category",
        )
    )


def _device_selector() -> selector.DeviceSelector:
    """Build device selector."""
    return selector.DeviceSelector(selector.DeviceSelectorConfig())


def _entity_selector(entity_ids: list[str]) -> selector.EntitySelector:
    """Build a single-entity selector filtered by a fixed entity allowlist."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            multiple=False,
            include_entities=entity_ids,
        )
    )


def _entity_ids_for_device(hass, device_id: str | None) -> list[str]:
    """Return selectable entity IDs, optionally filtered by device."""
    entity_registry = er.async_get(hass)
    entity_ids = [
        entry.entity_id
        for entry in entity_registry.entities.values()
        if (device_id is None or entry.device_id == device_id)
        and entry.disabled_by is None
    ]
    entity_ids.sort()
    return entity_ids


def _category_step_schema() -> vol.Schema:
    """Build schema for category selection."""
    return vol.Schema(
        {
            vol.Required(CONF_CATEGORY): _category_selector(),
        }
    )


def _device_step_schema() -> vol.Schema:
    """Build schema for device selection (optional)."""
    return vol.Schema(
        {
            vol.Optional(CONF_DEVICE_ID): _device_selector(),
        }
    )


def _role_step_schema(
    roles: list[str], entity_ids: list[str]
) -> vol.Schema:
    """Build schema for role-based entity mapping."""
    return vol.Schema(
        {vol.Optional(role): _entity_selector(entity_ids) for role in roles}
    )


def _device_name(hass, device_id: str) -> str:
    """Resolve a display name for a device ID."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)
    if device is None:
        return device_id
    return device.name_by_user or device.name or device_id


def _category_default_name(category: str | None) -> str:
    """Return a human-readable default name for a category when no device is selected."""
    label = _CATEGORY_LABELS.get(category or "", DEFAULT_NAME)
    return label.capitalize()


def _build_entry_description(category: str, device_name: str, role_entities: dict[str, str]) -> str:
    """Build a readable description for the created config entry."""
    category_label = _CATEGORY_LABELS.get(category, category)
    entity_list = ", ".join(f"{role}={eid}" for role, eid in role_entities.items())
    return f"type={category_label}; device={device_name}; entities={entity_list}"


def _entity_select_options(hass, entity_id: str) -> list[str]:
    """Return the available options for a select entity from the HA state machine."""
    state = hass.states.get(entity_id)
    return list(state.attributes.get("options", [])) if state else []


def _mode_mapping_schema(options: list[str], modes: list[str]) -> vol.Schema:
    """Build a schema that maps each semantic mode to one of the entity's native options."""
    opt_dicts = [selector.SelectOptionDict(value=o, label=o) for o in options]
    return vol.Schema(
        {
            vol.Required(mode): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=opt_dicts,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
            for mode in modes
        }
    )


class ZaehlerfreundeConfigFlow(config_entries.ConfigFlow, domain=PARTNER_ID):
    """Handle a config flow for Zaehlerfreunde."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._selected_category: str | None = None
        self._selected_device_id: str | None = None
        self._setup_code: str | None = None
        self._verification_url: str | None = None
        self._link_approved: bool = False
        self._link_error: str | None = None
        self._link_error_detail: str | None = None
        self._poll_task = None
        self._pending_mode_mapping_steps: list[str] = []

    async def async_step_user(self, user_input: dict | None = None):
        """Show an introduction screen, then proceed to category selection."""
        _LOGGER.debug("Config flow: user step called (user_input=%s)", user_input is not None)
        if user_input is not None:
            try:
                return await self.async_step_select_category()
            except Exception:  # pragma: no cover - defensive safety net
                _LOGGER.exception("Unexpected error while starting config flow")
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({}),
                    errors={"base": "unexpected_error"},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )

    async def async_step_select_category(self, user_input: dict | None = None):
        """Select which device category to configure."""
        errors: dict[str, str] = {}
        if user_input is not None:
            _LOGGER.debug("Config flow: category selected: %s", user_input.get(CONF_CATEGORY))
            try:
                selected_category = user_input.get(CONF_CATEGORY)
                if selected_category not in DEVICE_SELECTION_KEYS:
                    errors["base"] = "invalid_category"
                else:
                    self._selected_category = selected_category
                    return await self.async_step_select_device()
            except Exception:  # pragma: no cover - defensive safety net
                _LOGGER.exception("Unexpected error while selecting category")
                errors["base"] = "unexpected_error"

        return self.async_show_form(
            step_id="select_category",
            data_schema=_category_step_schema(),
            errors=errors,
        )

    async def async_step_select_device(self, user_input: dict | None = None):
        """Select a Home Assistant device (optional)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected_device_id = user_input.get(CONF_DEVICE_ID) or None
            _LOGGER.debug("Config flow: device selected: %s", selected_device_id)
            try:
                if selected_device_id and not _entity_ids_for_device(self.hass, selected_device_id):
                    errors["base"] = "no_entities_for_device"
                    return self.async_show_form(
                        step_id="select_device",
                        data_schema=_device_step_schema(),
                        errors=errors,
                    )
                self._selected_device_id = selected_device_id
                return await self.async_step_select_entities()
            except Exception:  # pragma: no cover - defensive safety net
                _LOGGER.exception("Unexpected error while selecting device")
                errors["base"] = "unexpected_error"

        return self.async_show_form(
            step_id="select_device",
            data_schema=_device_step_schema(),
            errors=errors,
        )

    async def async_step_select_entities(self, user_input: dict | None = None):
        """Select entities, optionally filtered to the chosen device."""
        if self._selected_category is None:
            return await self.async_step_select_category()

        selectable_entity_ids = _entity_ids_for_device(self.hass, self._selected_device_id)
        if not selectable_entity_ids:
            return self.async_show_form(
                step_id="select_device",
                data_schema=_device_step_schema(),
                errors={"base": "no_entities_for_device"},
            )

        roles = CATEGORY_ROLES.get(self._selected_category, [])
        errors: dict[str, str] = {}
        if user_input is not None:
            _LOGGER.debug(
                "Config flow: entity roles submitted for category %s: %s",
                self._selected_category,
                {role: user_input[role] for role in roles if role in user_input},
            )
            try:
                entity_roles = {
                     user_input[role]: role
                    for role in roles
                    if role in user_input
                }
                if not entity_roles:
                    errors["base"] = "no_entities_selected"
                else:
                    device_name = _device_name(self.hass, self._selected_device_id) if self._selected_device_id else _category_default_name(self._selected_category)
                    entry_data = {
                        CONF_ENTITY_ROLES: entity_roles,
                        "entry_device_type": self._selected_category,
                        "entry_device_id": self._selected_device_id,
                        "entry_device_name": device_name,
                        "entry_description": _build_entry_description(
                            self._selected_category,
                            device_name,
                            entity_roles,
                        ),
                    }
                    self.context["entry_data"] = entry_data

                    _LOGGER.error("CHecking if any modes are selected")

                    # Queue option-mapping steps for any mode-control roles that were mapped.
                    role_to_entity = {role: eid for eid, role in entity_roles.items()}
                    self._pending_mode_mapping_steps = []
                    if CONF_BATTERY_MODE in role_to_entity:
                        _LOGGER.error("The battery mode is there")
                        self._pending_mode_mapping_steps.append("map_battery_mode")
                    if CONF_HEAT_PUMP_MODE in role_to_entity:
                        self._pending_mode_mapping_steps.append("map_heat_pump_mode")

                    return await self._async_next_step_or_link_open()
            except Exception:  # pragma: no cover - defensive safety net
                _LOGGER.exception("Unexpected error while selecting entities")
                errors["base"] = "unexpected_error"

        return self.async_show_form(
            step_id="select_entities",
            data_schema=_role_step_schema(roles, selectable_entity_ids),
            errors=errors,
        )

    async def _async_next_step_or_link_open(self):
        """Navigate to the next mode-mapping step, or proceed to link_open."""
        if self._pending_mode_mapping_steps:
            step = self._pending_mode_mapping_steps.pop(0)
            return await getattr(self, f"async_step_{step}")()
        return await self.async_step_link_open()

    async def async_step_map_battery_mode(self, user_input: dict | None = None):
        """Ask user to map semantic battery modes (charge/discharge/idle) to native options."""
        entry_data = self.context["entry_data"]
        role_to_entity = {role: eid for eid, role in entry_data[CONF_ENTITY_ROLES].items()}
        entity_id = role_to_entity[CONF_BATTERY_MODE]
        options = _entity_select_options(self.hass, entity_id)

        if not options:
            _LOGGER.warning(
                "Config flow: battery_mode entity %s has no options; skipping mapping step", entity_id
            )
            entry_data[CONF_BATTERY_MODE_MAPPINGS] = {}
            return await self._async_next_step_or_link_open()

        if user_input is not None:
            entry_data[CONF_BATTERY_MODE_MAPPINGS] = dict(user_input)
            return await self._async_next_step_or_link_open()

        return self.async_show_form(
            step_id="map_battery_mode",
            data_schema=_mode_mapping_schema(options, BATTERY_MODES),
            description_placeholders={"entity_id": entity_id},
        )

    async def async_step_map_heat_pump_mode(self, user_input: dict | None = None):
        """Ask user to map semantic heat pump modes (boost/normal) to native options."""
        entry_data = self.context["entry_data"]
        role_to_entity = {role: eid for eid, role in entry_data[CONF_ENTITY_ROLES].items()}
        entity_id = role_to_entity[CONF_HEAT_PUMP_MODE]
        options = _entity_select_options(self.hass, entity_id)

        if not options:
            _LOGGER.warning(
                "Config flow: heat_pump_mode entity %s has no options; skipping mapping step", entity_id
            )
            entry_data[CONF_HEAT_PUMP_MODE_MAPPINGS] = {}
            return await self._async_next_step_or_link_open()

        if user_input is not None:
            entry_data[CONF_HEAT_PUMP_MODE_MAPPINGS] = dict(user_input)
            return await self._async_next_step_or_link_open()

        return self.async_show_form(
            step_id="map_heat_pump_mode",
            data_schema=_mode_mapping_schema(options, HEAT_PUMP_MODES),
            description_placeholders={"entity_id": entity_id},
        )

    async def async_step_link_open(self, user_input: dict | None = None):
        """Start the link session, open the verification URL, then advance automatically."""
        if self._setup_code is None or self._verification_url is None:
            try:
                ha_instance_id = await instance_id.async_get(self.hass)
                _LOGGER.debug(
                    "Config flow: starting link session for category %s, device %s",
                    self._selected_category,
                    self._selected_device_id,
                )

                link_session = await async_start_link_session(
                    ha_instance_id,
                    partner_id=PARTNER_ID,
                    category=self._selected_category,
                    device_name=_device_name(self.hass, self._selected_device_id) if self._selected_device_id else _category_default_name(self._selected_category),
                )
                self._setup_code = link_session.get("setup_code")
                self._verification_url = link_session.get("verification_url")
                _LOGGER.info(
                    "Config flow: link session started, verification_url=%s",
                    self._verification_url,
                )

                if not self._setup_code or not self._verification_url:
                    return self.async_show_form(
                        step_id="link_open",
                        data_schema=vol.Schema({}),
                        errors={"base": "invalid_link_response"},
                    )
            except LinkSessionError as err:
                _LOGGER.error("Failed to start link session: %s", err)
                return self.async_show_form(
                    step_id="link_open",
                    data_schema=vol.Schema({}),
                    errors={"base": "link_session_failed"},
                )
            except Exception:
                _LOGGER.exception("Unexpected error while starting link session")
                return self.async_show_form(
                    step_id="link_open",
                    data_schema=vol.Schema({}),
                    errors={"base": "unexpected_error"},
                )

        # Second call (from _async_advance_from_open): proceed to the polling step.
        if self._poll_task is not None:
            return self.async_external_step_done(next_step_id="link_start")

        # First call: start polling, schedule auto-advance, open the URL.
        self._poll_task = self.hass.async_create_task(self._async_poll_for_approval())
        self.hass.async_create_task(self._async_advance_from_open())
        return self.async_external_step(step_id="link_open", url=self._verification_url)

    async def _async_advance_from_open(self) -> None:
        """Wait briefly so the frontend can open the URL, then advance to the polling step."""
        await asyncio.sleep(1)
        try:
            await self.hass.config_entries.flow.async_configure(self.flow_id)
        except Exception:
            _LOGGER.exception("Failed to advance flow from link open step")

    async def async_step_link_start(self, user_input: dict | None = None):
        """Poll for link approval and advance automatically when approved."""
        if self._setup_code is None or self._poll_task is None:
            return await self.async_step_link_open()

        if not self._poll_task.done():
            return self.async_show_progress(
                step_id="link_start",
                progress_action="link_start",
                progress_task=self._poll_task,
            )

        # Task finished — check outcome.
        # show_progress can only transition to show_progress or show_progress_done,
        # so errors are routed through a dedicated step.
        if self._link_approved:
            return self.async_show_progress_done(next_step_id="link_tokens")

        return self.async_show_progress_done(next_step_id="link_error")

    async def async_step_link_error(self, user_input: dict | None = None):
        """Show the link error and allow the user to retry."""
        _LOGGER.debug(
            "Config flow: link error step (error=%s, detail=%s, retry=%s)",
            self._link_error,
            self._link_error_detail,
            user_input is not None,
        )
        if user_input is not None:
            self._link_error = None
            self._link_error_detail = None
            self._poll_task = None
            self._setup_code = None
            self._verification_url = None
            self._link_approved = False
            return await self.async_step_link_open()

        error = self._link_error or "unexpected_error"
        return self.async_show_form(
            step_id="link_error",
            data_schema=vol.Schema({}),
            errors={"base": error},
            description_placeholders={"error_detail": self._link_error_detail or "Unknown error"},
        )

    async def _async_poll_for_approval(self) -> None:
        """Poll the backend until the link session is approved."""
        _LOGGER.debug("Config flow: starting polling for link approval (setup_code=%s)", self._setup_code)
        start = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start < LINK_POLLING_TIMEOUT_SECONDS:
            try:
                if await async_check_link_status(self._setup_code):
                    self._link_approved = True
                    _LOGGER.info("Config flow: link session approved for setup_code=%s", self._setup_code)
                    return
            except LinkSessionError as err:
                _LOGGER.error("Config flow: failed to check link status: %s", err)
                self._link_error = "link_status_check_failed"
                self._link_error_detail = str(err)
                return
            await asyncio.sleep(LINK_POLLING_INTERVAL_SECONDS)
        _LOGGER.warning(
            "Config flow: link approval timed out after %s seconds",
            LINK_POLLING_TIMEOUT_SECONDS,
        )
        self._link_error = "link_timeout"
        self._link_error_detail = f"No approval received within {LINK_POLLING_TIMEOUT_SECONDS} seconds."
    
    async def async_step_link_tokens(self, user_input: dict | None = None):
        """Fetch tokens and create the config entry."""
        _LOGGER.debug("Config flow: fetching link tokens (setup_code=%s)", self._setup_code)
        if self._setup_code is None:
            return await self.async_step_link_start()

        errors: dict[str, str] = {}

        try:
            tokens = await async_get_link_tokens(self._setup_code)
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")

            if not access_token or not refresh_token:
                errors["base"] = "invalid_tokens_response"
            else:
                _LOGGER.info(
                    "Config flow: successfully obtained tokens, creating entry for device '%s'",
                    self.context.get("entry_data", {}).get("entry_device_name", DEFAULT_NAME),
                )
                entry_data = self.context.get("entry_data", {})
                entry_data[CONF_ACCESS_TOKEN] = access_token
                entry_data[CONF_REFRESH_TOKEN] = refresh_token
                entry_data[CONF_SETUP_CODE] = self._setup_code

                title = entry_data.get("entry_device_name", DEFAULT_NAME)
                return self.async_create_entry(
                    title=title,
                    data=entry_data,
                )
        except LinkSessionError as err:
            _LOGGER.error("Failed to fetch tokens: %s", err)
            errors["base"] = "link_tokens_failed"
        except Exception:
            _LOGGER.exception("Unexpected error while fetching tokens")
            errors["base"] = "unexpected_error"

        if errors:
            return self.async_show_form(
                step_id="link_tokens",
                data_schema=vol.Schema({}),
                errors=errors,
            )

