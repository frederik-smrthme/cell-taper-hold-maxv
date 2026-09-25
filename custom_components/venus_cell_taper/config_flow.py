import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import DOMAIN

DOMAINS = {
    "manual": "switch", "vmax": "sensor", "vmin": "sensor",
    "ac": "sensor", "dc": "sensor", "power": "number", "force": "select",
}


class VenusCellTaperFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(user_input["manual"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Venus Cell Taper", data=user_input)
        schema = vol.Schema({
            vol.Required(key): EntitySelector(EntitySelectorConfig(domain=domain))
            for key, domain in DOMAINS.items()
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return VenusCellTaperOptionsFlow()


class VenusCellTaperOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = int(self.config_entry.options.get("min_charge_w", 40))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("min_charge_w", default=current): vol.In([10, 20, 30, 40, 50])
            }),
        )
