"""Home Assistant coordinator for Venus Cell Taper."""

import asyncio
import logging
import math
from datetime import timedelta, datetime, timezone
from time import monotonic

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .const import DOMAIN, LIMIT, FIELDS
from .control import VoltageController

LOGGER = logging.getLogger(__name__)
PLATFORMS = ["switch", "sensor"]


class TaperRuntime:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass, self.entry = hass, entry
        self.entities_config = {key: entry.options.get(key, entry.data[key]) for key in FIELDS}
        self.controller = VoltageController(
            min_charge_w=int(entry.options.get("min_charge_w", 40))
        )
        self.active = False  # Never resume an interrupted charge after restart.
        self.status = "Aus"
        self.lock = asyncio.Lock()
        self.started_at = 0.0
        self.no_dc_ticks = 0
        self.listeners = []
        self.entities = []

    def value(self, key: str) -> float | None:
        state = self.hass.states.get(self.entities_config[key])
        try:
            result = float(state.state) if state else None
            return result if result is not None and math.isfinite(result) else None
        except (TypeError, ValueError):
            return None

    def voltage(self) -> float | None:
        state = self.hass.states.get(self.entities_config["vmax"])
        if state is None:
            return None
        # A frozen sensor must not leave the battery charging indefinitely.
        reported = getattr(state, "last_reported", None) or state.last_updated
        if (datetime.now(timezone.utc) - reported).total_seconds() > 90:
            return None
        return self.value("vmax")

    def manual(self) -> bool:
        return self.hass.states.is_state(self.entities_config["manual"], "on")

    def notify(self):
        for entity in self.entities:
            entity.async_write_ha_state()

    async def service(self, domain: str, name: str, key: str, field: str, value):
        await self.hass.services.async_call(
            domain, name,
            {"entity_id": self.entities_config[key], field: value}, blocking=True,
        )

    async def verified_write(self, domain: str, name: str, key: str, field: str, value):
        """Require a readback: Omnibattery can swallow a failed register write."""
        await self.service(domain, name, key, field, value)
        last_seen = None
        for attempt in range(11):
            state = self.hass.states.get(self.entities_config[key])
            last_seen = state.state if state else "nicht verfügbar"
            if state is not None:
                if key == "power":
                    try:
                        if abs(float(state.state) - float(value)) <= 1:
                            return
                    except (ValueError, TypeError):
                        pass
                elif state.state == value:
                    return
            if attempt < 10:
                await asyncio.sleep(0.5)
        raise ValueError(
            f"{self.entities_config[key]}: Soll {value}, Rückmeldung {last_seen} "
            "nach 5 Sekunden"
        )

    async def safe_idle(self) -> bool:
        """Stop charging; try 0 W if Force Mode cannot be confirmed."""
        if not self.manual():
            return True  # Omnibattery owns the handoff after manual mode exits.
        try:
            await self.verified_write("select", "select_option", "force", "option", "None")
            return True
        except Exception:
            LOGGER.exception("Force Mode None was not confirmed; trying 0 W")
            try:
                await self.verified_write("number", "set_value", "power", "value", 0)
                self.status = "Force Mode nicht bestätigt – Ladesollwert 0 W"
                return False
            except Exception:
                LOGGER.exception("Neither Force Mode None nor 0 W was confirmed")
                self.status = "STOPP fehlgeschlagen – Batterie sofort prüfen"
                return False

    async def stop(self, reason="Aus"):
        async with self.lock:
            self.active = False
            self.status = reason
            await self.safe_idle()
            self.notify()

    async def start(self):
        async with self.lock:
            if self.active:
                return
            voltage = self.voltage()
            if not self.manual() or voltage is None or voltage >= 3.52:
                self.status = "Start verweigert: manueller Modus oder Vmax prüfen"
                self.notify()
                return
            power_entity = self.hass.states.get(self.entities_config["power"])
            force_entity = self.hass.states.get(self.entities_config["force"])
            if power_entity is None or force_entity is None:
                self.status = "Start verweigert: Ladesoll oder Force Mode fehlt"
                self.notify()
                return
            try:
                # Explicit idle handoff; the manual mode itself is never changed.
                await self.verified_write("select", "select_option", "force", "option", "None")
                power = self.controller.start(voltage, monotonic())
                ceiling = power_entity.attributes.get("max")
                if ceiling is not None and float(ceiling) < power:
                    raise ValueError(f"Ladesoll begrenzt auf {ceiling} W; Start benötigt {power} W")
                await self.verified_write("number", "set_value", "power", "value", power)
                # Recheck after awaited I/O; voltage/manual ownership may have
                # changed while the start sequence was in flight.
                if not self.manual() or self.voltage() is None or self.voltage() >= 3.52:
                    raise ValueError("voltage or manual ownership changed during start")
                self.active = True
                await self.verified_write("select", "select_option", "force", "option", "Charge")
                if not self.manual() or self.voltage() is None or self.voltage() >= LIMIT:
                    raise ValueError("voltage or manual ownership changed during charge command")
                self.started_at = monotonic()
                self.no_dc_ticks = 0
                self.status = f"Laden {power} W"
            except Exception as exc:
                LOGGER.exception("Unable to start regulator")
                self.active = False
                self.status = f"Start fehlgeschlagen: {exc}"
                await self.safe_idle()
            self.notify()

    async def tick(self, _now=None):
        if not self.active:
            return
        if not self.manual():
            await self.stop("Manueller Modus aus")
            return
        voltage = self.voltage()
        if voltage is None or voltage >= LIMIT:
            await self.stop("Stopp: Vmax fehlt oder Grenzwert erreicht")
            return
        if not self.hass.states.is_state(self.entities_config["force"], "Charge"):
            await self.stop("Stopp: Force Mode nicht mehr Charge")
            return
        dc_power = self.value("dc")
        if dc_power is None:
            await self.stop("Stopp: DC-Leistung nicht verfügbar")
            return
        if monotonic() - self.started_at >= 30:
            self.no_dc_ticks = self.no_dc_ticks + 1 if dc_power <= 2 else 0
            if self.no_dc_ticks >= 3:
                await self.stop("Stopp: keine DC-Ladung")
                return
        async with self.lock:
            if not self.active:
                return
            try:
                proposed = self.controller.update(voltage, monotonic())
                if proposed is not None:
                    await self.verified_write("number", "set_value", "power", "value", proposed)
                    self.status = f"Laden {proposed} W"
                    self.notify()
            except Exception as exc:
                LOGGER.exception("Control cycle failed")
                self.active = False
                self.status = (
                    "Stopp: Mindestleistung hält Zellspannung nicht"
                    if isinstance(exc, ValueError) else "Regelfehler – gestoppt"
                )
                await self.safe_idle()
                self.notify()

    @callback
    def state_changed(self, event):
        if not self.active:
            return
        entity_id = event.data.get("entity_id")
        if entity_id == self.entities_config["manual"] and not self.manual():
            self.hass.async_create_task(self.stop("Manueller Modus aus"))
        if entity_id == self.entities_config["vmax"]:
            voltage = self.voltage()
            if voltage is None or voltage >= LIMIT:
                self.hass.async_create_task(self.stop("Spannungsstopp"))

    async def async_setup(self):
        self.listeners.append(async_track_time_interval(self.hass, self.tick, timedelta(seconds=10)))
        self.listeners.append(async_track_state_change_event(
            self.hass, [self.entities_config["manual"], self.entities_config["vmax"]], self.state_changed
        ))

    async def async_unload(self):
        if self.active:
            await self.stop("Integration entladen")
        for unsubscribe in self.listeners:
            unsubscribe()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = TaperRuntime(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await runtime.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload safely when the minimum is changed; never resume charging."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = hass.data[DOMAIN][entry.entry_id]
    await runtime.async_unload()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
