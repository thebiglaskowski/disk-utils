"""
Pytest configuration and shared fixtures for disk-utils tests.
"""
import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Generator

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    tmp = tempfile.mkdtemp(prefix="diskutils_test_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def sample_files(temp_dir: Path) -> Path:
    """Create a sample directory structure with test files."""
    # Create directories
    (temp_dir / "subdir1").mkdir()
    (temp_dir / "subdir2").mkdir()
    (temp_dir / "subdir1" / "nested").mkdir()

    # Create files with known content
    (temp_dir / "file1.txt").write_text("Hello World")
    (temp_dir / "file2.txt").write_text("Hello World")  # Duplicate of file1
    (temp_dir / "file3.txt").write_text("Different content here")
    (temp_dir / "subdir1" / "file4.txt").write_text("Hello World")  # Another duplicate
    (temp_dir / "subdir1" / "nested" / "file5.txt").write_text("Nested file content")
    (temp_dir / "subdir2" / "large.bin").write_bytes(b"x" * 10000)

    return temp_dir


@pytest.fixture
def duplicate_files(temp_dir: Path) -> Path:
    """Create files specifically for duplicate detection testing."""
    # Same content, different names
    content = b"This is duplicate content for testing purposes." * 100

    (temp_dir / "original.dat").write_bytes(content)
    (temp_dir / "copy1.dat").write_bytes(content)
    (temp_dir / "copy2.dat").write_bytes(content)

    # Different content
    (temp_dir / "unique1.dat").write_bytes(b"Unique content 1" * 50)
    (temp_dir / "unique2.dat").write_bytes(b"Unique content 2" * 50)

    # Same size, different content (tests hash phase)
    same_size_content1 = b"A" * 1000
    same_size_content2 = b"B" * 1000
    (temp_dir / "samesize1.dat").write_bytes(same_size_content1)
    (temp_dir / "samesize2.dat").write_bytes(same_size_content2)

    return temp_dir


@pytest.fixture
def empty_dir(temp_dir: Path) -> Path:
    """Create an empty directory."""
    return temp_dir


@pytest.fixture
def deep_dir(temp_dir: Path) -> Path:
    """Create a deeply nested directory structure."""
    current = temp_dir
    for i in range(10):
        current = current / f"level{i}"
        current.mkdir()
        (current / f"file{i}.txt").write_text(f"Content at level {i}")
    return temp_dir
