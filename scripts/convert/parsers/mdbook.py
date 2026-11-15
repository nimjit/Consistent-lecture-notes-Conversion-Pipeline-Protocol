"""Parse an mdbook `source/src/SUMMARY.md` + markdown tree.

SUMMARY.md is the authoritative page order and hierarchy. Pages whose paths
match `**/lecture-notes/lecture-N(.5)?-*.md` become `LECTURE` entries;
everything else becomes `SUPPLEMENTARY`. Lecture numbers are grouped by
integer part so a fractional sibling (e.g. `lecture-4.5`) yields `04a`/`04b`.

The parser supports an `exclude` kwarg: pages whose source path contains any
excluded substring are dropped (needed for `lecture-1.5-git.md`, which the
user treats as not-core).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from ..ids import IdAllocator
from ..model import CourseMeta, Page, PageKind, ParsedCourse
from ..slug import assign_letter_suffixes, slugify
from .base import Parser

_SUMMARY_ITEM = re.compile(r"^(\s*)- \[([^\]]+)\]\(([^)]+)\)")
_SUMMARY_SECTION = re.compile(r"^#\s+(.+?)\s*$")
_LECTURE_FILENAME = re.compile(r"^lecture-(\d+)(?:\.(\d+))?-(.+)\.md$")
_LECTURE_NOTES_DIR = re.compile(r"(^|/)lecture-notes/")


class MdbookParser(Parser):
    name = "mdbook"

    def discover(
        self,
        course_dir: Path,
        meta: CourseMeta,
        exclude: Optional[list[str]] = None,
    ) -> ParsedCourse:
        src_root = course_dir / "source" / "src"
        summary = src_root / "SUMMARY.md"
        if not summary.exists():
            raise FileNotFoundError(f"no SUMMARY.md at {summary}")

        exclude = exclude or []
        entries = list(self._parse_summary(summary, src_root, exclude))

        allocator = IdAllocator(meta.short, reproducible=True)

        # Partition into lectures (with fractional-grouped numbers) and supplementary.
        lecture_tuples: list[tuple[int, Optional[float], str, Path]] = []  # (int, frac, title, path)
        supplementary: list[tuple[str, Path]] = []  # (title, path)
        for title, path, _section in entries:
            cls = self._classify(path)
            if cls == PageKind.LECTURE:
                m = _LECTURE_FILENAME.match(path.name)
                if not m:
                    # Shouldn't happen given _classify matched, but defensive.
                    supplementary.append((title, path))
                    continue
                int_part = int(m.group(1))
                frac_part = float(f"0.{m.group(2)}") if m.group(2) else None
                lecture_tuples.append((int_part, frac_part, title, path))
            else:
                supplementary.append((title, path))

        # Assign zero-padded numbers with letter suffixes where needed.
        number_input = [(n, f) for n, f, _, _ in lecture_tuples]
        numbers = assign_letter_suffixes(number_input)

        pages: list[Page] = []
        for (int_part, frac_part, title, path), number in zip(lecture_tuples, numbers):
            fn_match = _LECTURE_FILENAME.match(path.name)
            raw_slug = fn_match.group(3) if fn_match else path.stem
            slug = slugify(raw_slug) or f"lecture-{number}"
            body = path.read_text(encoding="utf-8")
            relpath = path.relative_to(course_dir)
            pages.append(
                Page(
                    kind=PageKind.LECTURE,
                    number=number,
                    slug=slug,
                    title=title,
                    body=body,
                    org_id=allocator.for_path(relpath),
                    source_path=path,
                )
            )

        for title, path in supplementary:
            # Flattened path becomes the slug (minus the .md).
            rel_from_src = path.relative_to(src_root)
            flat = str(rel_from_src.with_suffix("")).replace("/", "-")
            slug = slugify(flat) or path.stem
            body = path.read_text(encoding="utf-8")
            relpath = path.relative_to(course_dir)
            pages.append(
                Page(
                    kind=PageKind.SUPPLEMENTARY,
                    number="",
                    slug=slug,
                    title=title,
                    body=body,
                    org_id=allocator.for_path(relpath),
                    source_path=path,
                )
            )

        return ParsedCourse(meta=meta, pages=pages)

    def _parse_summary(
        self,
        summary: Path,
        src_root: Path,
        exclude: list[str],
    ) -> Iterable[tuple[str, Path, str]]:
        """Yield (title, abs_path, section_heading) in document order."""
        text = summary.read_text(encoding="utf-8")
        current_section = ""
        for raw_line in text.split("\n"):
            m_sec = _SUMMARY_SECTION.match(raw_line)
            if m_sec:
                current_section = m_sec.group(1).strip()
                continue
            m_item = _SUMMARY_ITEM.match(raw_line)
            if not m_item:
                continue
            title = m_item.group(2).strip()
            raw_path = m_item.group(3).strip()
            if raw_path.startswith("./"):
                raw_path = raw_path[2:]
            abs_path = (src_root / raw_path).resolve()
            if any(x in str(abs_path) for x in exclude):
                continue
            if not abs_path.exists():
                print(f"  skipping missing SUMMARY entry: {raw_path}")
                continue
            yield title, abs_path, current_section

    def _classify(self, path: Path) -> PageKind:
        if _LECTURE_NOTES_DIR.search(str(path)) and _LECTURE_FILENAME.match(path.name):
            return PageKind.LECTURE
        return PageKind.SUPPLEMENTARY
