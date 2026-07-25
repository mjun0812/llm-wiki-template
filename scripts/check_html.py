#!/usr/bin/env python3
"""Lint generated HTML wiki pages under html/.

Rules:
    HTML001  external-resource        resource is loaded from an external URL
    HTML002  script-forbidden         script element is used
    HTML003  iframe-forbidden         iframe element is used
    HTML004  stylesheet-mismatch      stylesheet is not exactly html/assets/style.css
    HTML005  missing-wiki-source      wiki-source meta is missing or malformed
    HTML006  missing-link-target      local link target does not exist
    HTML007  unexpanded-placeholder   {{...}} template placeholder remains
    HTML008  stale-page               wiki-source updated differs from the current
                                      frontmatter updated (warning only)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

RESOURCE_TAGS = {
    "audio",
    "embed",
    "iframe",
    "img",
    "link",
    "object",
    "script",
    "source",
    "video",
}
URL_ATTRIBUTES = ("src", "href", "poster", "data")
STYLESHEET_PATH = Path("html/assets/style.css")
WIKI_SOURCE_PATTERN = re.compile(r"^(?P<path>\S+) (?P<date>\d{4}-\d{2}-\d{2})$")
PLACEHOLDER_PATTERN = re.compile(r"\{\{[^}\n]*\}\}")
FRONTMATTER_UPDATED_PATTERN = re.compile(
    r"^updated:\s*\"?(\d{4}-\d{2}-\d{2})\"?\s*$", re.MULTILINE
)
RULES_TABLE = (
    "HTML001  external-resource        resource is loaded from an external URL\n"
    "HTML002  script-forbidden         script element is used\n"
    "HTML003  iframe-forbidden         iframe element is used\n"
    "HTML004  stylesheet-mismatch      stylesheet is not exactly html/assets/style.css\n"
    "HTML005  missing-wiki-source      wiki-source meta is missing or malformed\n"
    "HTML006  missing-link-target      local link target does not exist\n"
    "HTML007  unexpanded-placeholder   {{...}} template placeholder remains\n"
    "HTML008  stale-page               wiki-source updated differs (warning only)"
)


@dataclass(frozen=True)
class Element:
    """One HTML start tag occurrence.

    Attributes:
        tag: Lowercase tag name.
        attrs: Attribute mapping. Missing values are stored as empty strings.
        line: 1-based line number of the start tag.
    """

    tag: str
    attrs: dict[str, str]
    line: int


@dataclass(frozen=True)
class Diagnostic:
    """A single HTML lint finding.

    Attributes:
        path: HTML file path that the diagnostic refers to.
        line: 1-based line number to surface in the output.
        code: Rule code such as ``HTML001``.
        message: Human-readable message in Japanese.
        warning: Whether the finding is reported without failing the check.
    """

    path: Path
    line: int
    code: str
    message: str
    warning: bool = False


class ElementCollector(HTMLParser):
    """Collect start tags with their attributes and line numbers."""

    def __init__(self) -> None:
        """Initialize the collector with an empty element list."""
        super().__init__()
        self.elements: list[Element] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record a start tag occurrence.

        Args:
            tag: Lowercase tag name reported by the parser.
            attrs: Attribute pairs reported by the parser.
        """
        line = self.getpos()[0]
        self.elements.append(
            Element(
                tag=tag,
                attrs={name: value or "" for name, value in attrs},
                line=line,
            )
        )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record a self-closing tag occurrence.

        Args:
            tag: Lowercase tag name reported by the parser.
            attrs: Attribute pairs reported by the parser.
        """
        self.handle_starttag(tag, attrs)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument vector to parse. ``None`` uses ``sys.argv[1:]``.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Lint generated HTML wiki pages.",
        epilog=RULES_TABLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "Files or directories to lint. Directories are walked recursively for "
            "*.html. Defaults to html/ when no path is given."
        ),
    )
    return parser.parse_args(argv)


def collect_targets(paths: list[Path]) -> list[Path]:
    """Expand path arguments into a deduplicated list of HTML files.

    Args:
        paths: Files and/or directories from the command line. An empty list
            falls back to ``Path("html")``.

    Returns:
        Sorted, deduplicated HTML file paths.
    """
    if not paths:
        paths = [Path("html")]

    collected: set[Path] = set()
    for entry in paths:
        if entry.is_file() and entry.suffix == ".html":
            collected.add(entry)
        elif entry.is_dir():
            collected.update(p for p in entry.rglob("*.html") if p.is_file())
    return sorted(collected)


def is_external_url(target: str) -> bool:
    """Return whether a URL points outside the repository.

    Args:
        target: Raw attribute value such as ``href`` or ``src``.

    Returns:
        ``True`` for absolute URLs, protocol-relative URLs, and data URIs.
    """
    if target.startswith("//"):
        return True
    parsed = urlparse(target)
    return bool(parsed.scheme)


def line_number_of(text: str, needle: str) -> int:
    """Return the 1-based line number of the first occurrence of a substring.

    Args:
        text: Full file text.
        needle: Substring to locate.

    Returns:
        1-based line number, or 1 when the substring is not found.
    """
    index = text.find(needle)
    if index == -1:
        return 1
    return text.count("\n", 0, index) + 1


def frontmatter_updated(path: Path) -> str | None:
    """Read the frontmatter ``updated`` date from a Markdown file.

    Args:
        path: Markdown file path.

    Returns:
        The ``updated`` value in ``YYYY-MM-DD`` form, or ``None`` when the file
        has no parseable frontmatter ``updated``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    match = FRONTMATTER_UPDATED_PATTERN.search(text[:end])
    return match.group(1) if match is not None else None


def check_forbidden_elements(path: Path, elements: list[Element]) -> list[Diagnostic]:
    """Check script/iframe usage and external resource loading.

    Args:
        path: HTML file path.
        elements: Collected start tags.

    Returns:
        Diagnostics for HTML001, HTML002, and HTML003.
    """
    diagnostics: list[Diagnostic] = []
    for element in elements:
        if element.tag == "script":
            diagnostics.append(
                Diagnostic(path, element.line, "HTML002", "scriptタグは使用できません")
            )
        if element.tag == "iframe":
            diagnostics.append(
                Diagnostic(path, element.line, "HTML003", "iframeタグは使用できません")
            )
        if element.tag not in RESOURCE_TAGS:
            continue
        for attribute in URL_ATTRIBUTES:
            target = element.attrs.get(attribute, "")
            if target and is_external_url(target):
                diagnostics.append(
                    Diagnostic(
                        path,
                        element.line,
                        "HTML001",
                        f"外部リソースを読み込んでいます: `{target}`",
                    )
                )
    return diagnostics


def check_stylesheets(path: Path, elements: list[Element]) -> list[Diagnostic]:
    """Check that the page references exactly the shared stylesheet.

    Args:
        path: HTML file path.
        elements: Collected start tags.

    Returns:
        Diagnostics for HTML004.
    """
    stylesheets = [
        element
        for element in elements
        if element.tag == "link"
        and "stylesheet" in element.attrs.get("rel", "").lower()
        and not is_external_url(element.attrs.get("href", ""))
    ]
    diagnostics: list[Diagnostic] = []
    expected = STYLESHEET_PATH.resolve()
    for element in stylesheets:
        href = unquote(element.attrs.get("href", ""))
        resolved = (path.parent / href).resolve()
        if resolved != expected:
            diagnostics.append(
                Diagnostic(
                    path,
                    element.line,
                    "HTML004",
                    f"stylesheetは共通CSSだけを参照してください: `{href}`",
                )
            )
    if not stylesheets:
        diagnostics.append(
            Diagnostic(
                path,
                1,
                "HTML004",
                "共通CSS (html/assets/style.css) への stylesheet がありません",
            )
        )
    return diagnostics


def check_wiki_source_meta(
    path: Path, elements: list[Element]
) -> tuple[list[Diagnostic], list[tuple[str, str, int]]]:
    """Check wiki-source meta declarations.

    Args:
        path: HTML file path.
        elements: Collected start tags.

    Returns:
        Tuple of ``(diagnostics, sources)`` where ``sources`` holds
        ``(repo_relative_path, updated, line)`` for each valid declaration.
    """
    metas = [
        element
        for element in elements
        if element.tag == "meta" and element.attrs.get("name") == "wiki-source"
    ]
    diagnostics: list[Diagnostic] = []
    sources: list[tuple[str, str, int]] = []
    for element in metas:
        content = element.attrs.get("content", "")
        match = WIKI_SOURCE_PATTERN.match(content)
        if match is None:
            diagnostics.append(
                Diagnostic(
                    path,
                    element.line,
                    "HTML005",
                    "wiki-source metaは `<repo相対パス> <YYYY-MM-DD>` 形式にしてください: "
                    f"`{content}`",
                )
            )
            continue
        sources.append((match.group("path"), match.group("date"), element.line))
    if not metas and path.name != "index.html":
        diagnostics.append(
            Diagnostic(
                path,
                1,
                "HTML005",
                '由来meta (`<meta name="wiki-source" ...>`) がありません',
            )
        )
    return diagnostics, sources


def check_link_targets(path: Path, elements: list[Element]) -> list[Diagnostic]:
    """Check that local link and resource targets exist.

    Args:
        path: HTML file path.
        elements: Collected start tags.

    Returns:
        Diagnostics for HTML006.
    """
    diagnostics: list[Diagnostic] = []
    for element in elements:
        for attribute in URL_ATTRIBUTES:
            target = element.attrs.get(attribute, "")
            if not target or is_external_url(target) or target.startswith("#"):
                continue
            local_path = unquote(target).split("#", 1)[0]
            if not local_path:
                continue
            if not (path.parent / local_path).exists():
                diagnostics.append(
                    Diagnostic(
                        path,
                        element.line,
                        "HTML006",
                        f"リンク先が存在しません: `{target}`",
                    )
                )
    return diagnostics


def check_staleness(
    path: Path, sources: list[tuple[str, str, int]]
) -> list[Diagnostic]:
    """Check wiki-source declarations against the current Markdown files.

    Args:
        path: HTML file path.
        sources: Valid ``(repo_relative_path, updated, line)`` declarations.

    Returns:
        Diagnostics for HTML006 (missing source file) and HTML008 (stale).
    """
    diagnostics: list[Diagnostic] = []
    for source_path_text, declared_updated, line in sources:
        source_path = Path(source_path_text)
        if not source_path.exists():
            diagnostics.append(
                Diagnostic(
                    path,
                    line,
                    "HTML006",
                    f"wiki-sourceの参照先が存在しません: `{source_path_text}`",
                )
            )
            continue
        current_updated = frontmatter_updated(source_path)
        if current_updated is not None and current_updated != declared_updated:
            diagnostics.append(
                Diagnostic(
                    path,
                    line,
                    "HTML008",
                    f"参照先が更新されています: `{source_path_text}` "
                    f"(生成時 {declared_updated} → 現在 {current_updated})。"
                    "html-maintenance での再生成を検討してください",
                    warning=True,
                )
            )
    return diagnostics


def check_placeholders(path: Path, text: str) -> list[Diagnostic]:
    """Check for unexpanded template placeholders.

    Args:
        path: HTML file path.
        text: Full file text.

    Returns:
        Diagnostics for HTML007.
    """
    return [
        Diagnostic(
            path,
            line_number_of(text, match.group(0)),
            "HTML007",
            f"テンプレートのプレースホルダーが残っています: `{match.group(0)}`",
        )
        for match in PLACEHOLDER_PATTERN.finditer(text)
    ]


def check_file(path: Path) -> list[Diagnostic]:
    """Check one HTML file against all rules.

    Args:
        path: HTML file path.

    Returns:
        Diagnostics in rule order. Warnings are included with ``warning=True``.
    """
    text = path.read_text(encoding="utf-8")
    collector = ElementCollector()
    collector.feed(text)
    elements = collector.elements

    diagnostics = check_forbidden_elements(path, elements)
    diagnostics += check_stylesheets(path, elements)
    meta_diagnostics, sources = check_wiki_source_meta(path, elements)
    diagnostics += meta_diagnostics
    diagnostics += check_link_targets(path, elements)
    diagnostics += check_staleness(path, sources)
    diagnostics += check_placeholders(path, text)
    return diagnostics


def main(argv: list[str] | None = None) -> int:
    """Run the HTML checker.

    Args:
        argv: Argument vector. ``None`` uses ``sys.argv[1:]``.

    Returns:
        Exit code: ``0`` on success or warnings only, ``1`` when errors remain.
    """
    args = parse_args(argv)
    targets = collect_targets(args.paths)
    diagnostics = [
        diagnostic for target in targets for diagnostic in check_file(target)
    ]
    diagnostics.sort(key=lambda diagnostic: (str(diagnostic.path), diagnostic.line))
    errors = [diagnostic for diagnostic in diagnostics if not diagnostic.warning]
    warnings = [diagnostic for diagnostic in diagnostics if diagnostic.warning]

    for diagnostic in diagnostics:
        prefix = "warning: " if diagnostic.warning else ""
        print(
            f"{diagnostic.path}:{diagnostic.line}: "
            f"[{diagnostic.code}] {prefix}{diagnostic.message}",
            file=sys.stderr,
        )

    if errors:
        print(f"Found {len(errors)} error(s).", file=sys.stderr)
        return 1
    if warnings:
        print(f"Found {len(warnings)} warning(s).", file=sys.stderr)
    print(f"All html checks passed ({len(targets)} file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
