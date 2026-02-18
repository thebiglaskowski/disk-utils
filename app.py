#!/usr/bin/env python3
"""
Disk Utils - Comprehensive Disk Management Suite
=================================================
A beautiful terminal application combining duplicate file detection
and disk space analysis with rich visualizations and smart features.

Dependencies: pip install rich questionary
Optional:     pip install xxhash ollama
"""

import sys
import os

# Rich library for beautiful terminal output
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Questionary for interactive menus
import questionary

# Shared utilities
from utils import create_menu_style

# Import tool modules
from treesize_cli import main_menu as treesize_menu
from nul_scanner import main_menu as nul_menu

# --- Configuration ---
console = Console()

MENU_STYLE = create_menu_style('#00bcd4')

# Icons
ICONS = {
    'app': '🛠️',
    'duplicates': '🔍',
    'treesize': '💾',
    'nul': '☢️',
    'exit': '🚪',
    'success': '✅',
    'info': 'ℹ️',
}


def show_main_banner():
    """Display the main application banner."""
    banner = Text()
    banner.append("╔══════════════════════════════════════════════════════════════════╗\n", style="bold magenta")
    banner.append("║", style="bold magenta")
    banner.append("              🛠️  DISK UTILS - Management Suite  🛠️              ", style="bold white")
    banner.append("║\n", style="bold magenta")
    banner.append("║", style="bold magenta")
    banner.append("      Duplicate Finder  •  Disk Analyzer  •  NUL Nuker      ", style="dim white")
    banner.append("║\n", style="bold magenta")
    banner.append("╚══════════════════════════════════════════════════════════════════╝", style="bold magenta")
    console.print(banner)
    console.print()


def show_about():
    """Display about information."""
    console.print()
    console.print(Panel(
        "[bold cyan]Disk Utils[/] - A comprehensive disk management suite\n\n"
        "[bold]Features:[/]\n"
        "  • [cyan]Duplicate Finder[/] - Find and handle duplicate files\n"
        "    - 3-stage filtering (size → partial hash → full hash)\n"
        "    - Parallel hashing with configurable threads\n"
        "    - Smart keeper selection (oldest, newest, shortest path)\n"
        "    - Actions: report, delete, move, hardlink\n"
        "    - Optional xxhash for faster detection\n\n"
        "  • [cyan]TreeSize CLI[/] - Analyze disk space usage\n"
        "    - Find largest files and directories\n"
        "    - File age analysis\n"
        "    - Extension breakdown\n"
        "    - AI-powered cleanup suggestions (Ollama)\n"
        "    - Export to CSV/JSON\n\n"
        "  • [cyan]NUL Nuker[/] - Find & nuke reserved-name artifacts\n"
        "    - Scan for 'nul' files (buggy tool artifacts)\n"
        "    - Optional scan for all Windows reserved names\n"
        "    - Safe deletion using \\\\\\\\?\\\\ extended path prefix\n"
        "    - Dry-run mode with confirmation\n\n"
        "[dim]Press any key to return to the main menu...[/]",
        title=f"{ICONS['info']} About Disk Utils",
        border_style="cyan",
        padding=(1, 2)
    ))
    questionary.press_any_key_to_continue(style=MENU_STYLE).ask()


def main():
    """Main application entry point."""
    while True:
        console.clear()
        show_main_banner()

        # Show quick tips
        console.print("[dim]Select a utility to get started:[/]\n")

        choice = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice(
                    f"{ICONS['duplicates']} Duplicate File Finder",
                    value="duplicates"
                ),
                questionary.Choice(
                    f"{ICONS['treesize']} Disk Space Analyzer (TreeSize)",
                    value="treesize"
                ),
                questionary.Choice(
                    f"{ICONS['nul']} NUL Nuker",
                    value="nul_scanner"
                ),
                questionary.Choice(
                    f"{ICONS['info']} About",
                    value="about"
                ),
                questionary.Choice(
                    f"{ICONS['exit']} Exit",
                    value="exit"
                ),
            ],
            style=MENU_STYLE
        ).ask()

        if choice is None or choice == "exit":
            console.clear()
            console.print(Panel(
                "[bold green]Thank you for using Disk Utils![/]\n\n"
                "[dim]Keep your drives clean and organized.[/]",
                title=f"{ICONS['success']} Goodbye",
                border_style="green"
            ))
            break

        elif choice == "duplicates":
            console.clear()
            try:
                # Run the duplicates interactive menu
                from duplicates import main as run_duplicates
                run_duplicates()
            except KeyboardInterrupt:
                console.print("\n[yellow]Returning to main menu...[/]")
            except SystemExit:
                pass  # Catch sys.exit() from the module

        elif choice == "treesize":
            console.clear()
            try:
                # Run the treesize menu
                treesize_menu()
            except KeyboardInterrupt:
                console.print("\n[yellow]Returning to main menu...[/]")
            except SystemExit:
                pass  # Catch sys.exit() from the module

        elif choice == "nul_scanner":
            console.clear()
            try:
                nul_menu()
            except KeyboardInterrupt:
                console.print("\n[yellow]Returning to main menu...[/]")
            except SystemExit:
                pass

        elif choice == "about":
            console.clear()
            show_about()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Goodbye![/]")
        sys.exit(0)
