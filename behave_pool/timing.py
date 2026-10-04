"""TimingStore: persist historical work unit durations for LPT balancing."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _work_unit_feature_path(work_unit_id: str) -> str | None:
    """Extract the feature file path from a work unit id, if present."""
    rest = work_unit_id
    for prefix in ("feature:", "scenario:"):
        if rest.startswith(prefix):
            rest = rest[len(prefix) :]
            break
    else:
        return None
    path = rest.partition("#")[0]
    marker = ".feature"
    if marker in path:
        path = path[: path.index(marker) + len(marker)]
    return path or None


class TimingStore:
    """Load and save historical work unit durations as JSON.

    The file format is a simple mapping of work unit IDs to durations
    in seconds::

        {"feature:login.feature": 1.23, "feature:checkout.feature": 0.45}

    Attributes:
        path: Path to the JSON timing file.
    """

    def __init__(self, path: Path = Path(".behave-pool-timing.json")) -> None:
        self.path = path
        self._data: dict[str, float] = {}
        self._loaded: bool = False

    def load(self) -> dict[str, float]:
        """Load timing data from the JSON file.

        Returns:
            Dict mapping work unit IDs to durations in seconds.
            Returns an empty dict if the file is missing or corrupt.
        """
        if not self.path.exists():
            self._data = {}
            self._loaded = True
            return self._data

        try:
            text = self.path.read_text(encoding="utf-8")
            raw = json.loads(text)
            if not isinstance(raw, dict):
                logger.warning("Timing file %s is not a JSON object; ignoring.", self.path)
                self._data = {}
            else:
                self._data = {}
                for k, v in raw.items():
                    try:
                        coerced = float(v)
                    except (TypeError, ValueError):
                        logger.warning(
                            "Timing file %s: skipping invalid entry %r=%r", self.path, k, v
                        )
                        continue
                    if not math.isfinite(coerced):
                        logger.warning(
                            "Timing file %s: skipping non-finite entry %r=%r", self.path, k, v
                        )
                        continue
                    self._data[str(k)] = coerced
        except (json.JSONDecodeError, ValueError, TypeError, OSError) as exc:
            logger.warning("Timing file %s is corrupt (%s); ignoring.", self.path, exc)
            self._data = {}

        self._loaded = True
        return self._data

    def save(self, data: dict[str, float]) -> None:
        """Write timing data to the JSON file atomically with indent=2.

        Writes to a temporary file in the same directory and then
        atomically replaces the target file, preventing corruption
        if the process crashes during a write.

        Args:
            data: Dict mapping work unit IDs to durations in seconds.
        """
        text = json.dumps(data, indent=2, sort_keys=True)
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp", prefix=self.path.name + "_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp_path, self.path)
        except OSError:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
        self._data = dict(data)

    def get_duration(self, work_unit_id: str) -> float:
        """Return the stored duration for a work unit, or 0.0 if unknown."""
        if not self._loaded:
            self.load()
        return self._data.get(work_unit_id, 0.0)

    def update(self, work_unit_id: str, duration: float) -> None:
        """Insert or update the duration for a work unit.

        Non-finite values (inf, NaN) are rejected because they produce
        non-standard JSON and break save_if_changed equality checks
        (NaN != NaN).
        """
        if not self._loaded:
            self.load()
        if not math.isfinite(duration):
            logger.warning(
                "Ignoring non-finite duration %r for work unit %r", duration, work_unit_id
            )
            return
        self._data[work_unit_id] = duration

    def prune_stale(self) -> int:
        """Remove entries whose feature file no longer exists.

        Work unit ids embed the feature path (``feature:<path>``,
        ``feature:<path>#serial``, ``scenario:<path>:<line>``).  Entries
        for deleted or renamed feature files are dropped so the timing
        file does not grow forever.  Entries whose path cannot be
        extracted are kept.

        Returns:
            Number of entries removed.
        """
        if not self._loaded:
            self.load()
        removed = 0
        for uid in list(self._data):
            path = _work_unit_feature_path(uid)
            if path and not Path(path).exists():
                del self._data[uid]
                removed += 1
        return removed

    def save_if_changed(self) -> bool:
        """Save data only if it differs from what was loaded.

        Returns:
            True if the file was written, False if no changes were detected.
        """
        if not self._loaded:
            self.load()

        # Read the file contents without overwriting self._data.
        original: dict[str, float] = {}
        if self.path.exists():
            try:
                text = self.path.read_text(encoding="utf-8")
                raw = json.loads(text)
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        with contextlib.suppress(TypeError, ValueError):
                            coerced = float(v)
                            if math.isfinite(coerced):
                                original[str(k)] = coerced
            except (json.JSONDecodeError, ValueError, TypeError, OSError):
                pass

        if self._data == original:
            return False

        self.save(self._data)
        return True
