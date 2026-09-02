#!/usr/bin/env python3
"""Fetch only get_plug_info for the first C4 cloud device."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import requests

from probe_c4_cloud import _device_candidates, get_devices, load_access_token, redact


PLUG_INFO_URL = "https://slapi.oray.net/plug"
PLUGIN_SCHEMA = "==smart-plug=="


def main() -> int:
    parser = argparse.ArgumentParser(description="只读查询 C4 的 get_plug_info")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    session = requests.Session()
    try:
        token = load_access_token(args.token_file)
        devices_data = get_devices(session, token, args.timeout)
        devices = devices_data.get("devices", [])
        if isinstance(devices, dict):
            devices = list(devices.values())
        candidates = _device_candidates(devices if isinstance(devices, list) else [])
        c4 = next((device for device in candidates if "c4" in str(device.get("model", "")).lower()), None)
        if not c4 or not c4.get("sn"):
            raise RuntimeError("设备列表中没有带 SN 的 C4 设备")
        sn = str(c4["sn"])
        seed = time.strftime("%m%d%H%M")
        key = hashlib.md5(f"{sn}{PLUGIN_SCHEMA}{seed}".encode()).hexdigest()
        response = session.get(
            PLUG_INFO_URL,
            # Include the serial on the signed request.  C4-V2 still returns
            # only ``{"result": 0}`` for this legacy info operation; use
            # ``get_plug_version`` for firmware data.
            params={"_api": "get_plug_info", "sn": sn, "time": seed, "key": key},
            headers={"Authorization": f"Bearer {token}"},
            timeout=args.timeout,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"get_plug_info 返回非 JSON (HTTP {response.status_code})") from exc
        if not response.ok:
            message = payload.get("error") or payload.get("message") or response.reason
            raise RuntimeError(f"get_plug_info 失败 (HTTP {response.status_code}): {message}")
    except (requests.RequestException, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        session.close()

    sanitized = redact(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "response_keys": sorted(payload.keys()) if isinstance(payload, dict) else []}))
    print(f"已保存脱敏结果：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
