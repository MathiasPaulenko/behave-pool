# API reference

This page documents the full public API of `behave-pool`. Each module is
documented with its classes, methods, and usage examples.

## Package

::: behave_pool

## ParallelRunner

The coordinator that orchestrates parallel feature execution. Extends
`behave.runner.Runner` and implements Behave's `ITestRunner` interface.

```python
from behave_pool import ParallelRunner
from behave.configuration import Configuration

config = Configuration(["--parallel", "4", "features/"])
runner = ParallelRunner(config)
failed = runner.run()  # True if any test failed
```

::: behave_pool.runner

## Configuration

`ConfigSnapshot` is a picklable snapshot of Behave's `Configuration` that can
be safely sent to worker processes via `spawn`.

```python
from behave_pool.config import ConfigSnapshot, snapshot_config

snapshot = snapshot_config(config)
print(snapshot.parallel)  # 4
print(snapshot.parallel_scheme)  # "feature"
print(snapshot.base_dir)  # "features"
```

::: behave_pool.config

## WorkUnit

A frozen dataclass representing a single unit of test work dispatched to a
worker process.

```python
from behave_pool.work_unit import WorkUnit
from behave_pool.config import ConfigSnapshot

unit = WorkUnit(
    id="feature:features/login.feature",
    config=ConfigSnapshot(
        base_dir="features",
        steps_dir="steps",
        environment_file="environment.py",
        lang=None,
        stop=False,
    ),
    feature_path="features/login.feature",
    tags=["serial"],
    serial_mode="only",
)

print(unit.is_serial)  # True
```

`serial_mode` selects which scenarios of a feature the unit executes:
`"all"` (default), `"only"` (`@serial` scenarios), or `"exclude"`
(everything except `@serial`). Mixed features are split by the planner
into a `"exclude"` parallel unit and a `"only"` serial unit.

::: behave_pool.work_unit

## WorkerResult

The outcome of executing a `WorkUnit` in a worker process.

```python
from behave_pool.result import WorkerResult

result = WorkerResult(
    worker_id=0,
    work_unit_id="feature:features/login.feature",
    failed=False,
    duration=1.23,
)
print(result.failed)  # False
print(result.duration)  # 1.23
```

::: behave_pool.result

## TimingStore

Loads and saves historical work unit durations as JSON for LPT balancing.

```python
from pathlib import Path
from behave_pool.timing import TimingStore

store = TimingStore(path=Path(".behave-pool-timing.json"))
store.load()
print(store.get_duration("feature:features/login.feature"))  # 1.23

store.update("feature:features/login.feature", 1.45)
store.save_if_changed()  # True if file was written
```

::: behave_pool.timing

## WorkUnitIterator

Strategy pattern for generating `WorkUnit` objects from parsed features.

```python
from behave_pool.iterator import WorkUnitIterator

iterator = WorkUnitIterator.for_scheme(
    scheme="feature",
    features=features,
    config=config,
)
for unit in iterator.iterate():
    print(unit.id, unit.feature_path)
```

::: behave_pool.iterator

## Sharding

`ShardConfig` configures sharding for CI parallelism. `run_with_shard` is a
convenience function that creates a `ParallelRunner` with shard settings.

```python
from behave_pool import ShardConfig, run_with_shard

config = ShardConfig(
    shard_index=1,
    total_shards=3,
    features_dir="features/",
    parallel=4,
)
failed = run_with_shard(config)
```

`parse_shard_string` parses `INDEX/TOTAL` strings:

```python
from behave_pool.shard import parse_shard_string

config = parse_shard_string("2/3")
print(config.shard_index)  # 2
print(config.total_shards)  # 3
```

`split_shards` divides a sorted list into contiguous groups:

```python
from behave_pool.shard import split_shards

items = list(range(10))
shard1 = split_shards(items, 1, 3)  # [0, 1, 2, 3]
shard2 = split_shards(items, 2, 3)  # [4, 5, 6]
shard3 = split_shards(items, 3, 3)  # [7, 8, 9]
```

::: behave_pool.shard

## Worker

`WorkerRunner` executes work units inside an isolated worker process.
`WorkerProcess` wraps `multiprocessing.Process` for lifecycle management.

These classes are used internally by `ParallelRunner` and are not typically
instantiated directly by end users.

::: behave_pool.worker

## Serial detection

Shared helpers used by both the coordinator (planning) and the workers
(execution) to identify `@serial` scenarios consistently.

::: behave_pool.serial

## CLI

The `behave-pool` console entry point — a behave wrapper that registers
the pool options before argument parsing.

::: behave_pool.cli
