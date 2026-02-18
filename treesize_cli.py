#!/usr/bin/env python3
"""
TreeSize CLI - Disk Space Analyzer
===================================
Interactive terminal application for analyzing disk usage with
rich visualizations, progress indicators, and smart filtering.

Dependencies: pip install rich questionary ollama
"""

import os
import csv
import json
from pathlib import Path
from typing import Dict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.markdown import Markdown

import questionary

from utils import format_size, create_menu_style

# Scanning engine
from treesize_scan import (
    parse_age,
    scan_largest_files,
    scan_largest_dirs,
    analyze_file_ages,
)

# Display / visualization
from treesize_display import (
    get_size_style,
    create_size_bar,
    print_file_results,
    print_treemap,
    print_dir_results,
    print_age_analysis,
    print_disk_usage,
)

# AI analysis (Ollama)
from treesize_ai import (
    get_ollama_models,
    check_ollama_running,
    ai_analyze_results,
)

# --- Configuration & Constants ---
console = Console()

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

MENU_STYLE = create_menu_style('#2196f3')


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

        console.print(f"[dim]Default path: {settings['default_path']}[/]")
        console.print()

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
