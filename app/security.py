"""Password hashing and random tokens. Standard library only, so there is nothing to explain away."""
import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return hmac.compare_digest(actual, expected)  # constant-time comparison


# Verified against when the email is unknown, so "no such user" and "wrong password" take equally long.
DUMMY_HASH = hash_password("not-a-real-password")


def new_token() -> str:
    """256 bits of randomness. Used for session cookies and share links."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Tokens are high-entropy, so a fast hash is enough. The DB never holds a usable token."""
    return hashlib.sha256(token.encode()).hexdigest()
