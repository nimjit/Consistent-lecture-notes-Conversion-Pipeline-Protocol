"""Load CourseMeta from a course root.

Reads README.org if present, otherwise infers from the course path.
Short code and name can also be overridden by the CLI.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from .model import CourseMeta, PageKind
from .slug import default_short_from_slug

_TITLE_RE = re.compile(r"^#\+title:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_SHORT_RE = re.compile(r"\*\s*Short code:\*\s*=([a-z][a-z0-9-]*)=")
_LICENCE_RE = re.compile(r"\*\s*(?:Wiki )?[Ll]icen[cs]e:\*\s*(.+)")
_UPSTREAM_RE = re.compile(r"\*\s*Upstream URL:\*\s*(\S+)")


def _git_remote_url(course_dir: Path) -> Optional[str]:
    """Try to get upstream URL from source/.git/config."""
    for src in (course_dir / "source", course_dir / "markdown"):
        if (src / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "-C", str(src), "remote", "get-url", "origin"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
    return None


def _humanize_slug(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-"))


def load_meta(
    course_dir: Path,
    override_short: Optional[str] = None,
    override_name: Optional[str] = None,
    override_type: Optional[PageKind] = None,
) -> CourseMeta:
    """Load course meta. Overrides win over README over inferred."""
    readme = course_dir / "README.org"
    name: Optional[str] = None
    short: Optional[str] = None
    licence: Optional[str] = None
    upstream: Optional[str] = None

    if readme.exists():
        text = readme.read_text()
        tm = _TITLE_RE.search(text)
        if tm:
            name = tm.group(1).strip()
        sm = _SHORT_RE.search(text)
        if sm:
            short = sm.group(1)
        lm = _LICENCE_RE.search(text)
        if lm:
            licence = lm.group(1).strip()
        um = _UPSTREAM_RE.search(text)
        if um:
            upstream = um.group(1).strip().strip("<>")

    if override_short:
        short = override_short
    if override_name:
        name = override_name

    slug = course_dir.name
    if name is None:
        name = _humanize_slug(slug)
    if short is None:
        short = default_short_from_slug(slug)
    if upstream is None:
        upstream = _git_remote_url(course_dir)

    domain = course_dir.parent.name

    return CourseMeta(
        name=name,
        short=short,
        domain=domain,
        course_dir=course_dir,
        tags=[domain] if domain else [],
        license=licence,
        upstream_url=upstream,
        default_type=override_type or PageKind.LECTURE,
    )
