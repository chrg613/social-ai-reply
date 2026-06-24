"""Fernet-based encryption for secrets storage.

The module supports two modes for the ENCRYPTION_KEY environment variable:

1. **Pre-generated Fernet key** (preferred for production). Generate one via
   ``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``
   and set ``ENCRYPTION_KEY`` to the 44-character base64 string. This path does
   no key derivation and is the standard recommended by the cryptography library.

2. **Passphrase** (convenience for dev). Any string that isn't a valid Fernet
   key is treated as a passphrase and stretched via PBKDF2-HMAC-SHA256 with a
   stable salt derived from the passphrase itself. This is not as strong as a
   real random Fernet key but is materially better than plain SHA-256 of the
   passphrase.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import get_settings

# Stable application-wide salt. Not secret (salts don't need to be); used so
# that the same passphrase always derives the same Fernet key. The value is a
# 16-byte constant string; changing it would invalidate existing ciphertext.
_APP_SALT = b"signalflow:enc:v1"
_PBKDF2_ITERATIONS = 200_000


def _is_fernet_key(value: str) -> bool:
    """Return True when the string is a valid 44-char urlsafe-base64 Fernet key."""
    try:
        raw = base64.urlsafe_b64decode(value.encode("utf-8"))
    except (ValueError, TypeError):
        return False
    return len(raw) == 32


def _derive_fernet_key(passphrase: str) -> bytes:
    """Derive a 32-byte key from a passphrase using PBKDF2-HMAC-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=hashlib.sha256(_APP_SALT + passphrase.encode("utf-8")).digest()[:16],
        iterations=_PBKDF2_ITERATIONS,
    )
    raw_key = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw_key)


def _build_fernet() -> Fernet:
    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError(
            "ENCRYPTION_KEY must be set to use encryption features. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    key_value = settings.encryption_key.strip()
    # If it's already a valid Fernet key, use it directly; otherwise derive
    # a 32-byte key from the passphrase via PBKDF2 (dev convenience).
    key = key_value.encode("utf-8") if _is_fernet_key(key_value) else _derive_fernet_key(key_value)
    return Fernet(key)


def encrypt_text(value: str) -> str:
    return _build_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_text(value: str) -> str:
    try:
        return _build_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Ciphertext is invalid or was encrypted with a different key.") from exc
