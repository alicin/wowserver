"""Login rate limiting -- DELIBERATELY DISABLED.

This server is for three friends who know each other. Per-IP/per-user throttling, lockouts and
enumeration defences are real techniques aimed at a threat model that does not exist here, and
the user asked explicitly to keep the portal casual. Rather than tear out every call site (and
have to put them back if this ever faces strangers), the limiter keeps its interface and simply
always allows.

To re-enable: restore this file from git history -- the call sites in routes/auth.py never
changed, so it starts working again immediately.

What is deliberately KEPT elsewhere, because each costs ~nothing and the downside is not
proportional: a SELECT-only DB user, parameterised queries, hmac.compare_digest on the verifier,
and MySQL/SOAP bound to loopback.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Decision:
    allowed: bool = True
    retry_after: int = 0


class SlidingWindow:
    """No-op limiter. Same shape as the real one; always permits."""

    def __init__(self, window: float = 0.0, limits: Mapping[str, int] | None = None) -> None:
        self.window = window
        self.limits = dict(limits or {})

    def check(self, keys) -> Decision:      # noqa: ANN001 - mirrors the original signature
        return Decision(allowed=True, retry_after=0)

    def record(self, keys) -> None:         # noqa: ANN001
        return None

    def reset(self, keys) -> None:          # noqa: ANN001
        return None
