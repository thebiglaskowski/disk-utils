"""
Tests for nul_scanner.py — Windows reserved-name file detection and deletion.
"""
import io
import os
import sys
import ctypes
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from nul_scanner import (
    WINDOWS_RESERVED_NAMES,
    scan_nul_files,
    delete_nul_file,
    delete_selected,
    print_results,
)


def _create_reserved_file(path: str, content: bytes = b"") -> bool:
    """Create a file with a Windows reserved name using \\\\?\\ prefix.
    Returns True on success, False if not possible (non-Windows)."""
    if os.name != 'nt':
        # On non-Windows, just create normally since names aren't reserved
        with open(path, 'wb') as f:
            f.write(content)
        return True
    clean = path.replace("/", "\\")
    extended = "\\\\?\\" + clean
    try:
        kernel32 = ctypes.windll.kernel32
        GENERIC_WRITE = 0x40000000
        CREATE_ALWAYS = 2
        FILE_ATTRIBUTE_NORMAL = 0x80
        handle = kernel32.CreateFileW(
            extended, GENERIC_WRITE, 0, None,
            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, None,
        )
        if handle == -1:
            return False
        if content:
            written = ctypes.c_ulong(0)
            kernel32.WriteFile(handle, content, len(content), ctypes.byref(written), None)
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


# Provide a quiet console for tests that need Rich Progress to work
@pytest.fixture
def quiet_console():
    """Patch nul_scanner.console with a silent Console."""
    silent = Console(file=io.StringIO(), force_terminal=True)
    with patch('nul_scanner.console', silent):
        yield silent


class TestWindowsReservedNames:
    """Tests for the WINDOWS_RESERVED_NAMES constant."""

    def test_contains_nul(self):
        assert 'nul' in WINDOWS_RESERVED_NAMES

    def test_contains_standard_devices(self):
        for name in ('con', 'prn', 'aux', 'nul'):
            assert name in WINDOWS_RESERVED_NAMES

    def test_contains_com_ports(self):
        for i in range(10):
            assert f'com{i}' in WINDOWS_RESERVED_NAMES

    def test_contains_lpt_ports(self):
        for i in range(10):
            assert f'lpt{i}' in WINDOWS_RESERVED_NAMES

    def test_all_lowercase(self):
        for name in WINDOWS_RESERVED_NAMES:
            assert name == name.lower()


class TestScanNulFiles:
    """Tests for scanning nul files in a directory tree."""

    def test_finds_nul_file(self, quiet_console, temp_dir: Path):
        """Test that a file named 'nul' is found."""
        nul_path = str(temp_dir / "nul")
        if not _create_reserved_file(nul_path, b"fake nul"):
            pytest.skip("Cannot create reserved-name file on this platform")

        results = scan_nul_files(str(temp_dir))

        assert len(results) == 1
        assert results[0]['name'].lower() == 'nul'

    def test_finds_nul_with_extension(self, quiet_console, temp_dir: Path):
        """Test that 'nul.txt' is also detected (stem is 'nul')."""
        (temp_dir / "nul.txt").write_text("nul with extension")

        results = scan_nul_files(str(temp_dir))

        assert len(results) == 1
        assert results[0]['name'] == 'nul.txt'

    def test_ignores_normal_files(self, quiet_console, temp_dir: Path):
        """Test that normal files are not flagged."""
        (temp_dir / "readme.txt").write_text("normal file")
        (temp_dir / "data.bin").write_bytes(b"\x00" * 100)

        results = scan_nul_files(str(temp_dir))

        assert len(results) == 0

    def test_empty_directory(self, quiet_console, temp_dir: Path):
        """Test scanning an empty directory returns nothing."""
        results = scan_nul_files(str(temp_dir))
        assert len(results) == 0

    def test_include_all_reserved(self, quiet_console, temp_dir: Path):
        """Test scanning for all reserved names, not just nul."""
        # Use names with extensions to avoid Windows reservation issues
        (temp_dir / "con.txt").write_text("con artifact")
        (temp_dir / "prn.log").write_text("prn artifact")
        (temp_dir / "normal.txt").write_text("normal")

        results = scan_nul_files(str(temp_dir), include_all_reserved=True)

        names = {r['name'] for r in results}
        assert 'con.txt' in names
        assert 'prn.log' in names
        assert 'normal.txt' not in names

    def test_nul_only_mode_ignores_other_reserved(self, quiet_console, temp_dir: Path):
        """Test that default mode only finds 'nul', not other reserved names."""
        (temp_dir / "con.txt").write_text("con artifact")
        (temp_dir / "prn.log").write_text("prn artifact")

        results = scan_nul_files(str(temp_dir), include_all_reserved=False)

        assert len(results) == 0

    def test_skips_configured_dirs(self, quiet_console, temp_dir: Path):
        """Test that skip_dirs are respected."""
        skip_dir = temp_dir / "node_modules"
        skip_dir.mkdir()
        (skip_dir / "nul.txt").write_text("hidden nul")

        results = scan_nul_files(str(temp_dir))

        assert len(results) == 0

    def test_custom_skip_dirs(self, quiet_console, temp_dir: Path):
        """Test custom skip_dirs parameter."""
        skip_dir = temp_dir / "myskip"
        skip_dir.mkdir()
        (skip_dir / "nul.txt").write_text("skipped")

        normal_dir = temp_dir / "include"
        normal_dir.mkdir()
        (normal_dir / "nul.txt").write_text("found")

        results = scan_nul_files(str(temp_dir), skip_dirs={"myskip"})

        assert len(results) == 1
        assert "include" in results[0]['path']

    def test_nested_nul_files(self, quiet_console, temp_dir: Path):
        """Test finding nul files in nested directories."""
        nested = temp_dir / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (temp_dir / "nul.txt").write_text("root nul")
        (nested / "nul.log").write_text("nested nul")

        results = scan_nul_files(str(temp_dir))

        assert len(results) == 2

    def test_result_contains_expected_keys(self, quiet_console, temp_dir: Path):
        """Test result dicts contain expected keys."""
        (temp_dir / "nul.dat").write_text("content")

        results = scan_nul_files(str(temp_dir))

        assert len(results) == 1
        item = results[0]
        assert 'path' in item
        assert 'size' in item
        assert 'modified' in item
        assert 'name' in item
        assert os.path.isfile(item['path'])

    def test_bare_nul_on_windows(self, quiet_console, temp_dir: Path):
        """Test finding a bare 'nul' file created via Win32 API."""
        nul_path = str(temp_dir / "nul")
        if not _create_reserved_file(nul_path, b"nul content"):
            pytest.skip("Cannot create reserved-name file")

        results = scan_nul_files(str(temp_dir))

        assert len(results) == 1
        assert results[0]['name'].lower() == 'nul'


class TestDeleteNulFile:
    """Tests for deleting nul files."""

    def test_delete_normal_file(self, temp_dir: Path):
        """Test deleting a regular file."""
        test_file = temp_dir / "test_delete_me.txt"
        test_file.write_text("delete me")

        success, msg = delete_nul_file(str(test_file))

        assert success is True
        assert not test_file.exists()

    def test_delete_nonexistent_file(self, temp_dir: Path):
        """Test deleting a file that doesn't exist."""
        fake_path = str(temp_dir / "nonexistent.txt")

        success, msg = delete_nul_file(fake_path)

        assert success is False
        assert "Failed" in msg

    def test_delete_returns_path_in_message(self, temp_dir: Path):
        """Test that the result message contains the file path."""
        test_file = temp_dir / "traceable.txt"
        test_file.write_text("track me")

        success, msg = delete_nul_file(str(test_file))

        assert str(test_file) in msg

    def test_delete_reserved_name_file(self, temp_dir: Path):
        """Test deleting a file with a reserved name via Win32 API."""
        nul_path = str(temp_dir / "nul")
        if not _create_reserved_file(nul_path, b"to delete"):
            pytest.skip("Cannot create reserved-name file")

        success, msg = delete_nul_file(nul_path)

        assert success is True
        assert "Nuked" in msg


class TestDeleteSelected:
    """Tests for batch deletion of nul files."""

    def test_dry_run_does_not_delete(self, quiet_console, temp_dir: Path):
        """Test that dry run doesn't actually delete files."""
        test_file = temp_dir / "keep_me.txt"
        test_file.write_text("I should survive")

        results = [{'path': str(test_file), 'size': 17, 'modified': None, 'name': 'keep_me.txt'}]

        success, failed = delete_selected(results, dry_run=True)

        assert success == 1
        assert failed == 0
        assert test_file.exists()

    def test_real_delete(self, quiet_console, temp_dir: Path):
        """Test that real deletion removes files."""
        test_file = temp_dir / "delete_me.txt"
        test_file.write_text("goodbye")

        results = [{'path': str(test_file), 'size': 7, 'modified': None, 'name': 'delete_me.txt'}]

        success, failed = delete_selected(results, dry_run=False)

        assert success == 1
        assert failed == 0
        assert not test_file.exists()

    def test_multiple_files(self, quiet_console, temp_dir: Path):
        """Test deleting multiple files at once."""
        files = []
        for i in range(5):
            f = temp_dir / f"file{i}.txt"
            f.write_text(f"content {i}")
            files.append({'path': str(f), 'size': 9, 'modified': None, 'name': f.name})

        success, failed = delete_selected(files, dry_run=False)

        assert success == 5
        assert failed == 0

    def test_handles_missing_file_in_batch(self, quiet_console, temp_dir: Path):
        """Test that a missing file in a batch doesn't stop other deletions."""
        good_file = temp_dir / "good.txt"
        good_file.write_text("good")

        results = [
            {'path': str(temp_dir / "missing.txt"), 'size': 0, 'modified': None, 'name': 'missing.txt'},
            {'path': str(good_file), 'size': 4, 'modified': None, 'name': 'good.txt'},
        ]

        success, failed = delete_selected(results, dry_run=False)

        assert success == 1
        assert failed == 1
        assert not good_file.exists()

    def test_empty_results(self, quiet_console, temp_dir: Path):
        """Test batch delete with empty results list."""
        success, failed = delete_selected([], dry_run=False)

        assert success == 0
        assert failed == 0


class TestPrintResults:
    """Tests for the print_results display function."""

    def test_empty_results(self, quiet_console):
        """Test printing empty results doesn't crash."""
        print_results([])

    def test_with_results(self, quiet_console):
        """Test printing results with data."""
        from datetime import datetime

        results = [
            {
                'path': '/test/nul',
                'size': 1024,
                'modified': datetime(2025, 1, 1, 12, 0),
                'name': 'nul',
            },
        ]

        print_results(results)

    def test_with_none_modified(self, quiet_console):
        """Test printing results where modified is None."""
        results = [
            {
                'path': '/test/nul',
                'size': 0,
                'modified': None,
                'name': 'nul',
            },
        ]

        print_results(results)
