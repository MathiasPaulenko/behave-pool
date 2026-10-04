"""Unit tests for the ``behave-pool`` CLI wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestOptionRegistration:
    def test_pool_options_registered_on_import(self) -> None:
        """Importing behave_pool.cli must register pool options early."""
        from behave.configuration import OPTIONS

        import behave_pool.cli  # noqa: F401

        flag_names = {fixed[0] for fixed, _ in OPTIONS if fixed}
        assert "--parallel-scheme" in flag_names
        assert "--parallel-balance" in flag_names
        assert "--parallel-timing-file" in flag_names
        assert "--parallel-report" in flag_names
        assert "--shard" in flag_names


class TestMain:
    def test_main_parses_pool_options(self) -> None:
        """``main()`` must accept pool options that plain behave rejects."""
        import behave_pool.cli

        with patch("behave.__main__.run_behave", return_value=0) as mock_run:
            rc = behave_pool.cli.main(
                ["--parallel", "2", "--shard", "1/3", "--parallel-balance", "fifo", "features/"]
            )
        assert rc == 0
        config = mock_run.call_args[0][0]
        assert config.jobs == 2
        assert config.shard == "1/3"
        assert config.parallel_balance == "fifo"

    def test_main_defaults_to_parallel_runner(self) -> None:
        """Without --runner, ParallelRunner is selected automatically."""
        import behave_pool.cli
        from behave_pool.runner import ParallelRunner

        with patch("behave.__main__.run_behave", return_value=0) as mock_run:
            behave_pool.cli.main(["features/"])
        assert mock_run.call_args[1]["runner_class"] is ParallelRunner

    def test_main_respects_explicit_runner(self) -> None:
        """--runner with a custom class must not be overridden."""
        import behave_pool.cli

        with patch("behave.__main__.run_behave", return_value=0) as mock_run:
            behave_pool.cli.main(["--runner", "behave.runner:Runner", "features/"])
        assert mock_run.call_args[1]["runner_class"] is None

    def test_main_invalid_args_raise_system_exit(self) -> None:
        """Unrecognized args exit like behave's own CLI (SystemExit)."""
        import pytest

        import behave_pool.cli

        with pytest.raises(SystemExit) as exc_info:
            behave_pool.cli.main(["--bogus-option-xyz"])
        assert exc_info.value.code != 0

    def test_main_returns_nonzero_on_failures(self) -> None:
        import behave_pool.cli

        with patch("behave.__main__.run_behave", return_value=1):
            assert behave_pool.cli.main(["features/"]) == 1


class TestModuleEntryPoint:
    def test_python_m_entrypoint_calls_main(self) -> None:
        """``python -m behave_pool`` delegates to cli.main."""
        import contextlib
        import runpy
        from unittest.mock import patch

        with (
            patch("behave_pool.cli.main", return_value=0) as mock_main,
            patch("sys.exit") as mock_exit,
            contextlib.suppress(SystemExit),
        ):
            runpy.run_module("behave_pool", run_name="__main__")
        mock_main.assert_called_once_with()
        mock_exit.assert_called_once_with(0)

    def test_cli_main_accepts_none_args(self) -> None:
        """main(None) must read sys.argv[1:]."""
        import sys

        import behave_pool.cli

        mock_argv = ["behave-pool", "features/"]
        with (
            patch.object(sys, "argv", mock_argv),
            patch("behave.configuration.Configuration") as mock_cfg,
            patch("behave.__main__.run_behave", return_value=0),
        ):
            mock_cfg.return_value.runner = MagicMock()
            behave_pool.cli.main(None)
        assert mock_cfg.call_args[0][0] == ["features/"]
