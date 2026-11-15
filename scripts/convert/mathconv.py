"""Pandoc wrapper + math-safe post-processor.

For every content conversion the pipeline does, use convert().
By default (`math_format="latex"`), Pandoc emits native Org LaTeX
fragments (`\\(...\\)`, `\\[...\\]`, and `\\begin{equation}...\\end{equation}`).
When `math_format="typst"`, the Lua filter at lua/latex-to-typst.lua
intercepts Math AST nodes and rewrites LaTeX fragments as Typst.

The post-pass sanitiser repairs two known pandoc-org pitfalls:
  (a) '#'-prefixed tokens getting mis-interpreted as org tags, and
  (b) stray lines starting with '#+' outside intended keywords.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_LUA_FILTER = Path(__file__).parent / "lua" / "latex-to-typst.lua"


def ensure_pandoc() -> None:
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc not found on PATH")


def convert(text: str, from_fmt: str, *, math_format: str = "latex") -> str:
    """Convert `text` from `from_fmt` to org.

    `from_fmt` is a pandoc input format, e.g. 'markdown+tex_math_dollars' or 'latex'.
    `yaml_metadata_block` is disabled for markdown inputs so bare `---`
    horizontal rules don't get misparsed as frontmatter.
    """
    if math_format not in ("latex", "typst"):
        raise ValueError(f"unsupported math_format: {math_format!r} (expected 'latex' or 'typst')")

    ensure_pandoc()
    if from_fmt.startswith("markdown") and "yaml_metadata_block" not in from_fmt:
        from_fmt = from_fmt + "-yaml_metadata_block"
    args = [
        "pandoc",
        f"--from={from_fmt}",
        "--to=org",
        "--wrap=preserve",
    ]
    if math_format == "typst":
        if not _LUA_FILTER.exists():
            raise FileNotFoundError(f"Typst Lua filter missing: {_LUA_FILTER}")
        args.append(f"--lua-filter={_LUA_FILTER}")
    result = subprocess.run(
        args, input=text, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pandoc failed:\n{result.stderr}")
    return _sanitize(result.stdout)


# ---------- post-pandoc sanitiser --------------------------------------

_HEADING_WITH_TAGS = re.compile(
    r"^(\*+ .+?)\s+(:[A-Za-z0-9_@#:/-]+:)\s*$", re.MULTILINE,
)
_SPURIOUS_DIRECTIVE = re.compile(r"^#\+[A-Z_]+:\s*$", re.MULTILINE)
_PANDOC_CUSTOM_ID_DRAWER = re.compile(
    r"\n:PROPERTIES:\n(?::[A-Z_]+:[^\n]*\n)+:END:\n",
)
_HTML_HR = re.compile(
    r"[ \t]*#\+begin_html[ \t]*\n[ \t]*<hr\s*/?>[ \t]*\n[ \t]*#\+end_html[ \t]*\n",
    re.IGNORECASE,
)
_HTML_STRUCTURAL = re.compile(
    r"[ \t]*#\+begin_html[ \t]*\n"
    r"[ \t]*</?(?:table|tr|td|th|thead|tbody|div|span|br)\b[^>]*/?>[ \t]*\n"
    r"[ \t]*#\+end_html[ \t]*\n",
    re.IGNORECASE,
)


def _sanitize(org: str) -> str:
    """Repair known pandoc→org mishandlings around '#' and strip clutter."""

    def _strip_bad_tags(m: re.Match) -> str:
        heading, tags = m.group(1), m.group(2)
        bits = [t for t in tags.strip(":").split(":") if t]
        safe = [t for t in bits if re.match(r"^[A-Za-z0-9_@-]+$", t)]
        if len(safe) == len(bits):
            return m.group(0)
        if not safe:
            return heading
        return f"{heading} :{':'.join(safe)}:"

    org = _HEADING_WITH_TAGS.sub(_strip_bad_tags, org)
    org = _SPURIOUS_DIRECTIVE.sub("", org)
    org = _PANDOC_CUSTOM_ID_DRAWER.sub("\n", org)
    org = _HTML_HR.sub("", org)
    org = _HTML_STRUCTURAL.sub("", org)
    org = _strip_leading_h1(org)
    org = _rewrite_list_markers(org)
    return org


def _strip_leading_h1(org: str) -> str:
    """Drop the body's first level-1 heading if it precedes all other content."""
    lines = org.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "":
            continue
        if stripped.startswith("#+"):
            continue
        if line.startswith("* ") and not line.startswith("** "):
            del lines[i]
            while i < len(lines) and lines[i].strip() == "":
                del lines[i]
            return "\n".join(lines)
        return org
    return org


_LIST_LINE = re.compile(r"^(\s*)(?:-|​\*)(\s)", re.MULTILINE)
_BLOCK_BEGIN = re.compile(r"^#\+BEGIN_(SRC|EXAMPLE|HTML|QUOTE|COMMENT|VERSE|EXPORT|CENTER)\b", re.IGNORECASE)
_BLOCK_END = re.compile(r"^#\+END_(SRC|EXAMPLE|HTML|QUOTE|COMMENT|VERSE|EXPORT|CENTER)\b", re.IGNORECASE)
_BRACKET_MATH_BEGIN = re.compile(r"^\s*\\\[")
_BRACKET_MATH_END = re.compile(r"\\\]\s*$")
_ENV_MATH_BEGIN = re.compile(r"^\s*\\begin\{([A-Za-z*]+)\}")
_ENV_MATH_END = re.compile(r"\\end\{([A-Za-z*]+)\}\s*$")


def _rewrite_list_markers(org: str) -> str:
    """Replace '- ' bullets with '+ ' outside block and display-math regions."""
    out: list[str] = []
    in_block = False
    in_bracket_math = False
    env_depth = 0

    for line in org.split("\n"):
        if in_block:
            out.append(line)
            if _BLOCK_END.match(line):
                in_block = False
            continue
        if _BLOCK_BEGIN.match(line):
            in_block = True
            out.append(line)
            continue

        if in_bracket_math:
            out.append(line)
            if _BRACKET_MATH_END.search(line):
                in_bracket_math = False
            continue
        if _BRACKET_MATH_BEGIN.match(line):
            out.append(line)
            if not _BRACKET_MATH_END.search(line):
                in_bracket_math = True
            continue

        if env_depth > 0:
            out.append(line)
            if _ENV_MATH_BEGIN.match(line) and not _ENV_MATH_END.search(line):
                env_depth += 1
            elif _ENV_MATH_END.search(line):
                env_depth = max(0, env_depth - 1)
            continue
        if _ENV_MATH_BEGIN.match(line):
            out.append(line)
            if not _ENV_MATH_END.search(line):
                env_depth = 1
            continue

        out.append(_LIST_LINE.sub(r"\1+\2", line))
    return "\n".join(out)
