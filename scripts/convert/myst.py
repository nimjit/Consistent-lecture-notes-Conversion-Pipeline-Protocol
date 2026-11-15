"""Preprocess MyST-Markdown directives before handing text to pandoc.

Jupyter Book uses MyST, which has directives pandoc does not natively parse:

- ```` ```{figure} path\n...\n``` ```` — figure with caption and options
- ```` ```{math} ...\n``` ```` — display math block
- `` {numref}`label` `` — cross-reference role

We rewrite the ones that would otherwise disappear or confuse pandoc into
plain markdown or Typst-friendly equivalents.

This module also carries `rewrite_html_images`, which turns raw HTML
`<img src="…">` into markdown `![alt](src)` so the shared asset registry
picks them up regardless of source format. Called from the pipeline for
every page, not just Jupyter Book ones.
"""
from __future__ import annotations

import re

# ```{figure} path.png
# ---
# name: fig:foo
# alt: Alt text
# width: 50%
# ---
# Caption text.
# ```
#
# Also accepts the simpler `:name: foo` style without --- fences.
_FIGURE = re.compile(
    r"```\{figure\}\s+(?P<path>\S+)\s*\n"
    r"(?P<opts>(?:---\s*\n(?:.|\n)*?---\s*\n|(?::[^\n]+\n)*))"
    r"(?P<caption>(?:(?!```)[^\n]*\n?)*)"
    r"```",
    re.MULTILINE,
)

_ALT_RE = re.compile(r":alt:\s*\"?(?P<alt>.+?)\"?\s*$", re.MULTILINE)

# ```{math}
# e^{i\pi} + 1 = 0
# ```
_MATH_BLOCK = re.compile(r"```\{math\}\s*\n(?P<body>.+?)\n```", re.DOTALL)

# {numref}`fig:foo` — collapse to the label.
_NUMREF = re.compile(r"\{numref\}`([^`]+)`")

# {ref}`...`, {doc}`...`, {eq}`...` — strip role, keep label.
_SIMPLE_ROLE = re.compile(r"\{(?:ref|doc|eq)\}`([^`]+)`")

# Generic ```{directive} ... ``` block. We convert these to pandoc
# `fenced_divs` so their inner body is still parsed as markdown (preserving
# math, links, etc.) rather than being treated as a code block.
_DIRECTIVE_BLOCK = re.compile(
    r"```\{(?P<name>[a-z][\w-]*)\}(?P<arg>[^\n]*)\n"
    r"(?P<opts>(?:---\s*\n(?:.|\n)*?---\s*\n|(?::[^\n:]+:[^\n]*\n)*))"
    r"(?P<body>(?:(?!```).*\n?)*)"
    r"```",
    re.MULTILINE,
)


def preprocess(body: str) -> str:
    body = _rewrite_figures(body)
    body = _rewrite_math_blocks(body)
    body = _NUMREF.sub(lambda m: m.group(1), body)
    body = _SIMPLE_ROLE.sub(lambda m: m.group(1), body)
    body = _rewrite_directive_blocks(body)
    return body


# Raw HTML <img ...>. Match self-closing and open tags.
_HTML_IMG = re.compile(r"<img\s+([^>]*?)/?>", re.IGNORECASE)
_HTML_SRC = re.compile(r'''src\s*=\s*["']([^"']+)["']''', re.IGNORECASE)
_HTML_ALT = re.compile(r'''alt\s*=\s*["']([^"']*)["']''', re.IGNORECASE)


def rewrite_html_images(body: str) -> str:
    """Rewrite raw HTML `<img src="...">` tags to markdown `![alt](src)`.

    Picked up by the asset registry on the subsequent pre-pandoc pass.
    Preserves the full URL for external images (which won't attachment-ify
    but will remain as plain org links through pandoc).
    """
    def repl(m: re.Match) -> str:
        attrs = m.group(1)
        src_m = _HTML_SRC.search(attrs)
        if not src_m:
            return m.group(0)
        src = src_m.group(1)
        alt_m = _HTML_ALT.search(attrs)
        alt = alt_m.group(1) if alt_m else ""
        return f"![{alt}]({src})"
    return _HTML_IMG.sub(repl, body)


# `<hN>…</hN>` wrappers used for styling in Jupyter Book. Pandoc preserves
# these as raw HTML, which means their contents (including math) are not
# markdown-parsed. Rewrite to markdown atx headings pre-pandoc.
_HTML_HEADING_OPEN = re.compile(r"^\s*<h([1-6])\b[^>]*>\s*\n?", re.MULTILINE | re.IGNORECASE)
_HTML_HEADING_CLOSE = re.compile(r"\s*</h([1-6])>\s*\n?", re.IGNORECASE)


def rewrite_html_headings(body: str) -> str:
    """Convert `<hN>...</hN>` wrapper tags to markdown atx headings.

    Only works when the opening and content/closing are on separate lines
    (which is how Jupyter Book sources are written). The closing tag is
    removed; the opening becomes `###### ` or similar.
    """
    out = _HTML_HEADING_OPEN.sub(lambda m: "#" * int(m.group(1)) + " ", body)
    out = _HTML_HEADING_CLOSE.sub("\n", out)
    return out


# Pandoc's `tex_math_dollars` extension refuses `$<space>x$` or `$x<space>$`
# — whitespace adjacent to the delimiter kills the match. CMSR sources use
# this spaced style consistently for what the author meant as display math,
# so promote any whitespace-adjacent `$...$` to `$$...$$`.
#
# Negative look-around keeps us out of existing `$$...$$` display blocks.
_LOOSE_INLINE_MATH = re.compile(r"(?<!\$)\$([^\$\n]+?)\$(?!\$)")


def normalise_spaced_math(body: str) -> str:
    """Promote `$ x $`, `$x $`, or `$ x$` to `$$x$$`.

    Leaves `$x$` (no inner whitespace) and `$$x$$` alone.
    """
    def repl(m: re.Match) -> str:
        content = m.group(1)
        stripped = content.strip()
        if stripped == content:
            return m.group(0)  # flush — real inline math, leave alone
        return f"$${stripped}$$"
    return _LOOSE_INLINE_MATH.sub(repl, body)


def _rewrite_figures(body: str) -> str:
    def repl(m: re.Match) -> str:
        path = m.group("path")
        caption = (m.group("caption") or "").strip()
        opts = m.group("opts") or ""
        alt_match = _ALT_RE.search(opts)
        alt = (alt_match.group("alt") if alt_match else "").strip()
        img = f"![{alt}]({path})"
        if caption:
            return f"\n{img}\n\n*{caption}*\n"
        return f"\n{img}\n"
    return _FIGURE.sub(repl, body)


def _rewrite_math_blocks(body: str) -> str:
    def repl(m: re.Match) -> str:
        inner = m.group("body").strip()
        return f"\n$$\n{inner}\n$$\n"
    return _MATH_BLOCK.sub(repl, body)


def _rewrite_directive_blocks(body: str) -> str:
    """Convert ```{directive}` blocks to pandoc fenced_divs.

    The fenced_div form keeps the inner content as markdown so math,
    links, images, etc. are still parsed correctly. Pandoc renders a
    fenced_div as `#+begin_<class> ... #+end_<class>` in org.
    """
    def repl(m: re.Match) -> str:
        name = m.group("name")
        arg = (m.group("arg") or "").strip()
        opts = m.group("opts") or ""
        body = m.group("body").rstrip()
        # Extract any `:class: foo` from the options into an extra class.
        extra_class = ""
        class_m = re.search(r":class:\s*(.+)", opts)
        if class_m:
            extra_class = " " + " ".join(
                "." + c.strip() for c in re.split(r"[,\s]+", class_m.group(1)) if c.strip()
            )
        header = ""
        if arg:
            header = f"**{arg}**\n\n"
        return f"\n::: {{.{name}{extra_class}}}\n{header}{body}\n:::\n"
    return _DIRECTIVE_BLOCK.sub(repl, body)
