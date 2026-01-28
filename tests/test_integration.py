"""
Integration tests for end-to-end duplicate detection and directory scanning.
"""
import os
from pathlib import Path

import pytest

from duplicates import DuplicateFinder
from treesize_cli import analyze_file_ages


class TestDuplicateFinderIntegration:
    """End-to-end tests for duplicate detection."""

    def test_find_duplicates_basic(self, duplicate_files: Path):
        """Test finding duplicates in a directory with known duplicates."""
        finder = DuplicateFinder(str(duplicate_files))

        # Mock console output to avoid terminal issues in tests
        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None

        try:
            duplicates_found = finder.find_duplicates()
        finally:
            duplicates.console.print = original_print

        # Should find the duplicate group (original.dat, copy1.dat, copy2.dat)
        assert len(duplicates_found) >= 1

        # Find the group with 3 files
        large_group = [g for g in duplicates_found if len(g) == 3]
        assert len(large_group) == 1

        # Verify the files in the group
        group_files = set(os.path.basename(f) for f in large_group[0])
        assert group_files == {"original.dat", "copy1.dat", "copy2.dat"}

    def test_find_duplicates_no_duplicates(self, temp_dir: Path):
        """Test with files that have no duplicates."""
        # Create files with unique content
        (temp_dir / "file1.txt").write_text("Unique content 1")
        (temp_dir / "file2.txt").write_text("Unique content 2")
        (temp_dir / "file3.txt").write_text("Unique content 3")

        finder = DuplicateFinder(str(temp_dir))

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None

        try:
            duplicates_found = finder.find_duplicates()
        finally:
            duplicates.console.print = original_print

        # Should find no duplicates
        assert len(duplicates_found) == 0

    def test_find_duplicates_with_size_filter(self, duplicate_files: Path):
        """Test duplicate finding with size filters."""
        # The duplicate files are ~4700 bytes each
        finder = DuplicateFinder(
            str(duplicate_files),
            min_size=10000,  # Higher than our test files
        )

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None

        try:
            duplicates_found = finder.find_duplicates()
        finally:
            duplicates.console.print = original_print

        # Should find no duplicates (all files filtered out)
        assert len(duplicates_found) == 0

    def test_find_duplicates_same_size_different_content(self, temp_dir: Path):
        """Test that files with same size but different content are not duplicates."""
        # Create files with same size but different content
        (temp_dir / "a.bin").write_bytes(b"A" * 1000)
        (temp_dir / "b.bin").write_bytes(b"B" * 1000)

        finder = DuplicateFinder(str(temp_dir))

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None

        try:
            duplicates_found = finder.find_duplicates()
        finally:
            duplicates.console.print = original_print

        # Should not be marked as duplicates
        assert len(duplicates_found) == 0


class TestAnalyzeFileAges:
    """Tests for file age analysis."""

    def test_analyze_ages_basic(self, sample_files: Path):
        """Test basic file age analysis."""
        import treesize_cli
        original_print = treesize_cli.console.print
        treesize_cli.console.print = lambda *args, **kwargs: None

        try:
            age_buckets = analyze_file_ages(str(sample_files))
        finally:
            treesize_cli.console.print = original_print

        # Should return a dict with age buckets
        assert isinstance(age_buckets, dict)
        assert "< 7 days" in age_buckets
        assert "> 1 year" in age_buckets

        # All files we just created should be in < 7 days bucket
        assert age_buckets["< 7 days"]["count"] > 0

    def test_analyze_ages_buckets(self, sample_files: Path):
        """Test that all age buckets are present."""
        import treesize_cli
        original_print = treesize_cli.console.print
        treesize_cli.console.print = lambda *args, **kwargs: None

        try:
            age_buckets = analyze_file_ages(str(sample_files))
        finally:
            treesize_cli.console.print = original_print

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

    def test_path_interning_reduces_memory(self, sample_files: Path):
        """Test that path interning actually shares string objects."""
        from duplicates import DuplicateFinder

        finder = DuplicateFinder(str(sample_files))

        # Intern the same path twice
        path1 = finder._intern_path(str(sample_files))
        path2 = finder._intern_path(str(sample_files))

        # Should be the exact same object (not just equal)
        assert path1 is path2

    def test_lru_cache_working(self):
        """Test that LRU cache is functioning."""
        from duplicates import format_size

        # Clear cache
        format_size.cache_clear()

        # First call - cache miss
        format_size(1024)
        info1 = format_size.cache_info()

        # Second call - cache hit
        format_size(1024)
        info2 = format_size.cache_info()

        assert info2.hits > info1.hits

    def test_slots_reduce_memory(self):
        """Test that __slots__ reduces instance memory."""
        from duplicates import DuplicateFinder, SmartDuplicateHandler

        # Classes with __slots__ shouldn't have __dict__
        finder = DuplicateFinder(".")
        handler = SmartDuplicateHandler("report", "oldest")

        assert not hasattr(finder, "__dict__")
        assert not hasattr(handler, "__dict__")
