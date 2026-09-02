#!/usr/bin/env python3
"""Read-only Sunlogin cloud probe for identifying C4/C4 4G devices.

The script intentionally performs only password login and device-list requests.
It never calls any plug control endpoint and never persists live credentials.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://api-std.sunlogin.oray.com"
LOGIN_URL = f"{BASE_URL}/authorization"
DEVICES_URL = f"{BASE_URL}/wakeup/devices"
APP_ID = "kNUC97u86Zr7mt9xeZVl"
USER_AGENT = "SLCC/15.3.4 (IOS,appname=sunloginControlClient)"
TERMINAL_NAME = "iPhone15Plus"
CLIENT_SALT = "==SunLogin@2023=="
SENSITIVE_KEY_PARTS = (
    "token",
    "password",
    "secret",
    "authorization",
    "userid",
    "user_id",
    "client_id",
    "device_id",
    "owner_id",
    "refresh",
)
SENSITIVE_KEYS = {
    "sn",
    "mac",
    "imei",
    "iccid",
    "uid",
    "user",
    "loginname",
    "serial",
    "serialnumber",
}


def _digest(value: Any) -> str:
    """Return a stable, non-reversible identifier for a sensitive value."""
    raw = str(value).encode("utf-8", "replace")
    return f"<redacted:{hashlib.sha256(raw).hexdigest()[:12]}>"


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9_]", "", key.lower())
    return normalized in SENSITIVE_KEYS or any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact(value: Any, key: str = "") -> Any:
    """Recursively redact credentials and hardware identifiers from JSON data."""
    if _is_sensitive_key(key):
        if isinstance(value, (dict, list)):
            return "<redacted>"
        return _digest(value)
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    return value


def _headers() -> dict[str, str]:
    # Match the integration's client identity header.  The value is a stable
    # UUID derived locally and does not contain the raw network adapter address.
    fake_host = f"{uuid.getnode()}.{CLIENT_SALT}.xyz"
    client_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, fake_host))
    return {
        "User-Agent": USER_AGENT,
        "X-AppID": APP_ID,
        "Accept": "*/*",
        "Country-Region": "zh-Hans_US",
        "Accept-Language": "zh-Hans_US",
        "EX-ClientId": client_id,
    }


def _json_response(response: requests.Response, endpoint: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{endpoint} 返回了非 JSON 响应 (HTTP {response.status_code})") from exc
    if not response.ok:
        message = data.get("error") or data.get("message") or response.reason
        raise RuntimeError(f"{endpoint} 请求失败 (HTTP {response.status_code}): {message}")
    if not isinstance(data, dict):
        raise RuntimeError(f"{endpoint} 返回格式异常")
    # The API may return an application error while still using HTTP 200.
    if data.get("error") not in (None, "", 0, False):
        raise RuntimeError(f"{endpoint} 业务错误: {data['error']}")
    return data


def login(session: requests.Session, username: str, password: str, timeout: float) -> dict[str, Any]:
    payload = {
        "loginname": username,
        "terminal_name": TERMINAL_NAME,
        "type": "password",
        "ismd5": True,
        "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
    }
    response = session.post(LOGIN_URL, json=payload, headers=_headers(), timeout=timeout)
    data = _json_response(response, "登录")
    if not data.get("access_token"):
        raise RuntimeError("登录响应中没有 access_token，可能需要短信/二维码验证")
    return data


def login_by_sms(session: requests.Session, username: str, code: str, timeout: float) -> dict[str, Any]:
    payload = {
        "loginname": username,
        "terminal_name": TERMINAL_NAME,
        "type": "securecode",
        "medium": "sms",
        "code": code,
    }
    response = session.post(LOGIN_URL, json=payload, headers=_headers(), timeout=timeout)
    data = _json_response(response, "短信验证码登录")
    if not data.get("access_token"):
        raise RuntimeError("验证码登录响应中没有 access_token")
    return data


def get_devices(session: requests.Session, access_token: str, timeout: float) -> dict[str, Any]:
    headers = _headers() | {"Authorization": f"Bearer {access_token}"}
    response = session.get(DEVICES_URL, headers=headers, timeout=timeout)
    return _json_response(response, "设备列表")


def load_access_token(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"无法读取 token 文件：{path}") from exc
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise RuntimeError("token 文件中没有 access_token")
    return str(token)


def _device_candidates(devices: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        haystack = " ".join(str(device.get(k, "")) for k in ("device_type", "model", "name", "product"))
        # Keep all smart plugs and anything that looks like C4 so an unknown
        # device_type used by a new firmware is still visible for analysis.
        if device.get("device_type") == "sl_smartplug" or re.search(r"c4|smart.?plug|插座", haystack, re.I):
            candidates.append(device)
    return candidates


def _summary(device: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "device_type",
        "model",
        "name",
        "isenable",
        "online",
        "status",
        "version",
        "address",
        "outlet_count",
        "outletCount",
        "plugins",
    )
    return {field: redact(device[field], field) for field in fields if field in device}


def run(args: argparse.Namespace) -> int:
    session = requests.Session()
    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})
    try:
        if args.token_file:
            access_token = load_access_token(args.token_file)
        else:
            username = args.username or input("向日葵账号（手机号/邮箱）：").strip()
            password = getpass.getpass("向日葵密码（不会显示）：")
            access_token = login(session, username, password, args.timeout)["access_token"]
        devices_data = get_devices(session, access_token, args.timeout)
    except (requests.RequestException, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        # Remove credentials from the session as soon as the read-only calls finish.
        session.close()

    devices = devices_data.get("devices", [])
    if isinstance(devices, dict):
        devices = list(devices.values())
    if not isinstance(devices, list):
        print("错误：设备列表字段格式异常", file=sys.stderr)
        return 1
    candidates = _device_candidates(devices) if not args.all_devices else [d for d in devices if isinstance(d, dict)]
    output = {
        "endpoint": BASE_URL,
        "device_count": len(devices),
        "candidate_count": len(candidates),
        "candidates": [redact(device) for device in candidates],
    }
    print(json.dumps({"device_count": len(devices), "candidate_count": len(candidates)}, ensure_ascii=False))
    for index, device in enumerate(candidates, 1):
        print(f"\n设备 {index}（只读摘要）：")
        print(json.dumps(_summary(device), ensure_ascii=False, indent=2))
    if not candidates:
        print("未筛选到智能插座/C4 设备；可使用 --all-devices 查看脱敏后的完整设备列表。")
    if args.output:
        path = Path(args.output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(redact(output), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n已保存脱敏结果：{path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="只读获取向日葵 C4/C4 4G 云端设备信息")
    parser.add_argument("--username", help="账号；省略则在终端交互输入")
    parser.add_argument("--proxy", help="可选 HTTP(S) 代理，例如 http://127.0.0.1:60808")
    parser.add_argument("--timeout", type=float, default=20, help="单次请求超时秒数（默认 20）")
    parser.add_argument("--all-devices", action="store_true", help="显示全部设备（仍然脱敏）")
    parser.add_argument("--token-file", type=Path, help="使用 login_sunlogin.py 保存的 token，跳过再次登录")
    parser.add_argument("--output", help="保存脱敏 JSON 的路径")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
