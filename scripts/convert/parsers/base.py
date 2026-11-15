"""Parser ABC. Concrete parsers return a ParsedCourse."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..model import CourseMeta, ParsedCourse


class Parser(ABC):
    """A format-specific parser.

    Parsers are pure: `discover()` must not write anything.
    """

    #: Human-readable format name (also the registry key).
    name: str = ""

    #: Pandoc input format for each page's body. Markdown-ish parsers use
    #: an extended markdown dialect; the LaTeX parser overrides to "latex".
    pandoc_from_fmt: str = "markdown+tex_math_dollars+raw_tex+fenced_divs"

    @abstractmethod
    def discover(self, course_dir: Path, meta: CourseMeta) -> ParsedCourse:
        """Return a ParsedCourse with the ordered Page list filled in."""
        raise NotImplementedError
