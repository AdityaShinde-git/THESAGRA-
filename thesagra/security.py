import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, iterations: int = 240_000) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return (
        f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    if encoded.startswith("pbkdf2_sha256$"):
        try:
            _, iterations_text, salt_hex, digest_hex = encoded.split("$", 3)
            iterations = int(iterations_text)
            if iterations < 100_000:
                return False
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                iterations,
            )
            return hmac.compare_digest(actual, expected)
        except (ValueError, OverflowError):
            return False
    if encoded.startswith("plain$"):
        configured = encoded.split("$", 1)[1]
        return hmac.compare_digest(
            password.encode("utf-8"),
            configured.encode("utf-8"),
        )
    return hmac.compare_digest(
        password.encode("utf-8"),
        encoded.encode("utf-8"),
    )


class FailureThrottle:
    def __init__(self, max_failures=5, window_seconds=60,
                 lock_seconds=60):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self.failures = {}
        self.lock = threading.Lock()

    def blocked(self, identity):
        now = time.monotonic()
        with self.lock:
            entry = self.failures.get(identity)
            if entry is None:
                return False
            if entry["blocked_until"] is not None:
                if now < entry["blocked_until"]:
                    return True
                entry["blocked_until"] = None
                entry["count"] = 0
            return False

    def record_failure(self, identity):
        now = time.monotonic()
        with self.lock:
            entry = self.failures.setdefault(
                identity,
                {"count": 0, "window_start": now,
                 "blocked_until": None},
            )
            if now - entry["window_start"] >= self.window_seconds:
                entry["count"] = 0
                entry["window_start"] = now
            entry["count"] += 1
            if entry["count"] >= self.max_failures:
                entry["blocked_until"] = now + self.lock_seconds
                return True
        return False

    def record_success(self, identity):
        with self.lock:
            self.failures.pop(identity, None)


class AuditLog:
    def __init__(self, database_path):
        self.path = os.path.splitext(
            os.fspath(database_path)
        )[0] + ".audit.jsonl"

    def write(self, event, peer=None, detail=None):
        entry = {
            "timestamp": utc_timestamp(),
            "event": event,
        }
        if peer:
            entry["peer"] = str(peer)
        if detail:
            entry["detail"] = str(detail)
        with open(self.path, "a", encoding="utf-8") as audit_file:
            audit_file.write(
                json.dumps(entry, separators=(",", ":")) + "\n"
            )
            audit_file.flush()
            os.fsync(audit_file.fileno())
