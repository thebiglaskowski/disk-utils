#!/usr/bin/env python3
"""
TreeSize CLI - Disk Space Analyzer
===================================
A beautiful terminal application for analyzing disk usage with
rich visualizations, progress indicators, and smart filtering.

Dependencies: pip install rich questionary ollama

Performance optimizations:
- Custom scandir-based walker (2-3x faster than os.walk on Windows)
- Path interning for memory reduction
- LRU caching for repeated computations
- Optimized directory size calculation
"""

# Optional Ollama integration for AI analysis
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

import os
import sys
import time
import heapq
import shutil
import csv
import json
import re
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict, Optional, Set, Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import threading
from functools import lru_cache

# Rich library for beautiful terminal output
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, MofNCompleteColumn, FileSizeColumn, TotalFileSizeColumn, TransferSpeedColumn
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from rich.live import Live
from rich.layout import Layout
from rich import box
from rich.bar import Bar
from rich.columns import Columns
from rich.markdown import Markdown

# Questionary for interactive menus
import questionary
from questionary import Style

# --- Configuration & Constants ---
console = Console()

# Size unit tuple (constant, not recreated each call)
SIZE_UNITS = ('B', 'KB', 'MB', 'GB', 'TB', 'PB')


def parse_size(size_str: str) -> Optional[int]:
    """Parse human-readable size string to bytes (e.g., '10MB', '1GB')."""
    if size_str is None:
        return None
    size_str = size_str.strip().upper()
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?$', size_str)
    if not match:
        try:
            result = int(size_str)
            return result if result >= 0 else None
        except ValueError:
            return None
    value = float(match.group(1))
    unit = match.group(2) or 'B'
    multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
    return int(value * multipliers.get(unit, 1))


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

# Icons for visual flair
ICONS = {
    'folder': '📂',
    'file': '📄',
    'disk': '💾',
    'chart': '📊',
    'settings': '⚙️',
    'export': '📤',
    'scan': '🔍',
    'exit': '🚪',
    'success': '✅',
    'warning': '⚠️',
    'error': '❌',
    'tree': '🌳',
    'clock': '⏱️',
    'speed': '⚡',
    'ai': '🤖',
}

# Custom style for questionary
MENU_STYLE = Style([
    ('qmark', 'fg:#673ab7 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#2196f3 bold'),
    ('pointer', 'fg:#673ab7 bold'),
    ('highlighted', 'fg:#673ab7 bold'),
    ('selected', 'fg:#2196f3'),
    ('separator', 'fg:#673ab7'),
    ('instruction', 'fg:#808080'),
])

# Directories to skip during scanning (significant speedup)
SKIP_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env',
    '$RECYCLE.BIN', 'System Volume Information', '.Trash-1000',
    'Windows', 'ProgramData', '.cache', '.npm', '.yarn',
    'AppData', '.local', 'site-packages', '.tox', '.pytest_cache',
}

# Path interning cache for memory optimization
_INTERNED_PATHS: Dict[str, str] = {}


def intern_path(path: str) -> str:
    """Intern paths to reduce memory usage from duplicate strings."""
    if path not in _INTERNED_PATHS:
        _INTERNED_PATHS[path] = sys.intern(path)
    return _INTERNED_PATHS[path]


def clear_path_cache() -> None:
    """Clear the path interning cache to free memory between scans."""
    _INTERNED_PATHS.clear()


def fast_walk(top: str, skip_dirs: Optional[Set[str]] = None, follow_symlinks: bool = False,
              max_depth: Optional[int] = None) -> Generator[Tuple[str, List[str], List[os.DirEntry], int], None, None]:
    """
    Fast directory walker using os.scandir() instead of os.walk().

    Returns DirEntry objects instead of filenames, avoiding redundant stat() calls.
    On Windows/NTFS, DirEntry.stat() is free (cached from directory entry).

    Yields: (dirpath, dirnames, file_entries, depth) where file_entries are DirEntry objects.
    """
    skip_dirs = skip_dirs or SKIP_DIRS
    top = os.path.abspath(top)

    # Use a stack for iterative traversal: (path, depth)
    stack = [(top, 0)]

    while stack:
        current_dir, depth = stack.pop()

        # Check depth limit
        if max_depth is not None and depth >= max_depth:
            continue

        dirnames = []
        file_entries = []

        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                        if is_dir:
                            if entry.name not in skip_dirs:
                                dirnames.append(entry.name)
                        elif entry.is_file(follow_symlinks=follow_symlinks):
                            file_entries.append(entry)
                    except OSError:
                        continue
        except OSError:
            continue

        # Yield current directory results with interned path
        yield intern_path(current_dir), dirnames, file_entries, depth

        # Add subdirectories to stack (reverse for consistent ordering)
        for dirname in reversed(dirnames):
            stack.append((os.path.join(current_dir, dirname), depth + 1))


def show_banner():
    """Display a styled startup banner."""
    banner = Text()
    banner.append("╔══════════════════════════════════════════════════════════════╗\n", style="bold cyan")
    banner.append("║", style="bold cyan")
    banner.append("           💾 TREESIZE CLI - Disk Analyzer 💾            ", style="bold white")
    banner.append("║\n", style="bold cyan")
    banner.append("║", style="bold cyan")
    banner.append("       Find the biggest files & folders on your drive    ", style="dim white")
    banner.append("║\n", style="bold cyan")
    banner.append("╚══════════════════════════════════════════════════════════════╝", style="bold cyan")
    console.print(banner)
    console.print()


@lru_cache(maxsize=1024)
def format_size(num_bytes: int) -> str:
    """Return human-readable file size. Cached for performance."""
    for unit in SIZE_UNITS:
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"


def get_size_style(size_bytes: int) -> str:
    """Get color style based on file size."""
    if size_bytes >= 1024 * 1024 * 1024:  # >= 1GB
        return "bold red"
    elif size_bytes >= 100 * 1024 * 1024:  # >= 100MB
        return "bold yellow"
    elif size_bytes >= 10 * 1024 * 1024:  # >= 10MB
        return "cyan"
    else:
        return "green"


def create_size_bar(size: int, max_size: int, width: int = 20) -> Text:
    """Create a visual bar representing relative size."""
    if max_size == 0:
        ratio = 0
    else:
        ratio = size / max_size
    
    filled = int(ratio * width)
    empty = width - filled
    
    bar = Text()
    bar.append("█" * filled, style=get_size_style(size))
    bar.append("░" * empty, style="dim")
    return bar


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
    # Clear path cache from previous scans to free memory
    clear_path_cache()

    root_path = os.path.abspath(root_path)
    file_heap = []
    total_files = 0
    total_size = 0
    extensions = defaultdict(lambda: {'count': 0, 'size': 0})
    start = time.time()

    # Quick mode minimum size
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

        # Use fast_walk with DirEntry objects (avoids redundant stat calls)
        for dirpath, dirnames, file_entries, depth in fast_walk(
            root_path, SKIP_DIRS, follow_symlinks, max_depth
        ):
            for entry in file_entries:
                try:
                    # DirEntry.stat() is cached on Windows NTFS - no extra syscall
                    st = entry.stat(follow_symlinks=follow_symlinks)
                    size = st.st_size
                    mtime = datetime.fromtimestamp(st.st_mtime)
                except (FileNotFoundError, PermissionError, OSError):
                    continue

                if size < effective_min_size:
                    continue

                # Extension filtering
                ext = os.path.splitext(entry.name)[1].lower().lstrip('.') or ''
                if include_extensions and ext not in include_extensions:
                    continue
                if exclude_extensions and ext in exclude_extensions:
                    continue

                # Age filtering
                if older_than and mtime > older_than:
                    continue
                if newer_than and mtime < newer_than:
                    continue

                total_files += 1
                total_size += size

                # Track extensions (with dot for display)
                ext_display = f'.{ext}' if ext else '(no ext)'
                extensions[ext_display]['count'] += 1
                extensions[ext_display]['size'] += size

                # Update progress every 500 files (less frequent = faster)
                if total_files % 500 == 0:
                    progress.update(task, files=total_files, size=format_size(total_size))

                # Build full path using interned directory
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
    
    # Get top extensions by size
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
    # Clear path cache from previous scans to free memory
    clear_path_cache()

    root_path = os.path.abspath(root_path)
    dir_sizes: Dict[str, int] = defaultdict(int)
    start = time.time()
    total_dirs = 0
    total_files = 0

    # Pre-compute path components for faster ancestor calculation
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

        # Use fast_walk with DirEntry objects
        for dirpath, dirnames, file_entries, depth in fast_walk(
            root_path, SKIP_DIRS, follow_symlinks, max_depth
        ):
            total_dirs += 1

            # Calculate size of files in this directory using cached stat
            for entry in file_entries:
                try:
                    # DirEntry.stat() is cached - no extra syscall on Windows
                    size = entry.stat(follow_symlinks=follow_symlinks).st_size
                    total_files += 1

                    # Optimized ancestor accumulation using string slicing
                    # Instead of repeated os.path.dirname calls
                    current = dirpath
                    while len(current) >= root_path_len:
                        dir_sizes[current] += size
                        # Find last separator
                        sep_pos = current.rfind(os.sep)
                        if sep_pos <= 0 or sep_pos < root_path_len:
                            break
                        current = current[:sep_pos]
                except (FileNotFoundError, PermissionError, OSError):
                    continue

            # Update progress every 200 directories
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


def print_file_results(largest_files: List[Tuple[int, str]], stats: Dict):
    """Display file scan results with rich formatting."""
    console.print()
    
    # Summary panel
    mode_text = "[yellow]QUICK MODE[/] (files >1MB only)" if stats.get('quick_mode') else ""
    summary = Table(box=box.ROUNDED, show_header=False, title=f"{ICONS['chart']} Scan Summary", title_style="bold")
    summary.add_column("Metric", style="dim")
    summary.add_column("Value", style="bold")
    
    summary.add_row("Files Scanned", f"{stats['total_files']:,}")
    summary.add_row("Total Size", format_size(stats['total_size']))
    summary.add_row("Time Elapsed", f"{stats['elapsed']:.2f}s")
    if mode_text:
        summary.add_row("Mode", mode_text)
    
    console.print(summary)
    
    if not largest_files:
        console.print(Panel(
            f"{ICONS['warning']} No files found matching criteria.",
            border_style="yellow"
        ))
        return
    
    # Results table with size bars
    max_size = largest_files[0][0] if largest_files else 1
    
    table = Table(
        title=f"{ICONS['file']} Top {len(largest_files)} Largest Files",
        box=box.ROUNDED,
        show_lines=False,
        title_style="bold cyan"
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Size", justify="right", width=12)
    table.add_column("", width=20)  # Size bar
    table.add_column("Path")
    
    for i, (size, path) in enumerate(largest_files, start=1):
        size_text = Text(format_size(size), style=get_size_style(size))
        size_bar = create_size_bar(size, max_size)
        table.add_row(str(i), size_text, size_bar, path)
    
    console.print()
    console.print(table)
    
    # Extension breakdown
    if stats.get('top_extensions'):
        console.print()
        ext_table = Table(
            title=f"{ICONS['chart']} Top Extensions by Size",
            box=box.SIMPLE,
            show_header=True,
            title_style="bold"
        )
        ext_table.add_column("Extension", style="cyan")
        ext_table.add_column("Files", justify="right")
        ext_table.add_column("Total Size", justify="right")
        
        for ext, data in stats['top_extensions'][:5]:
            ext_table.add_row(
                ext,
                f"{data['count']:,}",
                Text(format_size(data['size']), style=get_size_style(data['size']))
            )
        
        console.print(ext_table)


def get_item_emoji(path: str, is_dir: bool = True) -> str:
    """Get an appropriate emoji for a file/directory based on its name."""
    name = os.path.basename(path).lower()

    if is_dir:
        # Directory patterns
        if any(x in name for x in ['game', 'steam', 'epic', 'fortnite', 'minecraft']):
            return '🎮'
        elif any(x in name for x in ['photo', 'picture', 'image', 'dcim', 'camera']):
            return '📸'
        elif any(x in name for x in ['video', 'movie', 'film']):
            return '🎬'
        elif any(x in name for x in ['music', 'audio', 'spotify']):
            return '🎵'
        elif any(x in name for x in ['download']):
            return '📥'
        elif any(x in name for x in ['document', 'doc']):
            return '📝'
        elif any(x in name for x in ['backup', 'archive']):
            return '💾'
        elif any(x in name for x in ['cache', 'temp', 'tmp']):
            return '🗑️'
        elif any(x in name for x in ['node_modules', 'venv', '.git', 'package']):
            return '📦'
        elif any(x in name for x in ['program', 'app', 'software']):
            return '⚙️'
        elif any(x in name for x in ['user', 'profile']):
            return '👤'
        elif any(x in name for x in ['system', 'windows']):
            return '🖥️'
        elif any(x in name for x in ['model', 'ollama', 'llm', 'ai']):
            return '🤖'
        return '📁'
    else:
        # File patterns
        ext = os.path.splitext(name)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            return '🖼️'
        elif ext in ['.mp4', '.mkv', '.avi', '.mov', '.wmv']:
            return '🎬'
        elif ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg']:
            return '🎵'
        elif ext in ['.zip', '.rar', '.7z', '.tar', '.gz']:
            return '📦'
        elif ext in ['.exe', '.msi', '.dll']:
            return '⚙️'
        elif ext in ['.pdf']:
            return '📕'
        elif ext in ['.doc', '.docx', '.txt', '.md']:
            return '📝'
        elif ext in ['.iso', '.img']:
            return '💿'
        elif ext in ['.log', '.tmp']:
            return '🗑️'
        return '📄'


def print_treemap(data: List[Tuple[int, str]], total_size: int, title: str = "Treemap"):
    """Display a terminal-based treemap visualization as a readable bar chart."""
    if not data:
        return

    console.print()

    # Determine if this is files or directories
    is_dirs = "Director" in title

    # Create a table for the treemap
    table = Table(
        title=f"{'📊' if is_dirs else '📈'} {title}",
        box=box.ROUNDED,
        title_style="bold cyan",
        show_header=True,
        header_style="bold"
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("", width=2)  # Emoji column
    table.add_column("Name", style="cyan", max_width=40)
    table.add_column("Size", justify="right", width=10)
    table.add_column("%", justify="right", width=6)
    table.add_column("Usage", width=30)

    max_size = data[0][0] if data else 1
    bar_width = 25

    for i, (size, path) in enumerate(data[:20], start=1):  # Top 20
        pct = (size / total_size) * 100 if total_size > 0 else 0

        # Get display name
        name = os.path.basename(path) or path
        if len(name) > 38:
            name = name[:35] + "..."

        # Get emoji
        emoji = get_item_emoji(path, is_dirs)

        # Create visual bar
        filled = int((size / max_size) * bar_width)
        bar = Text()
        bar.append("█" * filled, style=get_size_style(size))
        bar.append("░" * (bar_width - filled), style="dim")

        table.add_row(
            str(i),
            emoji,
            name,
            format_size(size),
            f"{pct:.1f}%",
            bar
        )

    console.print(table)

    # Summary footer
    other_count = len(data) - 20 if len(data) > 20 else 0
    if other_count > 0:
        other_size = sum(size for size, _ in data[20:])
        other_pct = (other_size / total_size) * 100 if total_size > 0 else 0
        console.print(f"[dim]  ... and {other_count} more items ({format_size(other_size)}, {other_pct:.1f}%)[/]")

    console.print()
    console.print(f"[dim]Total: {format_size(total_size)}[/]")


def print_dir_results(largest_dirs: List[Tuple[int, str]], stats: Dict):
    """Display directory scan results with rich formatting."""
    console.print()
    
    summary = Table(box=box.ROUNDED, show_header=False, title=f"{ICONS['chart']} Scan Summary", title_style="bold")
    summary.add_column("Metric", style="dim")
    summary.add_column("Value", style="bold")
    
    summary.add_row("Directories Scanned", f"{stats['total_dirs']:,}")
    summary.add_row("Dirs Meeting Min Size", f"{stats['dirs_meeting_min']:,}")
    summary.add_row("Time Elapsed", f"{stats['elapsed']:.2f}s")
    
    console.print(summary)
    
    if not largest_dirs:
        console.print(Panel(
            f"{ICONS['warning']} No directories found matching criteria.",
            border_style="yellow"
        ))
        return
    
    max_size = largest_dirs[0][0] if largest_dirs else 1
    
    table = Table(
        title=f"{ICONS['folder']} Top {len(largest_dirs)} Largest Directories",
        box=box.ROUNDED,
        show_lines=False,
        title_style="bold cyan"
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Size", justify="right", width=12)
    table.add_column("", width=20)
    table.add_column("Directory")
    
    for i, (size, path) in enumerate(largest_dirs, start=1):
        size_text = Text(format_size(size), style=get_size_style(size))
        size_bar = create_size_bar(size, max_size)
        table.add_row(str(i), size_text, size_bar, path)
    
    console.print()
    console.print(table)


def analyze_file_ages(root_path: str, follow_symlinks: bool = False) -> Dict:
    """Analyze file age distribution in a directory using optimized fast_walk."""
    # Clear path cache from previous scans to free memory
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

        # Use fast_walk with DirEntry objects
        for dirpath, dirnames, file_entries, depth in fast_walk(root_path, SKIP_DIRS, follow_symlinks):
            for entry in file_entries:
                try:
                    # DirEntry.stat() is cached - no extra syscall on Windows
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


def print_age_analysis(age_buckets: Dict):
    """Display file age analysis results."""
    console.print()

    table = Table(
        title=f"{ICONS['clock']} File Age Distribution",
        box=box.ROUNDED,
        title_style="bold cyan"
    )
    table.add_column("Age", style="cyan")
    table.add_column("Files", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("", width=30)

    total_size = sum(b['size'] for b in age_buckets.values())
    max_size = max(b['size'] for b in age_buckets.values()) if age_buckets else 1

    for bucket, data in age_buckets.items():
        size_bar = create_size_bar(data['size'], max_size, width=30)
        table.add_row(
            bucket,
            f"{data['count']:,}",
            Text(format_size(data['size']), style=get_size_style(data['size'])),
            size_bar
        )

    console.print(table)

    # Highlight old files
    old_size = age_buckets['> 1 year']['size'] + age_buckets['6-12 months']['size']
    if old_size > 0 and total_size > 0:
        pct = (old_size / total_size) * 100
        console.print()
        console.print(Panel(
            f"[bold yellow]{format_size(old_size)}[/] ({pct:.1f}%) of files are older than 6 months.\n"
            f"[dim]Consider reviewing these files for potential cleanup.[/]",
            title=f"{ICONS['warning']} Cleanup Opportunity",
            border_style="yellow"
        ))


def print_disk_usage(path: str):
    """Print disk usage with visual gauge."""
    try:
        total, used, free = shutil.disk_usage(path)
    except FileNotFoundError:
        console.print(f"[red]{ICONS['error']} Path not found: {path}[/]")
        return

    if total == 0:
        console.print(f"[yellow]{ICONS['warning']} Unable to determine disk usage for: {path}[/]")
        return

    pct_used = (used / total) * 100
    pct_free = 100 - pct_used
    
    # Color based on usage
    if pct_used >= 90:
        bar_style = "red"
        status = f"{ICONS['warning']} CRITICAL"
    elif pct_used >= 75:
        bar_style = "yellow"
        status = f"{ICONS['warning']} Warning"
    else:
        bar_style = "green"
        status = f"{ICONS['success']} Healthy"
    
    console.print()
    console.print(Panel(
        f"[bold]{os.path.abspath(path)}[/]",
        title=f"{ICONS['disk']} Disk Usage",
        border_style="cyan"
    ))
    
    # Visual gauge
    bar_width = 40
    filled = int((used / total) * bar_width)
    empty = bar_width - filled
    
    gauge = Text()
    gauge.append("  [", style="dim")
    gauge.append("█" * filled, style=bar_style)
    gauge.append("░" * empty, style="dim")
    gauge.append("]", style="dim")
    gauge.append(f"  {pct_used:.1f}% used", style=bar_style)
    
    console.print(gauge)
    console.print()
    
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("", width=15)
    table.add_column("", justify="right")
    
    table.add_row("Total Space", format_size(total))
    table.add_row("Used", Text(format_size(used), style=bar_style))
    table.add_row("Free", Text(format_size(free), style="green"))
    table.add_row("Status", status)
    
    console.print(table)


def export_results(last_results: Dict, format_type: str = 'csv'):
    """Export results to CSV or JSON."""
    if last_results is None:
        console.print(f"[yellow]{ICONS['warning']} No scan results available to export.[/]")
        return

    result_type = last_results["type"]
    entries = last_results["data"]
    stats = last_results["stats"]

    if not entries:
        console.print(f"[yellow]{ICONS['warning']} No entries in last scan to export.[/]")
        return

    default_name = f"treesize_{result_type}.{format_type}"
    filename = questionary.text(
        f"Enter filename (default: {default_name}):",
        default=default_name,
        style=MENU_STYLE
    ).ask()
    
    if not filename:
        return

    try:
        if format_type == 'json':
            export_data = {
                "type": result_type,
                "stats": stats,
                "entries": [{"size": size, "size_human": format_size(size), "path": path} 
                           for size, path in entries]
            }
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, default=str)
        else:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Index", "Path", "SizeBytes", "SizeHuman"])
                for i, (size, path) in enumerate(entries, start=1):
                    writer.writerow([i, path, size, format_size(size)])

        console.print(f"[green]{ICONS['success']} Exported {len(entries)} entries to: {filename}[/]")
    except OSError as e:
        console.print(f"[red]{ICONS['error']} Failed to write file: {e}[/]")


def get_ollama_models() -> List[str]:
    """Get list of available Ollama models."""
    if not OLLAMA_AVAILABLE:
        console.print("[dim]Ollama Python package not installed. Run: pip install ollama[/]")
        return []
    try:
        models = ollama.list()
        # Handle different response formats (newer versions use 'model' instead of 'name')
        # Filter out None values in case both keys are missing
        return [
            name for m in models.get('models', [])
            if (name := m.get('name') or m.get('model'))
        ]
    except Exception as e:
        console.print(f"[dim]Ollama error: {e}[/]")
        return []


def check_ollama_running() -> bool:
    """Check if Ollama server is running."""
    if not OLLAMA_AVAILABLE:
        return False
    try:
        ollama.list()
        return True
    except Exception as e:
        # Show error for debugging
        console.print(f"[dim]Ollama connection failed: {type(e).__name__}: {e}[/]")
        return False


def ai_analyze_results(results: Dict, model: str) -> str:
    """Send scan results to Ollama for AI analysis."""
    if not OLLAMA_AVAILABLE or not results:
        return "AI analysis unavailable."
    
    result_type = results.get("type", "files")
    data = results.get("data", [])
    stats = results.get("stats", {})
    
    # Format results for the prompt
    if result_type == "files":
        items_text = "\n".join([
            f"  {i+1}. {format_size(size)} - {path}"
            for i, (size, path) in enumerate(data[:20])  # Limit to top 20
        ])
        prompt = f"""Analyze these largest files found on a disk scan and provide cleanup recommendations.

Scan Statistics:
- Total files scanned: {stats.get('total_files', 'N/A'):,}
- Total size: {format_size(stats.get('total_size', 0))}

Top {min(20, len(data))} Largest Files:
{items_text}

Format your response as follows (use these exact headers with emojis):

## 🗂️ File Categories
Briefly categorize what types of files were found.

## ✅ Safe to Delete
List files/patterns that are likely safe to remove (temp files, caches, old logs, etc.).
Use bullet points with the file name/path and brief reason.

## ⚠️ Review Before Deleting
List files that need user review before deletion.
Use bullet points with the file name/path and why it needs review.

## 🛡️ Keep (Do Not Delete)
List important files that should NOT be deleted (system files, important documents).
Use bullet points with the file name/path and why it's important.

## 💡 Recommendations
Provide 2-3 specific, actionable cleanup recommendations.

Be concise. Use short bullet points."""
    else:
        items_text = "\n".join([
            f"  {i+1}. {format_size(size)} - {path}"
            for i, (size, path) in enumerate(data[:20])
        ])
        prompt = f"""Analyze these largest directories found on a disk scan and provide cleanup recommendations.

Scan Statistics:
- Total directories scanned: {stats.get('total_dirs', 'N/A'):,}

Top {min(20, len(data))} Largest Directories:
{items_text}

Format your response as follows (use these exact headers with emojis):

## 🗂️ Directory Overview
Briefly describe what's taking up the most space.

## ✅ Safe to Clean
List directories that likely contain unnecessary data (node_modules, caches, temp files, old backups).
Use bullet points with the directory and brief reason.

## ⚠️ Review Before Cleaning
List directories that need user review before any cleanup.
Use bullet points with the directory and why.

## 🛡️ Do Not Delete
List system folders and important data directories that should NOT be touched.
Use bullet points with the directory and why it's critical.

## 💡 Recommendations
Provide 2-3 specific, actionable cleanup recommendations.

Be concise. Use short bullet points."""
    
    try:
        with console.status(f"[cyan]{ICONS['ai']} Analyzing with {model}...", spinner="dots"):
            response = ollama.chat(
                model=model,
                messages=[{'role': 'user', 'content': prompt}]
            )
        return response['message']['content']
    except Exception as e:
        return f"AI analysis failed: {e}"


def load_settings(config_path: str) -> dict:
    """Load settings from JSON config file."""
    default_settings = {
        "top_n": 50,
        "min_file_size_bytes": 0,
        "min_dir_size_bytes": 0,
        "follow_symlinks": False,
        "default_path": os.getcwd(),
        "max_depth": None,
        "quick_mode": False,
        "ollama_model": None,
        "ollama_enabled": True,
    }
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_settings.update(saved)
    except (json.JSONDecodeError, IOError):
        pass
    return default_settings


def save_settings(settings: dict, config_path: str):
    """Save settings to JSON config file."""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except IOError as e:
        console.print(f"[yellow]{ICONS['warning']} Could not save settings: {e}[/]")


def settings_menu(settings: dict, config_path: str) -> dict:
    """Interactive settings menu."""
    first_run = True
    while True:
        if first_run:
            console.clear()
            first_run = False
        console.print(Panel(
            "[bold]Configure scan parameters[/]",
            title=f"{ICONS['settings']} Settings",
            border_style="cyan"
        ))
        
        # Show current settings
        settings_table = Table(box=box.SIMPLE, show_header=False)
        settings_table.add_column("Setting", style="dim")
        settings_table.add_column("Value", style="bold")
        
        settings_table.add_row("Default Path", settings['default_path'])
        settings_table.add_row("Top N Entries", str(settings['top_n']))
        settings_table.add_row("Min File Size", format_size(settings['min_file_size_bytes']) if settings['min_file_size_bytes'] > 0 else "None")
        settings_table.add_row("Min Dir Size", format_size(settings['min_dir_size_bytes']) if settings['min_dir_size_bytes'] > 0 else "None")
        settings_table.add_row("Follow Symlinks", "Yes" if settings['follow_symlinks'] else "No")
        settings_table.add_row("Max Depth", str(settings['max_depth']) if settings['max_depth'] else "Unlimited")
        settings_table.add_row("Quick Mode", "On" if settings.get('quick_mode') else "Off")
        
        # Show AI settings if available
        ollama_status = "Available" if check_ollama_running() else "Not running"
        settings_table.add_row("Ollama Status", ollama_status)
        settings_table.add_row("AI Model", settings.get('ollama_model') or "Not selected")
        
        console.print(settings_table)
        console.print()
        
        choice = questionary.select(
            "Select setting to change:",
            choices=[
                questionary.Choice(f"📂 Default Path", value="path"),
                questionary.Choice(f"🔢 Top N Entries ({settings['top_n']})", value="top_n"),
                questionary.Choice(f"📄 Min File Size ({format_size(settings['min_file_size_bytes'])})", value="min_file"),
                questionary.Choice(f"📁 Min Directory Size ({format_size(settings['min_dir_size_bytes'])})", value="min_dir"),
                questionary.Choice(f"🔗 Follow Symlinks ({'Yes' if settings['follow_symlinks'] else 'No'})", value="symlinks"),
                questionary.Choice(f"📏 Max Scan Depth ({settings['max_depth'] or 'Unlimited'})", value="depth"),
                questionary.Choice(f"⚡ Quick Mode ({'On' if settings.get('quick_mode') else 'Off'})", value="quick"),
                questionary.Choice(f"🤖 Select AI Model ({settings.get('ollama_model') or 'None'})", value="ai_model"),
                questionary.Choice(f"⬅️  Back to Main Menu", value="back"),
            ],
            style=MENU_STYLE
        ).ask()
        
        if choice is None or choice == "back":
            break
        elif choice == "path":
            new_path = questionary.path(
                "Enter new default path:",
                only_directories=True,
                style=MENU_STYLE
            ).ask()
            if new_path and os.path.exists(new_path):
                settings['default_path'] = new_path
                save_settings(settings, config_path)
        elif choice == "top_n":
            value = questionary.text(
                "Enter number of top entries to show:",
                default=str(settings['top_n']),
                style=MENU_STYLE
            ).ask()
            if value and value.isdigit():
                settings['top_n'] = max(1, int(value))
                save_settings(settings, config_path)
        elif choice == "min_file":
            value = questionary.text(
                "Enter minimum file size in MB (0 for none):",
                default=str(settings['min_file_size_bytes'] // (1024*1024)),
                style=MENU_STYLE
            ).ask()
            if value and value.isdigit():
                settings['min_file_size_bytes'] = int(value) * 1024 * 1024
                save_settings(settings, config_path)
        elif choice == "min_dir":
            value = questionary.text(
                "Enter minimum directory size in MB (0 for none):",
                default=str(settings['min_dir_size_bytes'] // (1024*1024)),
                style=MENU_STYLE
            ).ask()
            if value and value.isdigit():
                settings['min_dir_size_bytes'] = int(value) * 1024 * 1024
                save_settings(settings, config_path)
        elif choice == "symlinks":
            settings['follow_symlinks'] = not settings['follow_symlinks']
            save_settings(settings, config_path)
        elif choice == "depth":
            value = questionary.text(
                "Enter max depth (0 for unlimited):",
                default=str(settings['max_depth'] or 0),
                style=MENU_STYLE
            ).ask()
            if value and value.isdigit():
                settings['max_depth'] = int(value) if int(value) > 0 else None
                save_settings(settings, config_path)
        elif choice == "quick":
            settings['quick_mode'] = not settings.get('quick_mode', False)
            save_settings(settings, config_path)
        elif choice == "ai_model":
            models = get_ollama_models()
            if not models:
                console.print(f"\n[yellow]{ICONS['warning']} No Ollama models found. Make sure Ollama is running.[/]")
                console.print("[dim]Run 'ollama list' to see available models, or 'ollama pull llama3.2' to download one.[/]")
                questionary.press_any_key_to_continue(style=MENU_STYLE).ask()
            else:
                model_choices = [questionary.Choice(m, value=m) for m in models]
                model_choices.append(questionary.Choice("Cancel", value=None))
                selected = questionary.select(
                    "Select Ollama model for AI analysis:",
                    choices=model_choices,
                    style=MENU_STYLE
                ).ask()
                if selected:
                    settings['ollama_model'] = selected
                    save_settings(settings, config_path)
                    console.print(f"[green]{ICONS['success']} Model set to: {selected}[/]")
    
    return settings


def main_menu():
    """Main interactive menu."""
    config_dir = Path.home() / ".treesize"
    config_dir.mkdir(exist_ok=True)
    config_path = str(config_dir / "settings.json")

    settings = load_settings(config_path)
    last_results = None

    while True:
        console.clear()
        show_banner()
        
        # Quick status
        console.print(f"[dim]Default path: {settings['default_path']}[/]")
        console.print()
        
        # Build menu choices dynamically based on Ollama availability
        menu_choices = [
            questionary.Choice(f"{ICONS['file']} Scan for Largest Files", value="files"),
            questionary.Choice(f"{ICONS['folder']} Scan for Largest Directories", value="dirs"),
            questionary.Choice(f"{ICONS['clock']} Analyze File Ages", value="ages"),
            questionary.Choice(f"{ICONS['disk']} Show Disk Usage", value="disk"),
            questionary.Choice(f"{ICONS['tree']} Show Treemap", value="treemap"),
            questionary.Choice(f"{ICONS['chart']} View Last Scan Results", value="view"),
            questionary.Choice(f"{ICONS['ai']} AI Analysis (Ollama)", value="ai"),
            questionary.Choice(f"{ICONS['export']} Export Results (CSV/JSON)", value="export"),
            questionary.Choice(f"{ICONS['settings']} Settings", value="settings"),
            questionary.Choice(f"{ICONS['exit']} Exit", value="exit"),
        ]
        
        choice = questionary.select(
            "What would you like to do?",
            choices=menu_choices,
            style=MENU_STYLE
        ).ask()

        if choice is None or choice == "exit":
            console.print(f"\n{ICONS['success']} Goodbye!")
            break

        elif choice == "files":
            path = questionary.path(
                f"Enter path to scan (default: {settings['default_path']}):",
                default=settings['default_path'],
                only_directories=True,
                style=MENU_STYLE
            ).ask()
            
            if not path:
                continue
            if not os.path.exists(path):
                console.print(f"[red]{ICONS['error']} Path does not exist: {path}[/]")
                questionary.press_any_key_to_continue(style=MENU_STYLE).ask()
                continue

            try:
                largest_files, stats = scan_largest_files(
                    path,
                    top_n=settings["top_n"],
                    min_size_bytes=settings["min_file_size_bytes"],
                    follow_symlinks=settings["follow_symlinks"],
                    max_depth=settings["max_depth"],
                    quick_mode=settings.get('quick_mode', False),
                )
                last_results = {"type": "files", "data": largest_files, "stats": stats}
                print_file_results(largest_files, stats)
            except KeyboardInterrupt:
                console.print(f"\n[yellow]{ICONS['warning']} Scan cancelled.[/]")
            
            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice == "dirs":
            path = questionary.path(
                f"Enter path to scan (default: {settings['default_path']}):",
                default=settings['default_path'],
                only_directories=True,
                style=MENU_STYLE
            ).ask()
            
            if not path:
                continue
            if not os.path.exists(path):
                console.print(f"[red]{ICONS['error']} Path does not exist: {path}[/]")
                questionary.press_any_key_to_continue(style=MENU_STYLE).ask()
                continue

            try:
                largest_dirs, stats = scan_largest_dirs(
                    path,
                    top_n=settings["top_n"],
                    min_size_bytes=settings["min_dir_size_bytes"],
                    follow_symlinks=settings["follow_symlinks"],
                    max_depth=settings["max_depth"],
                )
                last_results = {"type": "dirs", "data": largest_dirs, "stats": stats}
                print_dir_results(largest_dirs, stats)
            except KeyboardInterrupt:
                console.print(f"\n[yellow]{ICONS['warning']} Scan cancelled.[/]")
            
            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice == "ages":
            path = questionary.path(
                f"Enter path to analyze (default: {settings['default_path']}):",
                default=settings['default_path'],
                only_directories=True,
                style=MENU_STYLE
            ).ask()

            if not path:
                continue
            if not os.path.exists(path):
                console.print(f"[red]{ICONS['error']} Path does not exist: {path}[/]")
                questionary.press_any_key_to_continue(style=MENU_STYLE).ask()
                continue

            try:
                age_buckets = analyze_file_ages(path, settings["follow_symlinks"])
                print_age_analysis(age_buckets)
            except KeyboardInterrupt:
                console.print(f"\n[yellow]{ICONS['warning']} Analysis cancelled.[/]")

            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice == "disk":
            path = questionary.path(
                f"Enter path to check (default: {settings['default_path']}):",
                default=settings['default_path'],
                only_directories=True,
                style=MENU_STYLE
            ).ask()

            if path:
                print_disk_usage(path)
            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice == "treemap":
            if last_results is None:
                console.print(f"\n[yellow]{ICONS['warning']} No scan results available. Run a scan first.[/]")
            else:
                total = last_results["stats"].get("total_size", 0)
                if total == 0:
                    # For directory results, calculate total from data
                    total = sum(size for size, _ in last_results["data"])
                title = "Largest Files" if last_results["type"] == "files" else "Largest Directories"
                print_treemap(last_results["data"], total, title)
            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice == "view":
            if last_results is None:
                console.print(f"\n[yellow]{ICONS['warning']} No previous scan results available.[/]")
            else:
                if last_results["type"] == "files":
                    print_file_results(last_results["data"], last_results["stats"])
                else:
                    print_dir_results(last_results["data"], last_results["stats"])
            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice == "export":
            if last_results is None:
                console.print(f"\n[yellow]{ICONS['warning']} No results to export.[/]")
            else:
                format_choice = questionary.select(
                    "Export format:",
                    choices=[
                        questionary.Choice("📄 CSV", value="csv"),
                        questionary.Choice("📋 JSON", value="json"),
                    ],
                    style=MENU_STYLE
                ).ask()
                if format_choice:
                    export_results(last_results, format_choice)
            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice == "ai":
            if last_results is None:
                console.print(f"\n[yellow]{ICONS['warning']} No scan results available. Run a scan first.[/]")
            elif not check_ollama_running():
                console.print(f"\n[red]{ICONS['error']} Ollama is not running.[/]")
                console.print("[dim]Start Ollama with 'ollama serve' and try again.[/]")
            elif not settings.get('ollama_model'):
                console.print(f"\n[yellow]{ICONS['warning']} No AI model selected.[/]")
                console.print("[dim]Go to Settings > Select AI Model to choose one.[/]")
            else:
                console.print()
                console.print(Panel(
                    f"Analyzing {last_results['type']} scan results with [bold]{settings['ollama_model']}[/]",
                    title=f"{ICONS['ai']} AI Analysis",
                    border_style="cyan"
                ))
                
                analysis = ai_analyze_results(last_results, settings['ollama_model'])

                console.print()
                # Render as Markdown for proper formatting
                md = Markdown(analysis)
                console.print(Panel(
                    md,
                    title=f"{ICONS['success']} AI Recommendations",
                    border_style="green",
                    padding=(1, 2)
                ))
            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice == "settings":
            settings = settings_menu(settings, config_path)


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        console.print(f"\n[yellow]Exiting...[/]")
