# Serial scenarios

Some scenarios cannot run in parallel because they depend on shared state,
exclusive resources, or have side effects that would conflict with other tests.
`behave-pool` provides the `@serial` tag to handle these cases.

## How it works

`@serial` applies at **scenario granularity**:

- A feature with **no** `@serial` produces one parallel work unit.
- A feature tagged `@serial` at feature level produces one serial work
  unit (all its scenarios run serially).
- A feature **mixing** serial and non-serial scenarios is split into two
  work units: a parallel unit running only the non-serial scenarios, and
  a `<feature>#serial` unit running only the `@serial` scenarios.

The run then has two phases:

1. **Parallel phase** — All non-serial work units across N worker processes.
2. **Serial phase** — After all parallel workers complete, the serial
   work units run one at a time in a single worker process.

This ensures serial scenarios never run concurrently with each other or
with parallel work.

!!! note "With `--parallel-scheme scenario`"
    The description above applies to the default `feature` scheme. Under
    `scenario` scheme each run item becomes its own work unit, so a
    `@serial` scenario is a serial unit on its own (no `#serial` split
    needed). A ScenarioOutline is a single unit: if only some of its
    example rows are `@serial`, the whole outline runs serially.

## Tagging scenarios

### Single scenario as serial

```gherkin
Feature: Database operations

  Scenario: Query user data
    Given a user exists
    When I query the database
    Then I should see the user record

  @serial
  Scenario: Run database migration
    Given the database is empty
    When I run the migration script
    Then all tables should exist
```

In this example:

- "Query user data" runs in the **parallel phase**.
- "Run database migration" runs in the **serial phase**, after all parallel
  work is done.

### Entire feature as serial

```gherkin
@serial
Feature: Cleanup operations

  Scenario: Remove temporary files
    Given temp files exist
    When I run cleanup
    Then no temp files should remain

  Scenario: Reset test database
    Given a test database exists
    When I reset it
    Then the database should be empty
```

When a feature is tagged `@serial`, **all scenarios** in that feature run in
the serial phase.

### Multiple serial scenarios

```gherkin
Feature: Order processing

  Scenario: Create order
    Given a customer
    When I create an order
    Then the order should be saved

  @serial
  Scenario: Process payment
    Given an order exists
    When I process the payment
    Then the payment should be confirmed

  @serial
  Scenario: Send confirmation email
    Given a confirmed order
    When I send the confirmation email
    Then the email should be sent
```

Both serial scenarios are grouped into the feature's `#serial` work unit
and run **one at a time**, in file order: "Process payment" first, then
"Send confirmation email". Across features, serial work units run in the
planned dispatch order (LPT by default, or FIFO with
`--parallel-balance fifo`).

## Execution order

```
┌──────────────────────────────────────────────────────┐
│                    ParallelRunner                     │
│                                                       │
│  Phase 1: PARALLEL                                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐    │
│  │ Worker 0 │ │ Worker 1 │ │ Worker 2 │ │ Worker 3 │   │
│  │ feature A│ │ feature B│ │ feature C│ │ feature D│   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘    │
│                                                       │
│  Phase 2: SERIAL (after all workers finish)           │
│  ┌──────────────────────────────────────────┐        │
│  │ 1 worker: serial unit 1 → unit 2 → ...    │        │
│  └──────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────┘
```

!!! important "Serial phase only starts after parallel phase"
    If any parallel worker fails, the serial phase still runs. This ensures
    cleanup scenarios (e.g., `@serial` teardown) always execute. The serial
    phase is only skipped when the `stop_event` is set — i.e. `--stop` after
    a failure, a worker timeout, or a worker abort.

## Combining with other tags

`@serial` can be combined with any other tags:

```gherkin
@serial @slow @database
Scenario: Full database rebuild
  Given a populated database
  When I rebuild all indexes
  Then all indexes should be valid
```

You can use Behave's `--tags` filtering alongside `@serial`:

```bash
# Run only serial scenarios
behave-pool --parallel 4 --tags=@serial features/

# Exclude serial scenarios from the run
behave-pool --parallel 4 --tags="not @serial" features/
```

`--tags`/`--name` filters are propagated to every worker, so excluded
scenarios are skipped inside each work unit.

## Common use cases

### Database migrations

```gherkin
@serial
Scenario: Run schema migration
  Given the database is at version 1
  When I run the migration to version 2
  Then the schema should be at version 2
```

### Shared file system operations

```gherkin
@serial
Scenario: Write to shared log file
  Given a shared log file exists
  When I append an entry
  Then the log file should contain the entry
```

### External API rate-limited calls

```gherkin
@serial
Scenario: Call rate-limited API
  Given the API allows 1 request per second
  When I make a request
  Then I should receive a valid response
```

## Best practices

- **Tag at the scenario level** when only specific scenarios need serialization.
- **Tag at the feature level** when all scenarios in a feature are
  non-parallelizable.
- **Keep serial scenarios fast** — they run sequentially and can become a
  bottleneck if there are many slow serial scenarios.
- **Use `@serial` for correctness, not convenience** — only tag scenarios
  that truly cannot run in parallel.
