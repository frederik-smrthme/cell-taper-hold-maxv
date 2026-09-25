from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    entity = RegulatorSwitch(runtime)
    runtime.entities.append(entity)
    async_add_entities([entity])


class RegulatorSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "regulator"
    _attr_icon = "mdi:battery-sync"

    def __init__(self, runtime):
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_regulator"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, runtime.entry.entry_id)},
            "name": "Venus Cell Taper",
            "manufacturer": "Community",
        }

    @property
    def is_on(self):
        return self.runtime.active

    async def async_turn_on(self, **kwargs):
        await self.runtime.start()

    async def async_turn_off(self, **kwargs):
        await self.runtime.stop("Vom Benutzer gestoppt")
