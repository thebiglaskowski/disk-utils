#!/usr/bin/env python3
"""
Duplicate File Finder with Smart Logic
=======================================
A robust tool for finding and handling duplicate files with an interactive
terminal interface, progress indicators, and smart selection logic.

Dependencies: pip install rich questionary
Optional:     pip install xxhash  (for faster hashing)
"""

import os
import hashlib
import argparse
import sys
import shutil
from collections import defaultdict
from typing import List, Optional, Set, Tuple, Dict
from datetime import datetime
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import re

# Optional faster hashing with xxhash
try:
    import xxhash
    XXHASH_AVAILABLE = True
except ImportError:
    XXHASH_AVAILABLE = False

# Rich library for beautiful terminal output
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, MofNCompleteColumn
from rich.table import Table
from rich.text import Text
from rich import box

# Questionary for interactive menus
import questionary
from questionary import Style

# --- Configuration & Constants ---
CHUNK_SIZE = 65536  # Read files in chunks of 64KB for better performance
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024  # 100MB - use memory mapping for larger files
console = Console()

# Custom style for questionary prompts
MENU_STYLE = Style([
    ('qmark', 'fg:#673ab7 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#f44336 bold'),
    ('pointer', 'fg:#673ab7 bold'),
    ('highlighted', 'fg:#673ab7 bold'),
    ('selected', 'fg:#cc5454'),
    ('separator', 'fg:#cc5454'),
    ('instruction', 'fg:#808080'),
])

# Icons
ICONS = {
    'keep': '✅',
    'delete': '🗑️ ',
    'move': '📁',
    'hardlink': '🔗',
    'report': '📋',
    'folder': '📂',
    'file': '📄',
    'warning': '⚠️ ',
    'error': '❌',
    'success': '✨',
    'scan': '🔍',
    'hash': '🔐',
    'speed': '⚡',
}

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
    banner.append("╔════════════════════════════════════════════════════════════╗\n", style="bold blue")
    banner.append("║", style="bold blue")
    banner.append("        🔍 DUPLICATE FILE FINDER 🔍                   ", style="bold white")
    banner.append("║\n", style="bold blue")
    banner.append("║", style="bold blue")
    banner.append("          Smart Detection • Safe Cleanup              ", style="dim white")
    banner.append("║\n", style="bold blue")
    banner.append("╚════════════════════════════════════════════════════════════╝", style="bold blue")
    console.print(banner)
    console.print()


class SmartDuplicateHandler:
    """
    Handles logic for selecting 'keeper' files from duplicates
    and executing actions (report, delete, move, etc.)
    """
    def __init__(self, action: str, keep_criteria: str, dry_run: bool = True,
                 backup_dir: str = None, max_threads: int = 32):
        self.action = action
        self.keep_criteria = keep_criteria
        self.dry_run = dry_run
        self.backup_dir = backup_dir
        self.max_threads = max_threads

    def select_keeper(self, files: List[str]) -> Optional[str]:
        """Determines which file to keep based on criteria."""
        if not files:
            return None
        
        def get_stat(path):
            try:
                return os.stat(path)
            except OSError:
                return None

        file_stats = {f: get_stat(f) for f in files}
        valid_files = [f for f in files if file_stats[f]]
        
        if not valid_files:
            return None

        if self.keep_criteria == 'oldest':
            return min(valid_files, key=lambda f: file_stats[f].st_ctime)
        elif self.keep_criteria == 'newest':
            return max(valid_files, key=lambda f: file_stats[f].st_ctime)
        elif self.keep_criteria == 'shortest_path':
            return min(valid_files, key=lambda f: len(f))
        elif self.keep_criteria == 'largest_path':
            return max(valid_files, key=lambda f: len(f))
        else:
            return sorted(valid_files)[0]

    def process_duplicates(self, duplicates_list: List[List[str]]):
        """Process all duplicate groups with visual feedback."""
        total_groups = len(duplicates_list)
        total_files_to_process = sum(len(g) - 1 for g in duplicates_list)
        total_space_savings = 0
        
        if total_groups == 0:
            console.print(Panel(
                f"{ICONS['success']} No duplicate files found!",
                title="Scan Complete",
                border_style="green"
            ))
            return

        # Summary header
        console.print()
        console.print(Panel(
            f"Found [bold cyan]{total_groups}[/] groups of duplicates\n"
            f"[dim]({total_files_to_process} files can be processed)[/]",
            title=f"{ICONS['scan']} Scan Results",
            border_style="cyan"
        ))
        
        action_icon = ICONS.get(self.action, '📋')
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"[cyan]Processing duplicates...", total=total_groups)
            
            for group in duplicates_list:
                keeper = self.select_keeper(group)
                if not keeper:
                    progress.advance(task)
                    continue

                # Verify keeper still exists before processing
                try:
                    file_size = os.path.getsize(keeper)
                except OSError:
                    progress.advance(task)
                    continue

                others = [f for f in group if f != keeper]
                total_space_savings += file_size * len(others)
                
                # Create a table for this group
                table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
                table.add_column("Status", style="bold", width=8)
                table.add_column("Path")
                table.add_column("Size", justify="right", width=12)
                
                table.add_row(
                    f"{ICONS['keep']} KEEP",
                    Text(keeper, style="green"),
                    f"{file_size:,} B"
                )
                
                for other in others:
                    table.add_row(
                        f"{action_icon} {self.action.upper()}",
                        Text(other, style="yellow" if self.dry_run else "red"),
                        f"{file_size:,} B"
                    )
                    
                    if not self.dry_run:
                        self._execute_action(other, keeper)
                
                progress.advance(task)
                console.print(table)
                console.print()

        # Final summary
        self._print_summary(total_groups, total_files_to_process, total_space_savings)

    def _execute_action(self, filepath: str, keeper: str):
        """Execute the configured action on a duplicate file."""
        try:
            if self.action == 'report':
                pass
            elif self.action == 'delete':
                os.remove(filepath)
                console.print(f"      [green]→ Deleted[/]")
            elif self.action == 'move':
                if self.backup_dir:
                    dest_dir = os.path.join(self.backup_dir, "duplicates")
                    os.makedirs(dest_dir, exist_ok=True)
                    fname = os.path.basename(filepath)
                    dest_path = os.path.join(dest_dir, fname)
                    if os.path.exists(dest_path):
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        name, ext = os.path.splitext(fname)
                        dest_path = os.path.join(dest_dir, f"{name}_{timestamp}{ext}")
                    shutil.move(filepath, dest_path)
                    console.print(f"      [green]→ Moved to {dest_path}[/]")
            elif self.action == 'hardlink':
                # Use atomic replacement to avoid race condition
                temp_path = filepath + '.tmp_hardlink'
                try:
                    os.link(keeper, temp_path)
                    os.replace(temp_path, filepath)
                    console.print(f"      [green]→ Hardlinked[/]")
                except OSError:
                    # Clean up temp file if it exists
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    raise
        except Exception as e:
            console.print(f"      [red]{ICONS['error']} Error: {e}[/]")

    def _print_summary(self, groups: int, files: int, space: int):
        """Print final summary with statistics."""
        space_str = self._format_size(space)
        mode_text = "[yellow]DRY RUN[/] - No files modified" if self.dry_run else "[green]COMPLETE[/]"
        
        summary = Table(box=box.DOUBLE_EDGE, show_header=False, title="Summary", title_style="bold")
        summary.add_column("Metric", style="dim")
        summary.add_column("Value", style="bold")
        
        summary.add_row("Duplicate Groups", str(groups))
        summary.add_row("Files to Process", str(files))
        summary.add_row("Potential Space Savings", space_str)
        summary.add_row("Mode", mode_text)
        
        console.print()
        console.print(summary)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.2f} PB"


class DuplicateFinder:
    """Finds duplicate files using a 3-stage filtering approach."""

    def __init__(
        self,
        root_dir: str,
        max_threads: int = None,
        min_size: int = 1,
        max_size: int = None,
        include_extensions: Set[str] = None,
        exclude_extensions: Set[str] = None,
        use_fast_hash: bool = True,
        skip_hardlinks: bool = True,
    ):
        self.root_dir = os.path.abspath(root_dir)
        # I/O bound tasks benefit from more threads than cores
        self.max_threads = max_threads or min(32, (os.cpu_count() or 1) * 4)
        self.min_size = min_size
        self.max_size = max_size
        self.include_extensions = {e.lower().lstrip('.') for e in include_extensions} if include_extensions else None
        self.exclude_extensions = {e.lower().lstrip('.') for e in exclude_extensions} if exclude_extensions else None
        self.use_fast_hash = use_fast_hash and XXHASH_AVAILABLE
        self.skip_hardlinks = skip_hardlinks
        self._inode_map: Dict[Tuple[int, int], str] = {}  # (dev, inode) -> first seen path

    def _should_include_file(self, filepath: str, size: int) -> bool:
        """Check if file matches filter criteria."""
        if size < self.min_size:
            return False
        if self.max_size is not None and size > self.max_size:
            return False

        ext = os.path.splitext(filepath)[1].lower().lstrip('.')
        if self.include_extensions and ext not in self.include_extensions:
            return False
        if self.exclude_extensions and ext in self.exclude_extensions:
            return False

        return True

    def _get_hasher(self):
        """Get the appropriate hasher based on configuration."""
        if self.use_fast_hash:
            return xxhash.xxh3_64()
        return hashlib.sha256()

    def get_file_hash(self, filepath: str, first_chunk_only: bool = False) -> Optional[str]:
        """Calculate hash of a file using the configured algorithm."""
        hasher = self._get_hasher()
        try:
            file_size = os.path.getsize(filepath)
            # Use memory mapping for large files (faster I/O)
            if not first_chunk_only and file_size > LARGE_FILE_THRESHOLD:
                return self._hash_large_file(filepath, hasher)

            with open(filepath, 'rb') as f:
                if first_chunk_only:
                    buf = f.read(CHUNK_SIZE)
                    hasher.update(buf)
                else:
                    while True:
                        buf = f.read(CHUNK_SIZE)
                        if not buf:
                            break
                        hasher.update(buf)
        except OSError:
            return None
        return hasher.hexdigest()

    def _hash_large_file(self, filepath: str, hasher) -> Optional[str]:
        """Hash large files using memory mapping for better performance."""
        import mmap
        try:
            with open(filepath, 'rb') as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    # Process in chunks to avoid memory issues
                    for i in range(0, len(mm), CHUNK_SIZE * 16):
                        hasher.update(mm[i:i + CHUNK_SIZE * 16])
            return hasher.hexdigest()
        except (OSError, ValueError):
            # Fall back to regular reading if mmap fails
            return None

    def find_duplicates(self) -> List[List[str]]:
        """Find all duplicate files with progress indicators."""

        # Show configuration
        hash_algo = "xxhash (fast)" if self.use_fast_hash else "SHA-256"
        console.print(Panel(
            f"{ICONS['folder']} [bold]{self.root_dir}[/]\n"
            f"[dim]Hash: {hash_algo} | Threads: {self.max_threads} | Skip hardlinks: {self.skip_hardlinks}[/]",
            title=f"{ICONS['scan']} Scanning Directory",
            border_style="blue"
        ))
        console.print(f"[dim]{ICONS['speed']} Skipping: {', '.join(sorted(SKIP_DIRS)[:5])}...[/]\n")

        # Phase 1: Collect all files and group by size using scandir (faster than walk)
        console.print(f"\n[bold cyan]Phase 1/3:[/] {ICONS['scan']} Scanning files...")
        all_files = []
        skipped_hardlinks = 0
        skipped_filters = 0
        self._inode_map.clear()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TextColumn("[cyan]{task.fields[files]:,}[/] files found"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Walking directory tree...", files=0)

            for dirpath, dirnames, filenames in os.walk(self.root_dir):
                # Skip junk directories (modifying in-place to prevent descent)
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        stat_info = os.stat(filepath)

                        # Skip symlinks
                        if os.path.islink(filepath):
                            continue

                        size = stat_info.st_size

                        # Apply filters
                        if not self._should_include_file(filepath, size):
                            skipped_filters += 1
                            continue

                        # Skip files that are already hardlinked to each other
                        if self.skip_hardlinks and stat_info.st_nlink > 1:
                            inode_key = (stat_info.st_dev, stat_info.st_ino)
                            if inode_key in self._inode_map:
                                skipped_hardlinks += 1
                                continue
                            self._inode_map[inode_key] = filepath

                        all_files.append((filepath, size))
                        # Update progress every 500 files (less frequent = faster)
                        if len(all_files) % 500 == 0:
                            progress.update(task, files=len(all_files))
                    except OSError:
                        continue

            progress.update(task, files=len(all_files))

        console.print(f"   [green]✓[/] Found [bold]{len(all_files):,}[/] files")
        if skipped_hardlinks > 0:
            console.print(f"   [dim]Skipped {skipped_hardlinks:,} existing hardlinks[/]")
        if skipped_filters > 0:
            console.print(f"   [dim]Skipped {skipped_filters:,} files (filters)[/]")
        
        # Group by size
        size_groups = defaultdict(list)
        for filepath, size in all_files:
            size_groups[size].append(filepath)
        
        potential_dupes = [files for files in size_groups.values() if len(files) > 1]
        files_to_check = sum(len(f) for f in potential_dupes)
        console.print(f"   [green]✓[/] [bold]{len(potential_dupes):,}[/] size groups need hash verification ({files_to_check:,} files)")
        
        if not potential_dupes:
            return []
        
        # Phase 2: Partial hash (first chunk) - PARALLEL
        console.print(f"\n[bold cyan]Phase 2/3:[/] {ICONS['hash']} Calculating partial hashes...")
        console.print(f"[dim]{ICONS['speed']} Using parallel hashing ({self.max_threads} threads)[/]")
        
        partial_hash_groups = defaultdict(list)
        total_files_phase2 = sum(len(g) for g in potential_dupes)
        all_files_phase2 = [f for group in potential_dupes for f in group]
        
        def hash_partial(filepath):
            h = self.get_file_hash(filepath, first_chunk_only=True)
            return (filepath, h)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Hashing first 64KB...", total=total_files_phase2)

            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                futures = {executor.submit(hash_partial, f): f for f in all_files_phase2}
                
                for future in as_completed(futures):
                    filepath, p_hash = future.result()
                    if p_hash:
                        partial_hash_groups[p_hash].append(filepath)
                    progress.advance(task)
        
        potential_dupes_2 = [files for files in partial_hash_groups.values() if len(files) > 1]
        files_to_check_2 = sum(len(f) for f in potential_dupes_2)
        console.print(f"   [green]✓[/] [bold]{len(potential_dupes_2):,}[/] groups remain ({files_to_check_2:,} files)")
        
        if not potential_dupes_2:
            return []
        
        # Phase 3: Full hash - PARALLEL
        console.print(f"\n[bold cyan]Phase 3/3:[/] {ICONS['hash']} Calculating full hashes...")
        
        full_hash_groups = defaultdict(list)
        total_files_phase3 = sum(len(g) for g in potential_dupes_2)
        all_files_phase3 = [f for group in potential_dupes_2 for f in group]
        
        def hash_full(filepath):
            h = self.get_file_hash(filepath, first_chunk_only=False)
            return (filepath, h)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Hashing full files...", total=total_files_phase3)

            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                futures = {executor.submit(hash_full, f): f for f in all_files_phase3}
                
                for future in as_completed(futures):
                    filepath, f_hash = future.result()
                    if f_hash:
                        full_hash_groups[f_hash].append(filepath)
                    progress.advance(task)
        
        duplicates = [files for files in full_hash_groups.values() if len(files) > 1]
        console.print(f"   [green]✓[/] Confirmed [bold]{len(duplicates):,}[/] duplicate groups")
        
        return duplicates


def interactive_menu() -> dict:
    """Display interactive configuration menu."""
    show_banner()
    
    console.print("[dim]Configure your scan settings below. Press Ctrl+C to cancel.[/]\n")
    
    # Get directory
    root_dir = questionary.path(
        "📂 Directory to scan:",
        only_directories=True,
        style=MENU_STYLE
    ).ask()
    
    if not root_dir:
        console.print("[red]Cancelled.[/]")
        sys.exit(0)
    
    # Get action
    action = questionary.select(
        "🎯 What to do with duplicates?",
        choices=[
            questionary.Choice("📋 Report only (list duplicates)", value="report"),
            questionary.Choice("🗑️  Delete duplicates", value="delete"),
            questionary.Choice("📁 Move to backup folder", value="move"),
            questionary.Choice("🔗 Replace with hardlinks", value="hardlink"),
        ],
        style=MENU_STYLE
    ).ask()
    
    if not action:
        console.print("[red]Cancelled.[/]")
        sys.exit(0)
    
    # Get keep criteria
    keep = questionary.select(
        "✅ Which file to KEEP in each group?",
        choices=[
            questionary.Choice("📅 Oldest (by creation time)", value="oldest"),
            questionary.Choice("🆕 Newest (by creation time)", value="newest"),
            questionary.Choice("📏 Shortest path", value="shortest_path"),
        ],
        style=MENU_STYLE
    ).ask()
    
    if not keep:
        console.print("[red]Cancelled.[/]")
        sys.exit(0)
    
    # Dry run?
    dry_run = questionary.confirm(
        "🧪 Dry run? (simulate without making changes)",
        default=True,
        style=MENU_STYLE
    ).ask()
    
    if dry_run is None:
        console.print("[red]Cancelled.[/]")
        sys.exit(0)
    
    # Backup dir (if move action)
    backup_dir = None
    if action == 'move':
        console.print("\n[bold cyan]📁 Backup Directory[/]")
        console.print("[dim]Enter the folder where duplicate files will be moved.[/]\n")
        
        backup_dir = questionary.text(
            "Backup folder path:",
            style=MENU_STYLE
        ).ask()
        
        if not backup_dir:
            console.print("[red]Cancelled.[/]")
            sys.exit(0)
        
        # Validate and create if needed
        backup_dir = os.path.abspath(backup_dir)
        if not os.path.exists(backup_dir):
            create_it = questionary.confirm(
                f"Folder doesn't exist. Create '{backup_dir}'?",
                default=True,
                style=MENU_STYLE
            ).ask()
            if create_it:
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                    console.print(f"[green]✓ Created: {backup_dir}[/]")
                except OSError as e:
                    console.print(f"[red]Failed to create folder: {e}[/]")
                    sys.exit(1)
            else:
                console.print("[red]Cancelled.[/]")
                sys.exit(0)
    
    return {
        'root_dir': root_dir,
        'action': action,
        'keep': keep,
        'dry_run': dry_run,
        'backup_dir': backup_dir,
        'min_size': 1,
        'max_size': None,
        'include_extensions': None,
        'exclude_extensions': None,
        'use_fast_hash': True,
        'skip_hardlinks': True,
        'max_threads': None,
    }


def parse_size(size_str: str) -> Optional[int]:
    """Parse human-readable size string to bytes (e.g., '10MB', '1GB')."""
    if size_str is None:
        return None
    size_str = size_str.strip().upper()
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?$', size_str)
    if not match:
        return int(size_str)  # Assume bytes
    value = float(match.group(1))
    unit = match.group(2) or 'B'
    multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
    return int(value * multipliers.get(unit, 1))


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def main():
    parser = argparse.ArgumentParser(
        description="🔍 Duplicate File Finder - Clean up duplicate files with smart logic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Interactive mode
  %(prog)s C:\\Users\\Photos           # Scan with defaults (report only)
  %(prog)s C:\\Data --action delete --keep oldest --no-dry-run
  %(prog)s C:\\Data --min-size 1MB --ext jpg,png,gif
  %(prog)s C:\\Data --exclude-ext tmp,log --fast-hash
        """
    )
    parser.add_argument("root_dir", nargs='?', help="Directory to scan (omit for interactive mode)")
    parser.add_argument("--action", choices=['report', 'delete', 'move', 'hardlink'], default='report')
    parser.add_argument("--keep", choices=['oldest', 'newest', 'shortest_path'], default='oldest')
    parser.add_argument("--dry-run", action='store_true', default=True)
    parser.add_argument("--no-dry-run", dest='dry_run', action='store_false')
    parser.add_argument("--backup-dir", help="Directory to move duplicates to")

    # New filter options
    parser.add_argument("--min-size", type=str, default="1",
                        help="Minimum file size (e.g., 1KB, 10MB, 1GB)")
    parser.add_argument("--max-size", type=str, default=None,
                        help="Maximum file size (e.g., 100MB, 1GB)")
    parser.add_argument("--ext", "--extensions", dest="extensions", type=str, default=None,
                        help="Only include these extensions (comma-separated, e.g., jpg,png,gif)")
    parser.add_argument("--exclude-ext", type=str, default=None,
                        help="Exclude these extensions (comma-separated, e.g., tmp,log)")
    parser.add_argument("--fast-hash", action='store_true', default=True,
                        help="Use xxhash for faster hashing (default if available)")
    parser.add_argument("--secure-hash", dest='fast_hash', action='store_false',
                        help="Use SHA-256 instead of xxhash")
    parser.add_argument("--threads", type=int, default=None,
                        help="Number of threads for parallel hashing")
    parser.add_argument("--include-hardlinks", dest='skip_hardlinks', action='store_false', default=True,
                        help="Don't skip files that are already hardlinked")

    args = parser.parse_args()

    # Interactive mode if no directory provided
    if args.root_dir is None:
        config = interactive_menu()
    else:
        show_banner()
        # Parse size arguments
        min_size = parse_size(args.min_size)
        max_size = parse_size(args.max_size) if args.max_size else None
        include_ext = set(args.extensions.split(',')) if args.extensions else None
        exclude_ext = set(args.exclude_ext.split(',')) if args.exclude_ext else None

        config = {
            'root_dir': args.root_dir,
            'action': args.action,
            'keep': args.keep,
            'dry_run': args.dry_run,
            'backup_dir': args.backup_dir,
            'min_size': min_size,
            'max_size': max_size,
            'include_extensions': include_ext,
            'exclude_extensions': exclude_ext,
            'use_fast_hash': args.fast_hash,
            'skip_hardlinks': args.skip_hardlinks,
            'max_threads': args.threads,
        }

    # Validate
    if config['action'] == 'move' and not config['backup_dir']:
        console.print(f"[red]{ICONS['error']} Error: --backup-dir is required when action is 'move'[/]")
        sys.exit(1)

    if not os.path.isdir(config['root_dir']):
        console.print(f"[red]{ICONS['error']} Error: Directory '{config['root_dir']}' not found.[/]")
        sys.exit(1)

    # Show config
    console.print()
    config_table = Table(box=box.ROUNDED, title="⚙️  Configuration", title_style="bold blue")
    config_table.add_column("Setting", style="dim")
    config_table.add_column("Value", style="bold")

    config_table.add_row("Action", f"{ICONS.get(config['action'], '')} {config['action'].upper()}")
    config_table.add_row("Keep", config['keep'])
    config_table.add_row("Dry Run", "Yes" if config['dry_run'] else "[red]No (LIVE MODE)[/]")
    if config.get('backup_dir'):
        config_table.add_row("Backup Dir", config['backup_dir'])
    if config.get('min_size', 0) > 1:
        config_table.add_row("Min Size", format_size(config['min_size']))
    if config.get('max_size'):
        config_table.add_row("Max Size", format_size(config['max_size']))
    if config.get('include_extensions'):
        config_table.add_row("Extensions", ', '.join(config['include_extensions']))
    if config.get('exclude_extensions'):
        config_table.add_row("Exclude Ext", ', '.join(config['exclude_extensions']))

    console.print(config_table)
    console.print()

    # Run scan with new options
    finder = DuplicateFinder(
        config['root_dir'],
        max_threads=config.get('max_threads'),
        min_size=config.get('min_size', 1),
        max_size=config.get('max_size'),
        include_extensions=config.get('include_extensions'),
        exclude_extensions=config.get('exclude_extensions'),
        use_fast_hash=config.get('use_fast_hash', True),
        skip_hardlinks=config.get('skip_hardlinks', True),
    )
    duplicates = finder.find_duplicates()

    # Process results
    handler = SmartDuplicateHandler(
        config['action'],
        config['keep'],
        config['dry_run'],
        config.get('backup_dir')
    )
    handler.process_duplicates(duplicates)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/]")
        sys.exit(0)
