# behave-pool

Parallel test execution for [Behave](https://github.com/behave/behave) BDD via
native `ITestRunner`. Workers run in isolated processes with the `spawn` start
method for clean interpreter state on every platform.

## Why behave-pool?

Standard Behave runs all features sequentially in a single process. As test
suites grow, wall-clock time becomes a bottleneck. `behave-pool` solves this by:

- Splitting features across **N worker processes** that run in parallel.
- Using the **`spawn` start method** so every worker gets a clean interpreter
  state — no inherited global registries, no fork-related bugs on Linux.
- Providing **LPT load balancing** so the slowest features start first,
  minimizing total wall-clock time.
- Supporting **`@serial` tags** for scenarios that cannot run in parallel
  (database migrations, shared resources, etc.).
- Providing **sharding** (`--shard INDEX/TOTAL`) to split the suite across
  CI runners for distributed parallelism.

## Features

- **Native ITestRunner** — Registered via `--runner=` or `behave.ini`. Zero monkey-patching.
- **Two granularities** — `--parallel-scheme feature` (one unit per file) or `scenario` (one unit per scenario/outline).
- **Process isolation** — `spawn` start method ensures clean state in every worker, on every OS.
- **Dynamic dispatch** — `multiprocessing.Process` + `Queue`. Workers consume work units as they finish.
- **@serial tag** — Non-parallelizable scenarios run sequentially after the parallel phase.
- **LPT load balancing** — Historical durations for optimal work distribution.
- **Timing persistence** — `.behave-pool-timing.json` stores durations between runs.
- **Sharding** — `--shard INDEX/TOTAL` splits the suite across CI runners. Deterministic, compatible with `--parallel` and `@serial`.
- **Unified JSON report** — Merges all worker reports into a single `behave-modern-json-report` ExecutionReport (schema v1.1.0) with statistics, environment info, and full feature/scenario/step details.
- **Ecosystem integration** — Optional `behave-priority`, `behave-modern-json-report`. The unified report is directly consumable by any tool in the ecosystem.
- **Zero heavy dependencies** — Only stdlib `multiprocessing` + `behave>=1.3.0`.

## Quick start

```bash
pip install behave-pool
```

Run the suite with 4 parallel workers:

```bash
behave-pool --parallel 4 features/
```

Or register the runner in `behave.ini` and use plain `behave`:

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner
```

## How it works

```
┌─────────────────────────────────────────────────┐
│                  ParallelRunner                  │
│                                                  │
│  1. Plan    — parse features, create work units  │
│  2. Shard   — select shard slice (if --shard)    │
│  3. Split   — separate @serial from parallel     │
│  4. Dispatch — N parallel workers, then 1 serial │
│  5. Collect — gather results, update timings     │
└─────────────────────────────────────────────────┘
         │                          │
    ┌────▼────┐               ┌────▼────┐
    │ Worker 0 │               │ Worker N │
    │ (spawn)  │    ...        │ (spawn)  │
    │          │               │          │
    │ parse    │               │ parse    │
    │ features │               │ features │
    │ run      │               │ run      │
    │ report   │               │ report   │
    └──────────┘               └──────────┘
```

When `--parallel` is 1, the runner falls back to standard sequential Behave
execution with no overhead.

## Requirements

- Python >=3.11
- behave >=1.3.0

## Documentation

- [Getting started](getting-started.md) — Installation and first run
- [Configuration](configuration.md) — All CLI options and `behave.ini` settings
- [Serial scenarios](serial-scenarios.md) — Using the `@serial` tag
- [Sharding](sharding.md) — Splitting the suite across CI runners
- [LPT balancing](lpt-balancing.md) — How LPT scheduling works
- [Architecture](architecture.md) — Internal design and execution model
- [Ecosystem](ecosystem.md) — Integration with other behave packages
- [Examples](examples.md) — Complete worked examples
- [API reference](api-reference.md) — Full API documentation
