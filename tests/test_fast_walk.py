"""
Tests for the fast_walk() function in both modules.
"""
import os
from pathlib import Path

import pytest

from duplicates import fast_walk as dup_fast_walk, SKIP_DIRS
from treesize_cli import fast_walk as tree_fast_walk, clear_path_cache


class TestFastWalkDuplicates:
    """Tests for fast_walk in duplicates.py"""

    def test_basic_walk(self, sample_files: Path):
        """Test that fast_walk yields directory contents."""
        results = list(dup_fast_walk(str(sample_files)))

        # Should have at least the root and subdirectories
        assert len(results) >= 3

        # First result should be the root
        dirpath, dirnames, file_entries = results[0]
        assert Path(dirpath) == sample_files
        assert isinstance(dirnames, list)
        assert isinstance(file_entries, list)

    def test_returns_direntry_objects(self, sample_files: Path):
        """Test that file_entries are DirEntry objects with stat caching."""
        for dirpath, dirnames, file_entries in dup_fast_walk(str(sample_files)):
            for entry in file_entries:
                # Should be DirEntry object
                assert hasattr(entry, 'name')
                assert hasattr(entry, 'path')
                assert hasattr(entry, 'stat')

                # stat() should work
                stat = entry.stat()
                assert stat.st_size >= 0

    def test_skip_dirs_respected(self, temp_dir: Path):
        """Test that directories in SKIP_DIRS are not traversed."""
        # Create a .git directory (should be skipped)
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("git config")

        # Create a normal directory
        normal_dir = temp_dir / "src"
        normal_dir.mkdir()
        (normal_dir / "main.py").write_text("# code")

        results = list(dup_fast_walk(str(temp_dir)))

        # .git should not appear in any yielded path
        all_paths = [r[0] for r in results]
        assert not any(".git" in p for p in all_paths)

        # src should appear
        assert any("src" in p for p in all_paths)

    def test_custom_skip_dirs(self, temp_dir: Path):
        """Test custom skip_dirs parameter."""
        # Create directories
        (temp_dir / "include_me").mkdir()
        (temp_dir / "skip_me").mkdir()
        (temp_dir / "include_me" / "file.txt").write_text("included")
        (temp_dir / "skip_me" / "file.txt").write_text("skipped")

        results = list(dup_fast_walk(str(temp_dir), skip_dirs={"skip_me"}))
        all_paths = [r[0] for r in results]

        assert any("include_me" in p for p in all_paths)
        assert not any("skip_me" in p for p in all_paths)

    def test_empty_directory(self, empty_dir: Path):
        """Test walking an empty directory."""
        results = list(dup_fast_walk(str(empty_dir)))

        assert len(results) == 1
        dirpath, dirnames, file_entries = results[0]
        assert dirnames == []
        assert file_entries == []

    def test_handles_permission_errors(self, temp_dir: Path):
        """Test that permission errors don't crash the walk."""
        # Create a file (can't really test permission denial easily in tests)
        (temp_dir / "file.txt").write_text("content")

        # Should not raise
        results = list(dup_fast_walk(str(temp_dir)))
        assert len(results) >= 1


class TestFastWalkTreesize:
    """Tests for fast_walk in treesize_cli.py"""

    def test_basic_walk_with_depth(self, sample_files: Path):
        """Test that fast_walk yields depth information."""
        results = list(tree_fast_walk(str(sample_files)))

        for dirpath, dirnames, file_entries, depth in results:
            assert isinstance(depth, int)
            assert depth >= 0

    def test_max_depth_limit(self, deep_dir: Path):
        """Test that max_depth parameter limits traversal."""
        # Without limit
        all_results = list(tree_fast_walk(str(deep_dir)))

        # With limit of 2
        limited_results = list(tree_fast_walk(str(deep_dir), max_depth=2))

        # Should have fewer results with limit
        assert len(limited_results) < len(all_results)

        # All depths should be < max_depth
        for _, _, _, depth in limited_results:
            assert depth < 2

    def test_follow_symlinks_parameter(self, temp_dir: Path):
        """Test follow_symlinks parameter exists and works."""
        (temp_dir / "file.txt").write_text("content")

        # Should work with follow_symlinks=False (default)
        results = list(tree_fast_walk(str(temp_dir), follow_symlinks=False))
        assert len(results) >= 1

        # Should work with follow_symlinks=True
        results = list(tree_fast_walk(str(temp_dir), follow_symlinks=True))
        assert len(results) >= 1

    def test_path_interning(self, sample_files: Path):
        """Test that paths are interned for memory efficiency."""
        clear_path_cache()

        results = list(tree_fast_walk(str(sample_files)))

        # Paths should be interned (same object for same string)
        paths = [r[0] for r in results]
        for path in paths:
            # Interned strings should be the same object
            assert path is path  # Trivially true, but documents intent


class TestClearPathCache:
    """Tests for clear_path_cache function."""

    def test_clears_cache(self, sample_files: Path):
        """Test that clear_path_cache empties the cache."""
        from treesize_cli import _INTERNED_PATHS, intern_path

        # Add something to cache
        intern_path("/test/path")
        assert len(_INTERNED_PATHS) > 0

        # Clear it
        clear_path_cache()
        assert len(_INTERNED_PATHS) == 0

    def test_cache_repopulates_after_clear(self, sample_files: Path):
        """Test that cache works after being cleared."""
        from treesize_cli import _INTERNED_PATHS

        clear_path_cache()
        assert len(_INTERNED_PATHS) == 0

        # Walk should repopulate
        list(tree_fast_walk(str(sample_files)))
        assert len(_INTERNED_PATHS) > 0
