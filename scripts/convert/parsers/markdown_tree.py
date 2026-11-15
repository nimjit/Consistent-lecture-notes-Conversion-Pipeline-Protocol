"""Parse a flat markdown directory with numeric-prefixed filenames.

Target shape: `source/NN-Title-With-Dashes.md` (any `README.md` is skipped).
Order is given by the numeric prefix, not by alphabetical sort.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..ids import IdAllocator
from ..model import CourseMeta, Page, PageKind, ParsedCourse
from ..slug import pad_number, slugify
from .base import Parser

_NUMBERED = re.compile(r"^(\d+)[-_\s]+(.+)\.md$")


class MarkdownTreeParser(Parser):
    name = "markdown-tree"

    def discover(self, course_dir: Path, meta: CourseMeta) -> ParsedCourse:
        root = self._find_root(course_dir)
        if root is None:
            raise FileNotFoundError(
                f"No source/ or markdown/ dir with *.md files under {course_dir}"
            )

        allocator = IdAllocator(meta.short, reproducible=True)
        numbered: list[tuple[int, Path, str]] = []
        unnumbered: list[Path] = []
        for md in root.glob("*.md"):
            if md.name.lower() == "readme.md":
                continue
            m = _NUMBERED.match(md.name)
            if m:
                numbered.append((int(m.group(1)), md, m.group(2)))
            else:
                unnumbered.append(md)

        numbered.sort(key=lambda t: t[0])
        # When nothing has a numeric prefix, fall back to alphabetical
        # order and allocate sequential numbers so the pipeline has
        # something to work with.
        entries: list[tuple[int, Path, str]] = list(numbered)
        if not entries and unnumbered:
            for i, md in enumerate(sorted(unnumbered), start=1):
                entries.append((i, md, md.stem))

        pages: list[Page] = []
        for n, md, title_dash in entries:
            number = pad_number(n)
            title = title_dash.replace("-", " ").replace("_", " ")
            slug = slugify(title)
            body = md.read_text(encoding="utf-8")
            relpath = md.relative_to(course_dir)
            pages.append(
                Page(
                    kind=meta.default_type if meta.default_type != PageKind.ASSIGNMENT
                        else PageKind.LECTURE,
                    number=number,
                    slug=slug,
                    title=title,
                    body=body,
                    org_id=allocator.for_path(relpath),
                    source_path=md,
                )
            )

        return ParsedCourse(meta=meta, pages=pages)

    def _find_root(self, course_dir: Path) -> Path | None:
        for base in ("source", "markdown"):
            root = course_dir / base
            if root.is_dir() and list(root.glob("*.md")):
                return root
        return None
