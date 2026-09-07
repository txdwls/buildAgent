"""URL allowlist for browser tools.

The list is a comma-separated prefix set from the environment. Empty
means allow-all (dev default). Any non-empty list is enforced strictly:
the requested URL must start with one of the prefixes.
"""

from __future__ import annotations


def parse_allowlist(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def is_allowed(url: str, allowlist: tuple[str, ...]) -> bool:
    if not allowlist:
        return True
    return any(url.startswith(prefix) for prefix in allowlist)
