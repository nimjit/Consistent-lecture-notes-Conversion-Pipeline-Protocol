"""Collect upstream provenance & licence metadata and inject it into Org outputs."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_TITLE_RE = re.compile(r"^#\+title:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_LICENCE_RE = re.compile(r"\*\s*(?:Wiki )?[Ll]icen[cs]e:\*\s*(.+)")
_ORIGIN_RE = re.compile(r"\*\s*(?:Author|Origin|Upstream):\*\s*(.+)")
_URL_RE = re.compile(r"\*\s*(?:Upstream URL|Source URL|URL):\*\s*(.+)")


@dataclass
class ProvenanceInfo:
    title: str
    origin: str
    upstream_url: str
    licence: str


def _git_remote_url(course_dir: Path) -> str:
    for sub in ("source", "markdown"):
        git_dir = course_dir / sub / ".git"
        if git_dir.exists():
            res = subprocess.run(
                ["git", "-C", str(course_dir / sub), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                check=False,
            )
            url = res.stdout.strip()
            if url:
                return url
    return ""


def _read_courses_org_row(root: Path, domain: str, slug: str) -> tuple[str, str]:
    """Return `(origin, licence)` from root courses.org if present."""
    courses_org = root / "courses.org"
    if not courses_org.is_file():
        return "", ""
    text = courses_org.read_text(encoding="utf-8", errors="replace")
    current_domain: str | None = None
    col_map: dict[str, int] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("* ") and not line.startswith("** "):
            current_domain = line[2:].strip().lower()
            col_map = {}
            continue
        if current_domain != domain.lower() or not line.startswith("|"):
            continue
        if set(line.replace("|", "").replace("-", "").replace("+", "").strip()) == set():
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        if cells[0].lower() == "folder":
            col_map = {h.lower(): i for i, h in enumerate(cells)}
            continue

        row_slug = cells[0].strip("=~/ ")
        if row_slug == slug:
            origin = ""
            licence = ""
            for key in ("origin", "author / origin", "author"):
                if key in col_map and len(cells) > col_map[key]:
                    origin = cells[col_map[key]]
                    break
            for key in ("licence", "license"):
                if key in col_map and len(cells) > col_map[key]:
                    licence = cells[col_map[key]]
                    break
            return origin, licence
    return "", ""


def collect(course_dir: Path) -> ProvenanceInfo:
    """Gather attribution and licence metadata from README.org, courses.org, and git."""
    course_dir = course_dir.resolve()
    domain = course_dir.parent.name
    slug = course_dir.name
    root = course_dir.parent.parent

    title = slug
    origin = ""
    upstream_url = ""
    licence = ""

    readme = course_dir / "README.org"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8", errors="replace")
        if m := _TITLE_RE.search(text):
            title = m.group(1).strip()
        if m := _ORIGIN_RE.search(text):
            origin = m.group(1).strip()
        if m := _URL_RE.search(text):
            upstream_url = m.group(1).strip()
        if m := _LICENCE_RE.search(text):
            licence = m.group(1).strip()

    table_origin, table_licence = _read_courses_org_row(root, domain, slug)
    if not origin or origin == "—":
        origin = table_origin
    if not licence or licence == "none stated":
        licence = table_licence or licence

    if not upstream_url:
        upstream_url = _git_remote_url(course_dir)
    if (not origin or origin == "—") and upstream_url:
        m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", upstream_url)
        origin = m.group(1) if m else upstream_url

    return ProvenanceInfo(
        title=title,
        origin=origin or "unknown",
        upstream_url=upstream_url or "—",
        licence=licence or "none stated",
    )


def inject_page_properties(org_text: str, info: ProvenanceInfo) -> str:
    """Insert upstream attribution keys into the top-level :PROPERTIES: drawer."""
    extra = (
        f":UPSTREAM_ORIGIN: {info.origin}\n"
        f":UPSTREAM_URL: {info.upstream_url}\n"
        f":LICENCE: {info.licence}\n"
    )
    return re.sub(r"^:END:\s*$", extra + ":END:", org_text, count=1, flags=re.MULTILINE)


def render_org_section(info: ProvenanceInfo) -> str:
    """Return an Org section documenting copyright, origin, and licence for index.org."""
    lines = [
        "* Attribution & Licence",
        "",
        f"- *Original work:* {info.title}",
        f"- *Author / Origin:* {info.origin}",
        f"- *Upstream source:* {info.upstream_url}",
        f"- *Licence:* {info.licence}",
        "",
        "This Org-mode tree is a structural conversion generated from the",
        "upstream material above. Copyright and moral rights remain with the",
        "original author(s) under the stated licence terms.",
        "",
    ]
    return "\n".join(lines)
