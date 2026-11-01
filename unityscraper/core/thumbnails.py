"""Disk cache of resized cover thumbnails."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from unityscraper.core.paths import CACHE_DIR

DEFAULT_THUMBNAIL_DIR = CACHE_DIR / "thumbnails"


class ThumbnailCache:
    """Create PNG thumbnails of exactly ``size`` once and reuse them until the source changes.

    Safe to call from worker threads: each write goes to its own temp file and is
    published with an atomic replace.
    """

    def __init__(self, cache_dir: Path = DEFAULT_THUMBNAIL_DIR) -> None:
        self.cache_dir = Path(cache_dir)

    def get(self, source: Path, size: tuple[int, int]) -> Path | None:
        """Return the cached thumbnail path, or None when ``source`` is missing or unreadable."""
        try:
            path = Path(source).resolve()
            stat = path.stat()
        except OSError:
            return None
        width, height = size
        key = f"{path}|{stat.st_mtime_ns}|{stat.st_size}|{width}x{height}"
        target = self.cache_dir / f"{hashlib.sha1(key.encode('utf-8')).hexdigest()}.png"
        if target.is_file():
            return target

        temp_name: str | None = None
        try:
            with Image.open(path) as image:
                thumb = ImageOps.contain(
                    image.convert("RGBA"), (width, height), Image.Resampling.LANCZOS
                )
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            canvas.paste(thumb, ((width - thumb.width) // 2, (height - thumb.height) // 2))
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(dir=self.cache_dir, suffix=".partial")
            with os.fdopen(handle, "wb") as stream:
                canvas.save(stream, "PNG")
            os.replace(temp_name, target)
            temp_name = None
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            # A concurrent writer may already have published the same key (Windows
            # refuses the replace while it is open); otherwise the source is unusable.
            return target if target.is_file() else None
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)
        return target


__all__ = ["DEFAULT_THUMBNAIL_DIR", "ThumbnailCache"]
