import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


SESSION_COOKIE = "operator_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 600_000
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5

_login_attempts: dict[str, deque[float]] = defaultdict(deque)


def hash_password(password: str, salt: bytes | None = None) -> str:
    password_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        password_salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(password_salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_digest = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
        candidate_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(candidate_digest, expected_digest)


def auth_is_configured() -> bool:
    return bool(os.getenv("OPERATOR_PASSWORD_HASH") and os.getenv("OPERATOR_SESSION_SECRET"))


def create_session_token(now: int | None = None) -> str:
    secret = _session_secret()
    issued_at = int(now if now is not None else time.time())
    payload = {
        "sub": "operator",
        "iat": issued_at,
        "exp": issued_at + SESSION_TTL_SECONDS,
    }
    encoded_payload = _encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(encoded_payload, secret)
    return f"{encoded_payload}.{signature}"


def verify_session_token(token: str, now: int | None = None) -> dict:
    try:
        encoded_payload, supplied_signature = token.split(".", 1)
        expected_signature = _sign(encoded_payload, _session_secret())
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("Invalid signature")
        payload = json.loads(_decode(encoded_payload))
        if payload.get("sub") != "operator":
            raise ValueError("Invalid subject")
        current_time = int(now if now is not None else time.time())
        if int(payload.get("exp", 0)) <= current_time:
            raise ValueError("Session expired")
        return payload
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator authentication required",
        ) from exc


async def require_operator(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator authentication required",
        )
    return verify_session_token(token)


def require_csrf_header(request: Request) -> None:
    if request.headers.get("X-Operator-CSRF") != "1":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing operator request header",
        )


def login_allowed(client_key: str, now: float | None = None) -> bool:
    current_time = now if now is not None else time.time()
    attempts = _login_attempts[client_key]
    while attempts and attempts[0] <= current_time - LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) < LOGIN_MAX_ATTEMPTS


def record_failed_login(client_key: str, now: float | None = None) -> None:
    _login_attempts[client_key].append(now if now is not None else time.time())


def clear_failed_logins(client_key: str) -> None:
    _login_attempts.pop(client_key, None)


def cookie_is_secure(request: Request) -> bool:
    configured = os.getenv("OPERATOR_COOKIE_SECURE")
    if configured is not None:
        return configured.lower() not in {"0", "false", "no"}
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
    return request.url.scheme == "https" or forwarded_proto == "https"


def _session_secret() -> bytes:
    secret = os.getenv("OPERATOR_SESSION_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator authentication is not configured",
        )
    return secret.encode("utf-8")


def _sign(encoded_payload: str, secret: bytes) -> str:
    digest = hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return _encode(digest)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


if __name__ == "__main__":
    operator_password = getpass.getpass("Operator password: ")
    confirmed_password = getpass.getpass("Confirm operator password: ")
    if not operator_password or operator_password != confirmed_password:
        raise SystemExit("Passwords must be non-empty and match.")
    print(hash_password(operator_password))
