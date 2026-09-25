from homeassistant.components.sensor import SensorEntity
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    entity = StatusSensor(runtime)
    runtime.entities.append(entity)
    async_add_entities([entity])


class StatusSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "status"
    _attr_icon = "mdi:chart-line"

    def __init__(self, runtime):
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_status"
        self._attr_device_info = {"identifiers": {(DOMAIN, runtime.entry.entry_id)}}

    @property
    def native_value(self):
        return self.runtime.status

    @property
    def extra_state_attributes(self):
        return {
            "vmax": self.runtime.value("vmax"),
            "vmin": self.runtime.value("vmin"),
            "ac_power": self.runtime.value("ac"),
            "dc_power": self.runtime.value("dc"),
            "requested_power": self.runtime.controller.power,
            "minimum_charge_power": self.runtime.controller.min_charge_w,
            "manual_mode": self.runtime.manual(),
        }
