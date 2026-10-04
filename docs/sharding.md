# Sharding

Sharding splits the test suite into independent groups so multiple CI runners
can execute different shards in parallel across separate machines.

## Overview

```
CI Runner 1: --shard 1/3    CI Runner 2: --shard 2/3    CI Runner 3: --shard 3/3
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│  Shard 1 of 3    │        │  Shard 2 of 3    │        │  Shard 3 of 3    │
│  Features A, B   │        │  Features C, D   │        │  Features E, F   │
│  --parallel 4    │        │  --parallel 4    │        │  --parallel 4    │
│  4 local workers │        │  4 local workers │        │  4 local workers │
└──────────────────┘        └──────────────────┘        └──────────────────┘
```

Each CI runner executes only its assigned shard. Within each shard,
`--parallel` provides local parallelism as usual.

## Usage

### CLI

```bash
# 3 CI runners, each with 4 local workers
behave-pool --parallel 4 --shard 1/3 features/
behave-pool --parallel 4 --shard 2/3 features/
behave-pool --parallel 4 --shard 3/3 features/
```

### behave.ini

Via `behave-pool` / `python -m behave_pool` (pool options registered
before config parsing):

```ini
[behave]
jobs = 4
shard = 1/3
```

Via plain `behave`, use the userdata fallback:

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner

[behave.userdata]
pool.shard = 1/3
```

### Python API

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

## Algorithm

1. **Parse** all features and create work units (same as normal planning).
2. **Assign** work units to shards deterministically: sorted by work unit
   ID (feature path) and split into `TOTAL` contiguous groups. The first
   `len % TOTAL` shards receive one extra work unit.
3. **Execute** only the `INDEX`-th group (1-based), keeping the planned
   LPT/FIFO order inside the shard.

This ensures:

- **Deterministic** shard assignment — the same feature always lands in
  the same shard given the same `TOTAL`.
- **No overlap** — every work unit belongs to exactly one shard.
- **Even distribution** — shard sizes differ by at most one work unit.

## Compatibility

Sharding composes with all other `behave-pool` features:

| Feature | Behavior with sharding |
| --- | --- |
| `--parallel N` | Local parallelism within each shard. Shard filtering happens first, then work units are distributed among up to N workers. |
| `@serial` tag | Serial work units within the shard run sequentially after the parallel phase. |
| `--tags` / `--name` | Selection filters are propagated to every worker; non-matching scenarios are skipped inside their work unit. Shard assignment itself is computed over all work units, which keeps it identical on every machine regardless of filters. |
| `--parallel-balance` | LPT/FIFO ordering is preserved within the shard. |
| `--parallel-report` | Each shard produces its own report file. |

### Execution order

```
1. Planning + LPT ordering (--parallel-balance)
       ↓
2. Sharding (--shard INDEX/TOTAL, order preserved)
       ↓
3. Serial/parallel split (@serial)
       ↓
4. Local dispatch (--parallel N)
       ↓
5. Tag/name filtering applied inside each worker
```

## Validation

Invalid shard values raise `ShardError` with a clear message:

| Input | Error |
| --- | --- |
| `--shard 0/3` | `shard_index must be >= 1, got 0` |
| `--shard 4/3` | `shard_index (4) must be <= total_shards (3)` |
| `--shard 1/0` | `total_shards must be >= 1, got 0` |
| `--shard invalid` | `Invalid shard format 'invalid'. Expected 'INDEX/TOTAL' (e.g. '1/3').` |
| `--shard 13` | `Invalid shard format '13'. Expected 'INDEX/TOTAL' (e.g. '1/3').` |

## Output

When sharding is active, the runner logs shard metadata at INFO level:

```
Shard 1/3 - 4 work units selected (of 10 total)
```

## CI integration example

### GitHub Actions

```yaml
jobs:
  test:
    strategy:
      matrix:
        shard: [1/3, 2/3, 3/3]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install behave-pool
      - run: behave-pool --parallel 4 --shard ${{ matrix.shard }} features/
```

### GitLab CI

```yaml
test:
  parallel: 3
  script:
    - pip install behave-pool
    - behave-pool --parallel 4 --shard ${CI_NODE_INDEX}/${CI_NODE_TOTAL} features/
```
