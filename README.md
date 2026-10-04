# behave-pool

[![CI](https://github.com/MathiasPaulenko/behave-pool/actions/workflows/ci.yml/badge.svg)](https://github.com/MathiasPaulenko/behave-pool/actions/workflows/ci.yml)
[![Documentation](https://github.com/MathiasPaulenko/behave-pool/actions/workflows/docs.yml/badge.svg)](https://mathiaspaulenko.github.io/behave-pool/)
[![PyPI version](https://img.shields.io/pypi/v/behave-pool.svg?label=pypi)](https://pypi.org/project/behave-pool/)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.11-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

Parallel test execution for [Behave](https://github.com/behave/behave) BDD via
native `ITestRunner`. Workers run in isolated processes with `spawn` start
method for clean interpreter state on every platform.

## Features

- **Native ITestRunner** — Registered via `--runner=` or `behave.ini`. Zero monkey-patching.
- **Process isolation** — `spawn` start method ensures clean state in every worker, on every OS.
- **Dynamic dispatch** — `multiprocessing.Process` + `Queue`. Workers consume work units as they finish.
- **@serial tag** — Non-parallelizable scenarios run sequentially after the parallel phase.
- **LPT load balancing** — Historical durations for optimal work distribution.
- **Timing persistence** — `.behave-pool-timing.json` stores durations between runs.
- **Sharding** — Split the suite across CI runners with `--shard INDEX/TOTAL`. Deterministic, compatible with `--parallel` and `@serial`.
- **Unified JSON report** — Merges all worker reports into a single `behave-modern-json-report` ExecutionReport (schema v1.1.0) with statistics, environment info, and full feature/scenario/step details.
- **Ecosystem integration** — Optional `behave-priority`, `behave-modern-json-report`. The unified report is directly consumable by any tool in the ecosystem.
- **Zero heavy dependencies** — Only stdlib `multiprocessing` + `behave>=1.3.0`.

## Installation

```bash
pip install behave-pool
```

## Quick start

```bash
behave-pool --parallel 4 features/
```

`behave-pool` is a drop-in behave wrapper: it registers the extra
`--parallel-*`/`--shard` options before behave parses the command line
and uses `ParallelRunner` automatically (unless `--runner` selects a
different one). `python -m behave_pool` is equivalent.

Prefer the plain `behave` command? Register the runner alias and set
`jobs` in `behave.ini`:

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner
```

or map an alias and select it on the command line:

```ini
[behave.runners]
parallel = behave_pool:ParallelRunner
```

```bash
behave --runner=parallel --parallel 4 features/
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

Each worker runs in an isolated process with the `spawn` start method,
guaranteeing a clean interpreter state regardless of OS or Python version.
Workers consume work units from a shared `JoinableQueue` and write
`WorkerResult` objects back to a result queue. The coordinator collects
results, persists timings, and returns the aggregated exit code.

## CLI options

| Option | Default | Description |
| --- | --- | --- |
| `--parallel N` | `1` | Number of worker processes. `1` = sequential passthrough. |
| `--parallel-scheme` | `feature` | Parallelization unit: `feature` or `scenario`. A `scenario` unit maps to one Scenario or one whole ScenarioOutline. |
| `--parallel-balance` | `lpt` | Work ordering: `lpt` (longest first) or `fifo` (insertion order). |
| `--parallel-timing-file` | `.behave-pool-timing.json` | Path to timing file for LPT balancing. |
| `--parallel-report` | `behave-pool-report.json` | Path to unified JSON report (behave-modern-json-report format). |
| `--shard INDEX/TOTAL` | _(disabled)_ | Run only shard `INDEX` of `TOTAL` for CI parallelism across machines. |

## Usage

### Feature-level parallelization

Each feature file runs in its own worker process. Workers are dispatched dynamically and consume work units from a shared queue.

```bash
# 4 worker processes, LPT balancing
behave-pool --parallel 4 features/
```

For finer granularity, `--parallel-scheme scenario` creates one work unit
per scenario (a whole ScenarioOutline counts as a single unit):

```bash
behave-pool --parallel 4 --parallel-scheme scenario features/
```

### Serial scenarios

Tag scenarios with `@serial` to run them sequentially after all parallel work units complete:

```gherkin
@serial
Scenario: Database migration
  Given the database is empty
  When I run the migration
  Then all tables should exist
```

### LPT load balancing

By default, `behave-pool` uses Longest Processing Time (LPT) scheduling. It stores historical durations in `.behave-pool-timing.json` and dispatches the slowest features first, minimizing total wall-clock time.

```bash
# Use FIFO ordering instead of LPT
behave-pool --parallel 4 --parallel-balance fifo features/
```

### Unified JSON report

After all workers finish, `behave-pool` merges their results into a single
JSON report in the [`behave-modern-json-report`](https://github.com/MathiasPaulenko/behave-modern-json-report)
`ExecutionReport` format (schema v1.1.0). This report includes:

- **Execution metadata** — unique ID, status, duration, timestamps.
- **Aggregate statistics** — feature/scenario/step counts, pass rate, error count, per-tag breakdown.
- **Environment info** — Python and Behave versions, OS, CI provider, git branch/commit.
- **Full feature tree** — features, scenarios, and steps with IDs, locations, durations, errors, and tracebacks.

```bash
# Default report path
behave-pool --parallel 4 features/
# → writes behave-pool-report.json

# Custom report path
behave-pool --parallel 4 \
    --parallel-report reports/run.json \
    features/
```

Any tool built for the `behave-modern-json-report` ecosystem (HTML formatters,
dashboards, AI analyzers) can consume the parallel report directly — no
conversion needed.

### Sharding

Split the test suite across multiple CI runners. Each runner executes
only its assigned shard:

```bash
# Runner 1 of 3
behave-pool --parallel 4 --shard 1/3 features/

# Runner 2 of 3
behave-pool --parallel 4 --shard 2/3 features/

# Runner 3 of 3
behave-pool --parallel 4 --shard 3/3 features/
```

Sharding composes with all other features:

- **`--parallel`**: local parallelism within each shard.
- **`@serial`**: serial scenarios run sequentially within the shard.
- **`--tags`/`--name`**: selection filters are propagated to every worker.
- **`--parallel-balance`**: LPT/FIFO ordering is preserved inside the shard.

The algorithm sorts work units deterministically by ID to compute the
shard assignment, then executes them in the planned (LPT/FIFO) order.
The first `len % TOTAL` shards receive one extra work unit.

Output includes shard metadata (logged at INFO level):

```
Shard 1/3 - 4 work units selected (of 10 total)
```

Python API:

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

### behave.ini configuration

Config-file keys must use the option's `dest` name (underscores, not
dashes) — behave reads them verbatim. `--parallel` maps to `jobs`:

```ini
[behave]
jobs = 4
parallel_scheme = feature
parallel_balance = lpt
parallel_timing_file = .behave-pool-timing.json
parallel_report = behave-pool-report.json
shard = 1/3
```

The pool keys (`parallel_*`, `shard`) are only picked up when the
options were registered before behave parses the file — i.e. when using
`behave-pool` / `python -m behave_pool`. With the plain `behave`
command, use `[behave.userdata]` entries instead; they are applied when
the runner initialises:

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner

[behave.userdata]
pool.scheme = feature
pool.balance = fifo
pool.timing_file = .behave-pool-timing.json
pool.report = behave-pool-report.json
pool.shard = 1/3
```

The same `pool.*` keys work on the command line via `-D`:

```bash
behave --runner=behave_pool:ParallelRunner -D pool.jobs=4 -D pool.shard=1/3
```

## Requirements

- Python >=3.11
- behave >=1.3.0

## Example

A complete working example is included in [`examples/calculator/`](examples/calculator/).
It demonstrates parallel execution, `@serial` scenarios, and the unified JSON report:

```bash
cd examples/calculator
behave-pool --parallel 4
# → runs 3 scenarios (2 parallel + 1 @serial)
# → writes behave-pool-report.json with ExecutionReport format
```

## Documentation

Full documentation is available at
<https://mathiaspaulenko.github.io/behave-pool/>.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup
instructions and guidelines.

Please review our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for notable changes.

## License

[MIT](LICENSE) — Copyright (c) 2026 Mathias Paulenko

## Acknowledgements

- [Behave](https://github.com/behave/behave) — the BDD framework this library extends.
- [Contributor Covenant](https://www.contributor-covenant.org/) — Code of Conduct.
- [Keep a Changelog](https://keepachangelog.com/) — Changelog format.
