#!/usr/bin/env python3
"""Interactive Sunlogin login; persist only the returned session tokens."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from probe_c4_cloud import login, login_by_sms
import requests


DEFAULT_TOKEN_FILE = Path(__file__).resolve().parents[1] / "work" / "c4-4g-api-probe" / "artifacts" / "sunlogin_tokens.json"
QR_APPLY_URL = "https://user-api-v2.oray.com/qrcode/apply"
QR_STATUS_URL = "https://user-api-v2.oray.com/qrcode/status"
QR_LOGIN_URL = "https://user-api-v2.oray.com/qrcode/authorization"


def login_by_qrcode(session: requests.Session, timeout: float, artifact_dir: Path) -> dict:
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError("缺少 qrcode 库，请执行：python -m pip install qrcode[pil]") from exc

    response = session.get(QR_APPLY_URL, params={"_t": int(time.time() * 1000)}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    key, qrdata = payload.get("key"), payload.get("qrdata")
    if not key or not qrdata:
        raise RuntimeError("二维码申请响应缺少 key/qrdata")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    qr_path = artifact_dir / "sunlogin-login-qr.png"
    qrcode.make(qrdata).save(qr_path)
    print(f"二维码已生成：{qr_path}")
    print("请使用向日葵官方 App 扫码并确认登录，等待时间最长 3 分钟。")
    if os.name == "nt":
        os.startfile(qr_path)  # type: ignore[attr-defined]

    secret = None
    failures = 0
    deadline = time.monotonic() + 180
    try:
        while time.monotonic() < deadline:
            time.sleep(3)
            try:
                status_response = session.get(
                    QR_STATUS_URL,
                    params={"_t": int(time.time() * 1000), "key": key},
                    timeout=timeout,
                )
                status_response.raise_for_status()
                status_data = status_response.json()
                failures = 0
            except (requests.RequestException, ValueError):
                failures += 1
                if failures >= 3:
                    raise RuntimeError("二维码状态查询连续失败 3 次")
                continue
            status = status_data.get("status")
            if status == 2:
                secret = status_data.get("secret")
                break
        if not secret:
            raise RuntimeError("二维码未在 3 分钟内确认或已经过期")
        login_response = session.post(
            QR_LOGIN_URL,
            json={"key": secret, "issetcookie": True},
            timeout=timeout,
        )
        login_response.raise_for_status()
        login_data = login_response.json()
        if not login_data.get("access_token"):
            message = login_data.get("error") or login_data.get("message") or "响应中没有 access_token"
            raise RuntimeError(f"二维码授权失败：{message}")
        return login_data
    finally:
        try:
            qr_path.unlink(missing_ok=True)
        except OSError:
            pass


def _restrict_windows_acl(path: Path) -> None:
    """Best-effort ACL restriction; chmod remains useful on non-Windows hosts."""
    try:
        os.chmod(path, 0o600)
        if os.name == "nt":
            account = os.environ.get("USERNAME")
            if account:
                domain = os.environ.get("USERDOMAIN")
                if domain:
                    account = f"{domain}\\{account}"
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", f"{account}:F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
    except OSError:
        print("警告：无法自动收紧凭证文件权限，请手动限制该文件访问权限。", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="登录向日葵并保存会话 token（不保存密码）")
    parser.add_argument("--username", help="账号；省略则交互输入")
    parser.add_argument(
        "--method",
        choices=("qrcode", "password", "sms"),
        default="qrcode",
        help="登录方式，默认 qrcode",
    )
    parser.add_argument("--proxy", help="可选 HTTP(S) 代理，例如 http://127.0.0.1:60808")
    parser.add_argument("--timeout", type=float, default=20, help="请求超时秒数（默认 20）")
    parser.add_argument("--output", type=Path, default=DEFAULT_TOKEN_FILE, help="token 文件路径")
    args = parser.parse_args()

    session = requests.Session()
    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})
    try:
        if args.method == "qrcode":
            response = login_by_qrcode(session, args.timeout, args.output.parent)
        elif args.method == "sms":
            username = args.username or input("向日葵账号（手机号/邮箱）：").strip()
            code = input("请输入向日葵短信验证码（先在官方 App/网页触发发送）：").strip()
            response = login_by_sms(session, username, code, args.timeout)
        else:
            username = args.username or input("向日葵账号（手机号/邮箱）：").strip()
            password = getpass.getpass("向日葵密码（不会显示，且不会保存）：")
            response = login(session, username, password, args.timeout)
    except (requests.RequestException, RuntimeError) as exc:
        print(f"登录失败：{exc}", file=sys.stderr)
        if args.method == "password":
            print("若账号要求验证码，请先在向日葵官方 App/网页发送短信验证码，再运行：", file=sys.stderr)
            print("  python tools\\login_sunlogin.py --method sms", file=sys.stderr)
        return 1
    finally:
        session.close()

    token_data = {key: response[key] for key in ("access_token", "refresh_token", "refresh_expire") if key in response}
    if "access_token" not in token_data:
        print("登录响应没有 access_token，未写入文件。", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement avoids leaving a partially written token file.
    fd, temporary = tempfile.mkstemp(prefix=args.output.name + ".", dir=args.output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(token_data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    _restrict_windows_acl(args.output)
    print(f"登录成功，已保存 token（不含密码）：{args.output}")
    print("后续请求请使用该文件；不要将其上传、提交 Git 或发到聊天中。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
