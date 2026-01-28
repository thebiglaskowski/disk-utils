# Disk Utils

A comprehensive disk management suite with beautiful terminal interfaces for finding duplicate files and analyzing disk space usage.

![CI](https://github.com/thebiglaskowski/disk-utils/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Coverage](https://img.shields.io/badge/coverage-86%25-brightgreen.svg)

## Features

### Duplicate File Finder
- **3-Stage Detection**: Size grouping → Partial hash → Full hash (efficient and accurate)
- **Parallel Processing**: Multi-threaded hashing for fast scans
- **Smart Selection**: Keep oldest, newest, or shortest path files
- **Multiple Actions**: Report, delete, move to backup, or replace with hardlinks
- **Advanced Filters**: Filter by size, extension, skip existing hardlinks
- **Fast Hashing**: Optional xxhash support (10x faster than SHA-256)

### Disk Space Analyzer (TreeSize CLI)
- **Largest Files/Directories**: Find what's consuming your disk space
- **File Age Analysis**: Identify old files for potential cleanup
- **Extension Breakdown**: See which file types use the most space
- **Visual Treemap**: Terminal-based block visualization
- **AI Analysis**: Get cleanup recommendations via Ollama (optional)
- **Export**: Save results to CSV or JSON

## Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)

### Quick Install

```bash
# Clone the repository
git clone https://github.com/thebiglaskowski/disk-utils.git
cd disk-utils

# Install dependencies
pip install -r requirements.txt

# Optional: Install faster hashing
pip install xxhash

# Optional: Install Ollama integration
pip install ollama
```

### Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| `rich` | Yes | Beautiful terminal formatting |
| `questionary` | Yes | Interactive CLI prompts |
| `xxhash` | No | Faster hashing (recommended) |
| `ollama` | No | AI-powered analysis |

## Usage

### Main Application

Launch the unified menu to access all utilities:

```bash
python app.py
```

### Duplicate File Finder

#### Interactive Mode
```bash
python duplicates.py
```

#### Command Line Mode
```bash
# Basic scan (report only)
python duplicates.py /path/to/scan

# Delete duplicates, keep oldest files
python duplicates.py /path/to/scan --action delete --keep oldest --no-dry-run

# Move duplicates to backup folder
python duplicates.py /path/to/scan --action move --backup-dir /path/to/backup

# Replace duplicates with hardlinks (saves space)
python duplicates.py /path/to/scan --action hardlink --no-dry-run

# Scan only large image files
python duplicates.py /path/to/scan --min-size 1MB --ext jpg,png,gif

# Exclude temp files, use fast hashing
python duplicates.py /path/to/scan --exclude-ext tmp,log --fast-hash
```

#### Command Line Options

| Option | Description |
|--------|-------------|
| `--action` | Action for duplicates: `report`, `delete`, `move`, `hardlink` |
| `--keep` | Which file to keep: `oldest`, `newest`, `shortest_path` |
| `--dry-run` | Simulate without making changes (default) |
| `--no-dry-run` | Actually perform the action |
| `--backup-dir` | Directory to move duplicates (required for `move`) |
| `--min-size` | Minimum file size (e.g., `1KB`, `10MB`, `1GB`) |
| `--max-size` | Maximum file size |
| `--ext` | Only include these extensions (comma-separated) |
| `--exclude-ext` | Exclude these extensions |
| `--fast-hash` | Use xxhash for faster hashing (default if available) |
| `--secure-hash` | Use SHA-256 instead of xxhash |
| `--threads` | Number of threads for parallel hashing |
| `--include-hardlinks` | Don't skip files that are already hardlinked |

### Disk Space Analyzer

```bash
python treesize_cli.py
```

This launches an interactive menu with options to:
- Scan for largest files
- Scan for largest directories
- Analyze file ages
- Show disk usage
- View treemap visualization
- Get AI analysis (requires Ollama)
- Export results to CSV/JSON
- Configure settings

## Screenshots

### Main Menu
```
╔══════════════════════════════════════════════════════════════════╗
║              🛠️  DISK UTILS - Management Suite  🛠️              ║
║         Duplicate Finder  •  Disk Space Analyzer             ║
╚══════════════════════════════════════════════════════════════════╝

? What would you like to do?
❯ 🔍 Duplicate File Finder
  💾 Disk Space Analyzer (TreeSize)
  ℹ️  About
  🚪 Exit
```

### Duplicate Finder Results
```
╭──────────────────────────────────────────────────────────────────╮
│ 🔍 Scanning Directory                                            │
│ 📂 C:\Users\Photos                                               │
│ Hash: xxhash (fast) | Threads: 32 | Skip hardlinks: True         │
╰──────────────────────────────────────────────────────────────────╯

Phase 1/3: 🔍 Scanning files...
   ✓ Found 15,234 files

Phase 2/3: 🔐 Calculating partial hashes...
   ✓ 1,245 groups remain (3,891 files)

Phase 3/3: 🔐 Calculating full hashes...
   ✓ Confirmed 523 duplicate groups
```

### Disk Space Analysis
```
╭─────────────────────────────────────────╮
│ 📊 Top 10 Largest Files                 │
├────┬──────────────┬──────────────────────┤
│  1 │     4.52 GB  │ ████████████████████ │
│  2 │     2.31 GB  │ ██████████           │
│  3 │     1.87 GB  │ ████████             │
│  4 │   892.45 MB  │ ████                 │
│  5 │   654.12 MB  │ ███                  │
╰────┴──────────────┴──────────────────────╯
```

## Configuration

### TreeSize Settings

Settings are saved to `~/.treesize/settings.json`:

```json
{
  "top_n": 50,
  "min_file_size_bytes": 0,
  "min_dir_size_bytes": 0,
  "follow_symlinks": false,
  "default_path": "C:\\",
  "max_depth": null,
  "quick_mode": false,
  "ollama_model": "llama3.2"
}
```

### Skipped Directories

By default, these directories are skipped during scanning:
- `.git`, `node_modules`, `__pycache__`
- `.venv`, `venv`, `env`
- `$RECYCLE.BIN`, `System Volume Information`
- `Windows`, `ProgramData`, `AppData`
- `.cache`, `.npm`, `.yarn`

## AI Analysis (Ollama)

To enable AI-powered cleanup recommendations:

1. Install Ollama: https://ollama.ai
2. Pull a model: `ollama pull llama3.2`
3. Start Ollama: `ollama serve`
4. Install the Python package: `pip install ollama`
5. Select your model in Settings

The AI will analyze your scan results and provide:
- File categorization (temp files, caches, media, etc.)
- Safe-to-delete recommendations
- Files to keep
- Specific cleanup suggestions

## Performance Tips

1. **Use xxhash**: Install `xxhash` for 10x faster duplicate detection
2. **Quick Mode**: Enable in TreeSize settings to skip files under 1MB
3. **Thread Count**: Adjust based on your system (default: 4x CPU cores, max 32)
4. **Size Filters**: Use `--min-size` to skip small files when finding duplicates
5. **Extension Filters**: Focus on specific file types with `--ext`

## Safety Features

- **Dry Run by Default**: Duplicate finder simulates actions without making changes
- **Atomic Operations**: Hardlink replacement uses temp files to prevent data loss
- **Smart Skipping**: Automatically skips system directories and symlinks
- **Existing Hardlinks**: Detects and skips files already hardlinked to each other

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- [Rich](https://github.com/Textualize/rich) - Beautiful terminal formatting
- [Questionary](https://github.com/tmbo/questionary) - Interactive CLI prompts
- [xxhash](https://github.com/Cyan4973/xxHash) - Extremely fast hashing
- [Ollama](https://ollama.ai) - Local AI models
