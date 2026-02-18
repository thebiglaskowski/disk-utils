"""
Integration tests for end-to-end duplicate detection and directory scanning.
"""
import io
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from duplicates import DuplicateFinder
from treesize_scan import analyze_file_ages


def _silent_console():
    """Create a silent Console that swallows all output."""
    return Console(file=io.StringIO(), force_terminal=True)


class TestDuplicateFinderIntegration:
    """End-to-end tests for duplicate detection."""

    @patch('duplicates.console', new_callable=_silent_console)
    def test_find_duplicates_basic(self, mock_console, duplicate_files: Path):
        """Test finding duplicates in a directory with known duplicates."""
        finder = DuplicateFinder(str(duplicate_files))
        duplicates_found = finder.find_duplicates()

        assert len(duplicates_found) >= 1

        large_group = [g for g in duplicates_found if len(g) == 3]
        assert len(large_group) == 1

        group_files = set(os.path.basename(f) for f in large_group[0])
        assert group_files == {"original.dat", "copy1.dat", "copy2.dat"}

    @patch('duplicates.console', new_callable=_silent_console)
    def test_find_duplicates_no_duplicates(self, mock_console, temp_dir: Path):
        """Test with files that have no duplicates."""
        (temp_dir / "file1.txt").write_text("Unique content 1")
        (temp_dir / "file2.txt").write_text("Unique content 2")
        (temp_dir / "file3.txt").write_text("Unique content 3")

        finder = DuplicateFinder(str(temp_dir))
        duplicates_found = finder.find_duplicates()

        assert len(duplicates_found) == 0

    @patch('duplicates.console', new_callable=_silent_console)
    def test_find_duplicates_with_size_filter(self, mock_console, duplicate_files: Path):
        """Test duplicate finding with size filters."""
        finder = DuplicateFinder(
            str(duplicate_files),
            min_size=10000,
        )
        duplicates_found = finder.find_duplicates()

        assert len(duplicates_found) == 0

    @patch('duplicates.console', new_callable=_silent_console)
    def test_find_duplicates_same_size_different_content(self, mock_console, temp_dir: Path):
        """Test that files with same size but different content are not duplicates."""
        (temp_dir / "a.bin").write_bytes(b"A" * 1000)
        (temp_dir / "b.bin").write_bytes(b"B" * 1000)

        finder = DuplicateFinder(str(temp_dir))
        duplicates_found = finder.find_duplicates()

        assert len(duplicates_found) == 0


class TestAnalyzeFileAges:
    """Tests for file age analysis."""

    @patch('treesize_scan.console', new_callable=_silent_console)
    def test_analyze_ages_basic(self, mock_console, sample_files: Path):
        """Test basic file age analysis."""
        age_buckets = analyze_file_ages(str(sample_files))

        assert isinstance(age_buckets, dict)
        assert "< 7 days" in age_buckets
        assert "> 1 year" in age_buckets
        assert age_buckets["< 7 days"]["count"] > 0

    @patch('treesize_scan.console', new_callable=_silent_console)
    def test_analyze_ages_buckets(self, mock_console, sample_files: Path):
        """Test that all age buckets are present."""
        age_buckets = analyze_file_ages(str(sample_files))

        expected_buckets = [
            "< 7 days",
            "7-30 days",
            "1-3 months",
            "3-6 months",
            "6-12 months",
            "> 1 year",
        ]

        for bucket in expected_buckets:
            assert bucket in age_buckets
            assert "count" in age_buckets[bucket]
            assert "size" in age_buckets[bucket]


class TestMemoryOptimizations:
    """Tests verifying memory optimizations are working."""

    def test_path_interning_reduces_memory(self):
        """Test that path interning actually shares string objects."""
        from utils import intern_path, clear_path_cache

        clear_path_cache()

        path1 = intern_path("/test/integration/path")
        path2 = intern_path("/test/integration/path")

        assert path1 is path2

    def test_lru_cache_working(self):
        """Test that LRU cache is functioning."""
        from utils import format_size

        format_size.cache_clear()

        format_size(1024)
        info1 = format_size.cache_info()

        format_size(1024)
        info2 = format_size.cache_info()

        assert info2.hits > info1.hits

    def test_slots_reduce_memory(self):
        """Test that __slots__ reduces instance memory."""
        from duplicates import DuplicateFinder, SmartDuplicateHandler

        finder = DuplicateFinder(".")
        handler = SmartDuplicateHandler("report", "oldest")

        assert not hasattr(finder, "__dict__")
        assert not hasattr(handler, "__dict__")
