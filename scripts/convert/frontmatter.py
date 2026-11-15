"""Emit the E1 PROPERTIES drawer for a page."""
from __future__ import annotations

from typing import Optional

from .model import CourseMeta, Page, PageKind


def emit(
    page: Page,
    meta: CourseMeta,
    *,
    status: str = "draft",
    extra_tags: Optional[list[str]] = None,
) -> str:
    """Build the :PROPERTIES: ... :END: block + #+title: line.

    Lines up with protocol E1 (fields) and D2 (PREV/NEXT in frontmatter).
    """
    tags = list(meta.tags)
    if extra_tags:
        for t in extra_tags:
            if t not in tags:
                tags.append(t)

    type_value = _type_for(page, meta)

    lines = [
        ":PROPERTIES:",
        f":ID:           {page.org_id}",
        f":COURSE:       {meta.name}",
        f":COURSE_SHORT: {meta.short}",
        f":TYPE:         {type_value}",
        f":NUMBER:       {page.number}",
        f":PREV:         {page.prev_id or ''}",
        f":NEXT:         {page.next_id or ''}",
        f":STATUS:       {status}",
        f":TAGS:         {' '.join(tags)}",
        ":END:",
        f"#+title: {page.title}",
        "",
    ]
    return "\n".join(lines)


def _type_for(page: Page, meta: CourseMeta) -> str:
    if page.kind == PageKind.ASSIGNMENT:
        return "assignment"
    if page.kind == PageKind.SUPPLEMENTARY:
        return "supplementary"
    if page.kind == PageKind.OWN_NOTES or meta.default_type == PageKind.OWN_NOTES:
        return "own-notes"
    return "lecture"
