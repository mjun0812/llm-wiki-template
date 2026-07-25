#!/usr/bin/env python3
"""Lint links inside wiki/ and the index coverage of wiki pages.

Rules:
    WIKI001  unindexed-page          wiki page is not linked from wiki/index.md
    WIKI002  missing-link-target     local link target does not exist
    WIKI003  emphasized-link-label   link label contains emphasis produced from filename underscores
    WIKI004  unreferenced-source     source note is not referenced from any wiki page
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

INDEX_FILENAME = "index.md"
CHANGELOG_FILENAME = "changelog.md"
MARKDOWN_LINK_PATTERN = re.compile(
    r"(?<!!)\[(?P<label>(?:[^\[\]\n]|\\.)*)\]"
    r"\((?:<(?P<angle>[^>\n]+)>|(?P<plain>[^)\s\n]+))\)"
)
EMPHASIS_PATTERN = re.compile(r"\*\*|\*|\\_")
RULES_TABLE = (
    "WIKI001  unindexed-page          wiki page is not linked from wiki/index.md\n"
    "WIKI002  missing-link-target     local link target does not exist\n"
    "WIKI003  emphasized-link-label   link label contains emphasis produced from filename underscores\n"
    "WIKI004  unreferenced-source     source note is not referenced from any wiki page"
)


@dataclass(frozen=True)
class Link:
    """One Markdown link occurrence.

    Attributes:
        line: 1-based line number.
        label: Link label text as written in the Markdown source.
        target: Link target text with any angle brackets removed.
    """

    line: int
    label: str
    target: str


@dataclass(frozen=True)
class Diagnostic:
    """A single lint finding.

    Attributes:
        path: Markdown file path that the diagnostic refers to.
        line: 1-based line number to surface in the output.
        code: Rule code (e.g. ``WIKI001``).
        message: Human-readable message in Japanese.
    """

    path: Path
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class FileLinks:
    """Links collected from one Markdown file.

    Attributes:
        path: Markdown file the links were read from.
        links: Every Markdown link occurrence in source order.
    """

    path: Path
    links: list[Link]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument vector to parse. ``None`` uses ``sys.argv[1:]``.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Lint links inside wiki/ and the index coverage of wiki pages.",
        epilog=RULES_TABLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "Files or directories to lint. Directories are walked recursively for "
            "*.md. Defaults to wiki/ when no path is given."
        ),
    )
    parser.add_argument(
        "--wiki",
        type=Path,
        default=Path("wiki"),
        help="Wiki root directory that holds index.md.",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=Path("sources"),
        help="Source root directory checked by --check-unreferenced.",
    )
    parser.add_argument(
        "--check-unreferenced",
        action="store_true",
        help=(
            "Also report source notes that no wiki page links to (WIKI004). "
            "Enable this only when the wiki keeps a reference map covering every note."
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="Number of worker threads. Defaults to the Python default for ThreadPoolExecutor.",
    )
    return parser.parse_args(argv)


def is_external_target(target: str) -> bool:
    """Report whether a link target points outside the repository.

    Args:
        target: Link target text.

    Returns:
        ``True`` for URLs, mail links and pure in-page anchors.
    """
    if target.startswith("#"):
        return True
    parsed = urlparse(target)
    return bool(parsed.scheme) or bool(parsed.netloc)


def strip_fragment(target: str) -> str:
    """Remove a trailing ``#fragment`` from a link target.

    Args:
        target: Link target text.

    Returns:
        Target text without its fragment part.
    """
    return target.split("#", 1)[0]


def find_links(text: str) -> list[Link]:
    """Collect Markdown links from file text.

    Image links are skipped because ``check_image_links.py`` owns them.

    Args:
        text: Full Markdown file text.

    Returns:
        Link occurrences in source order.
    """
    links: list[Link] = []
    for match in MARKDOWN_LINK_PATTERN.finditer(text):
        target = match.group("angle") or match.group("plain")
        links.append(
            Link(
                line=text.count("\n", 0, match.start()) + 1,
                label=match.group("label"),
                target=target.strip(),
            )
        )
    return links


def read_links(path: Path) -> FileLinks:
    """Read one Markdown file and collect its links.

    Args:
        path: Markdown file path.

    Returns:
        The links found in the file.
    """
    return FileLinks(path=path, links=find_links(path.read_text(encoding="utf-8")))


def resolve_target(markdown_path: Path, target: str) -> Path | None:
    """Resolve a local link target against the file that contains it.

    Percent-encoded targets are retried after decoding, because links copied
    from an editor often keep the encoded form of a Japanese filename.

    Args:
        markdown_path: Markdown file holding the link.
        target: Link target text without its fragment.

    Returns:
        The existing path the target points to, or ``None`` when nothing matches.
    """
    for text in (target, unquote(target)):
        if not text:
            continue
        candidate = markdown_path.parent / text
        try:
            if candidate.exists():
                return candidate.resolve()
        except OSError:
            # A decoded name can exceed the filesystem limit; treat it as a miss.
            continue
    return None


def check_link_targets(file_links: FileLinks) -> list[Diagnostic]:
    """Check that every local link target of one file exists (WIKI002, WIKI003).

    Args:
        file_links: Links collected from one Markdown file.

    Returns:
        Diagnostics for the file. Empty when every link passes.
    """
    diagnostics: list[Diagnostic] = []
    for link in file_links.links:
        if is_external_target(link.target):
            continue
        target = strip_fragment(link.target)
        if not target:
            continue
        resolved = resolve_target(file_links.path, target)
        if resolved is None:
            diagnostics.append(
                Diagnostic(
                    path=file_links.path,
                    line=link.line,
                    code="WIKI002",
                    message=f"リンク先 `{target}` が存在しません",
                )
            )
            continue
        if (
            resolved.suffix == ".md"
            and "_" in resolved.stem
            and EMPHASIS_PATTERN.search(link.label)
        ):
            diagnostics.append(
                Diagnostic(
                    path=file_links.path,
                    line=link.line,
                    code="WIKI003",
                    message=(
                        "リンクテキストがMarkdownの強調として解釈されています。"
                        "ファイル名のアンダースコアはスペースに置き換えてください"
                    ),
                )
            )
    return diagnostics


def check_index_coverage(
    wiki_root: Path, index_path: Path, index_links: list[Link]
) -> list[Diagnostic]:
    """Check that every wiki page is linked from the index (WIKI001).

    ``index.md`` and ``changelog.md`` are exempt because they are the index and
    the history log themselves.

    Args:
        wiki_root: Wiki root directory.
        index_path: Path to the wiki index file.
        index_links: Links collected from the index file.

    Returns:
        One diagnostic per wiki page missing from the index.
    """
    indexed: set[Path] = set()
    for link in index_links:
        if is_external_target(link.target):
            continue
        target = strip_fragment(link.target)
        if not target:
            continue
        resolved = resolve_target(index_path, target)
        if resolved is not None:
            indexed.add(resolved)

    diagnostics: list[Diagnostic] = []
    for page in sorted(wiki_root.rglob("*.md")):
        if page.name in {INDEX_FILENAME, CHANGELOG_FILENAME}:
            continue
        if page.resolve() not in indexed:
            diagnostics.append(
                Diagnostic(
                    path=page,
                    line=1,
                    code="WIKI001",
                    message=f"`{index_path}` からリンクされていません",
                )
            )
    return diagnostics


def check_unreferenced_sources(
    sources_root: Path, wiki_links: list[FileLinks]
) -> list[Diagnostic]:
    """Check that every source note is referenced from the wiki (WIKI004).

    Args:
        sources_root: Source root directory.
        wiki_links: Links collected from every wiki page.

    Returns:
        One diagnostic per source note that no wiki page links to.
    """
    referenced: set[Path] = set()
    for file_links in wiki_links:
        for link in file_links.links:
            if is_external_target(link.target):
                continue
            target = strip_fragment(link.target)
            if not target:
                continue
            resolved = resolve_target(file_links.path, target)
            if resolved is not None:
                referenced.add(resolved)

    diagnostics: list[Diagnostic] = []
    for note in sorted(sources_root.rglob("*.md")):
        if note.resolve() not in referenced:
            diagnostics.append(
                Diagnostic(
                    path=note,
                    line=1,
                    code="WIKI004",
                    message="どのWikiページからも参照されていません",
                )
            )
    return diagnostics


def collect_targets(paths: list[Path], default_root: Path) -> list[Path]:
    """Expand path arguments into a deduplicated list of Markdown files.

    Args:
        paths: Files and/or directories from the command line. An empty list
            falls back to ``default_root``.
        default_root: Directory used when no path argument is given.

    Returns:
        Sorted, deduplicated Markdown file paths.
    """
    if not paths:
        paths = [default_root]

    collected: set[Path] = set()
    for entry in paths:
        if entry.is_file():
            collected.add(entry)
        elif entry.is_dir():
            collected.update(p for p in entry.rglob("*.md") if p.is_file())
    return sorted(collected)


def run_checks(
    targets: list[Path],
    wiki_root: Path,
    sources_root: Path,
    check_unreferenced: bool,
    jobs: int | None = None,
) -> list[Diagnostic]:
    """Run every rule and collect diagnostics.

    Args:
        targets: Markdown files to check for link targets.
        wiki_root: Wiki root directory.
        sources_root: Source root directory.
        check_unreferenced: Whether to run WIKI004.
        jobs: Worker thread count. ``None`` uses the ThreadPoolExecutor default.

    Returns:
        All diagnostics, sorted by ``(path, line, code)``.
    """
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        file_links = list(executor.map(read_links, targets))

    diagnostics: list[Diagnostic] = []
    for links in file_links:
        diagnostics.extend(check_link_targets(links))

    index_path = wiki_root / INDEX_FILENAME
    if index_path.is_file():
        diagnostics.extend(
            check_index_coverage(wiki_root, index_path, read_links(index_path).links)
        )

    if check_unreferenced and sources_root.is_dir():
        wiki_pages = collect_targets([], wiki_root)
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            all_wiki_links = list(executor.map(read_links, wiki_pages))
        diagnostics.extend(check_unreferenced_sources(sources_root, all_wiki_links))

    diagnostics.sort(key=lambda d: (str(d.path), d.line, d.code))
    return diagnostics


def main(argv: list[str] | None = None) -> int:
    """Run the linter.

    Args:
        argv: Argument vector. ``None`` uses ``sys.argv[1:]``.

    Returns:
        Exit code: ``0`` on success, ``1`` when any diagnostic was emitted.
    """
    args = parse_args(argv)
    targets = collect_targets(args.paths, args.wiki)
    diagnostics = run_checks(
        targets,
        wiki_root=args.wiki,
        sources_root=args.sources,
        check_unreferenced=args.check_unreferenced,
        jobs=args.jobs,
    )

    if not diagnostics:
        print(f"All checks passed ({len(targets)} file(s)).")
        return 0

    for diagnostic in diagnostics:
        print(
            f"{diagnostic.path}:{diagnostic.line}: [{diagnostic.code}] {diagnostic.message}",
            file=sys.stderr,
        )
    print(f"Found {len(diagnostics)} error(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
