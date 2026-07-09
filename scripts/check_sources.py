#!/usr/bin/env python3
"""Lint Markdown files under sources/ against _template/source.md.

The template frontmatter defines required keys. Source notes may also keep
optional provenance metadata such as ``model``.

Rules:
    SRC001  missing-frontmatter         frontmatter block does not start with `---`
    SRC002  unterminated-frontmatter    closing `---` is missing
    SRC003  missing-required-key        a required frontmatter key is absent
    SRC004  empty-frontmatter-value     a checked frontmatter key has an empty value
    SRC005  unexpanded-placeholder      a `{{...}}` template placeholder remains
    SRC006  invalid-filename            filename does not match `YYYY-MM-DD_slug.md`
    SRC007  created-mismatch            filename date does not match frontmatter `created`
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

FRONTMATTER_DELIMITER = "---"
PLACEHOLDER_PATTERN = re.compile(r"\{\{[^}]+\}\}")
OPTIONAL_FRONTMATTER_KEYS = frozenset({"model"})
SOURCE_FILENAME_PATTERN = re.compile(
    r"^(?P<created>\d{4}-\d{2}-\d{2})_(?P<slug>.+)\.md$"
)

RULES_TABLE = (
    "SRC001  missing-frontmatter         frontmatter block does not start with `---`\n"
    "SRC002  unterminated-frontmatter    closing `---` is missing\n"
    "SRC003  missing-required-key        a required frontmatter key is absent\n"
    "SRC004  empty-frontmatter-value     a checked frontmatter key has an empty value\n"
    "SRC005  unexpanded-placeholder      a `{{...}}` template placeholder remains\n"
    "SRC006  invalid-filename            filename does not match `YYYY-MM-DD_slug.md`\n"
    "SRC007  created-mismatch            filename date does not match frontmatter `created`"
)


def clean_frontmatter_value(value: str) -> str:
    """Strip only matching YAML-ish quote pairs from a scalar value.

    Args:
        value: Raw value text after the first ``:``.

    Returns:
        Value with whitespace removed and one matching quote pair removed.
    """
    stripped = value.strip()
    if (
        len(stripped) >= 2
        and stripped[0] == stripped[-1]
        and stripped[0]
        in {
            '"',
            "'",
        }
    ):
        return stripped[1:-1]
    return stripped


@dataclass(frozen=True)
class Diagnostic:
    """A single lint finding for one source file.

    Attributes:
        path: Markdown file path that the diagnostic refers to.
        line: 1-based line number to surface in the output.
        code: Rule code (e.g. ``SRC001``).
        message: Human-readable message in Japanese.
    """

    path: Path
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class Frontmatter:
    """Parsed frontmatter with line-number provenance.

    Attributes:
        entries: Mapping from key to ``(line_number, value)``.
        diagnostic: Diagnostic emitted while parsing (SRC001 / SRC002),
            or ``None`` when the block is structurally well-formed.
    """

    entries: dict[str, tuple[int, str]]
    diagnostic: Diagnostic | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument vector to parse. ``None`` uses ``sys.argv[1:]``.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Lint Markdown files under sources/ against _template/source.md.",
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
        "--template",
        type=Path,
        default=Path("_template/source.md"),
        help="Template file that defines required frontmatter keys.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="Number of worker threads. Defaults to the Python default for ThreadPoolExecutor.",
    )
    return parser.parse_args(argv)


def parse_frontmatter(path: Path) -> Frontmatter:
    """Parse the YAML-ish frontmatter block of a Markdown file.

    Args:
        path: Markdown file path.

    Returns:
        A :class:`Frontmatter` carrying parsed entries and an optional diagnostic
        for SRC001 or SRC002.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return Frontmatter(
            entries={},
            diagnostic=Diagnostic(
                path=path,
                line=1,
                code="SRC001",
                message="frontmatterがありません",
            ),
        )

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == FRONTMATTER_DELIMITER:
            closing_index = index
            break

    if closing_index is None:
        return Frontmatter(
            entries={},
            diagnostic=Diagnostic(
                path=path,
                line=1,
                code="SRC002",
                message="frontmatterの終了区切りがありません",
            ),
        )

    entries: dict[str, tuple[int, str]] = {}
    for line_number, raw in enumerate(lines[1 : closing_index - 1], start=2):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if not separator:
            continue
        entries[key.strip()] = (line_number, clean_frontmatter_value(value))

    return Frontmatter(entries=entries, diagnostic=None)


def required_keys_from_template(template_path: Path) -> list[str]:
    """Read required frontmatter keys from the source template.

    Args:
        template_path: Path to ``_template/source.md``.

    Returns:
        Required top-level frontmatter keys in template order.

    Raises:
        ValueError: If the template has no parseable frontmatter block.
    """
    frontmatter = parse_frontmatter(template_path)
    if frontmatter.diagnostic is not None:
        msg = f"テンプレート {template_path} のfrontmatterを読み取れません: {frontmatter.diagnostic.message}"
        raise ValueError(msg)
    return list(frontmatter.entries)


def check_file(path: Path, required_keys: list[str]) -> list[Diagnostic]:
    """Run all rules against one Markdown file.

    Args:
        path: Markdown file path.
        required_keys: Frontmatter keys required by the template.

    Returns:
        Diagnostics for the file. Empty when the file passes every rule.
    """
    frontmatter = parse_frontmatter(path)
    if frontmatter.diagnostic is not None:
        return [frontmatter.diagnostic]

    diagnostics: list[Diagnostic] = []
    entries = frontmatter.entries

    checked_keys = [*required_keys, *sorted(OPTIONAL_FRONTMATTER_KEYS & entries.keys())]
    for key in checked_keys:
        if key not in entries:
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=1,
                    code="SRC003",
                    message=f"`{key}` がありません",
                )
            )
            continue
        line_number, value = entries[key]
        if not value:
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=line_number,
                    code="SRC004",
                    message=f"`{key}` が空です",
                )
            )
        if PLACEHOLDER_PATTERN.search(value):
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=line_number,
                    code="SRC005",
                    message=f"`{key}` に未展開のテンプレート値があります",
                )
            )

    filename_match = SOURCE_FILENAME_PATTERN.fullmatch(path.name)
    if filename_match is None:
        diagnostics.append(
            Diagnostic(
                path=path,
                line=1,
                code="SRC006",
                message="ファイル名が `YYYY-MM-DD_slug.md` 形式ではありません",
            )
        )
        return diagnostics

    created_entry = entries.get("created")
    if created_entry is not None and created_entry[1] != filename_match.group(
        "created"
    ):
        diagnostics.append(
            Diagnostic(
                path=path,
                line=created_entry[0],
                code="SRC007",
                message="ファイル名の日付とfrontmatterの`created`が一致しません",
            )
        )

    return diagnostics


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
        if entry.is_file():
            collected.add(entry)
        elif entry.is_dir():
            collected.update(p for p in entry.rglob("*.md") if p.is_file())
    return sorted(collected)


def run_checks(
    paths: list[Path],
    required_keys: list[str],
    jobs: int | None = None,
) -> list[Diagnostic]:
    """Lint every target file in parallel and collect diagnostics.

    Args:
        paths: Markdown file paths to lint.
        required_keys: Required frontmatter keys.
        jobs: Worker thread count. ``None`` uses the ThreadPoolExecutor default.

    Returns:
        All diagnostics across files, sorted by ``(path, line, code)``.
    """
    diagnostics: list[Diagnostic] = []
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        for file_diagnostics in executor.map(
            lambda p: check_file(p, required_keys), paths
        ):
            diagnostics.extend(file_diagnostics)
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
    required_keys = required_keys_from_template(args.template)
    targets = collect_targets(args.paths)
    diagnostics = run_checks(targets, required_keys, jobs=args.jobs)

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
