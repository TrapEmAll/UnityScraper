"""Package-domain exceptions shared by inspection and editing workflows."""

from __future__ import annotations


class PackageError(RuntimeError):
    """Base error for malformed or unsupported Xbox package operations."""


class InvalidPackageError(PackageError):
    """Raised when package metadata or block allocation is invalid."""


class UnsafeArchiveError(PackageError):
    """Raised when a package path could escape its selected destination."""


__all__ = ["InvalidPackageError", "PackageError", "UnsafeArchiveError"]
