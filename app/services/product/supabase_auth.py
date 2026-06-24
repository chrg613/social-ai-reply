"""Supabase Auth service — handles all communication with Supabase Auth API.

This module is the single point of integration between SignalFlow and Supabase Auth.
FastAPI remains the backend for business logic; Supabase handles identity only.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWK

from app.core.config import get_settings
from app.core.constants.timeouts import JWKS_CACHE_TTL, JWKS_REFRESH_COOLDOWN
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

# ── JWKS cache (thread-safe, TTL-bounded, refreshed on key-miss) ─

_jwks_cache: dict[str, PyJWK] = {}
_jwks_fetched_at: float = 0.0  # time.monotonic() of last successful fetch
_jwks_lock = threading.Lock()

# ── Data classes ─────────────────────────────────────────────────


@dataclass
class SupabaseUser:
    """Minimal representation of a Supabase auth user."""

    id: str  # Supabase UUID
    email: str
    email_confirmed_at: str | None = None
    full_name: str | None = None


# ── JWT verification (used by FastAPI dependencies) ──────────────


def _fetch_jwks() -> dict[str, PyJWK]:
    """Fetch the JSON Web Key Set from Supabase and return a kid→PyJWK map.

    Raises ``JWKSUnavailableError`` for configuration / network / upstream
    failures so that callers can distinguish service-unavailable (503) from
    invalid-token (401).
    """
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise JWKSUnavailableError(
            "SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are required for JWT verification."
        )
    try:
        resp = httpx.get(
            f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
            headers={"apikey": settings.supabase_publishable_key},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise JWKSUnavailableError(
            "Could not fetch Supabase JWKS. Check SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY."
        ) from exc
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise JWKSUnavailableError(
            f"Supabase JWKS endpoint returned {resp.status_code}."
        ) from exc
    keys = {}
    for key_data in resp.json().get("keys", []):
        kid = key_data.get("kid")
        if kid:
            keys[kid] = PyJWK(key_data)
    return keys


def _get_signing_key(kid: str) -> PyJWK:
    """Look up a signing key by kid, refreshing the JWKS cache if needed.

    The cache expires after ``JWKS_CACHE_TTL`` so rotated signing keys are
    picked up without a restart. Unknown kids also trigger a refresh, but at
    most once per ``JWKS_REFRESH_COOLDOWN`` so a flood of forged tokens can't
    hammer the Supabase JWKS endpoint.
    """
    global _jwks_cache, _jwks_fetched_at
    with _jwks_lock:
        now = time.monotonic()
        expired = now - _jwks_fetched_at >= JWKS_CACHE_TTL
        if kid in _jwks_cache and not expired:
            return _jwks_cache[kid]
        if expired or now - _jwks_fetched_at >= JWKS_REFRESH_COOLDOWN:
            _jwks_cache = _fetch_jwks()
            _jwks_fetched_at = time.monotonic()
        if kid in _jwks_cache:
            return _jwks_cache[kid]
    raise ValueError(f"Signing key '{kid}' not found in Supabase JWKS.")


def verify_supabase_jwt(token: str) -> dict:
    """Decode and verify a Supabase-issued JWT.

    Supports both asymmetric (ES256/RS256 via JWKS) and symmetric (HS256)
    algorithms depending on the Supabase project configuration.
    Returns the decoded payload dict on success, raises on failure.
    """
    settings = get_settings()

    # Peek at the token header to determine algorithm and key
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise jwt.InvalidTokenError("Malformed token header.") from exc

    alg = header.get("alg", "HS256")
    kid = header.get("kid")

    if alg == "HS256":
        # Symmetric HMAC — used when Supabase project uses HS256 signing
        secret = settings.supabase_jwt_secret
        if not secret:
            raise ValueError("SUPABASE_JWT_SECRET is not configured.")
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["sub", "exp", "aud"]},
        )

    # Asymmetric (ES256, RS256, etc.) — use JWKS public key
    if not kid:
        raise jwt.InvalidTokenError("Token missing 'kid' header for asymmetric verification.")
    if not settings.supabase_url:
        raise ValueError("SUPABASE_URL is not configured.")

    signing_key = _get_signing_key(kid)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=[alg],
        audience="authenticated",
        options={"require": ["sub", "exp", "aud"]},
    )


# ── Supabase Admin API helpers (server-side, uses secret key) ──


def _admin_headers() -> dict[str, str]:
    settings = get_settings()
    if not settings.supabase_secret_key:
        raise SupabaseAuthError(
            503,
            "SUPABASE_SECRET_KEY is not configured. Email/password registration requires the service role key.",
        )
    return {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }


def _auth_url(path: str) -> str:
    settings = get_settings()
    return f"{settings.supabase_url}/auth/v1{path}"


def _sign_in_with_password(email: str, password: str) -> dict:
    """Authenticate an existing user via email + password.

    Used internally during sign_up to get session tokens after admin user creation.
    """
    settings = get_settings()
    try:
        resp = httpx.post(
            _auth_url("/token?grant_type=password"),
            headers={
                "apikey": settings.supabase_publishable_key,
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise SupabaseAuthError(502, "Could not reach Supabase Auth.") from exc
    content_type = resp.headers.get("content-type", "")
    data = resp.json() if content_type.startswith("application/json") else {}
    if resp.status_code >= 400:
        msg = data.get("error_description") or data.get("msg") or data.get("message") or str(data)
        raise SupabaseAuthError(resp.status_code, msg)
    if not data:
        raise SupabaseAuthError(resp.status_code, "Supabase returned a non-JSON token response.")
    return data


def sign_up(email: str, password: str, full_name: str) -> dict:
    """Create a new user via Supabase Admin API and return session tokens.

    Uses the service-role admin endpoint to create a pre-confirmed user,
    then signs them in immediately to get access/refresh tokens.
    This avoids the email-confirmation-required issue with the public signup.
    """
    # Step 1: Create confirmed user via admin API
    try:
        resp = httpx.post(
            _auth_url("/admin/users"),
            headers=_admin_headers(),
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"full_name": full_name},
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise SupabaseAuthError(502, "Could not reach Supabase Auth.") from exc
    data = resp.json()
    if resp.status_code >= 400:
        msg = data.get("msg") or data.get("message") or data.get("error_description") or str(data)
        raise SupabaseAuthError(resp.status_code, msg)

    user_data = data  # Admin API returns the user object directly

    # Step 2: Sign in to get access + refresh tokens
    try:
        session_data = _sign_in_with_password(email, password)
    except SupabaseAuthError as exc:
        admin_delete_user(user_data["id"])
        raise SupabaseAuthError(exc.status_code, exc.message) from exc

    # Merge user info into session response
    session_data["user"] = user_data
    return session_data


def sign_out(access_token: str) -> None:
    """Invalidate a user's session on Supabase side.

    Raises SupabaseAuthError if Supabase returns an error response,
    so callers can decide whether to treat sign-out failure as critical.
    """
    settings = get_settings()
    try:
        resp = httpx.post(
            _auth_url("/logout"),
            headers={
                "apikey": settings.supabase_publishable_key,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise SupabaseAuthError(502, "Could not reach Supabase Auth.") from exc
    if resp.status_code >= 400:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        msg = data.get("error_description") or data.get("msg") or data.get("message") or f"Logout failed ({resp.status_code})"
        logger.warning("Supabase sign_out failed: %s %s", resp.status_code, msg)
        raise SupabaseAuthError(resp.status_code, msg)


def admin_get_user(supabase_user_id: str) -> dict:
    """Fetch a user by ID using the admin/service-role API."""
    try:
        resp = httpx.get(
            _auth_url(f"/admin/users/{supabase_user_id}"),
            headers=_admin_headers(),
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise SupabaseAuthError(502, "Could not reach Supabase Auth.") from exc
    data = resp.json()
    if resp.status_code >= 400:
        msg = data.get("msg") or data.get("message") or str(data)
        raise SupabaseAuthError(resp.status_code, msg)
    return data


def admin_delete_user(supabase_user_id: str) -> None:
    """Delete a user via the admin API (used for workspace deletion cleanup)."""
    try:
        resp = httpx.delete(
            _auth_url(f"/admin/users/{supabase_user_id}"),
            headers=_admin_headers(),
            timeout=10,
        )
    except SupabaseAuthError:
        logger.warning(
            "Skipping Supabase user cleanup for %s because admin auth is unavailable",
            supabase_user_id,
            exc_info=True,
        )
        return
    except httpx.HTTPError:
        logger.warning("Failed to delete Supabase user %s due to network error", supabase_user_id, exc_info=True)
        return
    if resp.status_code >= 400:
        logger.warning("Failed to delete Supabase user %s: %s", supabase_user_id, resp.text)


# ── Helpers ──────────────────────────────────────────────────────


def extract_user_from_response(data: dict) -> SupabaseUser:
    """Extract a SupabaseUser from a Supabase auth response (sign_up or sign_in)."""
    user_data = data.get("user", data)
    metadata = user_data.get("user_metadata", {})
    return SupabaseUser(
        id=user_data["id"],
        email=user_data.get("email", ""),
        email_confirmed_at=user_data.get("email_confirmed_at"),
        full_name=metadata.get("full_name"),
    )


# ── Exceptions ───────────────────────────────────────────────────


class SupabaseAuthError(AppError):
    """Raised when a Supabase Auth API call fails.

    Extends ``AppError`` so that the global exception handler in main.py
    returns the correct HTTP status code instead of a generic 500 (Issue #2).
    """

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.detail = f"Supabase Auth error ({status_code}): {message}"
        self.message = message
        super().__init__(self.detail)


class JWKSUnavailableError(AppError):
    """Raised when the Supabase JWKS endpoint cannot be reached or is misconfigured.

    Distinct from token-validation errors: this indicates a service-level
    problem (network / config / upstream) that should surface as HTTP 503,
    not 401. Call sites can pass a custom ``detail`` describing the actual
    cause (e.g. network timeout, missing env var) so the error payload is
    useful in logs.
    """

    status_code = 503

    def __init__(self, detail: str | None = None) -> None:
        message = detail or "Supabase JWKS endpoint is unavailable."
        self.detail = message
        super().__init__(message)
