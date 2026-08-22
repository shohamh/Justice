import os

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

# Argon2id is the default; tuned to ~100ms on commodity hardware.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)

_TEST_HASH_CACHE: dict[str, str] = {}


def hash_password(plain: str) -> str:
    # Under JUSTICE_TESTING=1, memoize per plaintext: test seeding creates
    # thousands of soldiers whose hashes would otherwise each pay the full
    # ~100ms argon2 cost. Production keeps a fresh salt on every call.
    if os.environ.get("JUSTICE_TESTING") == "1":
        cached = _TEST_HASH_CACHE.get(plain)
        if cached is None:
            cached = _TEST_HASH_CACHE[plain] = _hasher.hash(plain)
        return cached
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False
