"""Slug and filename utilities. Protocol C1-C5."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

MAX_SLUG_LEN = 60

_SLUG_FILLER = {"the", "a", "an", "of", "to", "in", "on", "and", "or"}

_PROTOCOL_FILENAME = re.compile(
    r"^([a-z][a-z0-9-]*?)-(\d+[a-z]?)-([a-z0-9-]+)\.org$"
)
_PROTOCOL_ASSIGNMENT = re.compile(
    r"^([a-z][a-z0-9-]*?)-(\d+[a-z]?)-assignment\.org$"
)


def slugify(text: str) -> str:
    """Lowercase hyphenated ASCII slug. Protocol C4."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    return text[:MAX_SLUG_LEN].strip("-")


def pad_number(n: int, width: int = 2) -> str:
    return f"{n:0{width}d}"


def format_lecture_filename(short: str, number: str, slug: str) -> str:
    """<short>-NN-slug.org for lectures. C1."""
    return f"{short}-{number}-{slug}.org"


def format_assignment_filename(short: str, number: str) -> str:
    """<short>-NN-assignment.org. I3 — lecture-aligned numbering."""
    return f"{short}-{number}-assignment.org"


def parse_protocol_filename(name: str) -> Optional[tuple[str, str, str, str]]:
    """Return (short, number, kind, slug) if name matches protocol pattern.

    kind is "lecture" or "assignment"; slug may be empty for assignments.
    """
    m = _PROTOCOL_ASSIGNMENT.match(name)
    if m:
        return m.group(1), m.group(2), "assignment", ""
    m = _PROTOCOL_FILENAME.match(name)
    if m:
        return m.group(1), m.group(2), "lecture", m.group(3)
    return None


def assign_letter_suffixes(nums: list[tuple[int, Optional[float]]]) -> list[str]:
    """Given [(int_part, frac_or_None), ...] in document order, return the
    corresponding zero-padded number strings. Groups with >1 member get
    letter suffixes `a`, `b`, `c` in input order; singleton groups get no suffix.

    Example:
        [(1, None), (1, 0.5), (2, None), (4, None), (4, 0.5)]
        → ["01a", "01b", "02", "04a", "04b"]
    """
    # Count how many times each integer appears.
    counts: dict[int, int] = {}
    for n, _ in nums:
        counts[n] = counts.get(n, 0) + 1
    out: list[str] = []
    seen: dict[int, int] = {}
    for n, _ in nums:
        seen[n] = seen.get(n, 0) + 1
        pad = pad_number(n)
        if counts[n] > 1:
            letter = chr(ord("a") + seen[n] - 1)
            out.append(f"{pad}{letter}")
        else:
            out.append(pad)
    return out


def default_short_from_slug(course_slug: str) -> str:
    """Best-effort short code from a course directory slug.

    "operating-systems-notes" -> "os"
    "software-fundamentals-lecture-notes" -> "sf"
    "quantum-field-theory" -> "qft"

    Not perfect; the user overrides via --short or by writing a README.
    """
    parts = [
        p for p in course_slug.split("-")
        if p and p.lower() not in _SLUG_FILLER
        and p.lower() not in {"notes", "lecture", "lectures"}
    ]
    initial = "".join(p[0] for p in parts if p)
    if initial:
        return initial.lower()
    return course_slug.replace("-", "")[:4] or "x"
