"""Exercise the Home Assistant command path with a small fake runtime."""
import asyncio
import importlib.util
import pathlib
import sys
import types
import unittest
from time import monotonic
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "venus_cell_taper"


class State:
    def __init__(self, value):
        self.state = str(value)
        self.attributes = {"max": 2300} if isinstance(value, (int, float)) else {}
        self.last_updated = datetime.now(timezone.utc)
        self.last_reported = self.last_updated


class States(dict):
    def is_state(self, entity_id, value):
        state = self.get(entity_id)
        return state is not None and state.state == value


class Services:
    def __init__(self, states):
        self.states = states
        self.calls = []
        self.ignore_power = False
        self.ignore_force_none = False

    async def async_call(self, domain, name, data, blocking):
        self.calls.append((domain, name, data))
        if not (self.ignore_power and domain == "number") and not (
            self.ignore_force_none and domain == "select" and data.get("option") == "None"
        ):
            self.states[data["entity_id"]] = State(data.get("value", data.get("option")))


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        package = sys.modules.get("venus_cell_taper")
        if package is None:
            package = types.ModuleType("venus_cell_taper")
            package.__path__ = [str(ROOT)]
            sys.modules[package.__name__] = package
        ha = types.ModuleType("homeassistant")
        ha.__path__ = []
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = type("HomeAssistant", (), {})
        core.callback = lambda func: func
        entries = types.ModuleType("homeassistant.config_entries")
        entries.ConfigEntry = type("ConfigEntry", (), {})
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        event = types.ModuleType("homeassistant.helpers.event")
        event.async_track_state_change_event = lambda *args: lambda: None
        event.async_track_time_interval = lambda *args: lambda: None
        cls.saved = {name: sys.modules.get(name) for name in (
            "homeassistant", "homeassistant.core", "homeassistant.config_entries",
            "homeassistant.helpers", "homeassistant.helpers.event"
        )}
        sys.modules.update({
            "homeassistant": ha, "homeassistant.core": core,
            "homeassistant.config_entries": entries,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.event": event,
        })
        cls.saved_package = sys.modules.get("venus_cell_taper")
        spec = importlib.util.spec_from_file_location(
            "venus_cell_taper", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
        )
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules["venus_cell_taper"] = cls.module
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        if cls.saved_package is None:
            sys.modules.pop("venus_cell_taper", None)
        else:
            sys.modules["venus_cell_taper"] = cls.saved_package
        for name, previous in cls.saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    async def asyncSetUp(self):
        self.entry = types.SimpleNamespace(data={
            "manual": "switch.manual", "vmax": "sensor.vmax",
            "vmin": "sensor.vmin", "ac": "sensor.ac", "dc": "sensor.dc",
            "power": "number.power", "force": "select.force",
        }, options={"min_charge_w": 30})
        self.states = States({
            "switch.manual": State("on"), "sensor.vmax": State(3.40),
            "number.power": State(0), "select.force": State("None"),
            "sensor.dc": State(300),
        })
        self.services = Services(self.states)
        self.hass = types.SimpleNamespace(states=self.states, services=self.services)
        self.runtime = self.module.TaperRuntime(self.hass, self.entry)

    async def test_start_and_stop_command_order(self):
        await self.runtime.start()
        self.assertTrue(self.runtime.active)
        self.assertEqual(self.runtime.controller.min_charge_w, 30)
        self.assertEqual([call[0] for call in self.services.calls], ["select", "number", "select"])
        self.assertEqual(self.states["select.force"].state, "Charge")
        await self.runtime.stop()
        self.assertFalse(self.runtime.active)
        self.assertEqual(self.states["select.force"].state, "None")

    async def test_failed_setpoint_readback_prevents_charge(self):
        self.services.ignore_power = True
        await self.runtime.start()
        self.assertFalse(self.runtime.active)
        self.assertEqual(self.states["select.force"].state, "None")
        self.assertIn("Rückmeldung 0", self.runtime.status)

    async def test_options_mapping_overrides_initial_data(self):
        self.entry.options["power"] = "number.corrected"
        self.states["number.corrected"] = State(0)
        runtime = self.module.TaperRuntime(self.hass, self.entry)
        await runtime.start()
        self.assertTrue(runtime.active)
        self.assertEqual(self.services.calls[1][2]["entity_id"], "number.corrected")

    async def test_low_maximum_does_not_start_charge(self):
        self.states["number.power"].attributes["max"] = 300
        await self.runtime.start()
        self.assertFalse(self.runtime.active)
        self.assertEqual(self.states["select.force"].state, "None")
        self.assertIn("300 W", self.runtime.status)

    async def test_voltage_limit_stops(self):
        await self.runtime.start()
        self.states["sensor.vmax"] = State(3.55)
        await self.runtime.tick()
        self.assertFalse(self.runtime.active)
        self.assertEqual(self.states["select.force"].state, "None")

    async def test_manual_mode_required(self):
        self.states["switch.manual"] = State("off")
        await self.runtime.start()
        self.assertFalse(self.runtime.active)
        self.assertEqual(self.services.calls, [])

    async def test_force_mode_change_stops(self):
        await self.runtime.start()
        self.states["select.force"] = State("None")
        await self.runtime.tick()
        self.assertFalse(self.runtime.active)

    async def test_missing_dc_charge_stops(self):
        await self.runtime.start()
        self.runtime.started_at = monotonic() - 60
        self.states["sensor.dc"] = State(0)
        for _ in range(3):
            await self.runtime.tick()
        self.assertFalse(self.runtime.active)
        self.assertEqual(self.states["select.force"].state, "None")

    async def test_stop_falls_back_to_zero_watts(self):
        await self.runtime.start()
        self.services.ignore_force_none = True
        await self.runtime.stop()
        self.assertFalse(self.runtime.active)
        self.assertEqual(self.states["number.power"].state, "0")
        self.assertIn("nicht bestätigt", self.runtime.status)
