# Getting started

This guide walks you through installing `behave-pool`, registering the runner,
and running your first parallel test suite.

## Installation

### From PyPI

```bash
pip install behave-pool
```

### With ecosystem extras

```bash
pip install "behave-pool[ecosystem]"
```

This installs optional packages:

- `behave-priority` — Priority-based scenario ordering
- `behave-modern-json-report` — Modern JSON report format

### From source

```bash
git clone https://github.com/MathiasPaulenko/behave-pool.git
cd behave-pool
pip install -e ".[dev]"
```

## The `behave-pool` command

The package installs a `behave-pool` executable — a drop-in behave
wrapper that registers the extra `--parallel-*` and `--shard` options
*before* behave parses the command line and selects `ParallelRunner`
automatically:

```bash
behave-pool --parallel 4 features/
```

`python -m behave_pool` is equivalent. All standard behave options keep
working.

!!! note "Why a wrapper?"
    Behave parses arguments and the config file *before* it loads the
    runner class, so runner-provided CLI options cannot be registered
    from inside the runner. The `behave-pool` command imports the
    package first, which makes the custom options available during
    parsing.

## Using plain `behave`

If you prefer the plain `behave` command, register the runner and set
the worker count in `behave.ini`:

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner
```

Then:

```bash
behave features/
```

Or map an alias and pass it on the command line:

```ini
[behave.runners]
parallel = behave_pool:ParallelRunner
```

```bash
behave --runner=parallel --parallel 4 features/
```

With plain `behave`, the pool options (`parallel_scheme`,
`parallel_balance`, `parallel_timing_file`, `parallel_report`, `shard`)
cannot be used as ini keys — behave ignores unknown keys during config
parsing. Use `[behave.userdata]` entries (`pool.scheme`, `pool.balance`,
`pool.timing_file`, `pool.report`, `pool.shard`, `pool.jobs`) or `-D`
flags instead — see [Configuration](configuration.md).

## Your first parallel run

Make sure you have a `features/` directory with at least two `.feature` files.

=== "bash"

    ```bash
    behave-pool --parallel 4 features/
    ```

=== "behave.ini"

    ```ini
    [behave]
    jobs = 4
    runner = behave_pool:ParallelRunner
    ```

    Then simply run:

    ```bash
    behave features/
    ```

### What happens?

1. `ParallelRunner` parses all `.feature` files in `features/`.
2. It creates one `WorkUnit` per feature file — two for features that
   mix `@serial` and non-serial scenarios.
3. It launches up to 4 worker processes (using `spawn` start method).
4. Each worker consumes work units from a shared queue.
5. Results are collected and aggregated.
6. A `.behave-pool-timing.json` file is created with observed durations.

### Output example

```
USING RUNNER: behave_pool.runner:ParallelRunner
feature:features/login.feature ... passed (0.32s)
feature:features/checkout.feature ... passed (0.45s)
2 features, 4 scenarios, 12 steps - passed: 12, failed: 0, skipped: 0, undefined: 0
```

One progress line is printed per finished work unit, followed by an
aggregate summary. `--format`/`--outfile` formatters are not wired up in
parallel mode — use `--parallel-report` for machine-readable output.

## Choosing the number of workers

A good starting point is the number of CPU cores:

```bash
# Check available cores
python -c "import os; print(os.cpu_count())"

# Use that many workers
behave-pool --parallel 8 features/
```

!!! tip "Rule of thumb"
    Start with `--parallel N` where N = number of CPU cores. If features are
    very fast (< 1s), fewer workers may be better due to spawn overhead. If
    features are slow (I/O bound), more workers than cores can improve
    throughput.

## Verifying installation

```bash
python -c "from behave_pool import ParallelRunner; print(ParallelRunner)"
```

Expected output:

```
<class 'behave_pool.runner.ParallelRunner'>
```

## Next steps

- [Configuration](configuration.md) — Learn about all CLI options and `behave.ini` settings
- [Serial scenarios](serial-scenarios.md) — Handle non-parallelizable scenarios with `@serial`
- [LPT balancing](lpt-balancing.md) — Optimize wall-clock time with LPT scheduling
- [Examples](examples.md) — See complete worked examples
