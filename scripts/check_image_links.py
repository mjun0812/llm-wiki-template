#!/usr/bin/env python3
"""Lint local image links and optionally normalize or remove broken links.

Rules:
    IMG001  missing-image               local image link target does not exist
    IMG002  noncanonical-image-target   local image link target is URL-encoded or contains spaces
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
}
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]\n]*\]\((?P<target>[^)\n]+)\)")
OBSIDIAN_IMAGE_PATTERN = re.compile(r"!\[\[(?P<target>[^\]\n]+)\]\]")
RULES_TABLE = (
    "IMG001  missing-image               local image link target does not exist\n"
    "IMG002  noncanonical-image-target   local image link target is URL-encoded or contains spaces"
)
LinkKind = Literal["markdown", "obsidian"]


@dataclass(frozen=True)
class ImageLink:
    """One Markdown image link occurrence.

    Attributes:
        start: 0-based start offset of the full image-link syntax.
        end: 0-based end offset of the full image-link syntax.
        line: 1-based line number.
        raw_target: Raw link target text from the Markdown source.
        target: Normalized local target path text.
        target_start: 0-based start offset of the raw target text.
        target_end: 0-based end offset of the raw target text.
        kind: Image link syntax kind.
    """

    start: int
    end: int
    line: int
    raw_target: str
    target: str
    target_start: int
    target_end: int
    kind: LinkKind


@dataclass(frozen=True)
class Diagnostic:
    """A single image-link lint finding.

    Attributes:
        path: Markdown file path that the diagnostic refers to.
        line: 1-based line number to surface in the output.
        code: Rule code such as ``IMG001``.
        message: Human-readable message in Japanese.
    """

    path: Path
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class FileResult:
    """Image-link check result for one Markdown file.

    Attributes:
        diagnostics: Diagnostics that remain after optional fixes.
        fixed: Whether the file was rewritten by ``--fix``.
        normalized_links: Number of image link targets normalized by ``--fix``.
        renamed_files: Number of image files renamed by ``--fix``.
        removed_links: Number of broken image links removed by ``--fix``.
    """

    diagnostics: list[Diagnostic]
    fixed: bool
    normalized_links: int = 0
    renamed_files: int = 0
    removed_links: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument vector to parse. ``None`` uses ``sys.argv[1:]``.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Lint local image links in Markdown files.",
        epilog=RULES_TABLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "Files or directories to lint. Directories are walked recursively for "
            "*.md. Defaults to sources/ when no path is given."
        ),
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            "URL-decode local image links, replace spaces with underscores in "
            "links and image filenames, and remove links whose targets still do not exist."
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="Number of worker threads. Defaults to the Python default for ThreadPoolExecutor.",
    )
    return parser.parse_args(argv)


def collect_targets(paths: list[Path]) -> list[Path]:
    """Expand path arguments into a deduplicated list of Markdown files.

    Args:
        paths: Files and/or directories from the command line. An empty list
            falls back to ``Path("sources")``.

    Returns:
        Sorted, deduplicated Markdown file paths.
    """
    if not paths:
        paths = [Path("sources")]

    collected: set[Path] = set()
    for entry in paths:
        if entry.is_file() and entry.suffix == ".md":
            collected.add(entry)
        elif entry.is_dir():
            collected.update(p for p in entry.rglob("*.md") if p.is_file())
    return sorted(collected)


def line_number_at(text: str, offset: int) -> int:
    """Calculate a 1-based line number for a character offset.

    Args:
        text: Full Markdown text.
        offset: 0-based character offset.

    Returns:
        1-based line number.
    """
    return text.count("\n", 0, offset) + 1


def strip_fragment(target: str) -> str:
    """Remove Markdown/Obsidian fragment suffixes from a target.

    Args:
        target: Link target without title text.

    Returns:
        Target path without ``#...``.
    """
    return target.split("#", 1)[0]


def normalize_markdown_target(raw_target: str) -> str:
    """Normalize a Markdown image target for filesystem lookup.

    Args:
        raw_target: Raw target text from ``![](...)``.

    Returns:
        Local target path text. Empty when no local target can be inferred.
    """
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    else:
        title_match = re.match(r"(?P<path>\\S+)\\s+['\"(].*", target)
        if title_match is not None:
            target = title_match.group("path")
    return strip_fragment(target)


def normalize_obsidian_target(raw_target: str) -> str:
    """Normalize an Obsidian image target for filesystem lookup.

    Args:
        raw_target: Raw target text from ``![[...]]``.

    Returns:
        Local target path text without aliases or fragments.
    """
    target = raw_target.split("|", 1)[0].strip()
    return strip_fragment(target)


def is_external_target(target: str) -> bool:
    """Return whether a target points outside the local filesystem.

    Args:
        target: Normalized link target.

    Returns:
        ``True`` for URLs, anchors, mail links, and data URIs.
    """
    if not target or target.startswith("#"):
        return True
    parsed = urlparse(target)
    return bool(parsed.scheme and parsed.scheme not in {"file"})


def is_image_target(target: str) -> bool:
    """Return whether a target appears to point to an image file.

    Args:
        target: Normalized link target.

    Returns:
        ``True`` when the target suffix is a known image extension.
    """
    return Path(unquote(target)).suffix.lower() in IMAGE_EXTENSIONS


def normalize_image_target(target: str) -> str:
    """URL-decode an image target and replace spaces with underscores.

    Args:
        target: Local image target without a fragment.

    Returns:
        Canonical target text for Markdown source and filesystem lookup.
    """
    return unquote(target).replace(" ", "_")


def target_needs_normalization(target: str) -> bool:
    """Return whether an image target violates the canonical target rule.

    Args:
        target: Local image target without a fragment.

    Returns:
        ``True`` when URL-decoding or space replacement would change the target.
    """
    return target != normalize_image_target(target)


def find_image_links(text: str) -> list[ImageLink]:
    """Find Markdown and Obsidian image links in text.

    Args:
        text: Markdown source text.

    Returns:
        Image link occurrences in source order.
    """
    links: list[ImageLink] = []
    for match in MARKDOWN_IMAGE_PATTERN.finditer(text):
        target = normalize_markdown_target(match.group("target"))
        if is_external_target(target) or not is_image_target(target):
            continue
        links.append(
            ImageLink(
                start=match.start(),
                end=match.end(),
                line=line_number_at(text, match.start()),
                raw_target=match.group("target"),
                target=target,
                target_start=match.start("target"),
                target_end=match.end("target"),
                kind="markdown",
            )
        )

    for match in OBSIDIAN_IMAGE_PATTERN.finditer(text):
        target = normalize_obsidian_target(match.group("target"))
        if is_external_target(target) or not is_image_target(target):
            continue
        links.append(
            ImageLink(
                start=match.start(),
                end=match.end(),
                line=line_number_at(text, match.start()),
                raw_target=match.group("target"),
                target=target,
                target_start=match.start("target"),
                target_end=match.end("target"),
                kind="obsidian",
            )
        )

    links.sort(key=lambda link: link.start)
    return links


def candidate_paths(markdown_path: Path, target: str) -> list[Path]:
    """Build candidate filesystem paths for one local image target.

    Args:
        markdown_path: Markdown file that contains the link.
        target: Normalized local target.

    Returns:
        Candidate paths to test for existence.
    """
    candidates: list[Path] = []
    for target_text in target_path_text_variants(target):
        target_path = Path(target_text)
        if target_path.is_absolute():
            candidates.append(target_path)
            continue

        candidates.append(markdown_path.parent / target_path)
        if len(target_path.parts) == 1:
            candidates.append(markdown_path.parent / "images" / target_path)

    deduplicated: list[Path] = []
    for candidate in candidates:
        if candidate not in deduplicated:
            deduplicated.append(candidate)
    return deduplicated


def target_path_text_variants(target: str) -> list[str]:
    """Build possible filesystem spellings for one target.

    Args:
        target: Normalized local target from Markdown source.

    Returns:
        Candidate path texts, including decoded and canonical spellings.
    """
    variants = [unquote(target), target, normalize_image_target(target)]
    deduplicated: list[str] = []
    for variant in variants:
        if variant not in deduplicated:
            deduplicated.append(variant)
    return deduplicated


def existing_target_path(markdown_path: Path, target: str) -> Path | None:
    """Return the first existing filesystem path for a local image target.

    Args:
        markdown_path: Markdown file that contains the link.
        target: Normalized local target.

    Returns:
        First matching path, or ``None`` when no candidate exists.
    """
    return next(
        (path for path in candidate_paths(markdown_path, target) if path.exists()),
        None,
    )


def target_exists(markdown_path: Path, target: str) -> bool:
    """Return whether a local image target exists for one Markdown file.

    Args:
        markdown_path: Markdown file that contains the link.
        target: Normalized local target.

    Returns:
        ``True`` when any candidate path exists.
    """
    return existing_target_path(markdown_path, target) is not None


def destination_path_for_normalized_target(
    markdown_path: Path,
    source_path: Path,
    target: str,
    normalized_target: str,
) -> Path:
    """Calculate where an existing image should move for a normalized target.

    Args:
        markdown_path: Markdown file that contains the link.
        source_path: Existing image file path.
        target: Current local image target.
        normalized_target: Canonical local image target.

    Returns:
        Destination path for the renamed image file.
    """
    target_path = Path(unquote(target))
    normalized_path = Path(normalized_target)
    if normalized_path.is_absolute():
        return normalized_path
    if len(target_path.parts) == 1:
        return source_path.parent / normalized_path.name
    return markdown_path.parent / normalized_path


def normalize_target_file(markdown_path: Path, target: str) -> bool:
    """Rename an existing image file to match the normalized target.

    Args:
        markdown_path: Markdown file that contains the link.
        target: Current local image target.

    Returns:
        ``True`` when a file was renamed.
    """
    normalized_target = normalize_image_target(target)
    if not target_needs_normalization(target):
        return False
    if any(path.exists() for path in candidate_paths(markdown_path, normalized_target)):
        return False

    source_path = existing_target_path(markdown_path, target)
    if source_path is None:
        return False

    destination_path = destination_path_for_normalized_target(
        markdown_path,
        source_path,
        target,
        normalized_target,
    )
    if source_path == destination_path:
        return False

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.rename(destination_path)
    return True


def rewrite_markdown_raw_target(raw_target: str, normalized_target: str) -> str:
    """Rewrite the path part inside a Markdown image target.

    Args:
        raw_target: Raw target text inside ``![](...)``.
        normalized_target: Canonical local image target.

    Returns:
        Raw target text with the path portion normalized.
    """
    leading = raw_target[: len(raw_target) - len(raw_target.lstrip())]
    stripped = raw_target.strip()
    trailing = raw_target[len(raw_target.rstrip()) :]

    if stripped.startswith("<"):
        closing_index = stripped.find(">")
        if closing_index != -1:
            suffix = stripped[closing_index + 1 :]
            return f"{leading}<{normalized_target}>{suffix}{trailing}"

    title_match = re.match(r"(?P<path>\S+)(?P<suffix>\s+['\"(].*)", stripped)
    if title_match is not None:
        return f"{leading}{normalized_target}{title_match.group('suffix')}{trailing}"
    return f"{leading}{normalized_target}{trailing}"


def rewrite_obsidian_raw_target(raw_target: str, normalized_target: str) -> str:
    """Rewrite the path part inside an Obsidian image target.

    Args:
        raw_target: Raw target text inside ``![[...]]``.
        normalized_target: Canonical local image target.

    Returns:
        Raw target text with aliases and fragments preserved.
    """
    target_part, alias_separator, alias = raw_target.partition("|")
    _path_part, fragment_separator, fragment = target_part.partition("#")
    fragment_text = f"{fragment_separator}{fragment}" if fragment_separator else ""
    return f"{normalized_target}{fragment_text}{alias_separator}{alias}"


def rewrite_raw_target(link: ImageLink) -> str:
    """Build normalized raw target text for one image link.

    Args:
        link: Image link occurrence.

    Returns:
        Replacement target text for the same link syntax.
    """
    normalized_target = normalize_image_target(link.target)
    if link.kind == "markdown":
        return rewrite_markdown_raw_target(link.raw_target, normalized_target)
    return rewrite_obsidian_raw_target(link.raw_target, normalized_target)


def normalize_links_and_files(
    markdown_path: Path,
    text: str,
    links: list[ImageLink],
) -> tuple[str, int, int]:
    """Normalize image link targets and matching local image filenames.

    Args:
        markdown_path: Markdown file being fixed.
        text: Original Markdown text.
        links: Image links detected in ``text``.

    Returns:
        Tuple of ``(updated_text, normalized_link_count, renamed_file_count)``.
    """
    updated = text
    normalized_links = 0
    renamed_files = 0
    for link in sorted(links, key=lambda item: item.target_start, reverse=True):
        if not target_needs_normalization(link.target):
            continue
        if normalize_target_file(markdown_path, link.target):
            renamed_files += 1
        replacement = rewrite_raw_target(link)
        updated = (
            updated[: link.target_start] + replacement + updated[link.target_end :]
        )
        normalized_links += 1
    return updated, normalized_links, renamed_files


def remove_links(text: str, links: list[ImageLink]) -> str:
    """Remove selected image-link syntaxes from Markdown text.

    Args:
        text: Original Markdown text.
        links: Image links to remove.

    Returns:
        Markdown text with the selected link syntaxes removed.
    """
    updated = text
    for link in sorted(links, key=lambda item: item.start, reverse=True):
        updated = updated[: link.start] + updated[link.end :]
    return updated


def build_diagnostics(path: Path, links: list[ImageLink]) -> list[Diagnostic]:
    """Build image-link diagnostics for one Markdown file.

    Args:
        path: Markdown file path.
        links: Image links to check.

    Returns:
        Diagnostics for noncanonical and missing local image targets.
    """
    diagnostics: list[Diagnostic] = []
    for link in links:
        normalized_target = normalize_image_target(link.target)
        if target_needs_normalization(link.target):
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=link.line,
                    code="IMG002",
                    message=(
                        "画像リンクはURL decodeし、スペースを`_`に置換してください: "
                        f"`{link.target}` -> `{normalized_target}`"
                    ),
                )
            )
        if not target_exists(path, link.target):
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=link.line,
                    code="IMG001",
                    message=f"画像リンク先が存在しません: `{link.target}`",
                )
            )
    return diagnostics


def check_file(path: Path, fix: bool = False) -> FileResult:
    """Check one Markdown file for local image-link problems.

    Args:
        path: Markdown file path.
        fix: Whether to normalize links/files and remove broken image links.

    Returns:
        Diagnostics and whether the file was rewritten.
    """
    text = path.read_text(encoding="utf-8")

    if not fix:
        return FileResult(
            diagnostics=build_diagnostics(path, find_image_links(text)),
            fixed=False,
        )

    updated, normalized_links, renamed_files = normalize_links_and_files(
        markdown_path=path,
        text=text,
        links=find_image_links(text),
    )

    links_after_normalization = find_image_links(updated)
    broken_links = [
        link
        for link in links_after_normalization
        if not target_exists(path, link.target)
    ]
    removed_links = len(broken_links)
    if broken_links:
        updated = remove_links(updated, broken_links)

    fixed = updated != text
    if fixed:
        path.write_text(updated, encoding="utf-8")

    final_diagnostics = build_diagnostics(path, find_image_links(updated))
    return FileResult(
        diagnostics=final_diagnostics,
        fixed=fixed,
        normalized_links=normalized_links,
        renamed_files=renamed_files,
        removed_links=removed_links,
    )


def run_checks(
    paths: list[Path],
    fix: bool = False,
    jobs: int | None = None,
) -> list[FileResult]:
    """Check every target file.

    Args:
        paths: Markdown files to check.
        fix: Whether to normalize links/files and remove broken image links.
        jobs: Worker thread count. ``None`` uses the ThreadPoolExecutor default.

    Returns:
        File results in target order.
    """
    if fix:
        return [check_file(path, fix=True) for path in paths]

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        return list(executor.map(lambda path: check_file(path, fix=False), paths))


def main(argv: list[str] | None = None) -> int:
    """Run the image-link checker.

    Args:
        argv: Argument vector. ``None`` uses ``sys.argv[1:]``.

    Returns:
        Exit code: ``0`` on success or successful fix, ``1`` when diagnostics
        remain.
    """
    args = parse_args(argv)
    targets = collect_targets(args.paths)
    results = run_checks(targets, fix=args.fix, jobs=args.jobs)
    diagnostics = [
        diagnostic for result in results for diagnostic in result.diagnostics
    ]
    diagnostics.sort(key=lambda diagnostic: (str(diagnostic.path), diagnostic.line))
    fixed_count = sum(1 for result in results if result.fixed)
    normalized_link_count = sum(result.normalized_links for result in results)
    renamed_file_count = sum(result.renamed_files for result in results)
    removed_link_count = sum(result.removed_links for result in results)

    if args.fix:
        print(f"Fixed {fixed_count} file(s).")
        print(f"Normalized {normalized_link_count} image link target(s).")
        print(f"Renamed {renamed_file_count} image file(s).")
        print(f"Removed {removed_link_count} broken image link(s).")

    if diagnostics and not args.fix:
        for diagnostic in diagnostics:
            print(
                f"{diagnostic.path}:{diagnostic.line}: [{diagnostic.code}] {diagnostic.message}",
                file=sys.stderr,
            )
        print(f"Found {len(diagnostics)} error(s).", file=sys.stderr)
        return 1

    if diagnostics and args.fix:
        for diagnostic in diagnostics:
            print(
                f"{diagnostic.path}:{diagnostic.line}: [{diagnostic.code}] {diagnostic.message}",
                file=sys.stderr,
            )
        print(f"Found {len(diagnostics)} remaining error(s).", file=sys.stderr)
        return 1

    print(f"All image links passed ({len(targets)} file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
