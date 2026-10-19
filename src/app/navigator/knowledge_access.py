"""Explicitly provisioned canton accounts; no membership inferred from browser data."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import HTTPException, Request

KEY = secrets.token_bytes(32)  # sessions intentionally expire on server restart
COOKIE = "bern_knowledge_session"
attempts: dict[str, list[float]] = {}


def accounts():
    path = os.getenv("KB_ACCOUNTS_FILE", "")
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}


def password_hash(password: str, salt: str | None = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + digest


def login(email: str, password: str, ip: str):
    now = time.time()
    # Bounded per-process throttling. No emails/passwords are logged.
    if len(attempts) > 2000:
        attempts.clear()
    attempts[ip] = [stamp for stamp in attempts.get(ip, []) if now - stamp < 300]
    if len(attempts[ip]) >= 10:
        raise HTTPException(429, "Too many attempts. Try again in five minutes.")
    attempts[ip].append(now)
    configured = accounts()
    if not configured:
        raise HTTPException(503, "Canton account access has not been configured by the administrator.")
    email = email.strip().lower()
    account = configured.get(email, {})
    stored = account.get("password_hash", "")
    try:
        valid = hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)
    except (ValueError, TypeError):
        # Comparable password work for nonexistent/invalid accounts.
        password_hash(password)
        valid = False
    if not valid or account.get("organization") != "kanton-bern" or not account.get("active", False):
        raise HTTPException(401, "Invalid credentials or account not enabled for canton access.")
    payload = (email + "|" + str(int(now + 8 * 3600))).encode().hex()
    signature = hmac.new(KEY, payload.encode(), "sha256").hexdigest()
    attempts.pop(ip, None)
    return payload + "." + signature


def member(request: Request):
    # Explicit local preview mode, enabled only by the server operator.
    if os.getenv("KB_INTERNAL_PREVIEW") == "1" and request.client and request.client.host in ("127.0.0.1", "::1"):
        role = 'representative'
        supplied = request.cookies.get('bern_preview_role', '')
        for candidate in ('agent', 'representative'):
            signed = candidate + '.' + hmac.new(KEY, candidate.encode(), 'sha256').hexdigest()
            if hmac.compare_digest(signed, supplied):
                role = candidate
        return {"email": "internal-preview@localhost", "name": "Kanton Bern", "can_manage_knowledge": True, 'role': role, 'preview': True, 'can_create_pitch': role == 'representative'}
    token = request.cookies.get(COOKIE, "")
    try:
        payload, signature = token.split(".")
        if not hmac.compare_digest(signature, hmac.new(KEY, payload.encode(), "sha256").hexdigest()):
            return None
        email, expiry = bytes.fromhex(payload).decode().split("|")
        account = accounts().get(email, {})
        if int(expiry) <= time.time() or not account.get("active") or account.get("organization") != "kanton-bern":
            return None
        role = account.get('role', 'agent')
        if role not in ('agent', 'representative'):
            return None
        return {"email": email, "name": account.get("name", email), "can_manage_knowledge": True, 'role': role, 'can_create_pitch': role == 'representative'}
    except (ValueError, TypeError, UnicodeError):
        return None


def require_member(request: Request):
    user = member(request)
    if not user:
        raise HTTPException(403, "Verified Kanton Bern account required.")
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin changes are not allowed.")
    return user


def require_representative(request: Request):
    user = require_member(request)
    if user.get('role', 'agent') != 'representative':
        raise HTTPException(403, 'The representative role is required to create or send a pitch.')
    return user


if __name__ == "__main__":
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description="Administrator: explicitly provision a canton Knowledge Base account.")
    parser.add_argument("--file", required=True, help="Private account file, never commit it")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument('--role', choices=['agent', 'representative'], default='agent')
    args = parser.parse_args()
    password = getpass.getpass("New password (at least 12 characters): ")
    if len(password) < 12 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("Password too short or confirmation does not match.")
    path = Path(args.file)
    configured = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    configured[args.email.strip().lower()] = {"name": args.name, "role": args.role, "organization": "kanton-bern", "active": True,
                                            "password_hash": password_hash(password)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(configured, indent=2), encoding="utf-8")
    print("Account provisioned. Set KB_ACCOUNTS_FILE to this private file before starting the server.")
