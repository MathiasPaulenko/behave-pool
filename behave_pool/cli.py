"""``behave-pool`` command: behave wrapper that registers pool options early.

Behave parses command-line arguments and config files inside
``Configuration.__init__``, before the runner class is loaded.  Custom
options therefore must be registered in ``behave.configuration.OPTIONS``
*before* ``Configuration`` is created.  Importing :mod:`behave_pool`
registers them, so this entry point simply imports the package first and
then delegates to behave's own ``main()`` flow.

Unless ``--runner`` (or the ``runner`` config key) selects a different
runner, the ``behave-pool`` command uses :class:`ParallelRunner`
automatically — no ``[behave.runners]`` alias is required.
"""

from __future__ import annotations

import sys

import behave_pool  # noqa: F401  -- registers --parallel-* / --shard options


def main(args: list[str] | None = None) -> int:
    """Entry point for the ``behave-pool`` command.

    Args:
        args: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 on success, non-zero on failure.
    """
    # behave_pool is imported at module level so that its options are
    # registered in behave.configuration.OPTIONS before Configuration
    # parses the command line.
    from behave.__main__ import run_behave
    from behave.configuration import DEFAULT_RUNNER_CLASS_NAME, Configuration
    from behave.exception import ConfigError, TagExpressionError

    try:
        # NOTE: behave only falls back to sys.argv when argv[0] contains
        # "behave"; under "python -m behave_pool" it does not, so the args
        # must be passed explicitly.
        args_list = list(args) if args is not None else sys.argv[1:]
        config = Configuration(args_list)
        runner_class = None
        user_runner_given = any(
            a == "--runner" or a.startswith("--runner=") or a.startswith("--runner:")
            for a in args_list
        )
        if config.runner == DEFAULT_RUNNER_CLASS_NAME and not user_runner_given:
            runner_class = behave_pool.ParallelRunner
        return int(run_behave(config, runner_class=runner_class))
    except ConfigError as e:
        print(f"{e.__class__.__name__}: {e}")
    except TagExpressionError as e:
        print(f"TagExpressionError: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
