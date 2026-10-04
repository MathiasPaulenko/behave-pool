# LPT load balancing

`behave-pool` uses **Longest Processing Time (LPT)** scheduling by default to
minimize total wall-clock time across parallel workers.

## What is LPT?

LPT is a classic scheduling heuristic for the **multiprocessor scheduling
problem**. The idea is simple:

1. Sort jobs by duration, **longest first**.
2. Assign each job to the next available worker.

By starting the longest jobs first, workers are kept busy for the maximum
possible time, reducing the "tail" — the period where some workers have
finished while others are still running a long job.

### Example

Suppose you have 4 features with these durations:

| Feature | Duration |
| --- | --- |
| `checkout.feature` | 10s |
| `search.feature` | 7s |
| `login.feature` | 3s |
| `logout.feature` | 2s |

With **4 workers** and **LPT**:

```
Worker 0: checkout.feature (10s)  ████████████████████
Worker 1: search.feature   (7s)   ██████████████
Worker 2: login.feature    (3s)   ██████
Worker 3: logout.feature   (2s)   ████

Total wall-clock time: 10s
```

With **FIFO** (insertion order, assuming alphabetical):

```
Worker 0: checkout.feature (10s)  ████████████████████
Worker 1: login.feature    (3s)   ██████
Worker 2: logout.feature   (2s)   ████
Worker 3: search.feature   (7s)   ██████████████

Total wall-clock time: 10s
```

In this case the total is the same because the longest job (10s) dominates.
But with **2 workers**:

**LPT**:
```
Worker 0: checkout (10s)  ████████████████████
Worker 1: search (7s)     ██████████████ → login (3s) ██████

Total: 10s
```

**FIFO**:
```
Worker 0: checkout (10s)  ████████████████████
Worker 1: login (3s)      ██████ → logout (2s) ████ → search (7s) ██████████████

Total: 12s
```

LPT saves 2 seconds by starting the second-longest job (search, 7s) before
the shorter ones.

## How behave-pool implements LPT

### First run (no timing data)

On the first run, no `.behave-pool-timing.json` file exists. All durations
default to `0.0`, so LPT sorting has no effect — features are dispatched in
discovery order (alphabetical by filename).

```bash
# First run — no timing file, LPT has no effect
behave-pool --parallel 4 features/

# .behave-pool-timing.json is created with observed durations
```

### Subsequent runs

After the first run, `.behave-pool-timing.json` contains real durations:

```json
{
  "feature:features/checkout.feature": 10.2,
  "feature:features/search.feature": 7.1,
  "feature:features/login.feature": 3.0,
  "feature:features/logout.feature": 1.8
}
```

On the next run, `behave-pool` sorts work units by their stored duration
(descending) before dispatching:

```bash
# Second run — LPT uses stored durations
behave-pool --parallel 4 features/

# checkout (10.2s) dispatched first, then search (7.1s), etc.
```

### Timing file updates

After every run, observed durations are merged into the timing file. If a
feature's duration changes (e.g., due to new scenarios), the updated value
is stored for the next run.

```json
{
  "feature:features/checkout.feature": 12.5,
  "feature:features/search.feature": 6.8,
  "feature:features/login.feature": 3.2,
  "feature:features/logout.feature": 1.5
}
```

## Switching to FIFO

If you prefer insertion order (alphabetical by filename) over LPT:

```bash
behave-pool --parallel 4 --parallel-balance fifo features/
```

Or in `behave.ini`:

```ini
[behave]
parallel-balance = fifo
```

## Custom timing file

You can specify a custom location for the timing file:

```bash
behave-pool --parallel 4 \
    --parallel-timing-file .ci-timings.json \
    features/
```

This is useful for:

- **CI vs local**: Use different timing files for CI and local development.
- **Branch-specific**: Use different timing files per branch.
- **Shared timings**: Commit the timing file to share LPT data across a team
  (though this is not recommended — durations vary by machine).

## Timing file format

The file is a JSON object mapping work unit IDs to durations in seconds:

```json
{
  "feature:features/login.feature": 1.23,
  "feature:features/checkout.feature": 4.56
}
```

- **Keys**: Work unit IDs in the format `feature:<relative-path>`.
- **Values**: Floating-point durations in seconds.
- **Missing entries**: Default to `0.0` (treated as shortest).
- **Corrupt or non-finite entries**: Skipped with a warning log.
- **Stale entries**: Units whose files no longer exist are pruned on save.

## Best practices

- **Don't commit the timing file** — durations are machine-specific. Add
  `.behave-pool-timing.json` to `.gitignore`.
- **Let it warm up** — the first run won't benefit from LPT. Run the suite
  at least twice before measuring wall-clock improvements.
- **Use LPT for uneven suites** — if all features take roughly the same time,
  LPT and FIFO produce similar results. LPT shines when durations vary widely.
- **Don't worry about stale entries** — entries for renamed or deleted
  features are pruned automatically on the next save.
