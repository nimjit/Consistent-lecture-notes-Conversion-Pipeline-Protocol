"""Org-id allocation.

UUIDv5 keyed on (course_short, relative_path) by default so re-runs
produce identical ids and PRs are reviewable. UUIDv4 is used when
`reproducible` is False.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Union

# Project namespace for v5. Chosen once by uuid4(); do not change — doing so
# invalidates every previously-minted deterministic id in the wiki.
_NAMESPACE = uuid.UUID("12b4b9e6-5f8a-4a9f-b1a7-55a08b7fa0b1")


def deterministic_id(course_short: str, relpath: Union[str, Path]) -> str:
    key = f"{course_short}:{relpath}"
    return str(uuid.uuid5(_NAMESPACE, key))


def random_id() -> str:
    return str(uuid.uuid4())


class IdAllocator:
    """Mints and caches ids for a single course."""

    def __init__(self, course_short: str, reproducible: bool = True):
        self.course_short = course_short
        self.reproducible = reproducible
        self._cache: dict[str, str] = {}

    def for_path(self, relpath: Union[str, Path]) -> str:
        key = str(relpath)
        if key in self._cache:
            return self._cache[key]
        if self.reproducible:
            uid = deterministic_id(self.course_short, key)
        else:
            uid = random_id()
        self._cache[key] = uid
        return uid
