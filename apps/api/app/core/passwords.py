"""Password hashing + basic policy checks.

Hashing: argon2id via ``argon2-cffi`` with OWASP password-storage
cheatsheet parameters (64 MiB memory, 3 iterations, 4 parallelism
as of late-2025).  ``verify`` returns ``False`` for bad hashes
rather than raising, matching the shape we want in the login path.

Policy (D-12 / research doc §3):

- Min length :data:`Settings.password_min_length` (default 10).
- No composition rules (NIST SP 800-63B).
- Reject any password that appears verbatim in
  :data:`_COMMON_PASSWORDS` — small embedded list of the most
  breached passwords. Not a substitute for rate limiting; it
  catches the obvious failures.

Two utilities for the login path:

- :func:`hash_password` — registration + password change.
- :func:`verify_password` — login. Constant-time at the argon2
  layer. A ``dummy_verify()`` helper is exposed so the login
  handler can pay the same CPU cost on "email not found" as on
  "wrong password" — otherwise timing discloses which emails are
  registered.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from argon2.profiles import RFC_9106_LOW_MEMORY

from app.core.config import get_settings


# OWASP-recommended parameters (~64 MiB memory, 3 iters, 4 par).
# ``type=ID`` (argon2id) is already the library default.
_HASHER = PasswordHasher(
    time_cost=RFC_9106_LOW_MEMORY.time_cost,
    memory_cost=RFC_9106_LOW_MEMORY.memory_cost,
    parallelism=RFC_9106_LOW_MEMORY.parallelism,
    hash_len=RFC_9106_LOW_MEMORY.hash_len,
    salt_len=RFC_9106_LOW_MEMORY.salt_len,
)

# Pre-computed dummy hash of a known never-in-use password. Used
# by :func:`dummy_verify` on the "user not found" login branch so
# login latency doesn't differ from the "user exists, wrong
# password" branch. Computing this on every call would defeat the
# purpose — capture it once at module import.
_DUMMY_HASH = _HASHER.hash("x" * 32)


# Top breached passwords. Small embedded list (not the full
# ten-million-passwords-top list — that's its own dependency).
# This rejects the obvious failures ("password", "qwerty",
# "123456") without making password-entry user-hostile. The full
# list lives in https://github.com/danielmiessler/SecLists; pull
# more down if abuse data shows it matters.
_COMMON_PASSWORDS: frozenset[str] = frozenset({
    "123456", "123456789", "12345678", "12345", "1234567",
    "password", "qwerty", "abc123", "letmein", "welcome",
    "monkey", "dragon", "master", "admin", "login",
    "passw0rd", "password1", "password123", "iloveyou",
    "trustno1", "sunshine", "princess", "football", "baseball",
    "shadow", "superman", "michael", "batman", "welcome1",
    "qwerty123", "1q2w3e4r", "1qaz2wsx", "qazwsx", "zxcvbnm",
    "asdfgh", "asdfghjkl", "qwertyuiop", "!@#$%^&*", "p@ssw0rd",
    "changeme", "letmein1", "abc12345", "q1w2e3r4", "admin123",
    "root", "toor", "test", "test123", "guest",
    "user", "default", "administrator", "system",
    "atlas", "atlas123",  # project-name obvious-footgun entries
})


class WeakPasswordError(ValueError):
    """Raised by :func:`validate_password_policy` on rejection.

    ``reason`` is a short code suitable for a 422 error body; the
    message is user-displayable.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.user_message = message


def validate_password_policy(password: str) -> None:
    """Raise :class:`WeakPasswordError` if the password is unacceptable.

    The caller should have already done length/non-empty validation
    at the Pydantic layer; this function is the last line of defence
    before hashing.
    """
    min_len = get_settings().password_min_length
    if len(password) < min_len:
        raise WeakPasswordError(
            reason="too_short",
            message=f"Password must be at least {min_len} characters.",
        )
    if password.lower() in _COMMON_PASSWORDS:
        raise WeakPasswordError(
            reason="common_password",
            message="This password appears in known breach lists. Pick a different one.",
        )


def hash_password(password: str) -> str:
    """Hash a password with argon2id. Raises :class:`WeakPasswordError`
    if policy checks fail.
    """
    validate_password_policy(password)
    return _HASHER.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time password check. Swallows argon2 exceptions —
    any failure (bad hash format, mismatch) returns ``False``."""
    try:
        _HASHER.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        # Corrupt hash, unknown algorithm, etc. — treat as no match.
        return False


def dummy_verify() -> None:
    """Pay the argon2 CPU cost without a real match.

    Used by the login endpoint on the "email not found" branch so
    its latency matches the "email found, wrong password" branch.
    Prevents timing attacks that enumerate registered emails.
    """
    try:
        _HASHER.verify(_DUMMY_HASH, "never-matches")
    except VerifyMismatchError:
        pass
    except Exception:
        pass


def needs_rehash(hashed: str) -> bool:
    """Has the argon2 parameter baseline moved past this hash?

    Call on successful login: if ``True``, re-hash the submitted
    password and update ``user.password_hash`` so the next login
    runs on current parameters.
    """
    try:
        return _HASHER.check_needs_rehash(hashed)
    except Exception:
        return False
