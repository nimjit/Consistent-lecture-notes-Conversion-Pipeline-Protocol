"""Format-specific parsers. Each returns a ParsedCourse."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .base import Parser
from .jupyter_book import JupyterBookParser
from .latex import LatexParser
from .markdown_tree import MarkdownTreeParser
from .mdbook import MdbookParser

if TYPE_CHECKING:
    from ..model import ParsedCourse  # noqa: F401

_REGISTRY: dict[str, type[Parser]] = {
    "markdown-tree": MarkdownTreeParser,
    "mdbook": MdbookParser,
    "jupyter-book": JupyterBookParser,
    "latex": LatexParser,
}


def available_formats() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_parser(fmt: str) -> type[Parser]:
    try:
        return _REGISTRY[fmt]
    except KeyError:
        raise ValueError(
            f"Unknown format {fmt!r}. Known: {', '.join(available_formats())}"
        )


def autodetect(course_dir: Path) -> str:
    """Pick a format based on what's in the course directory.

    Rules (first match wins):
    - source/book.toml           → mdbook
    - source/_toc.yml            → jupyter-book
    - source/main.tex            → latex
    - source/*.ipynb (majority)  → notebooks
    - source/ or markdown/ with *.md files → markdown-tree
    """
    for base in ("source", "markdown"):
        root = course_dir / base
        if not root.is_dir():
            continue
        if (root / "book.toml").exists():
            return "mdbook"
        # Jupyter Book may nest its _toc.yml inside a `book/` subdir.
        if (root / "_toc.yml").exists() or (root / "book" / "_toc.yml").exists():
            return "jupyter-book"
        if (root / "main.tex").exists() or (root / "book.tex").exists():
            return "latex"
        # Also accept a nested master like `source/main/main.tex` or
        # `source/book/book.tex` — some courses wrap their LaTeX in a subdir.
        for subdir in root.iterdir() if root.is_dir() else []:
            if not subdir.is_dir():
                continue
            if (subdir / "main.tex").exists() or (subdir / "book.tex").exists():
                return "latex"
        # Any `.tex` with \documentclass at the top is a LaTeX document.
        for tex in root.glob("*.tex"):
            try:
                head = tex.read_text(encoding="utf-8", errors="replace")[:2000]
                if r"\documentclass" in head:
                    return "latex"
            except Exception:
                continue
        # A root-level aggregator like `chapters.tex` with lots of \input
        # counts as LaTeX even without \documentclass.
        for tex in root.glob("*.tex"):
            try:
                head = tex.read_text(encoding="utf-8", errors="replace")[:4000]
                if head.count("\\input{") >= 3:
                    return "latex"
            except Exception:
                continue
        if list(root.glob("*.md")):
            return "markdown-tree"
    raise ValueError(f"Could not autodetect a format under {course_dir}")
