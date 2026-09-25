"""Smoke-test the config flow imports without installing all of Home Assistant."""
import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "venus_cell_taper"


class ConfigFlowImportTests(unittest.TestCase):
    def test_config_flow_module_imports(self):
        ha = types.ModuleType("homeassistant")
        ha.__path__ = []
        entries = types.ModuleType("homeassistant.config_entries")

        class ConfigFlow:
            def __init_subclass__(cls, **kwargs):
                super().__init_subclass__()

        entries.ConfigFlow = ConfigFlow
        entries.OptionsFlow = type("OptionsFlow", (), {})
        ha.config_entries = entries
        core = types.ModuleType("homeassistant.core")
        core.callback = lambda func: func
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        selectors = types.ModuleType("homeassistant.helpers.selector")
        selectors.EntitySelector = lambda config: config
        selectors.EntitySelectorConfig = lambda **kwargs: kwargs
        vol = types.ModuleType("voluptuous")
        vol.Schema = lambda schema: schema
        vol.Required = lambda key, **kwargs: key
        vol.In = lambda values: values

        fake = {
            "homeassistant": ha, "homeassistant.config_entries": entries,
            "homeassistant.core": core, "homeassistant.helpers": helpers,
            "homeassistant.helpers.selector": selectors, "voluptuous": vol,
        }
        package = types.ModuleType("venus_cell_taper")
        package.__path__ = [str(ROOT)]
        fake["venus_cell_taper"] = package
        saved = {name: sys.modules.get(name) for name in fake}
        try:
            sys.modules.update(fake)
            const_spec = importlib.util.spec_from_file_location(
                "venus_cell_taper.const", ROOT / "const.py"
            )
            const_module = importlib.util.module_from_spec(const_spec)
            sys.modules[const_spec.name] = const_module
            const_spec.loader.exec_module(const_module)
            spec = importlib.util.spec_from_file_location(
                "venus_cell_taper.config_flow", ROOT / "config_flow.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertTrue(hasattr(module, "VenusCellTaperFlow"))
        finally:
            sys.modules.pop("venus_cell_taper.const", None)
            for name, previous in saved.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous
