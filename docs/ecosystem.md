# Ecosystem

`behave-pool` is designed to integrate with other packages in the Behave
ecosystem. This page covers the optional integrations available.

## behave-priority

[**behave-priority**](https://pypi.org/project/behave-priority/) provides
priority-based scenario ordering. Scenarios tagged with `@priority.high`,
`@priority.medium`, or `@priority.low` are executed in priority order.

### Installation

```bash
pip install "behave-pool[ecosystem]"
```

Or separately:

```bash
pip install behave-priority
```

### Usage with behave-pool

`behave-priority` works as a Behave runner that wraps `ParallelRunner`.
Register both in `behave.ini`:

```ini
[behave]
jobs = 4

[behave.runners]
parallel = behave_pool:ParallelRunner
priority = behave_priority:PriorityRunner
```

Run with priority ordering and parallel execution:

```bash
behave --runner=priority --parallel 4 features/
```

### Example feature with priorities

```gherkin
Feature: User management

  @priority.high
  Scenario: Admin can create users
    Given I am an admin
    When I create a new user
    Then the user should exist

  @priority.medium
  Scenario: User can update profile
    Given I am a registered user
    When I update my profile
    Then my profile should be updated

  @priority.low
  Scenario: User can delete account
    Given I am a registered user
    When I delete my account
    Then my account should be removed
```

## behave-modern-json-report

[**behave-modern-json-report**](https://pypi.org/project/behave-modern-json-report/)
provides a modern JSON report format for Behave test results, with richer
output than Behave's built-in JSON formatter.

### Installation

```bash
pip install "behave-pool[ecosystem]"
```

Or separately:

```bash
pip install behave-modern-json-report
```

### Usage with behave-pool

Behave formatters (`--format`/`--outfile`) are not wired into the
parallel workers, so use the built-in unified report instead — it
implements the same `ExecutionReport` schema that
`behave-modern-json-report` produces:

```bash
behave-pool --parallel 4 --parallel-report report.json features/
```

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner

[behave.userdata]
pool.report = report.json
```

Any tool that consumes the modern JSON `ExecutionReport` format can read
this file directly — features, scenarios, steps, errors, durations and
tag statistics included.

### Output format

The unified report includes:

- Feature, scenario, and step-level results
- Durations for each level
- Error messages and tracebacks
- Tags and metadata

```json
{
  "features": [
    {
      "name": "Login functionality",
      "filename": "features/login.feature",
      "status": "passed",
      "duration": 1.23,
      "scenarios": [
        {
          "name": "User logs in with valid credentials",
          "status": "passed",
          "duration": 0.45,
          "steps": [...]
        }
      ]
    }
  ],
  "summary": {
    "total_features": 1,
    "total_scenarios": 1,
    "passed": 1,
    "failed": 0,
    "duration": 1.23
  }
}
```

## Using all ecosystem packages together

```bash
pip install "behave-pool[ecosystem]"
```

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner

[behave.userdata]
pool.balance = lpt
pool.report = report.json
```

```bash
behave-pool features/
```

This gives you:

- **Parallel execution** with 4 worker processes
- **LPT load balancing** for optimal wall-clock time
- **Unified JSON report** (modern-json compatible schema) for CI
  integration and reporting

## Compatibility

| Package | Status | Notes |
| --- | --- | --- |
| `behave-priority` | Compatible | Works as a wrapping runner |
| `behave-modern-json-report` | Schema-compatible | Formatters don't run inside workers; `--parallel-report` emits the same `ExecutionReport` schema |
| `behave` | Required (`>=1.3.0`) | Base framework |
| `pytest` | Compatible | For running `behave-pool`'s own test suite |

## Custom integrations

`behave-pool` exposes a stable public API for custom integrations:

```python
from behave_pool import ParallelRunner
from behave_pool.config import ConfigSnapshot, snapshot_config
from behave_pool.work_unit import WorkUnit
from behave_pool.result import WorkerResult
from behave_pool.timing import TimingStore
```

See the [API reference](api-reference.md) for full documentation of these
classes.
