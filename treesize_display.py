#!/usr/bin/env python3
"""
TreeSize Display Module
========================
Rich terminal display functions for scan results: file tables,
directory tables, treemap visualization, age analysis, and disk usage.
"""

import os
import shutil
from typing import List, Tuple, Dict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from utils import format_size

console = Console()

ICONS = {
    'file': '📄',
    'folder': '📂',
    'disk': '💾',
    'chart': '📊',
    'warning': '⚠️',
    'error': '❌',
    'success': '✅',
    'clock': '⏱️',
}

# --- Data-driven emoji lookup tables ---

DIR_EMOJI_RULES = [
    (['game', 'steam', 'epic', 'fortnite', 'minecraft'], '🎮'),
    (['photo', 'picture', 'image', 'dcim', 'camera'], '📸'),
    (['video', 'movie', 'film'], '🎬'),
    (['music', 'audio', 'spotify'], '🎵'),
    (['download'], '📥'),
    (['document', 'doc'], '📝'),
    (['backup', 'archive'], '💾'),
    (['cache', 'temp', 'tmp'], '🗑️'),
    (['node_modules', 'venv', '.git', 'package'], '📦'),
    (['program', 'app', 'software'], '⚙️'),
    (['user', 'profile'], '👤'),
    (['system', 'windows'], '🖥️'),
    (['model', 'ollama', 'llm', 'ai'], '🤖'),
]

FILE_EMOJI_MAP = {
    '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
    '.bmp': '🖼️', '.webp': '🖼️',
    '.mp4': '🎬', '.mkv': '🎬', '.avi': '🎬', '.mov': '🎬', '.wmv': '🎬',
    '.mp3': '🎵', '.wav': '🎵', '.flac': '🎵', '.aac': '🎵', '.ogg': '🎵',
    '.zip': '📦', '.rar': '📦', '.7z': '📦', '.tar': '📦', '.gz': '📦',
    '.exe': '⚙️', '.msi': '⚙️', '.dll': '⚙️',
    '.pdf': '📕',
    '.doc': '📝', '.docx': '📝', '.txt': '📝', '.md': '📝',
    '.iso': '💿', '.img': '💿',
    '.log': '🗑️', '.tmp': '🗑️',
}


def get_size_style(size_bytes: int) -> str:
    """Get color style based on file size."""
    if size_bytes >= 1024 * 1024 * 1024:
        return "bold red"
    elif size_bytes >= 100 * 1024 * 1024:
        return "bold yellow"
    elif size_bytes >= 10 * 1024 * 1024:
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


def get_item_emoji(path: str, is_dir: bool = True) -> str:
    """Get an appropriate emoji for a file/directory based on its name."""
    name = os.path.basename(path).lower()

    if is_dir:
        for keywords, emoji in DIR_EMOJI_RULES:
            if any(kw in name for kw in keywords):
                return emoji
        return '📁'
    else:
        ext = os.path.splitext(name)[1].lower()
        return FILE_EMOJI_MAP.get(ext, '📄')


def print_file_results(largest_files: List[Tuple[int, str]], stats: Dict):
    """Display file scan results with rich formatting."""
    console.print()

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

    max_size = largest_files[0][0] if largest_files else 1

    table = Table(
        title=f"{ICONS['file']} Top {len(largest_files)} Largest Files",
        box=box.ROUNDED,
        show_lines=False,
        title_style="bold cyan"
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Size", justify="right", width=12)
    table.add_column("", width=20)
    table.add_column("Path")

    for i, (size, path) in enumerate(largest_files, start=1):
        size_text = Text(format_size(size), style=get_size_style(size))
        size_bar = create_size_bar(size, max_size)
        table.add_row(str(i), size_text, size_bar, path)

    console.print()
    console.print(table)

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
    """Display a terminal-based treemap visualization as a readable bar chart."""
    if not data:
        return

    console.print()

    is_dirs = "Director" in title

    table = Table(
        title=f"{'📊' if is_dirs else '📈'} {title}",
        box=box.ROUNDED,
        title_style="bold cyan",
        show_header=True,
        header_style="bold"
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("", width=2)
    table.add_column("Name", style="cyan", max_width=40)
    table.add_column("Size", justify="right", width=10)
    table.add_column("%", justify="right", width=6)
    table.add_column("Usage", width=30)

    max_size = data[0][0] if data else 1
    bar_width = 25

    for i, (size, path) in enumerate(data[:20], start=1):
        pct = (size / total_size) * 100 if total_size > 0 else 0

        name = os.path.basename(path) or path
        if len(name) > 38:
            name = name[:35] + "..."

        emoji = get_item_emoji(path, is_dirs)

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
