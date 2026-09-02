#!/usr/bin/env python3
"""Capture the C4 remote read-only protocol.

The probe intentionally performs no control or configuration operation.  It
discovers the first C4 device from the authenticated cloud list, then calls
the status, metering, version, Wi-Fi, function-list and timer read endpoints
using the same time-based MD5 signature as the integration.  Output is
recursively redacted before it is written to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests

from probe_c4_cloud import _device_candidates, get_devices, load_access_token, redact


PLUG_URL = "https://slapi.oray.net/plug"
PLUGIN_SCHEMA = "==smart-plug=="
READ_APIS = (
    "get_plug_status",
    "get_plug_electric",
    "get_plug_version",
    "get_plug_wifi",
    "get_func_list",
    "plug_timer_get",
    "plug_cntdown_get",
    "plug_cntdowns_get",
)


def _signed_params(sn: str, api: str, seed: str) -> dict[str, str]:
    key = hashlib.md5(f"{sn}{PLUGIN_SCHEMA}{seed}".encode()).hexdigest()
    params = {"_api": api, "sn": sn, "time": seed, "key": key}
    if api in {"get_plug_status", "get_plug_electric", "get_plug_wifi"}:
        params["index"] = "0"
    return params


def run(token_file: Path, output: Path, timeout: float) -> None:
    session = requests.Session()
    token = load_access_token(token_file)
    try:
        devices_data = get_devices(session, token, timeout)
        devices = devices_data.get("devices", [])
        if isinstance(devices, dict):
            devices = list(devices.values())
        candidates = _device_candidates(devices if isinstance(devices, list) else [])
        c4 = next(
            (device for device in candidates if "c4" in str(device.get("model", "")).lower()),
            None,
        )
        if not c4 or not c4.get("sn"):
            raise RuntimeError("device list does not contain a C4 with serial number")
        sn = str(c4["sn"])
        headers = {"Authorization": f"Bearer {token}"}
        # Sign all requests with one minute seed, matching the official app.
        seed = time.strftime("%m%d%H%M")
        payload: dict[str, object] = {
            "endpoint": PLUG_URL,
            "model": c4.get("model"),
            "device_type": c4.get("device_type"),
            "outletcount": c4.get("outletcount"),
            "responses": {},
        }
        responses = payload["responses"]
        assert isinstance(responses, dict)
        for api in READ_APIS:
            response = session.get(
                PLUG_URL,
                params=_signed_params(sn, api, seed),
                headers=headers,
                timeout=timeout,
            )
            try:
                body: object = response.json()
            except ValueError:
                body = response.text[:1000]
            responses[api] = {"status_code": response.status_code, "body": body}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(redact(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="read-only C4 status/electric protocol probe")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    run(args.token_file, args.output, args.timeout)
    print(f"saved redacted C4 read-only responses: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
