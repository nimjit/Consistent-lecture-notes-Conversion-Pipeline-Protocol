"""Dataclasses that flow through the conversion pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class PageKind(str, Enum):
    LECTURE = "lecture"
    ASSIGNMENT = "assignment"
    OWN_NOTES = "own-notes"
    SUPPLEMENTARY = "supplementary"


@dataclass
class CourseMeta:
    """Course-level metadata. Carried on every emitted page's frontmatter."""
    name: str
    short: str
    domain: str
    course_dir: Path
    tags: list[str] = field(default_factory=list)
    license: Optional[str] = None
    upstream_url: Optional[str] = None
    default_type: PageKind = PageKind.LECTURE


@dataclass
class Asset:
    """An image or other binary attached to one or more pages."""
    source_path: Path
    target_slug: str
    extension: str
    org_id: str
    caption: Optional[str] = None
    externally_licensed: bool = False

    @property
    def target_filename(self) -> str:
        return f"{self.target_slug}{self.extension}"


@dataclass
class Page:
    """A single lecture or assignment page in a course."""
    kind: PageKind
    number: str                        # "01", "02", ..., or "04a", "04b"
    slug: str                          # topic slug for the filename
    title: str                         # human-readable
    body: str                          # org body, post-content-conversion
    org_id: str                        # UUIDv5 (default) or UUIDv4
    source_path: Path                  # upstream file (provenance)
    assets: list[Asset] = field(default_factory=list)
    prev_id: Optional[str] = None      # filled in a later pass
    next_id: Optional[str] = None


@dataclass
class ParsedCourse:
    """A parser's output. Format-agnostic from here on."""
    meta: CourseMeta
    pages: list[Page]
    shared_assets: list[Asset] = field(default_factory=list)
