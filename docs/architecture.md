# Architecture

This page describes the internal design of `behave-pool` and how the parallel
execution pipeline works.

## Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                      ParallelRunner                               │
│                     (coordinator process)                         │
│                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐  │
│  │  _plan() │→│ _shard() │→│ _split() │→│ _dispatch()│→│ _collect()│  │
│  └──────────┘  └──────────┘  └──────────┘  └───────────┘  └───────────┘  │
│       │             │             │              │               │        │
│       │             │             │              │               │        │
│  parse features  filter to    separate @serial  launch workers  drain    │
│  create units    shard slice  from parallel    enqueue units    results  │
│  sort by LPT    (if --shard)                  join workers      persist  │
│                                                                   timings  │
└──────────────────────────────────────────────────────────────────┘
         │
    ┌────▼────┐  ┌────────┐  ┌────────┐
    │Worker 0 │  │Worker 1│  │Worker N│
    │ (spawn) │  │(spawn) │  │(spawn) │
    │         │  │        │  │        │
    │ Worker  │  │ Worker │  │ Worker │
    │ Runner  │  │ Runner │  │ Runner │
    │         │  │        │  │        │
    │ setup() │  │ setup()│  │ setup()│
    │ loop:   │  │ loop:  │  │ loop:  │
    │  get()  │  │  get() │  │  get() │
    │  run()  │  │  run() │  │  run() │
    │  put()  │  │  put() │  │  put() │
    │ teardown│  │teardown│  │teardown│
    └─────────┘  └────────┘  └────────┘
```

## Components

### ParallelRunner

The coordinator. Extends `behave.runner.Runner` and implements the
`ITestRunner` interface. It runs in the main process and orchestrates the
entire pipeline.

**Responsibilities:**

- Parse feature files and create `WorkUnit` objects.
- Sort work units by LPT duration (or keep FIFO order).
- **Filter work units to the current shard** (when `--shard` is active).
- Split work units into parallel and serial batches.
- Launch worker processes and dispatch work.
- Collect results and compute the final exit code.
- Persist observed durations to the timing file.

### WorkerRunner

The per-worker runner. Extends `behave.runner.ModelRunner` and runs inside
each worker process.

**Responsibilities:**

- Load hooks (`before_all`, `after_all`, etc.) from `environment.py`.
- Load step definitions from the `steps/` directory.
- Execute work units (parse + run features).
- Write per-work-unit JSON reports to `tmp/`.
- Send `WorkerResult` objects back to the coordinator.

**Lifecycle:**

1. `setup()` — Called once at worker start. Loads hooks, steps, runs `before_all`.
2. `run_work_unit(unit)` — Called per work unit. Parses and runs the feature.
3. `teardown()` — Called once at worker exit. Runs `after_all`, closes formatters.

### WorkerProcess

A thin wrapper around `multiprocessing.Process` that manages a single worker.

**Responsibilities:**

- Launch the worker process with the `spawn` start method.
- Provide `join()`, `is_alive()`, and `terminate()` for lifecycle management.
- Pass the task queue, result queue, stop event, and config snapshot to the
  worker process.

### WorkUnit

A frozen dataclass representing a single unit of test work.

**Fields:**

- `id` — Unique identifier (e.g., `feature:features/login.feature` or
  `feature:features/login.feature#serial` for the serial half of a mixed
  feature).
- `config` — `ConfigSnapshot` with picklable configuration.
- `feature_path` — Path to the `.feature` file.
- `scenario_line` — Declaration line of the scenario/outline for units produced by `--parallel-scheme scenario`; `None` for feature-level units.
- `tags` — Tags from the feature and its scenarios.
- `serial_mode` — `"all"` (default), `"only"` or `"exclude"`: which
  scenarios of the feature this unit executes.
- `is_serial` — Property: `True` if `"serial"` is in `tags`.

### WorkerResult

A frozen dataclass representing the outcome of executing a `WorkUnit`.

**Fields:**

- `worker_id` — Which worker produced this result.
- `work_unit_id` — ID of the `WorkUnit` that was executed.
- `failed` — `True` if any scenario or step failed.
- `duration` — Wall-clock execution time in seconds.
- `report_path` — Path to the JSON report file (or `None`).
- `undefined_steps` — List of undefined step patterns.
- `error` — Error message if the worker crashed (or `None`).

### ConfigSnapshot

A frozen dataclass that captures the essential fields of Behave's
`Configuration` in a picklable format. This is necessary because the full
`Configuration` object contains non-picklable objects (file handles, reporters)
that cannot be sent to worker processes via `spawn`.

### TimingStore

Loads and saves historical work unit durations as JSON. Used by
`ParallelRunner` for LPT sorting and by `_update_timings` for persistence.

**Key methods:**

- `load()` — Load durations from JSON file (returns empty dict if missing/corrupt).
- `get_duration(id)` — Return stored duration for a work unit (or `0.0`).
- `update(id, duration)` — Insert or update a duration.
- `save_if_changed()` — Atomically write to disk only if data changed.

### WorkUnitIterator

Abstract strategy for generating `WorkUnit` objects from parsed features.
Two implementations:

- `FeatureIterator` — One `WorkUnit` per feature file (a feature mixing
  `@serial` and non-serial scenarios is split into two units).
- `ScenarioIterator` — One `WorkUnit` per scenario run item (a whole
  ScenarioOutline is one unit).

## Execution pipeline

### Step 1: Plan (`_plan`)

```python
feature_locations = [f for f in self.feature_locations() if not self.config.exclude(f)]
features = parse_features(feature_locations, language=self.config.lang)
iterator = WorkUnitIterator.for_scheme(
    scheme=self.config.parallel_scheme, features=features, config=self.config
)
work_units = list(iterator.iterate())
work_units = self._sort_by_duration(work_units)  # LPT or FIFO
```

The coordinator parses all feature files, creates work units, and sorts them.
Step definitions are **not** loaded in the coordinator — only in workers.

### Step 2: Split (`_split_by_serial_tag`)

```python
parallel_batch = [u for u in units if not u.is_serial]
serial_batch = [u for u in units if u.is_serial]
```

Work units tagged `@serial` are separated for the serial phase.

### Step 3: Dispatch (`_dispatch`)

**Phase 1 — Parallel:**

1. Enqueue all parallel work units into `task_queue`.
2. Enqueue `min(N, len(batch))` `None` sentinels (one per worker).
3. Launch `min(N, len(batch))` `WorkerProcess` instances — never more
   workers than there is work.
4. Each worker runs `_worker_run_loop`: `setup()` → loop(`get`, `run`, `put`) → `teardown()`.
5. The coordinator collects results **while dispatching**; each work
   unit may take up to 300 seconds — the clock restarts with every
   received result. On timeout the workers are terminated and the
   remaining units count as missing (failed).
6. If `config.stop` is set (`--stop`), the first failed result sets
   `stop_event` so workers drop all queued units.
7. After all results are in, workers get a 30-second grace period to
   exit before being terminated.

**Phase 2 — Serial:**

1. If `stop_event` is not set and there are serial work units:
2. Enqueue all serial work units plus one sentinel.
3. Launch a single `WorkerProcess` and collect results the same way
   (300s per unit, not per phase).

### Step 4: Collect (`_collect`)

1. Drain `WorkerResult` objects from `result_queue` (up to 30s deadline).
2. Check for missing results (worker crashes → treated as failures).
3. Compute `any_failed = any(r.failed for r in results) or missing`.
4. Update `.behave-pool-timing.json` with observed durations.
5. Clean up `tmp/` directory.
6. Return `any_failed` (Behave convention: `True` = failure).

## Process isolation: why spawn?

`behave-pool` forces the `spawn` start method on all platforms:

```python
ctx = multiprocessing.get_context("spawn")
```

### The problem with fork

On Linux (Python 3.11–3.13), the default start method is `fork`. When a
process forks, the child inherits a **copy of the parent's entire memory
space**, including:

- Behave's global step registry
- Loaded hooks
- Imported modules and their state

When the worker then calls `setup()` and reloads step definitions, the
registry gets **duplicated or corrupted**, leading to:

- `RuntimeError` from conflicting step definitions
- Silent failures with exit code 1 and no stderr
- Flaky behavior that passes on some Python versions but not others

### The solution: spawn

With `spawn`, each worker starts with a **fresh Python interpreter**. No
inherited state, no global registry conflicts. The worker loads its own
hooks and step definitions cleanly in `setup()`.

**Python 3.14** already defaults to `forkserver` on Linux, which has similar
benefits. By forcing `spawn`, `behave-pool` ensures consistent behavior
across all Python versions and platforms.

## Queue protocol

### Task queue (`JoinableQueue`)

The coordinator puts `WorkUnit` objects into the task queue. Workers consume
them with `task_queue.get(timeout=5)`.

**Sentinel:** A `None` value signals the worker to exit the loop. The
coordinator puts `N` sentinels (one per worker) after all work units.

**Task done:** Workers call `task_queue.task_done()` after processing each
unit (or sentinel).

### Result queue (`Queue`)

Workers put `WorkerResult` objects into the result queue after executing
each work unit. The coordinator drains these in `_collect`.

### Stop event (`Event`)

A cooperative cancellation mechanism. When set:

- Workers check `stop_event.is_set()` in their loop and exit gracefully.
- The serial phase is skipped if `stop_event` is set before it starts.

The coordinator sets `stop_event` in the `finally` block of `_run_parallel`
and when a worker times out.

## Timeout handling

| Component | Timeout | Behavior |
| --- | --- | --- |
| Work unit | 300s per result | `stop_event.set()` + workers terminated |
| Worker shutdown | 30s | `join()` grace period, then `terminate()` |
| Collect deadline | 30s | Stops waiting for missing results |

Missing results (worker crashed before sending a result) are treated as
failures.

## Caveats

- **Hooks run per worker.** `before_all`/`after_all` (and the other
  environment hooks) execute once *per worker process*, not once per
  run. If `environment.py` manages global resources (ports, containers,
  shared files), make those hooks idempotent or move the resource behind
  a `@serial` scenario.
- **Daemon workers.** Worker processes are created with
  `daemon=True`, so they cannot spawn child processes themselves —
  `multiprocessing` inside step definitions will fail with
  `AssertionError: daemonic processes are not allowed to have children`.
- **No formatters in parallel mode.** `--format`/`--outfile` are not
  wired into workers; console output is one line per finished work unit
  plus an aggregate summary, and `--parallel-report` produces the
  machine-readable report.
