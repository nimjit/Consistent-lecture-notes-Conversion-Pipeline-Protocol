"""Parse a Jupyter Book: `source/_toc.yml` + markdown or notebook pages.

The _toc.yml structure (jb-book) is nested parts → chapters → sections,
each with a `file:` entry naming a markdown or ipynb page. The TOC can
sit either at `source/_toc.yml` (typical Jupyter Book) or at
`source/book/_toc.yml` (some courses nest the book inside `source/`).

For `.ipynb` entries, nbconvert's MarkdownExporter converts in-process
and writes the result + any extracted images to a scratch dir, so the
rest of the pipeline operates on markdown as usual.

Pages whose stem matches a framing name (index/credits/preface/intro)
are classified as `SUPPLEMENTARY`; everything else is `LECTURE` with a
sequential 2-digit number.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..ids import IdAllocator
from ..model import CourseMeta, Page, PageKind, ParsedCourse
from ..myst import preprocess as myst_preprocess
from ..slug import pad_number, slugify
from .base import Parser

_FILE_LINE = re.compile(r"^\s*-?\s*file:\s*(\S+)\s*$")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# Framing files that aren't lecture content.
_SUPPLEMENTARY_STEMS = {"index", "credits", "preface", "intro"}


def _scratch_root(course_dir: Path) -> Path:
    """Where nb-converted markdown + images live during a run."""
    return (course_dir.parent.parent / ".staging"
            / f"{course_dir.parent.name}--{course_dir.name}" / "_nb")


class JupyterBookParser(Parser):
    name = "jupyter-book"

    def discover(
        self,
        course_dir: Path,
        meta: CourseMeta,
        exclude: Optional[list[str]] = None,
    ) -> ParsedCourse:
        src_root = self._find_src_root(course_dir)
        toc = src_root / "_toc.yml"
        if not toc.exists():
            raise FileNotFoundError(f"no _toc.yml at {toc}")

        exclude = exclude or []
        raw_entries = list(self._parse_toc(toc, src_root, exclude))

        # Pre-convert any .ipynb entry to markdown. The scratch dir mirrors
        # the entry's path under src_root so image refs resolve.
        scratch = _scratch_root(course_dir)
        entries: list[tuple[Path, Path]] = []  # (effective_path, id_key_path)
        for original in raw_entries:
            if original.suffix == ".ipynb":
                md_path = _convert_notebook(original, src_root, scratch)
                entries.append((md_path, original))
            else:
                entries.append((original, original))

        allocator = IdAllocator(meta.short, reproducible=True)

        lecture_entries: list[tuple[Path, Path]] = []
        supp_entries: list[tuple[Path, Path]] = []
        for effective, orig in entries:
            if orig.stem.lower() in _SUPPLEMENTARY_STEMS:
                supp_entries.append((effective, orig))
            else:
                lecture_entries.append((effective, orig))

        pages: list[Page] = []

        for n, (effective, orig) in enumerate(lecture_entries, start=1):
            number = pad_number(n)
            raw_body = effective.read_text(encoding="utf-8")
            body = myst_preprocess(raw_body)
            title = _extract_title(body) or _humanize_stem(orig.stem)
            slug = slugify(title) or slugify(orig.stem)
            id_relpath = orig.relative_to(course_dir)
            pages.append(Page(
                kind=PageKind.LECTURE,
                number=number,
                slug=slug,
                title=title,
                body=body,
                org_id=allocator.for_path(id_relpath),
                source_path=effective,
            ))

        for effective, orig in supp_entries:
            raw_body = effective.read_text(encoding="utf-8")
            body = myst_preprocess(raw_body)
            title = _extract_title(body) or _humanize_stem(orig.stem)
            rel_from_src = orig.relative_to(src_root)
            flat = str(rel_from_src.with_suffix("")).replace("/", "-")
            slug = slugify(flat) or orig.stem
            id_relpath = orig.relative_to(course_dir)
            pages.append(Page(
                kind=PageKind.SUPPLEMENTARY,
                number="",
                slug=slug,
                title=title,
                body=body,
                org_id=allocator.for_path(id_relpath),
                source_path=effective,
            ))

        return ParsedCourse(meta=meta, pages=pages)

    def _find_src_root(self, course_dir: Path) -> Path:
        """Jupyter Book root is `source/` or `source/book/`."""
        for candidate in (course_dir / "source", course_dir / "source" / "book"):
            if (candidate / "_toc.yml").exists():
                return candidate
        raise FileNotFoundError(
            f"no _toc.yml at {course_dir/'source'} or {course_dir/'source'/'book'}"
        )

    def _parse_toc(self, toc: Path, src_root: Path, exclude: list[str]):
        seen: set[Path] = set()
        for line in toc.read_text(encoding="utf-8").split("\n"):
            m = _FILE_LINE.match(line)
            if not m:
                continue
            rel = m.group(1).strip().strip("\"'")
            # _toc.yml entries may or may not include the extension.
            for ext in ("", ".md", ".ipynb"):
                candidate = (src_root / f"{rel}{ext}").resolve()
                if candidate.is_file():
                    break
            else:
                print(f"  skipping missing TOC entry: {rel}")
                continue
            if any(x in str(candidate) for x in exclude):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            yield candidate


# Catches image refs in all three forms that notebooks commonly use:
# markdown `![alt](path)`, MyST `{figure} path`, raw HTML `<img src="path">`.
_IMG_REFS = re.compile(
    r"!\[[^\]]*\]\(([^)\s]+)"
    r"|```\{figure\}\s+(\S+)"
    r"""|<img\s+[^>]*?src\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


def _convert_notebook(ipynb: Path, src_root: Path, scratch: Path) -> Path:
    """Convert a .ipynb to markdown + images in `scratch/<rel_from_src>.md`.

    Writes nbconvert's resource outputs (plot images, extracted bytes) to
    the scratch dir, AND copies any sibling media files the generated
    markdown references (gifs, pngs that live alongside the notebook in
    `source/` but weren't produced by cell execution).

    Reuses an existing conversion if its mtime is newer than the source
    notebook — cheap caching across repeated runs.
    """
    import shutil
    import nbformat
    from nbconvert import MarkdownExporter

    rel = ipynb.relative_to(src_root).with_suffix(".md")
    md_path = scratch / rel
    md_path.parent.mkdir(parents=True, exist_ok=True)

    if md_path.exists() and md_path.stat().st_mtime >= ipynb.stat().st_mtime:
        return md_path

    nb = nbformat.read(str(ipynb), as_version=4)
    body, resources = MarkdownExporter().from_notebook_node(nb)
    md_path.write_text(body, encoding="utf-8")
    for name, data in resources.get("outputs", {}).items():
        (md_path.parent / name).write_bytes(data)

    # Copy sibling media referenced by any form (markdown, MyST figure,
    # raw HTML <img>) that nbconvert didn't produce as a cell output.
    orig_dir = ipynb.parent
    for m in _IMG_REFS.finditer(body):
        ref = m.group(1) or m.group(2) or m.group(3)
        if not ref:
            continue
        if ref.startswith(("http://", "https://", "http:/", "https:/", "data:")):
            continue
        src = (orig_dir / ref).resolve()
        if not src.is_file():
            continue
        try:
            if src.is_relative_to(md_path.parent):
                continue
        except AttributeError:
            pass
        dst = md_path.parent / ref
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy2(src, dst)
    return md_path


def _extract_title(body: str) -> Optional[str]:
    m = _H1_RE.search(body)
    return m.group(1).strip() if m else None


def _humanize_stem(stem: str) -> str:
    # "Ch1_Introduction" → "Ch1 Introduction"
    return re.sub(r"[_-]", " ", stem)
