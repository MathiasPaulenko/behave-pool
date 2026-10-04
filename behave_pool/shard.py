"""Sharding support for CI parallelism across multiple machines.

Sharding divides the work units (one per feature file, plus the extra
``#serial`` units produced by mixed features) into ``total_shards``
contiguous groups.  Each CI runner executes only its assigned shard
(``shard_index``).

The algorithm:

1. Build the work units from the parsed features.
2. Sort a copy deterministically by work unit ``id`` (i.e. feature path)
   to compute shard membership identically on every machine.
3. Split the sorted list into ``total_shards`` groups.  The first
   ``len % total_shards`` shards receive one extra unit.
4. Return the ``shard_index``-th group (1-based) in the original input
   order, so the planned LPT/FIFO order is preserved.

Sharding composes with ``--parallel`` (local parallelism within a shard),
``--parallel-balance`` (ordering is preserved inside the shard), and
``@serial`` (serial work units within a shard run sequentially).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from behave.exception import ConfigError

if TYPE_CHECKING:
    from behave_pool.work_unit import WorkUnit

T = TypeVar("T")


class ShardError(ValueError, ConfigError):  # type: ignore[misc]
    """Raised when shard configuration or parsing is invalid.

    Also inherits from :class:`behave.exception.ConfigError` so that
    behave's ``main()`` catches it and prints a clean error message
    instead of a raw traceback.
    """


_SHARD_RE = re.compile(r"^(?P<index>\d+)/(?P<total>\d+)$")


@dataclass(frozen=True)
class ShardConfig:
    """Configuration for sharding.

    Attributes:
        shard_index: 1-based index of the shard to execute.
        total_shards: Total number of shards the suite is divided into.
        features_dir: Path to the features directory to scan.
        parallel: Number of local worker processes (0 or 1 = sequential).
    """

    shard_index: int
    total_shards: int
    features_dir: str = "features/"
    parallel: int = 1

    def __post_init__(self) -> None:
        validate_shard(self.shard_index, self.total_shards)


def parse_shard_string(value: str) -> ShardConfig:
    """Parse a ``INDEX/TOTAL`` shard string into a :class:`ShardConfig`.

    Args:
        value: String like ``"1/3"``.

    Returns:
        A :class:`ShardConfig` with ``shard_index`` and ``total_shards`` set.

    Raises:
        ShardError: If the string is malformed or values are out of range.
    """
    match = _SHARD_RE.match(value.strip())
    if not match:
        msg = f"Invalid shard format {value!r}. Expected 'INDEX/TOTAL' (e.g. '1/3')."
        raise ShardError(msg)

    shard_index = int(match.group("index"))
    total_shards = int(match.group("total"))
    validate_shard(shard_index, total_shards)
    return ShardConfig(shard_index=shard_index, total_shards=total_shards)


def validate_shard(shard_index: int, total_shards: int) -> None:
    """Validate shard parameters.

    Args:
        shard_index: 1-based shard index.
        total_shards: Total number of shards.

    Raises:
        ShardError: If ``total_shards`` < 1 or ``shard_index`` is out of range.
    """
    if total_shards < 1:
        msg = f"total_shards must be >= 1, got {total_shards}"
        raise ShardError(msg)
    if shard_index < 1:
        msg = f"shard_index must be >= 1, got {shard_index}"
        raise ShardError(msg)
    if shard_index > total_shards:
        msg = f"shard_index ({shard_index}) must be <= total_shards ({total_shards})"
        raise ShardError(msg)


def split_shards(
    items: list[T],
    shard_index: int,
    total_shards: int,
) -> list[T]:
    """Split a list into ``total_shards`` contiguous groups and return group ``shard_index``.

    The first ``len(items) % total_shards`` shards receive one extra item.

    Args:
        items: Sorted list of items to split.
        shard_index: 1-based shard index.
        total_shards: Total number of shards.

    Returns:
        The slice of items belonging to the requested shard.
    """
    validate_shard(shard_index, total_shards)
    n = len(items)
    base_size = n // total_shards
    remainder = n % total_shards

    start = (shard_index - 1) * base_size + min(shard_index - 1, remainder)
    count = base_size + (1 if shard_index <= remainder else 0)
    return items[start : start + count]


def select_shard_work_units(
    work_units: list[WorkUnit],
    shard_index: int,
    total_shards: int,
) -> list[WorkUnit]:
    """Select the work units belonging to a shard.

    Work units are sorted by their ``id`` (which encodes the feature path)
    to compute the shard assignment deterministically across machines,
    but the returned list preserves the incoming (e.g. LPT) order so that
    balancing is not lost.

    Args:
        work_units: All work units from the planning phase.
        shard_index: 1-based shard index.
        total_shards: Total number of shards.

    Returns:
        Work units assigned to the requested shard, in input order.
    """
    sorted_units = sorted(work_units, key=lambda u: u.id)
    selected = split_shards(sorted_units, shard_index, total_shards)
    selected_ids = {id(u) for u in selected}
    return [u for u in work_units if id(u) in selected_ids]


def run_with_shard(config: ShardConfig) -> bool:
    """Run a single shard of the test suite.

    Plans the work units from ``config.features_dir``, selects the shard
    deterministically, and executes it.  When ``config.parallel > 1``,
    work units within the shard are distributed among local workers.

    Args:
        config: Shard configuration.

    Returns:
        ``True`` if any test failed (Behave convention).
    """
    from behave.configuration import Configuration

    from behave_pool.runner import ParallelRunner

    behave_config = Configuration(
        command_args=[config.features_dir],
        load_config=False,
        jobs=config.parallel,
    )
    behave_config.shard_index = config.shard_index
    behave_config.total_shards = config.total_shards

    runner = ParallelRunner(behave_config)
    return runner.run()
