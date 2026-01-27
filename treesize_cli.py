#!/usr/bin/env python3
"""
TreeSize CLI - Disk Space Analyzer
===================================
A beautiful terminal application for analyzing disk usage with
rich visualizations, progress indicators, and smart filtering.

Dependencies: pip install rich questionary ollama
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
from typing import List, Tuple, Dict, Optional, Callable, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import threading

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

# Questionary for interactive menus
import questionary
from questionary import Style

# --- Configuration & Constants ---
console = Console()


def parse_size(size_str: str) -> Optional[int]:
    """Parse human-readable size string to bytes (e.g., '10MB', '1GB')."""
    if size_str is None:
        return None
    size_str = size_str.strip().upper()
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?$', size_str)
    if not match:
        try:
            return int(size_str)
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


def format_size(num_bytes: int) -> str:
    """Return human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
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
    max_depth: int = None,
    quick_mode: bool = False,
    older_than: datetime = None,
    newer_than: datetime = None,
    include_extensions: Set[str] = None,
    exclude_extensions: Set[str] = None,
) -> Tuple[List[Tuple[int, str]], Dict]:
    """
    Scan for largest files with rich progress display.
    """
    root_path = os.path.abspath(root_path)
    file_heap = []
    total_files = 0
    total_size = 0
    extensions = defaultdict(lambda: {'count': 0, 'size': 0})
    start = time.time()
    root_parts = Path(root_path).parts
    
    # Quick mode minimum size
    effective_min_size = max(min_size_bytes, 1024 * 1024) if quick_mode else min_size_bytes
    
    console.print(Panel(
        f"{ICONS['folder']} [bold]{root_path}[/]",
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
        
        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=follow_symlinks):
            # Skip junk directories (modifying in-place to prevent descent)
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            
            # Check depth limit
            if max_depth is not None:
                current_depth = len(Path(dirpath).parts) - len(root_parts)
                if current_depth >= max_depth:
                    dirnames.clear()
                    continue

            for name in filenames:
                full_path = os.path.join(dirpath, name)
                try:
                    st = os.stat(full_path)
                    size = st.st_size
                    mtime = datetime.fromtimestamp(st.st_mtime)
                except (FileNotFoundError, PermissionError, OSError):
                    continue

                if size < effective_min_size:
                    continue

                # Extension filtering
                ext = os.path.splitext(name)[1].lower().lstrip('.') or ''
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
    max_depth: int = None,
) -> Tuple[List[Tuple[int, str]], Dict]:
    """
    Compute total size per directory and return top_n largest.
    Uses topdown=True to properly filter SKIP_DIRS, then aggregates sizes.
    """
    root_path = os.path.abspath(root_path)
    dir_sizes = defaultdict(int)
    start = time.time()
    total_dirs = 0
    total_files = 0
    root_parts = Path(root_path).parts

    console.print(Panel(
        f"{ICONS['folder']} [bold]{root_path}[/]",
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

        # Use topdown=True so SKIP_DIRS filtering actually prevents descent
        for dirpath, dirnames, filenames in os.walk(root_path, topdown=True, followlinks=follow_symlinks):
            # Filter out SKIP_DIRS - this prevents descending into them
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            current_depth = len(Path(dirpath).parts) - len(root_parts)
            if max_depth is not None and current_depth >= max_depth:
                dirnames.clear()
                continue

            total_dirs += 1

            # Calculate size of files in this directory
            for name in filenames:
                full_path = os.path.join(dirpath, name)
                try:
                    size = os.stat(full_path).st_size
                    total_files += 1
                    # Add size to this directory and all ancestors up to root
                    current = dirpath
                    while len(current) >= len(root_path):
                        dir_sizes[current] += size
                        parent = os.path.dirname(current)
                        if parent == current:
                            break
                        current = parent
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


def print_treemap(data: List[Tuple[int, str]], total_size: int, title: str = "Treemap"):
    """Display a terminal-based treemap visualization."""
    if not data:
        return

    console.print()
    console.print(Panel(
        f"[bold]{title}[/]\n[dim]Block size represents relative space usage[/]",
        border_style="cyan"
    ))

    # Calculate percentages and create blocks
    terminal_width = min(console.width - 4, 100)
    blocks_per_row = 50

    rows = []
    current_row = []
    current_row_size = 0

    for size, path in data[:20]:  # Limit to top 20 for readability
        pct = (size / total_size) * 100 if total_size > 0 else 0
        blocks = max(1, int((size / total_size) * blocks_per_row)) if total_size > 0 else 1

        name = os.path.basename(path) or path
        if len(name) > 15:
            name = name[:12] + "..."

        entry = {
            'name': name,
            'size': size,
            'pct': pct,
            'blocks': blocks,
            'style': get_size_style(size)
        }

        if current_row_size + blocks <= blocks_per_row:
            current_row.append(entry)
            current_row_size += blocks
        else:
            if current_row:
                rows.append(current_row)
            current_row = [entry]
            current_row_size = blocks

    if current_row:
        rows.append(current_row)

    # Render rows
    for row in rows:
        line = Text()
        for entry in row:
            block_char = "█" * entry['blocks']
            line.append(block_char, style=entry['style'])
        console.print(line)

        # Labels row
        label_line = Text()
        for entry in row:
            label = f"{entry['name']} ({entry['pct']:.1f}%)"
            padding = entry['blocks'] - len(label)
            if padding > 0:
                label_line.append(label + " " * padding, style="dim")
            else:
                label_line.append(label[:entry['blocks']], style="dim")
        console.print(label_line)
        console.print()


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
    """Analyze file age distribution in a directory."""
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
        f"{ICONS['folder']} [bold]{root_path}[/]",
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

        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=follow_symlinks):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            for name in filenames:
                full_path = os.path.join(dirpath, name)
                try:
                    st = os.stat(full_path)
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

Please:
1. Categorize these files (temp files, caches, logs, media, documents, etc.)
2. Identify which are likely SAFE to delete (temp files, caches, old logs)
3. Identify which should be KEPT (important documents, system files)
4. Provide specific cleanup recommendations

Be concise and actionable."""
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

Please:
1. Identify directories that likely contain unnecessary data (node_modules, cache, temp, old backups)
2. Identify directories that should NOT be deleted (system folders, important data)
3. Provide specific cleanup recommendations

Be concise and actionable."""
    
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
                console.print(Panel(
                    analysis,
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
