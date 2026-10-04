# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.0] - 2026-10-04

### Added

- `behave-pool` console script and `python -m behave_pool` entry point:
  a Behave wrapper that registers the pool options (`--parallel-scheme`,
  `--parallel-balance`, `--parallel-timing-file`, `--parallel-report`,
  `--shard`) before argument parsing, so they actually work on the CLI
  and in `behave.ini` (ini keys use underscores, e.g. `parallel_balance`).
- `pool.*` userdata fallback so every pool option also works with plain
  `behave` via `-D pool.balance=fifo` or a `[behave.userdata]` section.
- Scenario-granular `@serial` support: a feature mixing serial and
  non-serial scenarios is split into a parallel work unit and a
  `<feature>#serial` work unit, so only the tagged scenarios run in the
  serial phase.
- Console progress output in parallel mode: one line per finished work
  unit plus an aggregate features/scenarios/steps summary.
- `ConfigSnapshot` now propagates `paths`, `lang`, `stop`, `tags`,
  `name`, `userdata` and the tag-expression fields to worker processes,
  so `--tags`, `--name`, `-D` and `--stop` behave the same in parallel
  mode.
- `TimingStore.prune_stale()`: entries for deleted or renamed feature
  files are removed on save.
- `--parallel-scheme scenario`: scenario-level parallelism, one work
  unit per scenario (a whole ScenarioOutline counts as one unit).
- `behave_pool.serial` module with shared `@serial` detection helpers.

### Fixed

- `--tags`, `--name`, `-D` userdata and `--stop` were silently ignored
  by workers; they are now propagated through `ConfigSnapshot`.
- `--stop` now sets the stop event on the first failure so workers drop
  all queued work units.
- The per-unit timeout now applies to each work unit (300s clock
  restarted per result) instead of covering a whole phase, and the
  serial phase uses the same collection loop.
- No more than `min(parallel, len(batch))` workers are spawned.
- Sharding preserves the LPT/FIFO planned order while keeping shard
  membership deterministic.
- `execution.duration` is now real wall-clock time and `startTime` /
  `endTime` differ as expected.
- `gitRemote` credentials and sensitive `-D key=value` userdata values
  are sanitized before being written to the JSON report.
- `undefined_steps` are propagated to the coordinator so undefined-step
  snippets work in parallel mode.
- Worker results are drained while dispatching and missing results are
  always reported as failures.
- Features split across work units (`#serial` halves or per-scenario
  units) were duplicated in the unified report; they are now merged by
  filename so `statistics.features` and the `features` list are correct.

### Documentation

- Corrected `behave.ini` examples (`jobs` key, `[behave.userdata]`
  fallbacks), removed the nonexistent `BEHAVE_CONFIG` variable, fixed
  broken step definitions in examples, and aligned the serial, sharding,
  ecosystem and architecture pages with the actual behavior (one serial
  worker, hooks run per worker, formatters not wired in parallel mode,
  shard unit = work unit).

## [1.2.0] - 2026-08-06

### Added

- **Sharding support** for CI parallelism across multiple machines.
  New `--shard INDEX/TOTAL` CLI option divides the test suite into
  `TOTAL` contiguous shards and executes only shard `INDEX`.
  Compatible with `--parallel` (local parallelism within a shard),
  `@serial` tag (serial scenarios within a shard run sequentially),
  and `--tags`.
  Python API: `ShardConfig` dataclass and `run_with_shard()` function.

### Fixed

- Worker status enum comparison and worker setup crash handling.
- Runner sorting consistency, `tmp/` report cleanup, and multiprocessing
  context propagation.
- Config snapshot independence and `--shard` option registration.

## [1.1.3] - 2026-08-06

### Fixed

- Missing author email in package metadata.

## [1.1.2] - 2026-07-31

### Added

- Test coverage for `_compute_statistics`, `_detect_environment` and
  `_build_execution`.

### Fixed

- `test_ci_provider` no longer asserts a hardcoded provider name and
  satisfies ruff E501.

## [1.1.1] - 2026-07-31

### Fixed

- Ruff lint violations, a mypy type error, and stale test expectations.

## [1.1.0] - 2026-07-31

### Added

- Unified JSON report (`--parallel-report`) implementing the
  `behave-modern-json-report` `ExecutionReport` schema (v1.1.0):
  merged feature/scenario/step results, statistics, tag breakdowns
  and environment info from all workers.

## [1.0.0] - 2026-07-31

### Added

- Initial project setup: scaffold, CI/CD, pre-commit, MkDocs configuration.
- `ParallelRunner` that delegates to standard Behave `Runner` when
  `parallel <= 1` (passthrough mode).
- `TimingStore` for persisting historical work unit durations as JSON.
- LPT (Longest Processing Time) load balancing via `--parallel-balance lpt|fifo`.
- `--parallel-timing-file` CLI option for custom timing file path.
- `@serial` tag support: two-phase dispatch (parallel then serial).
- Behave runner registration via `[behave.runners]` ini section.

### Fixed

- `TimingStore.load()` now catches `TypeError` for non-numeric JSON values.
- `TimingStore.save()` now uses atomic writes (temp file + rename) to prevent corruption.
- `TimingStore.save()` narrowed `except Exception` to `except OSError`.
- `WorkerRunner._write_report()` now reflects actual feature pass/fail status.
- `WorkerRunner._write_report()` now catches all exceptions (not just `OSError`),
  preventing non-serializable feature data from causing `TypeError` to propagate
  and incorrectly marking a work unit as failed.
- `WorkerRunner.run_work_unit()` now resets `self.aborted` before each work unit,
  preventing silent feature skips in subsequent work units after a KeyboardInterrupt
  or other abort in a previous work unit.
- `WorkerRunner.teardown()` is now safe when `setup()` did not complete.
- `WorkerRunner.run_work_unit()` now parses feature files from `WorkUnit.feature_path`
  via `parse_features` before running, fixing zero-feature execution in workers.
- `WorkerRunner.load_step_definitions()` now sets `self.step_registry` from the global
  Behave step registry, fixing `feature.run()` crashes in worker processes.
- `WorkerRunner._worker_run_loop()` now catches `EOFError`/`OSError` on closed task
  queue and exits gracefully instead of crashing.
- `WorkerRunner._worker_run_loop()` uses `task_queue.get(timeout=5)` instead of
  blocking `get()` to allow periodic `stop_event` checks.
- `ParallelRunner._dispatch()` skips launching parallel workers when batch is empty.
- `ParallelRunner._dispatch()` sets `stop_event` for workers that exceed join timeout.
- `ParallelRunner._dispatch()` skips serial phase when `stop_event` is set during
  parallel phase, preventing infinite block.
- `ParallelRunner._dispatch()` replaces `task_queue.join()` with `worker.join(timeout=300)`
  and explicit queue drain, preventing deadlock when workers exit prematurely or hang indefinitely.
  Workers that don't terminate within the timeout are now forcibly terminated via
  `WorkerProcess.terminate()`.
- `ParallelRunner._collect()` detects missing results from crashed workers and treats
  them as failures.
- `ParallelRunner._collect()` narrows `except` clause to `queue.Empty`/`EOFError`/`OSError`.
- `ParallelRunner._dispatch()` now returns the list of actually dispatched work units.
  `_run_parallel()` passes only dispatched units to `_collect()`, preventing false
  "missing results" warnings and a 30-second wait for serial units that were never
  enqueued when `stop_event` was set during the parallel phase.
- `ParallelRunner._run_parallel()` cleans up queues in `finally` block.
- `ConfigSnapshot` now includes `parallel`, `parallel_scheme`, `parallel_balance`,
  `parallel_timing_file`, `dry_run`, and `use_nested_step_modules` fields.
- `_make_config()` now sets all parallel-related fields from `ConfigSnapshot`.
- `__init__.py` docstring corrected: feature-level parallelization, not scenario.
- `config.py` help text corrected: removed stale scenario reference.
- `iterator.py` error message corrected: removed stale F9 reference.
- `_worker_run_loop()` now sets `stop_event` when a worker aborts, ensuring other
  workers stop cooperatively and the coordinator skips the serial phase. Without
  this, the aborted worker's sentinel remained in the queue and another worker
  could consume it and exit early, leaving work units unprocessed.
- Removed dead `TYPE_CHECKING` block in `work_unit.py`.
- Added picklability regression tests for `WorkerResult` and `WorkUnit`, both
  of which are sent through `multiprocessing.Queue` / `JoinableQueue` and must
  survive pickle round-trips.
- `ParallelRunner._collect()` now accepts a `deadline_seconds` parameter
  (default 30s) so tests can exercise the missing-result path without waiting
  the full 30-second deadline.
- Added regression test verifying `WorkerRunner.run_work_unit()` catches
  `parse_features` exceptions and returns a failed `WorkerResult` instead of
  propagating.
