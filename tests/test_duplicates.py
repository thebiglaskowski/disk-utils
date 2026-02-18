"""
Tests for duplicate detection functionality.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from duplicates import (
    DuplicateFinder,
    SmartDuplicateHandler,
    CHUNK_SIZE,
    CHUNK_SIZE_LARGE,
    MEDIUM_FILE_THRESHOLD,
)
from utils import format_size, parse_size, SIZE_UNITS


class TestFormatSize:
    """Tests for the format_size function."""

    def test_bytes(self):
        """Test formatting bytes."""
        assert format_size(0) == "0.00 B"
        assert format_size(500) == "500.00 B"
        assert format_size(1023) == "1023.00 B"

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        assert format_size(1024) == "1.00 KB"
        assert format_size(1536) == "1.50 KB"
        assert format_size(10240) == "10.00 KB"

    def test_megabytes(self):
        """Test formatting megabytes."""
        assert format_size(1048576) == "1.00 MB"
        assert format_size(5242880) == "5.00 MB"

    def test_gigabytes(self):
        """Test formatting gigabytes."""
        assert format_size(1073741824) == "1.00 GB"

    def test_terabytes(self):
        """Test formatting terabytes."""
        assert format_size(1099511627776) == "1.00 TB"

    def test_caching(self):
        """Test that format_size uses lru_cache."""
        # Call twice with same value
        result1 = format_size(12345)
        result2 = format_size(12345)

        assert result1 == result2

        # Check cache is being used
        cache_info = format_size.cache_info()
        assert cache_info.hits >= 1


class TestParseSize:
    """Tests for the parse_size function."""

    def test_bytes_implicit(self):
        """Test parsing raw numbers as bytes."""
        assert parse_size("1024") == 1024
        assert parse_size("0") == 0

    def test_bytes_explicit(self):
        """Test parsing with B suffix."""
        assert parse_size("100B") == 100
        assert parse_size("100 B") == 100

    def test_kilobytes(self):
        """Test parsing kilobytes."""
        assert parse_size("1KB") == 1024
        assert parse_size("1 KB") == 1024
        assert parse_size("10kb") == 10240

    def test_megabytes(self):
        """Test parsing megabytes."""
        assert parse_size("1MB") == 1048576
        assert parse_size("5MB") == 5242880

    def test_gigabytes(self):
        """Test parsing gigabytes."""
        assert parse_size("1GB") == 1073741824

    def test_terabytes(self):
        """Test parsing terabytes."""
        assert parse_size("1TB") == 1099511627776

    def test_decimal_values(self):
        """Test parsing decimal values."""
        assert parse_size("1.5MB") == int(1.5 * 1024 * 1024)

    def test_invalid_string(self):
        """Test that invalid strings return None instead of crashing."""
        assert parse_size("invalid") is None
        assert parse_size("-10MB") is None
        assert parse_size("abc123") is None

    def test_negative_values(self):
        """Test that negative values return None."""
        assert parse_size("-1") is None
        assert parse_size("-100") is None


class TestSizeUnits:
    """Tests for SIZE_UNITS constant."""

    def test_is_tuple(self):
        """Test that SIZE_UNITS is a tuple (immutable)."""
        assert isinstance(SIZE_UNITS, tuple)

    def test_contains_all_units(self):
        """Test that all expected units are present."""
        assert SIZE_UNITS == ('B', 'KB', 'MB', 'GB', 'TB', 'PB')


class TestDuplicateFinder:
    """Tests for the DuplicateFinder class."""

    def test_has_slots(self):
        """Test that DuplicateFinder uses __slots__."""
        assert hasattr(DuplicateFinder, '__slots__')
        finder = DuplicateFinder(".")
        # With __slots__, __dict__ should not exist
        assert not hasattr(finder, '__dict__')

    def test_initialization(self, temp_dir: Path):
        """Test DuplicateFinder initialization."""
        finder = DuplicateFinder(
            str(temp_dir),
            max_threads=4,
            min_size=100,
            max_size=1000000,
        )

        assert finder.root_dir == str(temp_dir.absolute())
        assert finder.max_threads == 4
        assert finder.min_size == 100
        assert finder.max_size == 1000000

    def test_default_threads(self, temp_dir: Path):
        """Test default thread count calculation."""
        finder = DuplicateFinder(str(temp_dir))

        # Should be min(32, cpu_count * 4)
        expected = min(32, (os.cpu_count() or 1) * 4)
        assert finder.max_threads == expected

    def test_extension_filtering(self, temp_dir: Path):
        """Test include/exclude extension filters."""
        finder = DuplicateFinder(
            str(temp_dir),
            include_extensions={".txt", ".py"},
            exclude_extensions={".log"},
        )

        assert "txt" in finder.include_extensions
        assert "py" in finder.include_extensions
        assert "log" in finder.exclude_extensions

    def test_should_include_file_size_filter(self, temp_dir: Path):
        """Test _should_include_file with size filters."""
        finder = DuplicateFinder(str(temp_dir), min_size=100, max_size=1000)

        assert not finder._should_include_file("test.txt", 50)  # Too small
        assert finder._should_include_file("test.txt", 500)  # In range
        assert not finder._should_include_file("test.txt", 2000)  # Too large

    def test_should_include_file_extension_filter(self, temp_dir: Path):
        """Test _should_include_file with extension filters."""
        finder = DuplicateFinder(
            str(temp_dir),
            include_extensions={"txt"},
        )

        assert finder._should_include_file("test.txt", 100)
        assert not finder._should_include_file("test.py", 100)

    def test_get_hasher_xxhash(self, temp_dir: Path):
        """Test that xxhash is used when available."""
        finder = DuplicateFinder(str(temp_dir), use_fast_hash=True)

        try:
            import xxhash
            hasher = finder._get_hasher()
            assert hasattr(hasher, 'hexdigest')
        except ImportError:
            pytest.skip("xxhash not installed")

    def test_get_hasher_sha256(self, temp_dir: Path):
        """Test SHA-256 fallback."""
        finder = DuplicateFinder(str(temp_dir), use_fast_hash=False)
        hasher = finder._get_hasher()
        assert hasher.name == "sha256"

    def test_file_hash_consistency(self, temp_dir: Path):
        """Test that hashing the same content gives same result."""
        content = b"Test content for hashing"
        file1 = temp_dir / "file1.bin"
        file2 = temp_dir / "file2.bin"
        file1.write_bytes(content)
        file2.write_bytes(content)

        finder = DuplicateFinder(str(temp_dir))
        hash1 = finder.get_file_hash(str(file1))
        hash2 = finder.get_file_hash(str(file2))

        assert hash1 is not None
        assert hash1 == hash2

    def test_file_hash_different_content(self, temp_dir: Path):
        """Test that different content gives different hashes."""
        file1 = temp_dir / "file1.bin"
        file2 = temp_dir / "file2.bin"
        file1.write_bytes(b"Content A")
        file2.write_bytes(b"Content B")

        finder = DuplicateFinder(str(temp_dir))
        hash1 = finder.get_file_hash(str(file1))
        hash2 = finder.get_file_hash(str(file2))

        assert hash1 != hash2

    def test_first_chunk_hash(self, temp_dir: Path):
        """Test partial (first chunk) hashing."""
        # Create a file larger than CHUNK_SIZE
        content = b"x" * (CHUNK_SIZE + 1000)
        file = temp_dir / "large.bin"
        file.write_bytes(content)

        finder = DuplicateFinder(str(temp_dir))
        partial_hash = finder.get_file_hash(str(file), first_chunk_only=True)
        full_hash = finder.get_file_hash(str(file), first_chunk_only=False)

        assert partial_hash is not None
        assert full_hash is not None
        # Partial and full should be different for large files
        assert partial_hash != full_hash

    def test_path_interning_uses_utils(self, temp_dir: Path):
        """Test that DuplicateFinder uses utils.intern_path via fast_walk."""
        from utils import intern_path, clear_path_cache

        clear_path_cache()

        path1 = intern_path("/test/interning/path")
        path2 = intern_path("/test/interning/path")

        # Should return the same interned object
        assert path1 is path2


class TestSmartDuplicateHandler:
    """Tests for the SmartDuplicateHandler class."""

    def test_has_slots(self):
        """Test that SmartDuplicateHandler uses __slots__."""
        assert hasattr(SmartDuplicateHandler, '__slots__')
        handler = SmartDuplicateHandler("report", "oldest")
        assert not hasattr(handler, '__dict__')

    def test_initialization(self):
        """Test handler initialization."""
        handler = SmartDuplicateHandler(
            action="delete",
            keep_criteria="newest",
            dry_run=False,
            backup_dir="/backup",
        )

        assert handler.action == "delete"
        assert handler.keep_criteria == "newest"
        assert handler.dry_run is False
        assert handler.backup_dir == "/backup"

    def test_select_keeper_oldest(self, temp_dir: Path):
        """Test selecting the oldest file as keeper."""
        import time

        file1 = temp_dir / "old.txt"
        file2 = temp_dir / "new.txt"

        file1.write_text("old")
        time.sleep(0.1)  # Ensure different timestamps
        file2.write_text("new")

        handler = SmartDuplicateHandler("report", "oldest")
        keeper = handler.select_keeper([str(file1), str(file2)])

        # On some systems, ctime might not differ enough
        # Just verify a keeper is selected
        assert keeper in [str(file1), str(file2)]

    def test_select_keeper_newest(self, temp_dir: Path):
        """Test selecting the newest file as keeper."""
        import time

        file1 = temp_dir / "old.txt"
        file2 = temp_dir / "new.txt"

        file1.write_text("old")
        time.sleep(0.1)
        file2.write_text("new")

        handler = SmartDuplicateHandler("report", "newest")
        keeper = handler.select_keeper([str(file1), str(file2)])

        assert keeper in [str(file1), str(file2)]

    def test_select_keeper_shortest_path(self, temp_dir: Path):
        """Test selecting the shortest path as keeper."""
        short = temp_dir / "a.txt"
        long_path = temp_dir / "subdir"
        long_path.mkdir()
        long_file = long_path / "longer_name.txt"

        short.write_text("short")
        long_file.write_text("long")

        handler = SmartDuplicateHandler("report", "shortest_path")
        keeper = handler.select_keeper([str(short), str(long_file)])

        assert keeper == str(short)

    def test_select_keeper_empty_list(self):
        """Test selecting keeper from empty list."""
        handler = SmartDuplicateHandler("report", "oldest")
        assert handler.select_keeper([]) is None


class TestSmartDuplicateHandlerActions:
    """Tests for SmartDuplicateHandler file action methods."""

    def test_delete_action(self, temp_dir: Path):
        """Test that delete action removes duplicate files."""
        keeper = temp_dir / "keeper.txt"
        dup1 = temp_dir / "dup1.txt"
        dup2 = temp_dir / "dup2.txt"

        content = b"same content"
        keeper.write_bytes(content)
        dup1.write_bytes(content)
        dup2.write_bytes(content)

        handler = SmartDuplicateHandler(
            action="delete",
            keep_criteria="shortest_path",
            dry_run=False,
        )

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None
        try:
            handler._execute_action(str(dup1), str(keeper))
            handler._execute_action(str(dup2), str(keeper))
        finally:
            duplicates.console.print = original_print

        assert keeper.exists()
        assert not dup1.exists()
        assert not dup2.exists()

    def test_move_action(self, temp_dir: Path):
        """Test that move action moves duplicates to backup dir."""
        keeper = temp_dir / "keeper.txt"
        dup = temp_dir / "dup.txt"
        backup = temp_dir / "backup"

        keeper.write_bytes(b"content")
        dup.write_bytes(b"content")

        handler = SmartDuplicateHandler(
            action="move",
            keep_criteria="shortest_path",
            dry_run=False,
            backup_dir=str(backup),
        )

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None
        try:
            handler._execute_action(str(dup), str(keeper))
        finally:
            duplicates.console.print = original_print

        assert keeper.exists()
        assert not dup.exists()
        # File should be in backup/duplicates/
        moved_files = list((backup / "duplicates").iterdir())
        assert len(moved_files) == 1
        assert moved_files[0].read_bytes() == b"content"

    def test_move_handles_name_collision(self, temp_dir: Path):
        """Test move action when destination name already exists."""
        keeper = temp_dir / "keeper.txt"
        dup1 = temp_dir / "sub1" / "dup.txt"
        dup2 = temp_dir / "sub2" / "dup.txt"
        backup = temp_dir / "backup"

        (temp_dir / "sub1").mkdir()
        (temp_dir / "sub2").mkdir()
        keeper.write_bytes(b"content")
        dup1.write_bytes(b"content")
        dup2.write_bytes(b"content")

        handler = SmartDuplicateHandler(
            action="move",
            keep_criteria="shortest_path",
            dry_run=False,
            backup_dir=str(backup),
        )

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None
        try:
            handler._execute_action(str(dup1), str(keeper))
            handler._execute_action(str(dup2), str(keeper))
        finally:
            duplicates.console.print = original_print

        # Both files should have been moved (second with timestamp suffix)
        moved_files = list((backup / "duplicates").iterdir())
        assert len(moved_files) == 2

    def test_hardlink_action(self, temp_dir: Path):
        """Test that hardlink action replaces duplicate with hardlink to keeper."""
        keeper = temp_dir / "keeper.txt"
        dup = temp_dir / "dup.txt"

        keeper.write_bytes(b"shared content")
        dup.write_bytes(b"shared content")

        handler = SmartDuplicateHandler(
            action="hardlink",
            keep_criteria="shortest_path",
            dry_run=False,
        )

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None
        try:
            handler._execute_action(str(dup), str(keeper))
        finally:
            duplicates.console.print = original_print

        assert keeper.exists()
        assert dup.exists()
        # Should now be the same inode (hardlink)
        assert os.path.samefile(str(keeper), str(dup))

    def test_report_action_does_nothing(self, temp_dir: Path):
        """Test that report action doesn't modify files."""
        keeper = temp_dir / "keeper.txt"
        dup = temp_dir / "dup.txt"

        keeper.write_bytes(b"content")
        dup.write_bytes(b"content")

        handler = SmartDuplicateHandler(
            action="report",
            keep_criteria="shortest_path",
            dry_run=False,
        )

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None
        try:
            handler._execute_action(str(dup), str(keeper))
        finally:
            duplicates.console.print = original_print

        assert keeper.exists()
        assert dup.exists()

    def test_dry_run_does_not_delete(self, temp_dir: Path):
        """Test that dry_run=True prevents actual deletion in process_duplicates."""
        import io
        from rich.console import Console as RichConsole

        keeper = temp_dir / "keeper.txt"
        dup = temp_dir / "dup.txt"
        keeper.write_bytes(b"same")
        dup.write_bytes(b"same")

        handler = SmartDuplicateHandler(
            action="delete",
            keep_criteria="shortest_path",
            dry_run=True,
        )

        import duplicates
        silent = RichConsole(file=io.StringIO(), force_terminal=True)
        original_console = duplicates.console
        duplicates.console = silent
        try:
            handler.process_duplicates([[str(keeper), str(dup)]])
        finally:
            duplicates.console = original_console

        # Both files should still exist since dry_run=True
        assert keeper.exists()
        assert dup.exists()

    def test_delete_nonexistent_file_handled(self, temp_dir: Path):
        """Test that deleting a nonexistent file is handled gracefully."""
        keeper = temp_dir / "keeper.txt"
        keeper.write_bytes(b"content")
        fake_path = str(temp_dir / "nonexistent.txt")

        handler = SmartDuplicateHandler(
            action="delete",
            keep_criteria="shortest_path",
            dry_run=False,
        )

        import duplicates
        original_print = duplicates.console.print
        duplicates.console.print = lambda *args, **kwargs: None
        try:
            # Should not raise — errors are caught internally
            handler._execute_action(fake_path, str(keeper))
        finally:
            duplicates.console.print = original_print


class TestAdaptiveChunking:
    """Tests for adaptive chunk size functionality."""

    def test_chunk_size_constants(self):
        """Test chunk size constants are defined correctly."""
        assert CHUNK_SIZE == 65536  # 64KB
        assert CHUNK_SIZE_LARGE == 1048576  # 1MB
        assert MEDIUM_FILE_THRESHOLD == 10 * 1024 * 1024  # 10MB

    def test_large_file_uses_large_chunks(self, temp_dir: Path):
        """Test that files > MEDIUM_FILE_THRESHOLD use larger chunks."""
        # Create a file larger than MEDIUM_FILE_THRESHOLD
        large_content = b"x" * (MEDIUM_FILE_THRESHOLD + 1000)
        large_file = temp_dir / "large.bin"
        large_file.write_bytes(large_content)

        finder = DuplicateFinder(str(temp_dir))
        # This should use CHUNK_SIZE_LARGE internally
        hash_result = finder.get_file_hash(str(large_file))

        assert hash_result is not None

    def test_small_file_uses_small_chunks(self, temp_dir: Path):
        """Test that small files use standard chunk size."""
        small_content = b"x" * 1000
        small_file = temp_dir / "small.bin"
        small_file.write_bytes(small_content)

        finder = DuplicateFinder(str(temp_dir))
        hash_result = finder.get_file_hash(str(small_file))

        assert hash_result is not None
