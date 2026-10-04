# behave-pool calculator example

This example demonstrates how to use `behave-pool` to run Behave features
in parallel.

## Structure

```text
examples/calculator/
  features/
    calculator.feature      # Feature with parallel and @serial scenarios
    steps/
      calculator_steps.py   # Step definitions
```

## Running

From the `examples/calculator` directory:

```bash
# Install behave-pool (if not already installed)
pip install behave-pool

# Run with 4 parallel workers (behave-pool is a behave wrapper)
behave-pool --parallel 4

# The included behave.ini already sets jobs=4, so plain behave works too:
behave
```

## What to expect

- The two non-serial scenarios run inside the parallel work unit, in
  parallel with other features' work units.
- The `@serial` scenario runs sequentially after all parallel work
  units complete (the feature is split into a parallel unit and a
  serial unit).
- A `.behave-pool-timing.json` file is created to store durations for
  LPT scheduling on subsequent runs.
- A `behave-pool-report.json` unified report is written.
