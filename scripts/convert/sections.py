"""Scaffold the D1 required sections around a converted body.

Lectures  : * Prev. lecture / * Content / * Summary / * Next lecture
Assignments: * Problem statement / * Solution / * Reflection  (per I1)

The body comes with its own top-level headings; those get demoted so they
nest under the wrapper's `* Content` (or `* Problem statement`).
"""
from __future__ import annotations

import re

from .model import Page, PageKind

_HEADING = re.compile(r"^(\*+)(\s)", re.MULTILINE)


def demote_headings(body: str, levels: int = 1) -> str:
    """Add `levels` stars to every heading line so the body nests."""
    stars = "*" * levels
    return _HEADING.sub(lambda m: f"{m.group(1)}{stars}{m.group(2)}", body)

SUMMARY_TEMPLATE = """\
** Recap

-
-
-

** Concepts introduced

-
"""


def wrap_lecture(page: Page, body: str) -> str:
    body = demote_headings(body)
    prev = _link_or_bare(page.prev_id, "Previous lecture", "(first lecture)")
    nxt = _link_or_bare(page.next_id, "Next lecture", "(last lecture)")
    return (
        "* Prev. lecture\n"
        f"\n{prev}\n\n"
        "* Content\n\n"
        f"{body.rstrip()}\n\n"
        "* Summary\n\n"
        f"{SUMMARY_TEMPLATE}\n"
        "* Next lecture\n"
        f"\n{nxt}\n"
    )


def wrap_assignment(page: Page, body: str) -> str:
    """I1 assignment template."""
    body = demote_headings(body)
    return (
        "* Problem statement\n\n"
        f"{body.rstrip()}\n\n"
        "* Solution\n\n"
        "* Reflection\n"
    )


def wrap_supplementary(page: Page, body: str) -> str:
    """Lighter wrapper for non-lecture reference pages: just `* Content`."""
    body = demote_headings(body)
    return "* Content\n\n" + body.rstrip() + "\n"


def wrap(page: Page, body: str) -> str:
    if page.kind == PageKind.ASSIGNMENT:
        return wrap_assignment(page, body)
    if page.kind == PageKind.SUPPLEMENTARY:
        return wrap_supplementary(page, body)
    return wrap_lecture(page, body)


def _link_or_bare(target_id: str | None, label: str, empty_text: str) -> str:
    if target_id:
        return f"[[id:{target_id}][{label}]]"
    return empty_text
