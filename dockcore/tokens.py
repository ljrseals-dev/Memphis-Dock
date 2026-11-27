from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

SECRET = os.environ.get("DOCK_SHARED_SECRET", "dev-secret-change-me").encode()


def _sign(raw: bytes) -> str:
    return hmac.new(SECRET, raw, hashlib.sha256).hexdigest()[:32]


def issue(plan_id: str, candidate_index: int, ttl_s: int = 900) -> str:
    payload = {"p": plan_id, "c": candidate_index, "e": int(time.time()) + ttl_s}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode() + "." + _sign(raw)


def verify(token: str) -> dict | None:
    try:
        b64, sig = token.split(".")
        raw = base64.urlsafe_b64decode(b64.encode())
        if not hmac.compare_digest(_sign(raw), sig):
            return None
        payload = json.loads(raw)
        if payload.get("e", 0) < time.time():
            return None
        return payload
    except Exception:
        return None
