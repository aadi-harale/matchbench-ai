from collections import defaultdict, deque
from threading import Lock
from time import monotonic, time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import Settings
from .db import User

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = hasher.hash("password never accepted")
COOKIE = "matchbench_session"


def sign(user: User, settings: Settings) -> str:
    return jwt.encode({"sub": user.id, "iat": int(time()), "exp": int(time()) + 86400 * 7,
                       "sv": user.session_version, "aud": "matchbench"},
                      settings.session_secret.get_secret_value(), algorithm="HS256")


def decode(token: str, settings: Settings) -> dict:
    return jwt.decode(token, settings.session_secret.get_secret_value(), algorithms=["HS256"],
                      audience="matchbench", options={"require": ["exp", "iat", "sub", "sv"]})


def verify(password: str, stored: str | None) -> bool:
    try:
        return hasher.verify(stored or DUMMY_HASH, password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


class RateLimits:
    def __init__(self):
        self.hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.lock = Lock()
        self.next_cleanup = 0.0

    def permit(self, key: str, action: str, maximum: int) -> bool:
        now = monotonic()
        with self.lock:
            if now >= self.next_cleanup:
                self.hits = defaultdict(deque, {key: values for key, values in self.hits.items()
                                                if values and values[-1] > now - 60})
                self.next_cleanup = now + 60
            recent = self.hits[key, action]
            while recent and now - recent[0] >= 60:
                recent.popleft()
            if len(recent) >= maximum:
                return False
            recent.append(now)
            return True
