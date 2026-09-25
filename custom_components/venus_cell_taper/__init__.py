"""Home Assistant coordinator for Venus Cell Taper."""

import asyncio
import logging
import math
from datetime import timedelta, datetime, timezone
from time import monotonic

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .const import DOMAIN, LIMIT
from .control import VoltageController

LOGGER = logging.getLogger(__name__)
PLATFORMS = ["switch", "sensor"]


class TaperRuntime:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass, self.entry = hass, entry
        self.controller = VoltageController(
            min_charge_w=int(entry.options.get("min_charge_w", 40))
        )
        self.active = False  # Never resume an interrupted charge after restart.
        self.status = "Aus"
        self.lock = asyncio.Lock()
        self.listeners = []
        self.entities = []

    def value(self, key: str) -> float | None:
        state = self.hass.states.get(self.entry.data[key])
        try:
            result = float(state.state) if state else None
            return result if result is not None and math.isfinite(result) else None
        except (TypeError, ValueError):
            return None

    def voltage(self) -> float | None:
        state = self.hass.states.get(self.entry.data["vmax"])
        if state is None:
            return None
        # A frozen sensor must not leave the battery charging indefinitely.
        reported = getattr(state, "last_reported", None) or state.last_updated
        if (datetime.now(timezone.utc) - reported).total_seconds() > 90:
            return None
        return self.value("vmax")

    def manual(self) -> bool:
        return self.hass.states.is_state(self.entry.data["manual"], "on")

    def notify(self):
        for entity in self.entities:
            entity.async_write_ha_state()

    async def service(self, domain: str, name: str, key: str, field: str, value):
        await self.hass.services.async_call(
            domain, name,
            {"entity_id": self.entry.data[key], field: value}, blocking=True,
        )

    async def stop(self, reason="Aus"):
        async with self.lock:
            self.active = False
            self.status = reason
            # Do not take control if the user already left manual mode.
            if self.manual():
                try:
                    await self.service("select", "select_option", "force", "option", "None")
                except Exception:
                    LOGGER.exception("Unable to stop charging; check Force Mode immediately")
                    self.status = "STOPP fehlgeschlagen – Force Mode prüfen"
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
            try:
                # Explicit idle handoff; the manual mode itself is never changed.
                await self.service("select", "select_option", "force", "option", "None")
                power = self.controller.start(voltage, monotonic())
                await self.service("number", "set_value", "power", "value", power)
                # Recheck after awaited I/O; voltage/manual ownership may have
                # changed while the start sequence was in flight.
                if not self.manual() or self.voltage() is None or self.voltage() >= 3.52:
                    raise ValueError("voltage or manual ownership changed during start")
                self.active = True
                await self.service("select", "select_option", "force", "option", "Charge")
                if not self.manual() or self.voltage() is None or self.voltage() >= LIMIT:
                    raise ValueError("voltage or manual ownership changed during charge command")
                self.status = f"Laden {power} W"
            except Exception:
                LOGGER.exception("Unable to start regulator")
                self.active = False
                self.status = "Start fehlgeschlagen"
                if self.manual():
                    try:
                        await self.service("select", "select_option", "force", "option", "None")
                    except Exception:
                        LOGGER.exception("Unable to restore idle Force Mode")
                        self.status = "STOPP fehlgeschlagen – Force Mode prüfen"
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
        async with self.lock:
            if not self.active:
                return
            try:
                proposed = self.controller.update(voltage, monotonic())
                if proposed is not None:
                    await self.service("number", "set_value", "power", "value", proposed)
                    self.status = f"Laden {proposed} W"
                    self.notify()
            except Exception as exc:
                LOGGER.exception("Control cycle failed")
                self.active = False
                self.status = (
                    "Stopp: Mindestleistung hält Zellspannung nicht"
                    if isinstance(exc, ValueError) else "Regelfehler – gestoppt"
                )
                try:
                    await self.service("select", "select_option", "force", "option", "None")
                except Exception:
                    LOGGER.exception("Unable to stop after control error")
                    self.status = "STOPP fehlgeschlagen – Force Mode prüfen"
                self.notify()

    @callback
    def state_changed(self, event):
        if not self.active:
            return
        entity_id = event.data.get("entity_id")
        if entity_id == self.entry.data["manual"] and not self.manual():
            self.hass.async_create_task(self.stop("Manueller Modus aus"))
        if entity_id == self.entry.data["vmax"]:
            voltage = self.voltage()
            if voltage is None or voltage >= LIMIT:
                self.hass.async_create_task(self.stop("Spannungsstopp"))

    async def async_setup(self):
        self.listeners.append(async_track_time_interval(self.hass, self.tick, timedelta(seconds=10)))
        self.listeners.append(async_track_state_change_event(
            self.hass, [self.entry.data["manual"], self.entry.data["vmax"]], self.state_changed
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
