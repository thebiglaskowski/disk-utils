#!/usr/bin/env python3
"""
TreeSize Scanning Engine
========================
Core scanning functions for analyzing disk usage: largest files,
largest directories, and file age distribution.
"""

import os
import time
import heapq
import re
from collections import defaultdict
from typing import List, Tuple, Dict, Optional, Set
from datetime import datetime, timedelta

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from utils import SKIP_DIRS, format_size, fast_walk, clear_path_cache

console = Console()

ICONS = {
    'folder': '📂',
    'scan': '🔍',
    'tree': '🌳',
    'clock': '⏱️',
    'speed': '⚡',
    'warning': '⚠️',
}


def parse_age(age_str: str) -> Optional[datetime]:
    """Parse age string to cutoff datetime (e.g., '7d', '30d', '1y')."""
    if age_str is None:
        return None
    age_str = age_str.strip().lower()
    match = re.match(r'^(\d+)\s*(d|w|m|y)$', age_str)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 'd':
        delta = timedelta(days=value)
    elif unit == 'w':
        delta = timedelta(weeks=value)
    elif unit == 'm':
        delta = timedelta(days=value * 30)
    elif unit == 'y':
        delta = timedelta(days=value * 365)
    else:
        return None
    return datetime.now() - delta


def scan_largest_files(
    root_path: str,
    top_n: int = 50,
    min_size_bytes: int = 0,
    follow_symlinks: bool = False,
    max_depth: Optional[int] = None,
    quick_mode: bool = False,
    older_than: Optional[datetime] = None,
    newer_than: Optional[datetime] = None,
    include_extensions: Optional[Set[str]] = None,
    exclude_extensions: Optional[Set[str]] = None,
) -> Tuple[List[Tuple[int, str]], Dict]:
    """
    Scan for largest files with rich progress display.
    Uses optimized fast_walk for 2-3x speedup on Windows.
    """
    clear_path_cache()

    root_path = os.path.abspath(root_path)
    file_heap = []
    total_files = 0
    total_size = 0
    extensions = defaultdict(lambda: {'count': 0, 'size': 0})
    start = time.time()

    effective_min_size = max(min_size_bytes, 1024 * 1024) if quick_mode else min_size_bytes

    console.print(Panel(
        f"{ICONS['folder']} [bold]{root_path}[/]\n"
        f"[dim]{ICONS['speed']} Using optimized scandir walker[/]",
        title=f"{ICONS['scan']} Scanning for Files",
        border_style="blue"
    ))
    console.print(f"[dim]Skipping: {', '.join(sorted(SKIP_DIRS)[:5])}...[/]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[cyan]{task.fields[files]:,}[/] files"),
        TextColumn("•"),
        TextColumn("[green]{task.fields[size]}[/]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            "[cyan]Scanning...",
            files=0,
            size="0 B",
            total=None
        )

        for dirpath, dirnames, file_entries, depth in fast_walk(
            root_path, SKIP_DIRS, follow_symlinks, max_depth
        ):
            for entry in file_entries:
                try:
                    st = entry.stat(follow_symlinks=follow_symlinks)
                    size = st.st_size
                    mtime = datetime.fromtimestamp(st.st_mtime)
                except (FileNotFoundError, PermissionError, OSError):
                    continue

                if size < effective_min_size:
                    continue

                ext = os.path.splitext(entry.name)[1].lower().lstrip('.') or ''
                if include_extensions and ext not in include_extensions:
                    continue
                if exclude_extensions and ext in exclude_extensions:
                    continue

                if older_than and mtime > older_than:
                    continue
                if newer_than and mtime < newer_than:
                    continue

                total_files += 1
                total_size += size

                ext_display = f'.{ext}' if ext else '(no ext)'
                extensions[ext_display]['count'] += 1
                extensions[ext_display]['size'] += size

                if total_files % 500 == 0:
                    progress.update(task, files=total_files, size=format_size(total_size))

                full_path = os.path.join(dirpath, entry.name)
                item = (size, full_path)
                if len(file_heap) < top_n:
                    heapq.heappush(file_heap, item)
                else:
                    if size > file_heap[0][0]:
                        heapq.heapreplace(file_heap, item)

        progress.update(task, files=total_files, size=format_size(total_size))

    elapsed = time.time() - start
    largest_files = sorted(file_heap, key=lambda x: x[0], reverse=True)

    top_extensions = sorted(extensions.items(), key=lambda x: x[1]['size'], reverse=True)[:10]

    stats = {
        "root_path": root_path,
        "total_files": total_files,
        "total_size": total_size,
        "elapsed": elapsed,
        "top_n": top_n,
        "min_size_bytes": effective_min_size,
        "max_depth": max_depth,
        "top_extensions": top_extensions,
        "quick_mode": quick_mode,
    }
    return largest_files, stats


def scan_largest_dirs(
    root_path: str,
    top_n: int = 50,
    min_size_bytes: int = 0,
    follow_symlinks: bool = False,
    max_depth: Optional[int] = None,
) -> Tuple[List[Tuple[int, str]], Dict]:
    """
    Compute total size per directory and return top_n largest.
    Uses optimized fast_walk and efficient path accumulation.
    """
    clear_path_cache()

    root_path = os.path.abspath(root_path)
    dir_sizes: Dict[str, int] = defaultdict(int)
    start = time.time()
    total_dirs = 0
    total_files = 0

    root_path_len = len(root_path)

    console.print(Panel(
        f"{ICONS['folder']} [bold]{root_path}[/]\n"
        f"[dim]{ICONS['speed']} Using optimized scandir walker[/]",
        title=f"{ICONS['tree']} Scanning Directories",
        border_style="blue"
    ))
    console.print(f"[dim]Skipping: {', '.join(sorted(SKIP_DIRS)[:5])}...[/]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("[cyan]{task.fields[dirs]:,}[/] directories"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("[cyan]Calculating sizes...", dirs=0)

        for dirpath, dirnames, file_entries, depth in fast_walk(
            root_path, SKIP_DIRS, follow_symlinks, max_depth
        ):
            total_dirs += 1

            for entry in file_entries:
                try:
                    size = entry.stat(follow_symlinks=follow_symlinks).st_size
                    total_files += 1

                    current = dirpath
                    while len(current) >= root_path_len:
                        dir_sizes[current] += size
                        sep_pos = current.rfind(os.sep)
                        if sep_pos <= 0 or sep_pos < root_path_len:
                            break
                        current = current[:sep_pos]
                except (FileNotFoundError, PermissionError, OSError):
                    continue

            if total_dirs % 200 == 0:
                progress.update(task, dirs=total_dirs)

        progress.update(task, dirs=total_dirs)

    heap = []
    kept_dirs_count = 0
    for dpath, size in dir_sizes.items():
        if size < min_size_bytes:
            continue
        kept_dirs_count += 1
        item = (size, dpath)
        if len(heap) < top_n:
            heapq.heappush(heap, item)
        else:
            if size > heap[0][0]:
                heapq.heapreplace(heap, item)

    elapsed = time.time() - start
    largest_dirs = sorted(heap, key=lambda x: x[0], reverse=True)

    stats = {
        "root_path": root_path,
        "total_dirs": total_dirs,
        "dirs_meeting_min": kept_dirs_count,
        "elapsed": elapsed,
        "top_n": top_n,
        "min_size_bytes": min_size_bytes,
        "max_depth": max_depth,
    }
    return largest_dirs, stats


def analyze_file_ages(root_path: str, follow_symlinks: bool = False) -> Dict:
    """Analyze file age distribution in a directory using optimized fast_walk."""
    clear_path_cache()

    root_path = os.path.abspath(root_path)
    now = datetime.now()

    age_buckets = {
        '< 7 days': {'count': 0, 'size': 0},
        '7-30 days': {'count': 0, 'size': 0},
        '1-3 months': {'count': 0, 'size': 0},
        '3-6 months': {'count': 0, 'size': 0},
        '6-12 months': {'count': 0, 'size': 0},
        '> 1 year': {'count': 0, 'size': 0},
    }

    thresholds = [
        (timedelta(days=7), '< 7 days'),
        (timedelta(days=30), '7-30 days'),
        (timedelta(days=90), '1-3 months'),
        (timedelta(days=180), '3-6 months'),
        (timedelta(days=365), '6-12 months'),
    ]

    console.print(Panel(
        f"{ICONS['folder']} [bold]{root_path}[/]\n"
        f"[dim]{ICONS['speed']} Using optimized scandir walker[/]",
        title=f"{ICONS['clock']} Analyzing File Ages",
        border_style="blue"
    ))

    total_files = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("[cyan]{task.fields[files]:,}[/] files"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Scanning...", files=0)

        for dirpath, dirnames, file_entries, depth in fast_walk(root_path, SKIP_DIRS, follow_symlinks):
            for entry in file_entries:
                try:
                    st = entry.stat(follow_symlinks=follow_symlinks)
                    size = st.st_size
                    mtime = datetime.fromtimestamp(st.st_mtime)
                    age = now - mtime

                    bucket = '> 1 year'
                    for threshold, bucket_name in thresholds:
                        if age < threshold:
                            bucket = bucket_name
                            break

                    age_buckets[bucket]['count'] += 1
                    age_buckets[bucket]['size'] += size
                    total_files += 1

                    if total_files % 1000 == 0:
                        progress.update(task, files=total_files)
                except (FileNotFoundError, PermissionError, OSError):
                    continue

        progress.update(task, files=total_files)

    return age_buckets
