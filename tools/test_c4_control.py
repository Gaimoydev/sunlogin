#!/usr/bin/env python3
"""Perform one reversible C4 outlet control test.

The script requires --confirm-control, targets exactly one C4 device, toggles
outlet 0 once, verifies it, and restores the original state in a finally
block.  It never prints credentials or hardware identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests

from probe_c4_cloud import _device_candidates, get_devices, load_access_token


PLUG_URL = "https://slapi.oray.net/plug"
SALT = "==smart-plug=="


def signed_params(sn: str, api: str, status: int | None = None) -> dict[str, str | int]:
    seed = time.strftime("%m%d%H%M")
    params: dict[str, str | int] = {
        "_api": api,
        "sn": sn,
        "time": seed,
        "key": hashlib.md5(f"{sn}{SALT}{seed}".encode()).hexdigest(),
        "index": 0,
    }
    if status is not None:
        params["status"] = status
    return params


def request(session: requests.Session, token: str, sn: str, api: str, status: int | None = None) -> dict:
    response = session.get(
        PLUG_URL,
        params=signed_params(sn, api, status),
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("result") not in (0, False):
        raise RuntimeError(f"{api} returned an unsuccessful response")
    return body


def current_state(body: dict) -> int:
    response = body.get("response")
    if not isinstance(response, list) or not response or not isinstance(response[0], dict):
        raise RuntimeError("status response has no outlet 0")
    value = response[0].get("status")
    if value not in (0, 1):
        raise RuntimeError("outlet 0 state is not binary")
    return int(value)


def run(token_file: Path, confirm: bool) -> None:
    if not confirm:
        raise SystemExit("refusing control request without --confirm-control")
    token = load_access_token(token_file)
    session = requests.Session()
    try:
        devices_data = get_devices(session, token, 20)
        devices = devices_data.get("devices", [])
        if isinstance(devices, dict):
            devices = list(devices.values())
        candidates = [
            item for item in _device_candidates(devices if isinstance(devices, list) else [])
            if "c4" in str(item.get("model", "")).lower()
        ]
        if len(candidates) != 1 or not candidates[0].get("sn"):
            raise RuntimeError(f"expected exactly one C4 device, found {len(candidates)}")
        sn = str(candidates[0]["sn"])

        before = current_state(request(session, token, sn, "get_plug_status"))
        target = 0 if before else 1
        switched = False
        try:
            set_body = request(session, token, sn, "set_plug_status", target)
            switched = True
            after_set = current_state(request(session, token, sn, "get_plug_status"))
            if after_set != target:
                raise RuntimeError(f"state did not reach requested value ({after_set} != {target})")
            print(json.dumps({"before": before, "target": target, "after_set": after_set}, ensure_ascii=False))
        finally:
            if switched:
                request(session, token, sn, "set_plug_status", before)
                restored = current_state(request(session, token, sn, "get_plug_status"))
                print(json.dumps({"restored": restored, "restore_ok": restored == before}, ensure_ascii=False))
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="reversible C4 outlet control test")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--confirm-control", action="store_true")
    args = parser.parse_args()
    run(args.token_file, args.confirm_control)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
