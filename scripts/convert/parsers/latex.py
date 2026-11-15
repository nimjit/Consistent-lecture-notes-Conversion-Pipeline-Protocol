"""Parse a monolithic LaTeX course rooted at `source/main.tex`.

Supports the common structure where `main.tex` contains the preamble and
a sequence of `\\input{chapter-name}` directives. Each `\\input`-ed file
becomes a Page; its body is wrapped with the shared preamble so pandoc
has access to any `\\newtheorem` / `\\DeclareMathOperator` declarations.

Classification: a file whose stem is `introduction`, `preface`, or
`credits` becomes `SUPPLEMENTARY`; everything else is a `LECTURE`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..ids import IdAllocator
from ..model import CourseMeta, Page, PageKind, ParsedCourse
from ..slug import pad_number, slugify
from .base import Parser

_INPUT_RE = re.compile(r"\\input\{([^}]+)\}")
_INCLUDE_RE = re.compile(r"\\include\{([^}]+)\}")
# \import{dir/}{file.tex} from the `import` package.
_IMPORT_RE = re.compile(r"\\import\{([^}]+)\}\{([^}]+)\}")
_SECTION_RE = re.compile(r"\\(?:chapter|section)\*?\{([^}]+)\}")
_DOCUMENT_BEGIN = re.compile(r"\\begin\{document\}")
_DOCUMENTCLASS_RE = re.compile(r"\\documentclass")

_SUPPLEMENTARY_STEMS = {"introduction", "preface", "credits"}


class LatexParser(Parser):
    name = "latex"
    pandoc_from_fmt = "latex"

    def discover(
        self,
        course_dir: Path,
        meta: CourseMeta,
        exclude: Optional[list[str]] = None,
    ) -> ParsedCourse:
        base = course_dir / "source"
        src_root, main = _resolve_src_root(base)
        if main is None:
            raise FileNotFoundError(
                f"no main.tex / book.tex / \\documentclass .tex file in {base}"
            )

        exclude = exclude or []
        main_text = _read_text(main)

        begin_m = _DOCUMENT_BEGIN.search(main_text)
        preamble = main_text[: begin_m.start()] if begin_m else ""
        body_text = main_text[begin_m.end():] if begin_m else main_text

        inputs: list[Path] = []
        # \input{name} and \include{name}
        for pattern in (_INPUT_RE, _INCLUDE_RE):
            for m in pattern.finditer(body_text):
                fname = m.group(1).strip()
                # Skip macro-parameter placeholders (\input{#1}, \input{\arg})
                # and empty names — these appear inside macro definitions.
                if not fname or fname.startswith(("#", "\\")):
                    continue
                path = _resolve_tex(src_root, fname)
                if path is None:
                    print(f"  skipping missing \\input: {fname}")
                    continue
                if any(x in str(path) for x in exclude):
                    continue
                if path not in inputs:
                    inputs.append(path)
        # \import{dir/}{file.tex} from the `import` package
        for m in _IMPORT_RE.finditer(body_text):
            d, fname = m.group(1).strip().rstrip("/"), m.group(2).strip()
            candidate = (src_root / d / fname).resolve()
            if not candidate.is_file() and not fname.endswith(".tex"):
                candidate = (src_root / d / f"{fname}.tex").resolve()
            if not candidate.is_file():
                print(f"  skipping missing \\import: {d}/{fname}")
                continue
            if any(x in str(candidate) for x in exclude):
                continue
            if candidate not in inputs:
                inputs.append(candidate)

        if not inputs:
            # Flat-LaTeX mode: no master document aggregates chapters.
            # Each `.tex` with `\documentclass` at the root is a separate
            # page. Skip the picked "main" if it was just the alphabetically
            # first standalone.
            for p in sorted(src_root.glob("*.tex")):
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                if _DOCUMENTCLASS_RE.search(text) and _DOCUMENT_BEGIN.search(text):
                    if any(x in str(p) for x in exclude):
                        continue
                    if p not in inputs:
                        inputs.append(p.resolve())
            if not inputs:
                raise RuntimeError(
                    f"no \\input / \\include / \\import entries found in {main}, "
                    f"and no standalone chapter .tex at the root"
                )

        allocator = IdAllocator(meta.short, reproducible=True)

        lecture_paths: list[Path] = []
        supp_paths: list[Path] = []
        for p in inputs:
            if p.stem.lower() in _SUPPLEMENTARY_STEMS:
                supp_paths.append(p)
            else:
                lecture_paths.append(p)

        pages: list[Page] = []

        for n, tex in enumerate(lecture_paths, start=1):
            number = pad_number(n)
            body = _read_text(tex)
            title = _extract_title(body) or _humanize_stem(tex.stem)
            slug = slugify(title) or slugify(tex.stem)
            relpath = tex.relative_to(course_dir)
            pages.append(Page(
                kind=PageKind.LECTURE,
                number=number,
                slug=slug,
                title=title,
                body=_wrap_with_preamble(body, preamble),
                org_id=allocator.for_path(relpath),
                source_path=tex,
            ))

        for tex in supp_paths:
            body = _read_text(tex)
            title = _extract_title(body) or _humanize_stem(tex.stem)
            relpath = tex.relative_to(course_dir)
            slug = slugify(tex.stem)
            pages.append(Page(
                kind=PageKind.SUPPLEMENTARY,
                number="",
                slug=slug,
                title=title,
                body=_wrap_with_preamble(body, preamble),
                org_id=allocator.for_path(relpath),
                source_path=tex,
            ))

        return ParsedCourse(meta=meta, pages=pages)


def _resolve_tex(root: Path, fname: str) -> Optional[Path]:
    """Try `root/fname.tex`, then `root/fname`, then nested `root/fname/fname.tex`."""
    for candidate in (
        root / f"{fname}.tex",
        root / fname,
        root / fname / f"{Path(fname).name}.tex",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


_COMMON_MAIN_NAMES = (
    "main.tex", "book.tex", "all-in-one.tex", "notes.tex",
    "master.tex", "root.tex", "index.tex", "chapters.tex",
)

_INCLUDES_PROBE = re.compile(r"\\(?:input|include|import)\b")


def _read_text(path: Path) -> str:
    """Read a file as text. LaTeX sources commonly use Latin-1 for ©/±
    symbols — fall back to that if UTF-8 fails, else replace bad bytes.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return path.read_text(encoding="latin-1")
    except Exception:
        return path.read_text(encoding="utf-8", errors="replace")


def _resolve_src_root(base: Path) -> tuple[Path, Optional[Path]]:
    """Pick the LaTeX source root and its entry point.

    Checks `base` first; if nothing suitable, descends one level into
    subdirs so `source/main/main.tex` style layouts work.
    """
    main = _find_main_tex(base)
    if main is not None:
        return base, main
    if base.is_dir():
        for sub in sorted(base.iterdir()):
            if not sub.is_dir():
                continue
            m = _find_main_tex(sub)
            if m is not None:
                return sub, m
    return base, None


def _find_main_tex(root: Path) -> Optional[Path]:
    """Pick the LaTeX entry point.

    Preference order:
    1. A file with one of the common master filenames (main.tex,
       book.tex, all-in-one.tex, notes.tex, …).
    2. Any `.tex` that has both `\\begin{document}` and at least one
       `\\input`/`\\include`/`\\import` — those are the files that
       actually aggregate chapters.
    3. First `.tex` with `\\documentclass`.
    """
    for name in _COMMON_MAIN_NAMES:
        p = root / name
        if p.is_file():
            return p

    all_tex = sorted(root.glob("*.tex"))
    aggregators: list[Path] = []
    classed: list[Path] = []
    for p in all_tex:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        has_class = _DOCUMENTCLASS_RE.search(text) is not None
        has_begin = _DOCUMENT_BEGIN.search(text) is not None
        has_includes = _INCLUDES_PROBE.search(text) is not None
        if has_begin and has_includes:
            aggregators.append(p)
        elif has_class:
            classed.append(p)
    if aggregators:
        return aggregators[0]
    return classed[0] if classed else None


def _extract_title(body: str) -> Optional[str]:
    m = _SECTION_RE.search(body)
    return m.group(1).strip() if m else None


def _humanize_stem(stem: str) -> str:
    return re.sub(r"[-_]", " ", stem).title()


def _wrap_with_preamble(body: str, preamble: str) -> str:
    """Build a self-contained LaTeX document for pandoc.

    If the body is already a complete LaTeX document (has its own
    `\\documentclass` and `\\begin{document}`, as `standalone`-style
    chapter files do), pass it through unchanged — double-wrapping it
    would make pandoc choke.

    Otherwise, prepend the master preamble so custom macros, theorem
    environments, and operator declarations are in scope. Empty preamble
    falls back to a bare article shell.
    """
    if "\\documentclass" in body and "\\begin{document}" in body:
        return body
    header = preamble.strip() or "\\documentclass{article}"
    return f"{header}\n\\begin{{document}}\n{body.strip()}\n\\end{{document}}\n"
