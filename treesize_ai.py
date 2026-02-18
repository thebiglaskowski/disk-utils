#!/usr/bin/env python3
"""
TreeSize AI Module
===================
Ollama integration for AI-powered analysis of scan results.
"""

from typing import List, Dict

from rich.console import Console

from utils import format_size

# Optional Ollama integration
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

console = Console()

ICONS = {
    'ai': '🤖',
    'warning': '⚠️',
}


def get_ollama_models() -> List[str]:
    """Get list of available Ollama models."""
    if not OLLAMA_AVAILABLE:
        console.print("[dim]Ollama Python package not installed. Run: pip install ollama[/]")
        return []
    try:
        models = ollama.list()
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
        console.print(f"[dim]Ollama connection failed: {type(e).__name__}: {e}[/]")
        return False


def ai_analyze_results(results: Dict, model: str) -> str:
    """Send scan results to Ollama for AI analysis."""
    if not OLLAMA_AVAILABLE or not results:
        return "AI analysis unavailable."

    result_type = results.get("type", "files")
    data = results.get("data", [])
    stats = results.get("stats", {})

    if result_type == "files":
        items_text = "\n".join([
            f"  {i+1}. {format_size(size)} - {path}"
            for i, (size, path) in enumerate(data[:20])
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
