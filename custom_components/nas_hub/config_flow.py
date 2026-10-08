"""Config flow: one entry per service, keys changeable later via Reconfigure."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CLIENTS, AuthError, EbooksClient, SeerrClient, ServiceError
from .const import (
    CONF_API_KEY,
    CONF_PUBLIC_URL,
    CONF_SERVICE,
    CONF_URL,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_ITEM_COUNT,
    DEFAULT_LIST_MINUTES,
    DEFAULT_LIST_MINUTES_BY_SERVICE,
    DEFAULT_LIVE_SECONDS,
    DEFAULT_MIN_REQUEST_DAYS,
    DEFAULT_URLS,
    DOMAIN,
    OPT_AVAILABILITY_ENTITY,
    OPT_DAYS_AHEAD,
    OPT_ITEM_COUNT,
    OPT_LIST_MINUTES,
    OPT_LIVE_SECONDS,
    OPT_MIN_REQUEST_DAYS,
    OPT_NOTIFY_MAP,
    OPT_SHOW_CINEMA,
    SERVICE_AUDIOBOOKSHELF,
    SERVICE_EBOOKS,
    SERVICE_JELLYFIN,
    SERVICE_NAMES,
    SERVICE_RADARR,
    SERVICE_SEERR,
    SERVICE_SONARR,
)

URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


# Services that run in the home network without a login (ebook-sender)
KEYLESS = {SERVICE_EBOOKS}


def _service_schema(service: str, defaults: Mapping[str, Any]) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Required(CONF_URL, default=defaults.get(CONF_URL, DEFAULT_URLS.get(service, ""))): URL_SELECTOR,
    }
    if service not in KEYLESS:
        schema[vol.Required(CONF_API_KEY, default=defaults.get(CONF_API_KEY, ""))] = KEY_SELECTOR
    schema[vol.Optional(
        CONF_PUBLIC_URL,
        description={"suggested_value": defaults.get(CONF_PUBLIC_URL)},
    )] = URL_SELECTOR
    return vol.Schema(schema)


async def _validate(hass, service: str, data: Mapping[str, Any]) -> str | None:
    """None if the service answered with this key, else an error key."""
    client = CLIENTS[service](async_get_clientsession(hass), data[CONF_URL], data.get(CONF_API_KEY, ""))
    try:
        await client.validate()
    except AuthError:
        return "invalid_auth"
    except ServiceError:
        return "cannot_connect"
    return None


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {k: v.strip() if isinstance(v, str) else v for k, v in user_input.items()}
    data[CONF_URL] = data[CONF_URL].rstrip("/")
    if data.get(CONF_PUBLIC_URL):
        data[CONF_PUBLIC_URL] = data[CONF_PUBLIC_URL].rstrip("/")
    else:
        data.pop(CONF_PUBLIC_URL, None)
    return data


class NasHubConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=[SERVICE_JELLYFIN, SERVICE_AUDIOBOOKSHELF, SERVICE_SONARR, SERVICE_RADARR, SERVICE_SEERR, SERVICE_EBOOKS],
        )

    async def _service_step(self, service: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            await self.async_set_unique_id(f"{service}_{data[CONF_URL].lower()}")
            self._abort_if_unique_id_configured()
            error = await _validate(self.hass, service, data)
            if error is None:
                return self.async_create_entry(
                    title=SERVICE_NAMES[service], data={CONF_SERVICE: service, **data}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id=service,
            data_schema=_service_schema(service, user_input or {}),
            errors=errors,
        )

    async def async_step_jellyfin(self, user_input=None) -> ConfigFlowResult:
        return await self._service_step(SERVICE_JELLYFIN, user_input)

    async def async_step_audiobookshelf(self, user_input=None) -> ConfigFlowResult:
        return await self._service_step(SERVICE_AUDIOBOOKSHELF, user_input)

    async def async_step_sonarr(self, user_input=None) -> ConfigFlowResult:
        return await self._service_step(SERVICE_SONARR, user_input)

    async def async_step_radarr(self, user_input=None) -> ConfigFlowResult:
        return await self._service_step(SERVICE_RADARR, user_input)

    async def async_step_seerr(self, user_input=None) -> ConfigFlowResult:
        return await self._service_step(SERVICE_SEERR, user_input)

    async def async_step_ebooks(self, user_input=None) -> ConfigFlowResult:
        return await self._service_step(SERVICE_EBOOKS, user_input)

    # ── change URL or key later ──

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        service = entry.data[CONF_SERVICE]
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            error = await _validate(self.hass, service, data)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data={CONF_SERVICE: service, **data},
                    unique_id=f"{service}_{data[CONF_URL].lower()}",
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_service_schema(service, user_input or entry.data),
            errors=errors,
            description_placeholders={"service": SERVICE_NAMES[service]},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        service = entry.data[CONF_SERVICE]
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_API_KEY: user_input[CONF_API_KEY].strip()}
            error = await _validate(self.hass, service, data)
            if error is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): KEY_SELECTOR}),
            errors=errors,
            description_placeholders={"service": SERVICE_NAMES[service]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NasHubOptionsFlow:
        return NasHubOptionsFlow()


def _number(minimum: int, maximum: int, step: int = 1, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX)
    # The selector rejects unit_of_measurement=None, so only pass a real unit
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


class NasHubOptionsFlow(OptionsFlow):
    """Intervals, list length, look-ahead and the entity that tells if the NAS sleeps.

    Seerr additionally maps each Seerr user to a notify service. The users are
    asked for live, so their names become the field labels ("Name (#id)").
    """

    def __init__(self) -> None:
        super().__init__()
        self._users: list[dict] | None = None

    async def _service_users(self, service: str) -> list[dict]:
        """Seerr's or ebook-sender's users, asked for live."""
        if self._users is None:
            data = self.config_entry.data
            client_cls = SeerrClient if service == SERVICE_SEERR else EbooksClient
            client = client_cls(async_get_clientsession(self.hass), data[CONF_URL], data.get(CONF_API_KEY, ""))
            try:
                self._users = await client.fetch_users()
            except ServiceError:
                self._users = []
        return self._users

    @staticmethod
    def _user_field(user: dict) -> str:
        return f"{user['name']} (#{user['id']})"

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        service = self.config_entry.data[CONF_SERVICE]
        opts = self.config_entry.options
        notifies = service in (SERVICE_SEERR, SERVICE_EBOOKS)
        users = await self._service_users(service) if notifies else []

        if user_input is not None:
            data = {k: int(v) if isinstance(v, float) else v for k, v in user_input.items()}
            if notifies:
                if users:
                    mapping = {}
                    for user in users:
                        target = data.pop(self._user_field(user), None)
                        if target:
                            mapping[str(user["id"])] = target
                    data[OPT_NOTIFY_MAP] = mapping
                else:
                    # Service unreachable: keep who was mapped before
                    data[OPT_NOTIFY_MAP] = opts.get(OPT_NOTIFY_MAP, {})
            return self.async_create_entry(title="", data=data)

        schema: dict[Any, Any] = {
            vol.Required(OPT_ITEM_COUNT, default=opts.get(OPT_ITEM_COUNT, DEFAULT_ITEM_COUNT)): _number(1, 30),
        }
        list_default = DEFAULT_LIST_MINUTES_BY_SERVICE.get(service, DEFAULT_LIST_MINUTES)
        schema[vol.Required(OPT_LIST_MINUTES, default=opts.get(OPT_LIST_MINUTES, list_default))] = _number(
            1 if service in KEYLESS else 5, 1440, unit="min"
        )
        if service not in (SERVICE_SEERR, SERVICE_EBOOKS):
            schema[vol.Required(OPT_LIVE_SECONDS, default=opts.get(OPT_LIVE_SECONDS, DEFAULT_LIVE_SECONDS))] = _number(15, 600, unit="s")
        if service in DEFAULT_DAYS_AHEAD:
            schema[vol.Required(OPT_DAYS_AHEAD, default=opts.get(OPT_DAYS_AHEAD, DEFAULT_DAYS_AHEAD[service]))] = _number(1, 365, unit="d")
        if service == SERVICE_RADARR:
            schema[vol.Required(OPT_SHOW_CINEMA, default=opts.get(OPT_SHOW_CINEMA, False))] = BooleanSelector()
        schema[vol.Optional(
            OPT_AVAILABILITY_ENTITY,
            description={"suggested_value": opts.get(OPT_AVAILABILITY_ENTITY)},
        )] = EntitySelector(EntitySelectorConfig())

        placeholders = {}
        step_id = "init"
        if notifies:
            step_id = service
            schema[vol.Required(
                OPT_MIN_REQUEST_DAYS, default=opts.get(OPT_MIN_REQUEST_DAYS, DEFAULT_MIN_REQUEST_DAYS)
            )] = _number(0, 90, unit="d")
            notify = sorted(self.hass.services.async_services_for_domain("notify"))
            selector = SelectSelector(SelectSelectorConfig(
                options=[SelectOptionDict(value=name, label=f"notify.{name}") for name in notify],
                mode=SelectSelectorMode.DROPDOWN,
            ))
            mapping = opts.get(OPT_NOTIFY_MAP, {})
            for user in users:
                schema[vol.Optional(
                    self._user_field(user),
                    description={"suggested_value": mapping.get(str(user["id"]))},
                )] = selector
            placeholders["users"] = (
                ", ".join(u["name"] for u in users) if users else "– (nicht erreichbar / not reachable)"
            )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(schema),
            description_placeholders=placeholders,
        )

    async def async_step_seerr(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_init(user_input)

    async def async_step_ebooks(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_init(user_input)
