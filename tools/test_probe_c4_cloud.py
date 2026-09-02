import unittest

from probe_c4_cloud import _device_candidates, _headers, redact
from probe_c4_readonly import _signed_params


class ProbeHelpersTest(unittest.TestCase):
    def test_headers_include_client_identity(self):
        self.assertRegex(_headers()["EX-ClientId"], r"^[0-9a-f-]{36}$")

    def test_redacts_sensitive_values_recursively(self):
        value = {"sn": "C4-SECRET", "nested": {"access_token": "jwt-secret"}, "model": "C4-4G"}
        result = redact(value)
        self.assertTrue(result["sn"].startswith("<redacted:"))
        self.assertTrue(result["nested"]["access_token"].startswith("<redacted:"))
        self.assertEqual(result["model"], "C4-4G")
        self.assertNotIn("C4-SECRET", str(result))

    def test_finds_smartplug_and_c4_even_with_unknown_type(self):
        devices = [
            {"device_type": "sl_smartplug", "model": "C2"},
            {"device_type": "unknown", "model": "C4-4G"},
            {"device_type": "computer", "model": "PC"},
        ]
        self.assertEqual(len(_device_candidates(devices)), 2)

    def test_signed_readonly_params_match_plugin_schema(self):
        params = _signed_params("SN", "get_plug_status", "09021855")
        self.assertEqual(params["_api"], "get_plug_status")
        self.assertEqual(params["sn"], "SN")
        self.assertEqual(params["time"], "09021855")
        self.assertRegex(params["key"], r"^[0-9a-f]{32}$")
        self.assertEqual(params["index"], "0")


if __name__ == "__main__":
    unittest.main()
