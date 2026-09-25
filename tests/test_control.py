"""Run with python -m unittest discover -s tests."""
import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "venus_cell_taper"
package = types.ModuleType("venus_cell_taper")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
for name in ("const", "control"):
    spec = importlib.util.spec_from_file_location(f"venus_cell_taper.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from venus_cell_taper.control import VoltageController, lower_step


class ControllerTests(unittest.TestCase):
    def test_ladder(self):
        values = [500]
        for _ in range(8):
            values.append(lower_step(values[-1]))
        self.assertEqual(values, [500, 400, 300, 200, 150, 100, 50, 40, 40])

    def test_configured_30_watt_minimum(self):
        self.assertEqual(lower_step(50, 30), 40)
        self.assertEqual(lower_step(40, 30), 30)
        self.assertEqual(lower_step(30, 30), 30)
        c = VoltageController(min_charge_w=30)
        c.start(3.49, 0)
        c.power = 30
        with self.assertRaises(ValueError):
            c.update(3.52, 40)

    def test_no_adjustment_during_settling(self):
        c = VoltageController()
        self.assertEqual(c.start(3.40, 0), 500)
        for t in (10, 20, 30):
            self.assertIsNone(c.update(3.47, t))
        self.assertEqual(c.update(3.49, 40), 400)

    def test_stop_limit(self):
        c = VoltageController()
        c.start(3.40, 0)
        with self.assertRaises(ValueError):
            c.update(3.55, 10)

    def test_large_overshoot_uses_multiple_ladder_steps(self):
        c = VoltageController()
        c.start(3.40, 0)
        for t in (10, 20, 30):
            c.update(3.49, t)
        self.assertEqual(c.update(3.51, 40), 200)

    def test_stops_if_minimum_power_cannot_hold_voltage(self):
        c = VoltageController()
        c.start(3.49, 0)
        c.power = 40
        with self.assertRaises(ValueError):
            c.update(3.52, 40)


if __name__ == "__main__":
    unittest.main()
