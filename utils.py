#!/usr/bin/env python3
"""
Shared Utilities for Disk Utils
================================
Common constants, functions, and helpers used across all disk-utils modules.
"""

import os
import sys
import re
from typing import Dict, Generator, List, Optional, Set, Tuple
from functools import lru_cache

from questionary import Style


# --- Constants ---

# Size unit tuple (constant, not recreated each call)
SIZE_UNITS = ('B', 'KB', 'MB', 'GB', 'TB', 'PB')

# Directories to skip during scanning (significant speedup)
SKIP_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env', '.env',
    '$RECYCLE.BIN', 'System Volume Information', '.Trash-1000',
    'Windows', 'ProgramData', '.cache', '.npm', '.yarn',
    'AppData', '.local', 'site-packages', '.tox', '.pytest_cache',
}


# --- Path Interning ---

_INTERNED_PATHS: Dict[str, str] = {}


def intern_path(path: str) -> str:
    """Intern paths to reduce memory usage from duplicate strings."""
    if path not in _INTERNED_PATHS:
        _INTERNED_PATHS[path] = sys.intern(path)
    return _INTERNED_PATHS[path]


def clear_path_cache() -> None:
    """Clear the path interning cache to free memory between scans."""
    _INTERNED_PATHS.clear()


# --- Size Formatting ---

@lru_cache(maxsize=1024)
def format_size(num_bytes: int) -> str:
    """Format bytes to human-readable string. Cached for performance."""
    for unit in SIZE_UNITS:
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"


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


# --- Directory Walking ---

def fast_walk(
    top: str,
    skip_dirs: Optional[Set[str]] = None,
    follow_symlinks: bool = False,
    max_depth: Optional[int] = None,
) -> Generator[Tuple[str, List[str], List[os.DirEntry], int], None, None]:
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
                        if entry.is_dir(follow_symlinks=follow_symlinks):
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


# --- Menu Style ---

def create_menu_style(
    answer_color: str,
    selected_color: str = None,
    separator_color: str = '#673ab7',
) -> Style:
    """Create a questionary Style with the standard purple theme and custom accent colors."""
    selected_color = selected_color or answer_color
    return Style([
        ('qmark', 'fg:#673ab7 bold'),
        ('question', 'bold'),
        ('answer', f'fg:{answer_color} bold'),
        ('pointer', 'fg:#673ab7 bold'),
        ('highlighted', 'fg:#673ab7 bold'),
        ('selected', f'fg:{selected_color}'),
        ('separator', f'fg:{separator_color}'),
        ('instruction', 'fg:#808080'),
    ])
