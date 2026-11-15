"""Top-level orchestration.

Given a course directory and a format, run:
  parser → asset collect/copy → pandoc convert → link rewrite → wrap → write.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import assets as assets_mod
from . import frontmatter, index_gen, links, mathconv, myst, sections
from .ids import IdAllocator
from .model import CourseMeta, Page, PageKind, ParsedCourse
from .parsers import autodetect, get_parser
from .readme import load_meta
from .slug import format_assignment_filename, format_lecture_filename
from .writer import StagedWriter


def _chain_pages(pages: list[Page]) -> None:
    """Fill PREV/NEXT ids on an ordered page list."""
    lectures = [p for p in pages if p.kind in (PageKind.LECTURE, PageKind.OWN_NOTES)]
    assignments = [p for p in pages if p.kind == PageKind.ASSIGNMENT]
    for group in (lectures, assignments):
        group.sort(key=lambda p: p.number)
        for i, p in enumerate(group):
            p.prev_id = group[i - 1].org_id if i > 0 else None
            p.next_id = group[i + 1].org_id if i < len(group) - 1 else None


def _subdir_for(page: Page) -> str:
    if page.kind == PageKind.ASSIGNMENT:
        return "assignments"
    if page.kind == PageKind.SUPPLEMENTARY:
        return "supplementary"
    return "lectures"


def _filename_for(page: Page, meta: CourseMeta) -> str:
    if page.kind == PageKind.ASSIGNMENT:
        return format_assignment_filename(meta.short, page.number)
    if page.kind == PageKind.SUPPLEMENTARY:
        return f"supp-{page.slug}.org"
    return format_lecture_filename(meta.short, page.number, page.slug)


def convert_course(
    course_dir: Path,
    *,
    fmt: Optional[str] = None,
    math_format: str = "latex",
    short_override: Optional[str] = None,
    name_override: Optional[str] = None,
    exclude: Optional[list[str]] = None,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:

    """Run the full pipeline on one course."""
    course_dir = course_dir.resolve()
    fmt = fmt or autodetect(course_dir)
    target_subdir = f"org-{math_format}"
    if verbose:
        print(f"format: {fmt} | math: {math_format} -> {target_subdir}/")

    meta = load_meta(course_dir, override_short=short_override, override_name=name_override)
    if verbose:
        print(f"meta: name={meta.name!r} short={meta.short!r} domain={meta.domain!r}")

    parser_cls = get_parser(fmt)
    parser = parser_cls()
    parser_kwargs = {}
    if exclude is not None:
        parser_kwargs["exclude"] = exclude
    try:
        parsed = parser.discover(course_dir, meta, **parser_kwargs)
    except TypeError:
        parsed = parser.discover(course_dir, meta)
    pandoc_from_fmt = parser.pandoc_from_fmt
    if verbose:
        print(f"parsed {len(parsed.pages)} page(s)")

    if not parsed.pages:
        raise RuntimeError(f"parser {fmt!r} found no pages in {course_dir}")

    _chain_pages(parsed.pages)

    allocator = IdAllocator(meta.short, reproducible=True)
    registry = assets_mod.AssetRegistry(allocator)

    page_lookups: dict[int, dict[str, assets_mod.Asset]] = {}

    is_markdown = pandoc_from_fmt.startswith("markdown")
    if is_markdown:
        for p in parsed.pages:
            p.body = myst.rewrite_html_images(p.body)
            p.body = myst.rewrite_html_headings(p.body)
            p.body = myst.normalise_spaced_math(p.body)

    for p in parsed.pages:
        page_dir = p.source_path.parent
        lookup: dict[str, assets_mod.Asset] = {}
        for alt, raw in assets_mod.collect_from_markdown(p.body):
            asset = registry.allocate(raw, page_dir, alt)
            if asset is not None:
                lookup[assets_mod._normalise_rel(raw)] = asset
        page_lookups[id(p)] = lookup

    good: list[Page] = []
    for p in parsed.pages:
        try:
            p.body = mathconv.convert(
                p.body,
                from_fmt=pandoc_from_fmt,
                math_format=math_format,
            )
            good.append(p)
        except RuntimeError as e:
            msg = str(e).splitlines()[0] if str(e) else "pandoc failed"
            print(f"  skip {p.source_path.name}: {msg}")
    parsed.pages = good
    if not parsed.pages:
        raise RuntimeError("every page failed to convert")

    for p in parsed.pages:
        page_dir = p.source_path.parent
        for alt, raw in assets_mod.collect_from_org(p.body):
            rel = assets_mod._normalise_rel(raw)
            if rel in page_lookups[id(p)]:
                continue
            asset = registry.allocate(raw, page_dir, alt)
            if asset is not None:
                page_lookups[id(p)][rel] = asset
        p.body = assets_mod.rewrite_in_org(p.body, page_lookups[id(p)])

    lookup = links.build_lookup(parsed.pages)
    for p in parsed.pages:
        p.body = links.rewrite(p.body, lookup)

    writer = StagedWriter(course_dir, target_subdir=target_subdir)
    staging = writer.prepare()
    if verbose:
        print(f"staging dir: {staging}")

    prov = provenance.collect(course_dir)

    for p in parsed.pages:
        filename = _filename_for(p, meta)
        subdir = _subdir_for(p)
        raw_page = frontmatter.emit(p, meta) + "\n" + sections.wrap(p, p.body)
        full = provenance.inject_page_properties(raw_page, prov)
        writer.write(f"{subdir}/{filename}", full)

    index_body = index_gen.build(meta, parsed.pages) + "\n" + provenance.render_org_section(prov)
    writer.write("index.org", index_body)

    attachments_dir = staging / assets_mod.ATTACHMENTS_SUBDIR
    registry.copy_all(attachments_dir)
    code_dir = staging / "assets" / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / ".gitkeep").write_text("")

    _self_check(parsed, writer.staging_dir)

    committed = writer.commit(force=force, dry_run=dry_run)
    if committed:
        print(f"wrote {committed} ({len(parsed.pages)} pages, {len(registry.by_abs)} assets)")


def _self_check(parsed: ParsedCourse, staging: Path) -> None:
    import re
    problems: list[str] = []
    ids = {p.org_id for p in parsed.pages}
    id_link = re.compile(r"\[\[id:([0-9a-f-]+)")
    attach_link = re.compile(r"\[\[attachment:([^\]]+)\]\]")
    attachments_dir = staging / "assets" / "attachments"
    attachment_files = {p.name for p in attachments_dir.iterdir()} if attachments_dir.exists() else set()

    for p in parsed.pages:
        for m in id_link.finditer(p.body):
            if m.group(1) not in ids:
                problems.append(f"{p.source_path.name}: unknown id link {m.group(1)}")
        for m in attach_link.finditer(p.body):
            if m.group(1) not in attachment_files:
                problems.append(f"{p.source_path.name}: unknown attachment {m.group(1)}")

    if problems:
        print(f"self-check: {len(problems)} problem(s)")
        for pb in problems[:20]:
            print(f"  {pb}")
