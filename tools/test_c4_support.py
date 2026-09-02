"""Dependency-free checks for the C4-specific pure processing helpers."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


def _load_helpers():
    source_path = Path(__file__).resolve().parents[1] / "custom_components" / "sunlogin" / "sunlogin.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {"get_entities", "plug_status_process", "plug_electric_process"}
    body = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    namespace = {}
    # The helpers use module-level DP_* constants; load only literal values so
    # this test does not need Home Assistant installed.
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.startswith("DP_")
        ):
            try:
                namespace[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    exec(compile(ast.Module(body=body, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace


class C4SupportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = _load_helpers()

    def test_c4_v2_selects_metered_single_outlet_entities(self):
        entities = self.helpers["get_entities"]("C4-V2")
        self.assertEqual(entities[:8], [
            "electricity_hour", "electricity_day", "electricity_week",
            "electricity_month", "electricity_lastmonth", "power",
            "current", "voltage",
        ])
        self.assertIn("relay0", entities)
        self.assertNotIn("relay1", entities)

    def test_c4_payload_units_match_official_client(self):
        status = self.helpers["plug_status_process"](
            {"response": [{"index": 0, "status": 1}], "led": 1, "def_st": 2}
        )
        self.assertEqual(status, {"relay0": 1, "led": 1, "def_st": 2})
        electric = self.helpers["plug_electric_process"](
            {"vol": 234671, "curr": 122, "power": 4000, "sub": [{"cur": 122, "pwr": 4000}]}
        )
        self.assertEqual(electric["current"], 122)  # mA is not divided again
        self.assertEqual(electric["power"], 4)       # mW -> W
        self.assertEqual(electric["sub_current0"], 122)
        self.assertEqual(electric["sub_power0"], 4)


if __name__ == "__main__":
    unittest.main()
