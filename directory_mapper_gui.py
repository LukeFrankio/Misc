#!/usr/bin/env python3
"""directory_mapper_gui.py

Directory Mapper (GUI + CLI)

This utility scans a directory, computes detailed stats (sizes, counts, largest files,
extension breakdown), and produces:

1) A Markdown report with a written tree view.
2) A treemap-style SVG image sized by bytes.

The GUI is intentionally "simple Tkinter like" (inspired by `file_merger_gui.py`) and
uses only the Python standard library.

Python version:
    Requires Python 3.11+ (recommended: Python 3.13+).

Examples:
    GUI:
        python directory_mapper_gui.py

    CLI:
        python directory_mapper_gui.py --root C:/Dev/Misc --out-dir C:/Dev/Misc --tree-depth 6
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk
from typing import Iterable, Mapping, NamedTuple


class FileSummary(NamedTuple):
    """Lightweight file facts used for reporting."""

    path: Path
    size_bytes: int
    mtime_unix: float


@dataclass(frozen=True)
class DirSummary:
    """Aggregated directory facts.

    Attributes:
        path: Directory path.
        size_bytes: Total size of all files under this directory (recursive).
        file_count: Number of files under this directory (recursive).
        dir_count: Number of subdirectories under this directory (recursive, excluding self).
    """

    path: Path
    size_bytes: int
    file_count: int
    dir_count: int


@dataclass(frozen=True)
class ScanOptions:
    """Options controlling scanning behavior."""

    follow_symlinks: bool
    include_hidden: bool
    ignore_globs: tuple[str, ...]


@dataclass(frozen=True)
class ReportOptions:
    """Options controlling report detail/size."""

    tree_depth: int
    tree_max_entries: int
    largest_files: int
    hash_largest_files_sha256: bool
    treemap_depth: int
    treemap_max_items: int


@dataclass(frozen=True)
class ScanResult:
    """Full scan output (facts + summaries) used to build reports."""

    root: Path
    started_at_utc: datetime
    finished_at_utc: datetime
    elapsed_seconds: float

    total_size_bytes: int
    total_file_count: int
    total_dir_count: int

    extension_bytes: Mapping[str, int]
    extension_counts: Mapping[str, int]

    largest_files: tuple[FileSummary, ...]
    dir_summaries: Mapping[Path, DirSummary]

    errors: tuple[str, ...]


def _is_probably_hidden(path: Path) -> bool:
    """Best-effort hidden check that works cross-platform.

    Note:
        On Windows, a file can be hidden without starting with '.', but checking the
        filesystem attribute would require platform-specific APIs. We keep it simple:
        names starting with '.' are treated as hidden.
    """

    return path.name.startswith(".")


def _matches_any_glob(rel_posix: str, globs: Iterable[str]) -> bool:
    """Returns True if rel_posix matches any ignore glob."""

    for pat in globs:
        if fnmatch.fnmatch(rel_posix, pat):
            return True
    return False


def _human_bytes(num_bytes: int) -> str:
    """Formats bytes as human-readable IEC units (KiB, MiB, GiB...).

    ✨ PURE FUNCTION ✨

    Args:
        num_bytes: Byte count (>= 0).

    Returns:
        Human-readable string.
    """

    if num_bytes < 1024:
        return f"{num_bytes} B"
    units = ["KiB", "MiB", "GiB", "TiB", "PiB"]
    value = float(num_bytes)
    for u in units:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.2f} {u}"
    return f"{value:.2f} EiB"


def _safe_rel_posix(root: Path, child: Path) -> str:
    """Computes child relative path as POSIX string for glob matching."""

    try:
        rel = child.relative_to(root)
    except Exception:
        # If it can't be made relative, treat as absolute-ish string
        rel = child
    return rel.as_posix()


def scan_directory(root: Path, options: ScanOptions, largest_files: int) -> ScanResult:
    """Scans a directory and returns aggregated stats.

    ⚠️ IMPURE FUNCTION (filesystem I/O)

    Args:
        root: Root directory to scan.
        options: Scan configuration.
        largest_files: Keep the N largest files for reporting.

    Returns:
        ScanResult with summaries and stats.

    Raises:
        FileNotFoundError: If root does not exist.
        NotADirectoryError: If root is not a directory.
    """

    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    ext_bytes: dict[str, int] = {}
    ext_counts: dict[str, int] = {}
    dir_summaries: dict[Path, DirSummary] = {}
    errors: list[str] = []

    # We keep a simple list and sort at the end; for directories with huge file counts,
    # you could switch to a heap, but this is usually fine for personal projects.
    largest: list[FileSummary] = []

    def record_file(path: Path, size: int, mtime: float) -> None:
        nonlocal largest
        ext = path.suffix.lower() or "<no-ext>"
        ext_bytes[ext] = ext_bytes.get(ext, 0) + size
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

        largest.append(FileSummary(path=path, size_bytes=size, mtime_unix=mtime))

    def should_skip(path: Path) -> bool:
        rel_posix = _safe_rel_posix(root, path)
        if _matches_any_glob(rel_posix, options.ignore_globs):
            return True
        if not options.include_hidden and _is_probably_hidden(path):
            return True
        return False

    def walk_dir(path: Path) -> DirSummary:
        """Recursive post-order walk computing directory aggregates."""

        size_total = 0
        file_count = 0
        dir_count = 0

        try:
            with os.scandir(path) as it:
                entries = list(it)
        except Exception as e:  # permissions, transient issues, etc.
            errors.append(f"Failed to list {path}: {e}")
            summary = DirSummary(path=path, size_bytes=0, file_count=0, dir_count=0)
            dir_summaries[path] = summary
            return summary

        for entry in entries:
            child = Path(entry.path)

            if should_skip(child):
                continue

            try:
                is_symlink = entry.is_symlink()
            except Exception:
                is_symlink = False

            if is_symlink and not options.follow_symlinks:
                continue

            try:
                if entry.is_file(follow_symlinks=options.follow_symlinks):
                    try:
                        st = entry.stat(follow_symlinks=options.follow_symlinks)
                        size = int(st.st_size)
                        mtime = float(st.st_mtime)
                    except Exception as e:
                        errors.append(f"Failed to stat file {child}: {e}")
                        continue

                    record_file(child, size=size, mtime=mtime)
                    size_total += size
                    file_count += 1

                elif entry.is_dir(follow_symlinks=options.follow_symlinks):
                    sub = walk_dir(child)
                    size_total += sub.size_bytes
                    file_count += sub.file_count
                    dir_count += 1 + sub.dir_count

                else:
                    # sockets, device files, etc. (rare on Windows)
                    continue

            except Exception as e:
                errors.append(f"Failed to inspect {child}: {e}")

        summary = DirSummary(path=path, size_bytes=size_total, file_count=file_count, dir_count=dir_count)
        dir_summaries[path] = summary
        return summary

    root_summary = walk_dir(root)

    # Finalize largest files (top N)
    largest_sorted = sorted(largest, key=lambda f: f.size_bytes, reverse=True)[: max(0, largest_files)]

    finished = datetime.now(timezone.utc)
    elapsed = time.perf_counter() - t0

    return ScanResult(
        root=root,
        started_at_utc=started,
        finished_at_utc=finished,
        elapsed_seconds=elapsed,
        total_size_bytes=root_summary.size_bytes,
        total_file_count=root_summary.file_count,
        total_dir_count=root_summary.dir_count,
        extension_bytes=dict(sorted(ext_bytes.items(), key=lambda kv: kv[1], reverse=True)),
        extension_counts=dict(sorted(ext_counts.items(), key=lambda kv: kv[1], reverse=True)),
        largest_files=tuple(largest_sorted),
        dir_summaries=dir_summaries,
        errors=tuple(errors),
    )


def _tree_lines(
    root: Path,
    scan: ScanResult,
    options: ScanOptions,
    depth: int,
    max_entries: int,
) -> list[str]:
    """Builds a tree view as text lines.

    ⚠️ IMPURE FUNCTION (filesystem I/O)

    This intentionally re-lists directories to avoid storing gigantic full trees in memory.
    Sizes come from the scan summaries so directory lines can show recursive totals.
    """

    lines: list[str] = []
    emitted = 0

    def should_skip(path: Path) -> bool:
        rel_posix = _safe_rel_posix(root, path)
        if _matches_any_glob(rel_posix, options.ignore_globs):
            return True
        if not options.include_hidden and _is_probably_hidden(path):
            return True
        return False

    def dir_label(path: Path) -> str:
        summ = scan.dir_summaries.get(path)
        if summ is None:
            return f"{path.name}/"
        return f"{path.name}/  ({_human_bytes(summ.size_bytes)}, {summ.file_count} files, {summ.dir_count} dirs)"

    def file_label(path: Path) -> str:
        try:
            st = path.stat()
            return f"{path.name}  ({_human_bytes(int(st.st_size))})"
        except Exception:
            return f"{path.name}  (<unreadable>)"

    def walk(current: Path, prefix: str, level: int) -> None:
        nonlocal emitted
        if emitted >= max_entries:
            return

        try:
            with os.scandir(current) as it:
                entries = list(it)
        except Exception:
            lines.append(prefix + "[unreadable]")
            emitted += 1
            return

        # Separate dirs/files and sort (dirs first, then by size desc)
        dirs: list[Path] = []
        files: list[Path] = []
        for e in entries:
            p = Path(e.path)
            if should_skip(p):
                continue
            try:
                if e.is_dir(follow_symlinks=options.follow_symlinks):
                    dirs.append(p)
                elif e.is_file(follow_symlinks=options.follow_symlinks):
                    files.append(p)
            except Exception:
                continue

        def dir_sort_key(p: Path) -> int:
            s = scan.dir_summaries.get(p)
            return -(s.size_bytes if s else 0)

        def file_sort_key(p: Path) -> int:
            try:
                return -int(p.stat().st_size)
            except Exception:
                return 0

        dirs.sort(key=dir_sort_key)
        files.sort(key=file_sort_key)

        children: list[tuple[Path, bool]] = [(d, True) for d in dirs] + [(f, False) for f in files]

        for idx, (child, is_dir) in enumerate(children):
            if emitted >= max_entries:
                return

            last = idx == (len(children) - 1)
            branch = "└── " if last else "├── "
            next_prefix = prefix + ("    " if last else "│   ")

            if is_dir:
                lines.append(prefix + branch + dir_label(child))
                emitted += 1
                # depth <= 0 means "unlimited" depth (bounded only by max_entries)
                if depth <= 0 or (level + 1) < depth:
                    walk(child, next_prefix, level + 1)
            else:
                lines.append(prefix + branch + file_label(child))
                emitted += 1

    # Root header line
    root_summ = scan.dir_summaries.get(root)
    if root_summ:
        lines.append(f"{root.name}/  ({_human_bytes(root_summ.size_bytes)}, {root_summ.file_count} files, {root_summ.dir_count} dirs)")
    else:
        lines.append(f"{root.name}/")

    walk(root, prefix="", level=0)

    if emitted >= max_entries:
        lines.append("… (tree truncated: reached max entries)")

    return lines


def _stable_color_hex(label: str) -> str:
    """Deterministic, readable-ish color from a label."""

    digest = hashlib.sha256(label.encode("utf-8")).digest()
    # Bias towards mid-range so text contrasts reasonably.
    r = 64 + (digest[0] % 160)
    g = 64 + (digest[1] % 160)
    b = 64 + (digest[2] % 160)
    return f"#{r:02x}{g:02x}{b:02x}"


class TreemapItem(NamedTuple):
    label: str
    size: int


def _group_sizes_for_treemap(root: Path, scan: ScanResult, depth: int) -> list[TreemapItem]:
    """Groups sizes for a treemap without double-counting bytes.

    The core idea: *partition* file bytes into disjoint buckets.

    - If depth == 0 ("infinite"), we create a bucket for each directory's **direct files**
      (non-recursive), labeled like `path/to/dir/·files`, plus individual root-level files.
      This yields a very detailed (potentially huge) treemap, so `treemap_max_items` is
      still the practical safety valve.

    - If depth >= 1, we create buckets for directories exactly at that depth
      (recursive totals), plus `…/·files` buckets for directories shallower than depth
      to account for files that live "above" the grouping level.

    ✨ PURE FUNCTION ✨ (given scan)
    """

    grouped: dict[str, int] = {}

    # Build parent -> child-dir list for computing "direct files" sizes:
    # direct_files_size(dir) = dir.size - sum(child_dir.size)
    children: dict[Path, list[Path]] = {}
    for d in scan.dir_summaries.keys():
        if d == root:
            continue
        try:
            d.relative_to(root)
        except Exception:
            continue
        parent = d.parent
        if parent not in children:
            children[parent] = []
        children[parent].append(d)

    child_sum: dict[Path, int] = {}
    for parent, kids in children.items():
        total = 0
        for k in kids:
            s = scan.dir_summaries.get(k)
            if s:
                total += s.size_bytes
        child_sum[parent] = total

    def add_bucket(label: str, size: int) -> None:
        if size <= 0:
            return
        grouped[label] = grouped.get(label, 0) + size

    # 1) Root-level files get their own buckets (nice for quick wins, and avoids
    # double-counting with a root "·files" bucket).
    try:
        for child in root.iterdir():
            if child.is_file():
                try:
                    size = int(child.stat().st_size)
                except Exception:
                    continue
                add_bucket(child.name, size)
    except Exception:
        # If root listing fails, we still can create directory buckets.
        pass

    # 2) Directory buckets
    for dir_path, summ in scan.dir_summaries.items():
        try:
            rel = dir_path.relative_to(root)
        except Exception:
            continue

        # Skip root itself for directory buckets.
        if rel == Path("."):
            continue

        rel_parts = rel.parts
        rel_depth = len(rel_parts)

        # Compute direct-files size for this directory.
        direct_files = summ.size_bytes - child_sum.get(dir_path, 0)
        if direct_files < 0:
            direct_files = 0

        if depth <= 0:
            # Infinite detail: bucket per directory's direct files.
            add_bucket(rel.as_posix() + "/·files", direct_files)
            continue

        if rel_depth < depth:
            # Files above the grouping level need their own bucket.
            add_bucket(rel.as_posix() + "/·files", direct_files)
            continue

        if rel_depth == depth:
            # This directory represents the full subtree for its prefix.
            add_bucket(rel.as_posix() + "/", summ.size_bytes)
            continue

        # rel_depth > depth: these bytes are already included in the ancestor dir
        # bucket at `depth`, so we must not add anything here (avoid double-count).

    items = [TreemapItem(label=k, size=v) for k, v in grouped.items() if v > 0]
    items.sort(key=lambda it: it.size, reverse=True)
    return items


def _normalize_sizes(sizes: list[float], width: float, height: float) -> list[float]:
    """Normalizes sizes to fit a rectangle of width*height."""

    total = sum(sizes)
    if total <= 0:
        return [0.0 for _ in sizes]
    factor = (width * height) / total
    return [s * factor for s in sizes]


def _worst_ratio(row: list[float], side: float) -> float:
    """Computes the worst aspect ratio for a row (squarify helper)."""

    if not row or side <= 0:
        return float("inf")
    s = sum(row)
    mx = max(row)
    mn = min(row)
    if mn <= 0:
        return float("inf")
    side2 = side * side
    return max((side2 * mx) / (s * s), (s * s) / (side2 * mn))


def _layout_row(row: list[float], x: float, y: float, w: float, h: float) -> tuple[list[tuple[float, float, float, float]], float, float, float, float]:
    """Lays out a row of rectangles in remaining space."""

    rects: list[tuple[float, float, float, float]] = []
    s = sum(row)
    if w >= h:
        # horizontal slice
        row_h = s / w if w > 0 else 0
        cx = x
        for r in row:
            rw = r / row_h if row_h > 0 else 0
            rects.append((cx, y, rw, row_h))
            cx += rw
        y += row_h
        h -= row_h
    else:
        # vertical slice
        row_w = s / h if h > 0 else 0
        cy = y
        for r in row:
            rh = r / row_w if row_w > 0 else 0
            rects.append((x, cy, row_w, rh))
            cy += rh
        x += row_w
        w -= row_w
    return rects, x, y, w, h


def treemap_rects(sizes: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Computes treemap rectangles using a squarify-style algorithm.

    ✨ PURE FUNCTION ✨

    Args:
        sizes: Positive weights, typically bytes.
        x, y: Origin.
        w, h: Dimensions.

    Returns:
        List of (x, y, width, height) rectangles.
    """

    sizes_n = _normalize_sizes(sizes, w, h)
    sizes_n = [s for s in sizes_n if s > 0]
    rects: list[tuple[float, float, float, float]] = []

    remaining = sizes_n[:]
    row: list[float] = []

    while remaining:
        row.append(remaining[0])
        side = min(w, h)

        if len(row) == 1:
            remaining.pop(0)
            continue

        prev = _worst_ratio(row[:-1], side)
        curr = _worst_ratio(row, side)
        if curr > prev:
            # Commit row without the last element
            last = row.pop()
            row_rects, x, y, w, h = _layout_row(row, x, y, w, h)
            rects.extend(row_rects)
            row = [last]
            remaining.pop(0)
        else:
            remaining.pop(0)

    if row:
        row_rects, x, y, w, h = _layout_row(row, x, y, w, h)
        rects.extend(row_rects)

    return rects


def render_treemap_svg(
    items: list[TreemapItem],
    out_svg: Path,
    title: str,
    width: int = 1400,
    height: int = 900,
) -> None:
    """Renders a treemap to an SVG file.

    ⚠️ IMPURE FUNCTION (file I/O)

    Args:
        items: Labeled weights.
        out_svg: Path to write.
        title: Title shown at top of image.
        width: SVG width in px.
        height: SVG height in px.
    """

    margin = 14
    header_h = 52
    inner_x = margin
    inner_y = margin + header_h
    inner_w = max(1, width - 2 * margin)
    inner_h = max(1, height - inner_y - margin)

    if not items:
        out_svg.write_text(
            """<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"200\">\n"
            "<text x=\"16\" y=\"40\" font-family=\"Segoe UI, Arial\" font-size=\"18\">No items to render.</text>\n"
            "</svg>\n""",
            encoding="utf-8",
        )
        return

    sizes = [float(it.size) for it in items]
    rects = treemap_rects(sizes, float(inner_x), float(inner_y), float(inner_w), float(inner_h))

    # Defensive: keep alignment with items
    rects = rects[: len(items)]

    def esc(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    svg_lines: list[str] = []
    svg_lines.append(f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\">")
    svg_lines.append("<rect x=\"0\" y=\"0\" width=\"100%\" height=\"100%\" fill=\"#0b1020\"/>")

    # Title
    svg_lines.append(
        f"<text x=\"{margin}\" y=\"{margin + 28}\" fill=\"#e6e6e6\" "
        "font-family=\"Segoe UI, Arial\" font-size=\"22\" font-weight=\"600\">"
        f"{esc(title)}"
        "</text>"
    )

    # Frame
    svg_lines.append(
        f"<rect x=\"{inner_x}\" y=\"{inner_y}\" width=\"{inner_w}\" height=\"{inner_h}\" "
        "fill=\"none\" stroke=\"#2b3350\" stroke-width=\"1\"/>")

    for (it, (x, y, w, h)) in zip(items, rects, strict=False):
        if w <= 0 or h <= 0:
            continue
        pad = 1.0
        rx = x + pad
        ry = y + pad
        rw = max(0.0, w - 2 * pad)
        rh = max(0.0, h - 2 * pad)

        fill = _stable_color_hex(it.label)
        label = it.label
        tooltip = f"{label}\\n{_human_bytes(it.size)}"

        svg_lines.append(
            f"<g>"
            f"<rect x=\"{rx:.2f}\" y=\"{ry:.2f}\" width=\"{rw:.2f}\" height=\"{rh:.2f}\" "
            f"fill=\"{fill}\" opacity=\"0.92\" stroke=\"#0b1020\" stroke-width=\"1\">"
            f"<title>{esc(tooltip)}</title>"
            "</rect>"
            "</g>"
        )

        # Only label if there's room
        if rw >= 120 and rh >= 26:
            text = f"{label} ({_human_bytes(it.size)})"
            svg_lines.append(
                f"<text x=\"{rx + 6:.2f}\" y=\"{ry + 18:.2f}\" fill=\"#0b1020\" "
                "font-family=\"Segoe UI, Arial\" font-size=\"14\" font-weight=\"600\">"
                f"{esc(text)}"
                "</text>"
            )

    svg_lines.append("</svg>")
    out_svg.write_text("\n".join(svg_lines) + "\n", encoding="utf-8")


def _sha256_hex(path: Path) -> str:
    """Computes SHA-256 of a file.

    ⚠️ IMPURE FUNCTION (filesystem I/O)

    This is intentionally used only when explicitly requested, because hashing
    large files across an entire repo can be slow.
    """

    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "<unreadable>"


def write_markdown_report(
    scan: ScanResult,
    scan_options: ScanOptions,
    report_options: ReportOptions,
    out_md: Path,
    treemap_rel_path: str | None,
) -> None:
    """Writes the Markdown report file.

    ⚠️ IMPURE FUNCTION (file I/O)
    """

    tree = _tree_lines(
        root=scan.root,
        scan=scan,
        options=scan_options,
        depth=report_options.tree_depth,
        max_entries=report_options.tree_max_entries,
    )

    def iso(ts: float) -> str:
        try:
            return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
        except Exception:
            return "<unknown>"

    md: list[str] = []
    md.append(f"# Directory Map: `{scan.root}`")
    md.append("")
    md.append(f"- **Scanned (UTC):** {scan.started_at_utc.isoformat(timespec='seconds')} → {scan.finished_at_utc.isoformat(timespec='seconds')}  ")
    md.append(f"- **Elapsed:** {scan.elapsed_seconds:.2f}s  ")
    md.append(f"- **Total size:** {_human_bytes(scan.total_size_bytes)} ({scan.total_size_bytes:,} bytes)  ")
    md.append(f"- **Files:** {scan.total_file_count:,}  ")
    md.append(f"- **Directories:** {scan.total_dir_count:,}  ")
    md.append("")

    md.append("## Options")
    md.append("")
    md.append(f"- **Include hidden:** {scan_options.include_hidden}")
    md.append(f"- **Follow symlinks:** {scan_options.follow_symlinks}")
    md.append(f"- **Ignore globs:** {', '.join(scan_options.ignore_globs) if scan_options.ignore_globs else '(none)'}")
    tree_depth_txt = "unlimited" if report_options.tree_depth <= 0 else str(report_options.tree_depth)
    md.append(f"- **Tree depth:** {tree_depth_txt} (max entries: {report_options.tree_max_entries:,})")
    md.append(f"- **Hash largest files (SHA-256):** {report_options.hash_largest_files_sha256}")
    treemap_depth_txt = "unlimited" if report_options.treemap_depth <= 0 else str(report_options.treemap_depth)
    md.append(f"- **Treemap depth:** {treemap_depth_txt} (max items: {report_options.treemap_max_items:,})")
    md.append("")

    if treemap_rel_path:
        md.append("## Treemap (size by bytes)")
        md.append("")
        md.append(f"![Treemap]({treemap_rel_path})")
        md.append("")

    md.append("## Tree view")
    md.append("")
    md.append("```text")
    md.extend(tree)
    md.append("```")
    md.append("")

    md.append("## Largest files")
    md.append("")
    if not scan.largest_files:
        md.append("(none)")
    else:
        if report_options.hash_largest_files_sha256:
            md.append("| Size | Modified | SHA-256 | Path |")
            md.append("|---:|---|---|---|")
        else:
            md.append("| Size | Modified | Path |")
            md.append("|---:|---|---|")
        for f in scan.largest_files:
            if report_options.hash_largest_files_sha256:
                sha = _sha256_hex(f.path)
                md.append(f"| {_human_bytes(f.size_bytes)} | {iso(f.mtime_unix)} | `{sha}` | `{f.path}` |")
            else:
                md.append(f"| {_human_bytes(f.size_bytes)} | {iso(f.mtime_unix)} | `{f.path}` |")
    md.append("")

    md.append("## Extension breakdown")
    md.append("")
    md.append("| Extension | Files | Bytes | Human |")
    md.append("|---|---:|---:|---:|")
    for ext, b in scan.extension_bytes.items():
        c = scan.extension_counts.get(ext, 0)
        md.append(f"| `{ext}` | {c:,} | {b:,} | {_human_bytes(b)} |")
    md.append("")

    if scan.errors:
        md.append("## Warnings / errors")
        md.append("")
        md.append("Some paths could not be read; totals may be incomplete:")
        md.append("")
        for e in scan.errors[:200]:
            md.append(f"- {e}")
        if len(scan.errors) > 200:
            md.append(f"- … (truncated: {len(scan.errors) - 200} more)")
        md.append("")

    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")


def generate_outputs(
    root: Path,
    out_dir: Path,
    scan_options: ScanOptions,
    report_options: ReportOptions,
) -> tuple[Path, Path]:
    """Generates the Markdown report and SVG treemap in out_dir.

    ⚠️ IMPURE FUNCTION (filesystem I/O)

    Returns:
        (markdown_path, svg_path)
    """

    out_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = root.name.replace(" ", "_")
    md_path = out_dir / f"{safe_stem}_dir_map.md"
    svg_path = out_dir / f"{safe_stem}_treemap.svg"

    scan = scan_directory(root, scan_options, largest_files=report_options.largest_files)

    items = _group_sizes_for_treemap(root, scan, depth=report_options.treemap_depth)
    items = items[: max(0, report_options.treemap_max_items)]
    render_treemap_svg(items, svg_path, title=f"Treemap: {root}")

    # Markdown should embed treemap relative to report when possible.
    treemap_rel = None
    try:
        treemap_rel = svg_path.relative_to(md_path.parent).as_posix()
    except Exception:
        treemap_rel = svg_path.as_posix()

    write_markdown_report(
        scan=scan,
        scan_options=scan_options,
        report_options=report_options,
        out_md=md_path,
        treemap_rel_path=treemap_rel,
    )

    return md_path, svg_path


class DirectoryMapperApp:
    """Tkinter GUI wrapper inspired by `file_merger_gui.py`."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Directory Mapper")
        root.geometry("860x520")

        self.root_dir_var = tk.StringVar(value="")
        self.out_dir_var = tk.StringVar(value="")

        self.include_hidden_var = tk.BooleanVar(value=False)
        self.follow_symlinks_var = tk.BooleanVar(value=False)
        self.ignore_globs_var = tk.StringVar(value=".git/**;__pycache__/**;*.pyc")

        # 0 means "unlimited" depth (bounded by max entries)
        self.tree_depth_var = tk.IntVar(value=0)
        self.tree_max_entries_var = tk.IntVar(value=5000)
        self.largest_files_var = tk.IntVar(value=30)
        self.hash_largest_files_var = tk.BooleanVar(value=False)

        # 0 means "infinite" detail (bucket per directory's direct files).
        self.treemap_depth_var = tk.IntVar(value=0)
        self.treemap_max_items_var = tk.IntVar(value=80)

        self.status = tk.StringVar(value="Ready")

        self._build_ui()

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        # Top: folder selection
        pick = ttk.LabelFrame(frm, text="Paths", padding=10)
        pick.pack(fill=tk.X)

        ttk.Label(pick, text="Root directory:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(pick, textvariable=self.root_dir_var).grid(row=0, column=1, sticky=tk.EW, padx=8)
        ttk.Button(pick, text="Choose…", command=self.choose_root).grid(row=0, column=2, sticky=tk.E)

        ttk.Label(pick, text="Output folder:").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(pick, textvariable=self.out_dir_var).grid(row=1, column=1, sticky=tk.EW, padx=8, pady=(8, 0))
        ttk.Button(pick, text="Choose…", command=self.choose_out_dir).grid(row=1, column=2, sticky=tk.E, pady=(8, 0))

        pick.columnconfigure(1, weight=1)

        # Options
        opts = ttk.Frame(frm)
        opts.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        left = ttk.LabelFrame(opts, text="Scan options", padding=10)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Checkbutton(left, text="Include hidden (names starting with '.')", variable=self.include_hidden_var).pack(anchor=tk.W)
        ttk.Checkbutton(left, text="Follow symlinks", variable=self.follow_symlinks_var).pack(anchor=tk.W, pady=(6, 0))

        ttk.Label(left, text="Ignore globs (semicolon-separated):").pack(anchor=tk.W, pady=(10, 0))
        ttk.Entry(left, textvariable=self.ignore_globs_var).pack(fill=tk.X, pady=(2, 0))

        right = ttk.LabelFrame(opts, text="Report detail", padding=10)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

        grid = ttk.Frame(right)
        grid.pack(fill=tk.X)

        def spin(row: int, label: str, var: tk.IntVar, frm_: int, to: int) -> None:
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky=tk.W, pady=4)
            ttk.Spinbox(grid, from_=frm_, to=to, textvariable=var, width=10).grid(row=row, column=1, sticky=tk.E)

        spin(0, "Tree depth (0=unlimited)", self.tree_depth_var, 0, 200)
        spin(1, "Tree max entries", self.tree_max_entries_var, 100, 1_000_000)
        spin(2, "Largest files", self.largest_files_var, 0, 5000)
        ttk.Checkbutton(
            right,
            text="Hash largest files (SHA-256)",
            variable=self.hash_largest_files_var,
        ).pack(anchor=tk.W, pady=(8, 0))
        spin(3, "Treemap depth (0=unlimited)", self.treemap_depth_var, 0, 25)
        spin(4, "Treemap max items", self.treemap_max_items_var, 5, 5000)

        # Actions
        actions = ttk.Frame(frm)
        actions.pack(fill=tk.X, pady=(12, 0))

        ttk.Button(actions, text="Generate", command=self.generate).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Open output folder", command=self.open_output_folder).pack(side=tk.RIGHT, padx=(0, 8))

        # Status bar
        status_bar = ttk.Label(self.root, textvariable=self.status, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def choose_root(self) -> None:
        p = filedialog.askdirectory(title="Choose a directory to map")
        if p:
            self.root_dir_var.set(p)
            if not self.out_dir_var.get():
                self.out_dir_var.set(p)

    def choose_out_dir(self) -> None:
        p = filedialog.askdirectory(title="Choose output folder")
        if p:
            self.out_dir_var.set(p)

    def open_output_folder(self) -> None:
        out = self.out_dir_var.get().strip()
        if not out:
            messagebox.showinfo("Output folder", "No output folder selected yet.")
            return
        try:
            os.startfile(out)  # type: ignore[attr-defined]
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open output folder:\n{e}")

    def generate(self) -> None:
        root_txt = self.root_dir_var.get().strip()
        out_txt = self.out_dir_var.get().strip()
        if not root_txt:
            messagebox.showwarning("Missing root", "Choose a root directory first.")
            return
        if not out_txt:
            messagebox.showwarning("Missing output", "Choose an output folder first.")
            return

        root = Path(root_txt)
        out_dir = Path(out_txt)

        ignore_globs = tuple(
            s.strip() for s in self.ignore_globs_var.get().split(";") if s.strip()
        )

        scan_options = ScanOptions(
            follow_symlinks=bool(self.follow_symlinks_var.get()),
            include_hidden=bool(self.include_hidden_var.get()),
            ignore_globs=ignore_globs,
        )

        report_options = ReportOptions(
            tree_depth=int(self.tree_depth_var.get()),
            tree_max_entries=int(self.tree_max_entries_var.get()),
            largest_files=int(self.largest_files_var.get()),
            hash_largest_files_sha256=bool(self.hash_largest_files_var.get()),
            treemap_depth=int(self.treemap_depth_var.get()),
            treemap_max_items=int(self.treemap_max_items_var.get()),
        )

        try:
            self.status.set("Scanning and generating outputs…")
            self.root.update_idletasks()

            md_path, svg_path = generate_outputs(
                root=root,
                out_dir=out_dir,
                scan_options=scan_options,
                report_options=report_options,
            )

            self.status.set(f"Done: {md_path.name} + {svg_path.name}")
            messagebox.showinfo(
                "Success",
                f"Generated:\n- {md_path}\n- {svg_path}",
            )
        except Exception as e:
            self.status.set("Error")
            messagebox.showerror("Error", f"Failed to generate directory map:\n{e}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Directory Mapper (Markdown tree + SVG treemap)")
    p.add_argument("--root", type=str, help="Root directory to scan")
    p.add_argument("--out-dir", type=str, help="Directory to write outputs")

    p.add_argument("--include-hidden", action="store_true", help="Include hidden names starting with '.'")
    p.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks/junctions")
    p.add_argument(
        "--ignore",
        type=str,
        default=".git/**;__pycache__/**;*.pyc",
        help="Semicolon-separated glob patterns relative to root (posix-style paths)",
    )

    p.add_argument("--tree-depth", type=int, default=0, help="Tree depth (0 = unlimited)")
    p.add_argument("--tree-max-entries", type=int, default=5000)
    p.add_argument("--largest-files", type=int, default=30)
    p.add_argument("--hash-largest-files", action="store_true", help="Compute SHA-256 for the largest-files table")
    p.add_argument("--treemap-depth", type=int, default=0, help="Treemap depth (0 = unlimited)")
    p.add_argument("--treemap-max-items", type=int, default=80)

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Program entry point.

    ⚠️ IMPURE FUNCTION (CLI + GUI side effects)
    """

    argv = list(sys.argv[1:] if argv is None else argv)

    # If any CLI args are provided, run CLI mode; otherwise open GUI.
    if argv:
        args = _parse_args(argv)
        if not args.root:
            print("--root is required in CLI mode", file=sys.stderr)
            return 2
        root = Path(args.root)
        out_dir = Path(args.out_dir) if args.out_dir else root

        ignore_globs = tuple(s.strip() for s in args.ignore.split(";") if s.strip())
        scan_options = ScanOptions(
            follow_symlinks=bool(args.follow_symlinks),
            include_hidden=bool(args.include_hidden),
            ignore_globs=ignore_globs,
        )
        report_options = ReportOptions(
            tree_depth=int(args.tree_depth),
            tree_max_entries=int(args.tree_max_entries),
            largest_files=int(args.largest_files),
            hash_largest_files_sha256=bool(args.hash_largest_files),
            treemap_depth=int(args.treemap_depth),
            treemap_max_items=int(args.treemap_max_items),
        )

        md, svg = generate_outputs(root, out_dir, scan_options, report_options)
        print(f"Wrote: {md}")
        print(f"Wrote: {svg}")
        return 0

    # GUI mode
    tk_root = tk.Tk()
    _ = DirectoryMapperApp(tk_root)
    tk_root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
