#!/usr/bin/env python3
"""
NUL Nuker
=========
Scans directories for Windows 'nul' files - artifacts created by buggy tools
that write to a literal file named 'nul' instead of the Windows NUL device.
These files are always safe to remove. Find them. Nuke them.

Dependencies: pip install rich questionary
"""

import os
import sys
import ctypes
from typing import List, Optional, Set, Tuple, Generator
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, MofNCompleteColumn
from rich.table import Table
from rich.text import Text
from rich import box

import questionary
from questionary import Style

# --- Configuration ---
console = Console()

MENU_STYLE = Style([
    ('qmark', 'fg:#673ab7 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#ff5722 bold'),
    ('pointer', 'fg:#673ab7 bold'),
    ('highlighted', 'fg:#673ab7 bold'),
    ('selected', 'fg:#ff5722'),
    ('separator', 'fg:#673ab7'),
    ('instruction', 'fg:#808080'),
])

ICONS = {
    'nuke': '☢️',
    'scan': '🔎',
    'delete': '💀',
    'success': '✅',
    'warning': '⚠️',
    'error': '❌',
    'folder': '📂',
    'file': '📄',
    'exit': '🚪',
    'info': 'ℹ️',
}

# Windows reserved device names (case-insensitive)
WINDOWS_RESERVED_NAMES = {
    'con', 'prn', 'aux', 'nul',
    'com0', 'com1', 'com2', 'com3', 'com4', 'com5', 'com6', 'com7', 'com8', 'com9',
    'lpt0', 'lpt1', 'lpt2', 'lpt3', 'lpt4', 'lpt5', 'lpt6', 'lpt7', 'lpt8', 'lpt9',
}

SKIP_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv', '.env',
    '$RECYCLE.BIN', 'System Volume Information', '.Trash-1000',
    'Windows', 'ProgramData', '.cache', '.npm', '.yarn',
    'AppData', '.local', 'site-packages', '.tox', '.pytest_cache',
}


def show_banner():
    """Display a styled startup banner."""
    banner = Text()
    banner.append("╔══════════════════════════════════════════════════════════════╗\n", style="bold red")
    banner.append("║", style="bold red")
    banner.append("              ☢️  NUL NUKER  ☢️                           ", style="bold white")
    banner.append("║\n", style="bold red")
    banner.append("║", style="bold red")
    banner.append("        Find & nuke Windows reserved-name artifacts       ", style="dim white")
    banner.append("║\n", style="bold red")
    banner.append("╚══════════════════════════════════════════════════════════════╝", style="bold red")
    console.print(banner)
    console.print()


def format_size(num_bytes: int) -> str:
    """Return human-readable file size."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"


def scan_nul_files(
    root_dir: str,
    skip_dirs: Optional[Set[str]] = None,
    include_all_reserved: bool = False,
) -> List[dict]:
    """
    Scan a directory tree for nul files (or all Windows reserved-name files).

    Returns a list of dicts with keys: path, size, modified, name
    """
    skip_dirs = skip_dirs or SKIP_DIRS
    target_names = WINDOWS_RESERVED_NAMES if include_all_reserved else {'nul'}
    results = []

    root_dir = os.path.abspath(root_dir)
    stack = [root_dir]

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning directories...", total=None)

        while stack:
            current_dir = stack.pop()
            try:
                with os.scandir(current_dir) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name not in skip_dirs:
                                    stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                # Check the base name without extension
                                name_lower = entry.name.lower()
                                stem = name_lower.split('.')[0] if '.' in name_lower else name_lower
                                if stem in target_names:
                                    try:
                                        stat = entry.stat(follow_symlinks=False)
                                        results.append({
                                            'path': entry.path,
                                            'size': stat.st_size,
                                            'modified': datetime.fromtimestamp(stat.st_mtime),
                                            'name': entry.name,
                                        })
                                    except OSError:
                                        # Can't stat but still record it
                                        results.append({
                                            'path': entry.path,
                                            'size': 0,
                                            'modified': None,
                                            'name': entry.name,
                                        })
                        except OSError:
                            continue
            except OSError:
                continue

            progress.update(task, description=f"Scanning... ({len(results)} found)")

    return results


def print_results(results: List[dict]):
    """Display scan results in a rich table."""
    if not results:
        console.print(Panel(
            f"[bold green]{ICONS['success']} No nul files found![/]\n\n"
            "[dim]Nothing to nuke. Your directory is clean.[/]",
            border_style="green",
        ))
        return

    table = Table(
        title=f"{ICONS['nuke']} Found {len(results)} nul file(s)",
        box=box.ROUNDED,
        border_style="red",
        show_lines=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("File", style="bold red")
    table.add_column("Size", justify="right", style="cyan")
    table.add_column("Modified", style="dim")
    table.add_column("Directory", style="dim")

    total_size = 0
    for i, item in enumerate(results, 1):
        total_size += item['size']
        modified = item['modified'].strftime('%Y-%m-%d %H:%M') if item['modified'] else 'unknown'
        directory = os.path.dirname(item['path'])
        table.add_row(
            str(i),
            item['name'],
            format_size(item['size']),
            modified,
            directory,
        )

    console.print(table)
    console.print(f"\n[bold]Total:[/] {len(results)} file(s), {format_size(total_size)}")


def delete_nul_file(filepath: str) -> Tuple[bool, str]:
    """
    Delete a nul file. On Windows, reserved names require the \\\\?\\ prefix
    to bypass the name reservation.

    Returns (success, message).
    """
    try:
        if os.name == 'nt':
            # Windows: use \\?\ extended-length path to bypass reserved name check
            abs_path = os.path.abspath(filepath)
            extended_path = f"\\\\?\\{abs_path}"
            # Try Python's os.remove with extended path first
            try:
                os.remove(extended_path)
                return True, f"Deleted: {filepath}"
            except OSError:
                # Fallback: use ctypes to call DeleteFileW directly
                if ctypes.windll.kernel32.DeleteFileW(extended_path):
                    return True, f"Deleted: {filepath}"
                error_code = ctypes.windll.kernel32.GetLastError()
                return False, f"Failed (error {error_code}): {filepath}"
        else:
            os.remove(filepath)
            return True, f"Deleted: {filepath}"
    except OSError as e:
        return False, f"Failed ({e}): {filepath}"


def delete_selected(results: List[dict], dry_run: bool = True) -> Tuple[int, int]:
    """
    Delete all found nul files.

    Returns (success_count, fail_count).
    """
    success = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Nuking..." if not dry_run else "Dry run...",
            total=len(results),
        )

        for item in results:
            if dry_run:
                console.print(f"  [dim][DRY RUN][/] Would delete: {item['path']}")
                success += 1
            else:
                ok, msg = delete_nul_file(item['path'])
                if ok:
                    console.print(f"  [green]{ICONS['success']}[/] {msg}")
                    success += 1
                else:
                    console.print(f"  [red]{ICONS['error']}[/] {msg}")
                    failed += 1
            progress.advance(task)

    return success, failed


def main_menu():
    """Main interactive menu for NUL Nuker."""
    while True:
        console.clear()
        show_banner()

        console.print("[dim]Find and nuke Windows reserved-name file artifacts.[/]\n")

        choice = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice(f"{ICONS['scan']} Scan for nul files", value="scan_nul"),
                questionary.Choice(f"{ICONS['scan']} Scan for ALL reserved-name files", value="scan_all"),
                questionary.Choice(f"{ICONS['info']} What are nul files?", value="info"),
                questionary.Choice(f"{ICONS['exit']} Back to main menu", value="exit"),
            ],
            style=MENU_STYLE,
        ).ask()

        if choice is None or choice == "exit":
            break

        elif choice == "info":
            console.print()
            console.print(Panel(
                "[bold cyan]What are nul files?[/]\n\n"
                "On Windows, [bold]NUL[/] is a reserved device name (like [bold]/dev/null[/] on Linux).\n"
                "It's meant to silently discard output.\n\n"
                "However, some buggy tools create a [bold red]literal file[/] named 'nul' instead\n"
                "of writing to the NUL device. These files:\n\n"
                "  • Contain garbage data or are empty\n"
                "  • Can't be deleted via normal Explorer/PowerShell commands\n"
                "  • Are never legitimate user files\n"
                "  • Can cause issues with some tools that misinterpret the name\n\n"
                "[bold]Other reserved names:[/] CON, PRN, AUX, COM1-9, LPT1-9\n\n"
                "[dim]This scanner uses the \\\\\\\\?\\\\ extended path prefix to bypass\n"
                "the name reservation and delete these files properly.[/]",
                title=f"{ICONS['info']} About Reserved-Name Files",
                border_style="cyan",
                padding=(1, 2),
            ))
            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()

        elif choice in ("scan_nul", "scan_all"):
            include_all = choice == "scan_all"
            label = "all reserved-name" if include_all else "nul"

            path = questionary.path(
                f"{ICONS['folder']} Directory to scan:",
                only_directories=True,
                style=MENU_STYLE,
            ).ask()

            if not path:
                continue
            if not os.path.exists(path):
                console.print(f"[red]{ICONS['error']} Path does not exist: {path}[/]")
                questionary.press_any_key_to_continue(style=MENU_STYLE).ask()
                continue

            console.print()
            results = scan_nul_files(path, include_all_reserved=include_all)
            console.print()
            print_results(results)

            if results:
                console.print()
                action = questionary.select(
                    f"Found {len(results)} {label} file(s). What would you like to do?",
                    choices=[
                        questionary.Choice(f"{ICONS['delete']} Nuke all (dry run first)", value="dry_run"),
                        questionary.Choice(f"{ICONS['delete']} Nuke all (for real)", value="delete"),
                        questionary.Choice(f"{ICONS['exit']} Skip / go back", value="skip"),
                    ],
                    style=MENU_STYLE,
                ).ask()

                if action == "dry_run":
                    console.print()
                    success, failed = delete_selected(results, dry_run=True)
                    console.print(f"\n[bold cyan]{ICONS['info']} Dry run complete.[/] "
                                  f"{success} file(s) would be deleted.")

                    proceed = questionary.confirm(
                        "Proceed with actual deletion?",
                        default=False,
                        style=MENU_STYLE,
                    ).ask()

                    if proceed:
                        console.print()
                        success, failed = delete_selected(results, dry_run=False)
                        console.print(f"\n[bold green]{ICONS['success']} Done![/] "
                                      f"{success} deleted, {failed} failed.")

                elif action == "delete":
                    confirm = questionary.confirm(
                        f"Are you sure you want to delete {len(results)} file(s)? This cannot be undone.",
                        default=False,
                        style=MENU_STYLE,
                    ).ask()

                    if confirm:
                        console.print()
                        success, failed = delete_selected(results, dry_run=False)
                        console.print(f"\n[bold green]{ICONS['success']} Done![/] "
                                      f"{success} deleted, {failed} failed.")

            questionary.press_any_key_to_continue(style=MENU_STYLE).ask()


def main():
    """Entry point for standalone usage."""
    try:
        main_menu()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Goodbye![/]")
        sys.exit(0)


if __name__ == "__main__":
    main()
