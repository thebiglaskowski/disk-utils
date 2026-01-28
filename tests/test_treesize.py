"""
Tests for treesize_cli functionality.
"""
import os
from pathlib import Path
from datetime import datetime, timedelta

import pytest

from treesize_cli import (
    format_size,
    parse_size,
    parse_age,
    get_size_style,
    create_size_bar,
    SIZE_UNITS,
    scan_largest_files,
    scan_largest_dirs,
)


class TestFormatSize:
    """Tests for the format_size function."""

    def test_bytes(self):
        """Test formatting bytes."""
        assert format_size(0) == "0.00 B"
        assert format_size(500) == "500.00 B"

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        assert format_size(1024) == "1.00 KB"

    def test_megabytes(self):
        """Test formatting megabytes."""
        assert format_size(1048576) == "1.00 MB"

    def test_gigabytes(self):
        """Test formatting gigabytes."""
        assert format_size(1073741824) == "1.00 GB"

    def test_caching(self):
        """Test that format_size uses lru_cache."""
        format_size(11111)
        format_size(11111)

        cache_info = format_size.cache_info()
        assert cache_info.hits >= 1


class TestParseSize:
    """Tests for the parse_size function."""

    def test_valid_sizes(self):
        """Test parsing valid size strings."""
        assert parse_size("100") == 100
        assert parse_size("1KB") == 1024
        assert parse_size("1MB") == 1048576
        assert parse_size("1GB") == 1073741824

    def test_with_spaces(self):
        """Test parsing with spaces."""
        assert parse_size("10 MB") == 10 * 1024 * 1024

    def test_case_insensitive(self):
        """Test case insensitivity."""
        assert parse_size("1kb") == 1024
        assert parse_size("1Kb") == 1024
        assert parse_size("1KB") == 1024

    def test_none_input(self):
        """Test None input returns None."""
        assert parse_size(None) is None

    def test_invalid_input(self):
        """Test invalid input returns None."""
        assert parse_size("invalid") is None


class TestParseAge:
    """Tests for the parse_age function."""

    def test_days(self):
        """Test parsing days."""
        result = parse_age("7d")
        expected = datetime.now() - timedelta(days=7)
        # Allow 1 second tolerance
        assert abs((result - expected).total_seconds()) < 1

    def test_weeks(self):
        """Test parsing weeks."""
        result = parse_age("2w")
        expected = datetime.now() - timedelta(weeks=2)
        assert abs((result - expected).total_seconds()) < 1

    def test_months(self):
        """Test parsing months (approximate)."""
        result = parse_age("1m")
        expected = datetime.now() - timedelta(days=30)
        assert abs((result - expected).total_seconds()) < 1

    def test_years(self):
        """Test parsing years (approximate)."""
        result = parse_age("1y")
        expected = datetime.now() - timedelta(days=365)
        assert abs((result - expected).total_seconds()) < 1

    def test_none_input(self):
        """Test None input returns None."""
        assert parse_age(None) is None

    def test_invalid_input(self):
        """Test invalid input returns None."""
        assert parse_age("invalid") is None
        assert parse_age("10x") is None


class TestGetSizeStyle:
    """Tests for the get_size_style function."""

    def test_small_files(self):
        """Test style for small files."""
        assert get_size_style(1000) == "green"
        assert get_size_style(1024 * 1024) == "green"

    def test_medium_files(self):
        """Test style for medium files (10MB+)."""
        assert get_size_style(10 * 1024 * 1024) == "cyan"
        assert get_size_style(50 * 1024 * 1024) == "cyan"

    def test_large_files(self):
        """Test style for large files (100MB+)."""
        assert get_size_style(100 * 1024 * 1024) == "bold yellow"
        assert get_size_style(500 * 1024 * 1024) == "bold yellow"

    def test_huge_files(self):
        """Test style for huge files (1GB+)."""
        assert get_size_style(1024 * 1024 * 1024) == "bold red"
        assert get_size_style(5 * 1024 * 1024 * 1024) == "bold red"


class TestCreateSizeBar:
    """Tests for the create_size_bar function."""

    def test_full_bar(self):
        """Test bar at 100%."""
        bar = create_size_bar(100, 100, width=10)
        # Should have filled characters
        assert "█" in str(bar)

    def test_empty_bar(self):
        """Test bar at 0%."""
        bar = create_size_bar(0, 100, width=10)
        # Should have empty characters
        assert "░" in str(bar)

    def test_half_bar(self):
        """Test bar at 50%."""
        bar = create_size_bar(50, 100, width=10)
        text = str(bar)
        assert "█" in text
        assert "░" in text

    def test_zero_max(self):
        """Test with zero max size."""
        bar = create_size_bar(0, 0, width=10)
        # Should not crash, should be empty
        assert "░" in str(bar)


class TestSizeUnits:
    """Tests for SIZE_UNITS constant."""

    def test_is_tuple(self):
        """Test SIZE_UNITS is immutable tuple."""
        assert isinstance(SIZE_UNITS, tuple)

    def test_contents(self):
        """Test SIZE_UNITS contains all units."""
        assert SIZE_UNITS == ('B', 'KB', 'MB', 'GB', 'TB', 'PB')


class TestScanLargestFiles:
    """Tests for scan_largest_files function."""

    def test_basic_scan(self, sample_files: Path):
        """Test basic file scanning."""
        results, stats = scan_largest_files(str(sample_files), top_n=10)

        assert isinstance(results, list)
        assert isinstance(stats, dict)
        assert "total_files" in stats
        assert "total_size" in stats
        assert stats["total_files"] > 0

    def test_top_n_limit(self, sample_files: Path):
        """Test that results are limited to top_n."""
        results, _ = scan_largest_files(str(sample_files), top_n=2)
        assert len(results) <= 2

    def test_results_sorted_descending(self, sample_files: Path):
        """Test that results are sorted largest first."""
        results, _ = scan_largest_files(str(sample_files), top_n=50)

        if len(results) > 1:
            sizes = [r[0] for r in results]
            assert sizes == sorted(sizes, reverse=True)

    def test_min_size_filter(self, sample_files: Path):
        """Test minimum size filtering."""
        results, stats = scan_largest_files(
            str(sample_files),
            min_size_bytes=5000,
            top_n=50,
        )

        # Only the large.bin file should pass (10000 bytes)
        for size, path in results:
            assert size >= 5000

    def test_quick_mode(self, sample_files: Path):
        """Test quick mode (files > 1MB only)."""
        results, stats = scan_largest_files(
            str(sample_files),
            quick_mode=True,
            top_n=50,
        )

        # Should filter out small test files
        assert stats.get("quick_mode") is True

    def test_returns_file_paths(self, sample_files: Path):
        """Test that results contain valid file paths."""
        results, _ = scan_largest_files(str(sample_files), top_n=50)

        for size, path in results:
            assert os.path.isfile(path)

    def test_extension_tracking(self, sample_files: Path):
        """Test that extension statistics are tracked."""
        results, stats = scan_largest_files(str(sample_files), top_n=50)

        assert "top_extensions" in stats
        # Should have tracked .txt and .bin extensions
        extensions = [ext for ext, _ in stats["top_extensions"]]
        assert len(extensions) > 0


class TestScanLargestDirs:
    """Tests for scan_largest_dirs function."""

    def test_basic_scan(self, sample_files: Path):
        """Test basic directory scanning."""
        results, stats = scan_largest_dirs(str(sample_files), top_n=10)

        assert isinstance(results, list)
        assert isinstance(stats, dict)
        assert "total_dirs" in stats
        assert stats["total_dirs"] > 0

    def test_top_n_limit(self, sample_files: Path):
        """Test that results are limited to top_n."""
        results, _ = scan_largest_dirs(str(sample_files), top_n=2)
        assert len(results) <= 2

    def test_results_sorted_descending(self, sample_files: Path):
        """Test that results are sorted largest first."""
        results, _ = scan_largest_dirs(str(sample_files), top_n=50)

        if len(results) > 1:
            sizes = [r[0] for r in results]
            assert sizes == sorted(sizes, reverse=True)

    def test_returns_directory_paths(self, sample_files: Path):
        """Test that results contain valid directory paths."""
        results, _ = scan_largest_dirs(str(sample_files), top_n=50)

        for size, path in results:
            assert os.path.isdir(path)

    def test_parent_includes_child_sizes(self, sample_files: Path):
        """Test that parent directory sizes include children."""
        results, _ = scan_largest_dirs(str(sample_files), top_n=50)

        # Root should have the largest size (includes all children)
        if results:
            root_entry = [r for r in results if r[1] == str(sample_files.absolute())]
            if root_entry:
                root_size = root_entry[0][0]
                # All other sizes should be <= root size
                for size, path in results:
                    assert size <= root_size

    def test_max_depth_limit(self, deep_dir: Path):
        """Test max_depth parameter limits depth."""
        shallow_results, _ = scan_largest_dirs(str(deep_dir), max_depth=2, top_n=50)
        deep_results, _ = scan_largest_dirs(str(deep_dir), max_depth=None, top_n=50)

        # Shallow scan should find fewer directories
        assert len(shallow_results) <= len(deep_results)
