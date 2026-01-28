# Known Issues & Technical Debt

## Accepted Technical Debt

The following items are **consciously accepted** trade-offs:

### Code Duplication (DEBT-001, 002, 003)

**What:** `fast_walk()`, `format_size()`, `SIZE_UNITS`, and `SKIP_DIRS` are duplicated in both `duplicates.py` and `treesize_cli.py`.

**Why Accepted:**
- Each module can be used standalone without dependencies on a shared module
- Total duplication is ~150 lines (minimal)
- Code is stable and rarely changes
- Extracting to shared module adds complexity without significant benefit

**Revisit When:**
- Adding a third module that needs these utilities
- Major refactoring of either module

---

## Maintenance Schedule

### Monthly: Dependency Updates

Check and update dependencies monthly:

```bash
pip list --outdated
pip install --upgrade rich questionary xxhash pytest pytest-cov
```

### Quarterly: Security Audit

Run `/secure` audit before each quarterly release.

---

## Current Limitations

### Platform-Specific Behavior

- `fast_walk()` performance gains are most significant on Windows NTFS
- Memory-mapped file hashing may behave differently on network drives
- Symlink handling varies by platform

### Not Supported

- Scanning of encrypted volumes (depends on OS decryption)
- Real-time file monitoring (scan is point-in-time)
- Remote/network path scanning (not tested, may work)

---

## Reporting Issues

If you encounter a bug, please include:
1. Operating system and Python version
2. Steps to reproduce
3. Expected vs actual behavior
4. Any error messages

Report issues at: https://github.com/thebiglaskowski/disk-utils/issues
