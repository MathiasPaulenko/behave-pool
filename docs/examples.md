# Examples

Complete worked examples showing how to use `behave-pool` in real projects.

## Example 0: Calculator (bundled)

A complete working example is included in the repository at
[`examples/calculator/`](https://github.com/MathiasPaulenko/behave-pool/tree/main/examples/calculator).
It demonstrates parallel execution, `@serial` scenarios, and the unified JSON report.

### Project structure

```text
examples/calculator/
├── behave.ini
├── features/
│   ├── calculator.feature      # Feature with parallel and @serial scenarios
│   └── steps/
│       └── calculator_steps.py # Step definitions
```

### `behave.ini`

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner

[behave.userdata]
pool.balance = lpt
pool.report = behave-pool-report.json
```

### `features/calculator.feature`

```gherkin
Feature: Calculator

  Scenario: Add two numbers
    Given I have a calculator
    When I add 2 and 3
    Then the result should be 5

  Scenario: Subtract two numbers
    Given I have a calculator
    When I subtract 5 from 8
    Then the result should be 3

  @serial
  Scenario: Shared resource operation
    Given I have a calculator
    When I multiply 4 by 6
    Then the result should be 24
```

### Running

```bash
cd examples/calculator
behave-pool --parallel 4
```

**What happens:**

1. The feature is split into two work units: `features/calculator.feature`
   (the two non-serial scenarios) and `features/calculator.feature#serial`.
2. "Shared resource operation" runs in the serial phase, after the parallel phase.
3. `behave-pool-report.json` is written with the full `ExecutionReport` format.

### Generated JSON report

The `behave-pool-report.json` file follows the
[`behave-modern-json-report`](https://github.com/MathiasPaulenko/behave-modern-json-report)
`ExecutionReport` schema (v1.1.0):

```json
{
  "schemaVersion": "1.1.0",
  "execution": {
    "executionId": "exec-b8f2ac918f12429da48f23df33337ea9",
    "status": "passed",
    "duration": 0.013614,
    "startTime": "2026-07-31T14:36:20.085Z",
    "endTime": "2026-07-31T14:36:20.099Z"
  },
  "statistics": {
    "features": 1,
    "scenarios": 3,
    "steps": 9,
    "passed": 9,
    "failed": 0,
    "skipped": 0,
    "undefined": 0,
    "pending": 0,
    "passRate": 1.0,
    "duration": 0.005959,
    "errorCount": 0,
    "totalAttachments": 0,
    "totalLogs": 0,
    "slowestStepDuration": 0.001035,
    "avgScenarioDuration": 0.001986,
    "byTag": {
      "serial": {
        "count": 1,
        "duration": 0.001811,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "undefined": 0,
        "pending": 0,
        "untested": 0,
        "error": 0,
        "hook_error": 0,
        "cleanup_error": 0,
        "xfailed": 0,
        "xpassed": 0
      }
    }
  },
  "environment": {
    "pythonVersion": "3.14.5",
    "platform": "win32",
    "os": "Windows",
    "osVersion": "10",
    "hostname": "MathiasLaptop",
    "cwd": "examples/calculator",
    "user": "mathi",
    "cpuCount": 12,
    "behaveVersion": "1.3.3",
    "gitBranch": "main",
    "gitCommit": "6a55636",
    "gitRemote": "https://github.com/MathiasPaulenko/behave-pool.git"
  },
  "features": [
    {
      "id": "feature-1df47553e00",
      "name": "Calculator",
      "tags": [],
      "filename": "features/calculator.feature",
      "line": 1,
      "status": "passed",
      "duration": 0.005958,
      "scenarios": [
        {
          "id": "scenario-1df47610050",
          "name": "Add two numbers",
          "featureId": "feature-1df47553e00",
          "tags": [],
          "location": { "filename": "features/calculator.feature", "line": 3 },
          "status": "passed",
          "duration": 0.002237,
          "steps": [
            {
              "id": "step-1df476101a0",
              "keyword": "Given",
              "text": "I have a calculator",
              "status": "passed",
              "duration": 0.001034,
              "location": { "filename": "features/calculator.feature", "line": 4 },
              "error": null,
              "attachments": [],
              "logs": []
            }
          ],
          "background": null,
          "rule": null,
          "isOutline": false,
          "outlineName": null,
          "retry": null
        }
      ],
      "background": null
    }
  ],
  "metadata": {}
}
```

!!! tip "Downstream tools"
    Any tool built for the `behave-modern-json-report` ecosystem (HTML
    formatters, dashboards, AI analyzers) can consume this report directly —
    no conversion needed.

## Example 1: Calculator API

A simple test suite with 3 feature files running in parallel.

### Project structure

```
my-project/
├── behave.ini
├── features/
│   ├── environment.py
│   ├── steps/
│   │   └── calculator_steps.py
│   ├── addition.feature
│   ├── subtraction.feature
│   └── multiplication.feature
```

### `behave.ini`

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner
```

### `features/addition.feature`

```gherkin
Feature: Addition

  Scenario: Add two positive numbers
    Given I have a calculator
    When I add 2 and 3
    Then the result should be 5

  Scenario: Add negative numbers
    Given I have a calculator
    When I add -1 and -2
    Then the result should be -3
```

### `features/subtraction.feature`

```gherkin
Feature: Subtraction

  Scenario: Subtract two numbers
    Given I have a calculator
    When I subtract 5 from 10
    Then the result should be 5

  Scenario: Subtract to get negative
    Given I have a calculator
    When I subtract 10 from 3
    Then the result should be -7
```

### `features/multiplication.feature`

```gherkin
@serial
Feature: Multiplication

  Scenario: Multiply two numbers
    Given I have a calculator
    When I multiply 3 by 4
    Then the result should be 12
```

### `features/steps/calculator_steps.py`

```python
from behave import given, when, then


@given("I have a calculator")
def step_have_calculator(context):
    context.calculator = {"ready": True}


@when("I add {a:d} and {b:d}")
def step_add(context, a, b):
    context.result = a + b


@when("I subtract {b:d} from {a:d}")
def step_subtract(context, a, b):
    context.result = a - b


@when("I multiply {a:d} by {b:d}")
def step_multiply(context, a, b):
    context.result = a * b


@then("the result should be {expected:d}")
def step_result(context, expected):
    assert context.result == expected, f"Expected {expected}, got {context.result}"
```

### Running

```bash
behave features/
```

**Output:**

```
USING RUNNER: behave_pool.runner:ParallelRunner
feature:features/addition.feature ... passed (0.01s)
feature:features/subtraction.feature ... passed (0.01s)
feature:features/multiplication.feature ... passed (0.01s)
3 features, 5 scenarios, 15 steps - passed: 15, failed: 0, skipped: 0, undefined: 0
```

**What happened:**

1. `addition.feature` and `subtraction.feature` ran in parallel (2 workers).
2. `multiplication.feature` was tagged `@serial`, so it ran after the parallel
   phase in a single worker.
3. `.behave-pool-timing.json` was created with durations.

## Example 2: Web API test suite

A larger suite with mixed parallel and serial scenarios.

### Project structure

```
api-tests/
├── behave.ini
├── features/
│   ├── environment.py
│   ├── steps/
│   │   ├── auth_steps.py
│   │   ├── user_steps.py
│   │   └── order_steps.py
│   ├── auth.feature
│   ├── users.feature
│   ├── orders.feature
│   └── cleanup.feature
```

### `behave.ini`

```ini
[behave]
jobs = 4
runner = behave_pool:ParallelRunner

[behave.userdata]
pool.balance = lpt
pool.timing_file = .api-test-timings.json
```

### `features/auth.feature`

```gherkin
Feature: Authentication

  Scenario: Login with valid credentials
    Given the API is running
    When I login as "admin" with password "secret"
    Then I should receive a valid token

  Scenario: Login with invalid credentials
    Given the API is running
    When I login as "admin" with password "wrong"
    Then I should receive a 401 error
```

### `features/users.feature`

```gherkin
Feature: User management

  Scenario: List all users
    Given I am authenticated as admin
    When I request the user list
    Then I should receive a list of users

  Scenario: Create a new user
    Given I am authenticated as admin
    When I create a user with email "test@example.com"
    Then the user should exist in the database
```

### `features/orders.feature`

```gherkin
Feature: Order processing

  Scenario: Create an order
    Given I am authenticated as a customer
    When I create an order for product "widget"
    Then the order should be created

  @serial
  Scenario: Process pending orders
    Given there are pending orders
    When I trigger order processing
    Then all orders should be processed
```

### `features/cleanup.feature`

```gherkin
@serial
Feature: Cleanup

  Scenario: Remove test data
    Given test data exists
    When I run the cleanup script
    Then no test data should remain
```

### `features/environment.py`

```python
import requests

BASE_URL = "http://localhost:8000"
_token = None


def before_all(context):
    context.base_url = BASE_URL
    context.session = requests.Session()


def before_scenario(context, scenario):
    if "authenticated" in scenario.effective_tags:
        if "admin" in scenario.effective_tags:
            resp = context.session.post(
                f"{context.base_url}/auth/login",
                json={"username": "admin", "password": "secret"},
            )
            context.token = resp.json()["token"]
            context.session.headers["Authorization"] = f"Bearer {context.token}"
        elif "customer" in scenario.effective_tags:
            resp = context.session.post(
                f"{context.base_url}/auth/login",
                json={"username": "customer", "password": "pass"},
            )
            context.token = resp.json()["token"]
            context.session.headers["Authorization"] = f"Bearer {context.token}"


def after_all(context):
    context.session.close()
```

### Running

```bash
# First run — no timing data, features run alphabetically
behave features/

# Second run — LPT uses stored durations
behave features/
```

**Execution order (second run with LPT):**

1. **Parallel phase**: `auth.feature`, `users.feature`, `orders.feature` (without
   the `@serial` scenario) run across 4 workers.
2. **Serial phase**: The `@serial` scenario from `orders.feature` and all
   scenarios from `cleanup.feature` run one at a time.

## Example 3: CI/CD pipeline

### GitHub Actions

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
        shard: ["1/3", "2/3", "3/3"]
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: behave-pool --parallel 4 --shard ${{ matrix.shard }} features/
```

### GitLab CI

```yaml
test:
  parallel: 3
  image: python:3.12
  script:
    - pip install behave-pool
    - behave-pool --parallel 4 --shard ${CI_NODE_INDEX}/${CI_NODE_TOTAL} features/
```

### Jenkins

```groovy
pipeline {
    agent any
    stages {
        stage('Test') {
            steps {
                sh 'pip install behave-pool'
                sh 'behave-pool --parallel 4 features/'
            }
        }
    }
}
```

## Example 4: Custom timing file per environment

Behave always reads the same config files (`behave.ini`, `.behaverc`,
`setup.cfg`, `tox.ini`, `pyproject.toml`) — there is no env var to point it
at a different file. Override per environment with CLI options or `-D`
userdata keys instead:

```ini
# behave.ini — defaults for local development
[behave]
jobs = 2
runner = behave_pool:ParallelRunner

[behave.userdata]
pool.balance = fifo
```

```bash
# CI: more workers and a dedicated timing file
behave-pool --parallel 8 --parallel-balance lpt \
    --parallel-timing-file .ci-timings.json features/

# or with plain behave
behave --parallel 8 \
    -D pool.balance=lpt -D pool.timing_file=.ci-timings.json features/

# Local
behave features/
```

## Example 5: Programmatic usage

You can use `behave-pool` programmatically without the `behave` CLI:

```python
from behave.configuration import Configuration
from behave_pool import ParallelRunner

# Create configuration
config = Configuration(["--parallel", "4", "features/"])

# Create and run the parallel runner
runner = ParallelRunner(config)
failed = runner.run()

if failed:
    print("Tests failed!")
    exit(1)
else:
    print("All tests passed!")
```

### Using TimingStore directly

```python
from pathlib import Path
from behave_pool.timing import TimingStore

# Load existing timings
store = TimingStore(path=Path(".behave-pool-timing.json"))
durations = store.load()
print(durations)
# {"feature:features/login.feature": 1.23, ...}

# Get duration for a specific feature
duration = store.get_duration("feature:features/login.feature")
print(f"Login feature took {duration}s last time")

# Update with new duration
store.update("feature:features/login.feature", 1.45)

# Save (only if changed)
saved = store.save_if_changed()
print(f"Saved: {saved}")
```

## Example 6: Sharding across CI runners

Split the test suite across 3 CI runners, each with 4 local workers:

### CLI

```bash
# Runner 1
behave-pool --parallel 4 --shard 1/3 features/

# Runner 2
behave-pool --parallel 4 --shard 2/3 features/

# Runner 3
behave-pool --parallel 4 --shard 3/3 features/
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

### With @serial and --tags

Sharding composes with `@serial` tags and `--tags` filtering:

```bash
behave-pool --parallel 4 \
    --tags @smoke \
    --shard 1/3 \
    features/
```

Serial work units within the shard run sequentially after the parallel
phase. `--tags`/`--name` filters are propagated to workers, so the shard
assignment stays identical on every machine.
