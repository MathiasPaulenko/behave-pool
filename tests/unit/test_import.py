"""Test that behave_pool public API is importable."""

from __future__ import annotations

import behave_pool


def test_parallel_runner_importable() -> None:
    """ParallelRunner must be importable from behave_pool."""
    from behave_pool import ParallelRunner

    assert ParallelRunner is not None


def test_version_attribute() -> None:
    """behave_pool must expose __version__."""
    assert hasattr(behave_pool, "__version__")
    assert isinstance(behave_pool.__version__, str)
    assert behave_pool.__version__ == "1.3.0"


def test_all_exports() -> None:
    """__all__ must list ParallelRunner and __version__."""
    assert "ParallelRunner" in behave_pool.__all__
    assert "__version__" in behave_pool.__all__
