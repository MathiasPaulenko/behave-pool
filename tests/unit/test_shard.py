"""Unit tests for sharding support."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from behave.model import Feature

from behave_pool.config import ConfigSnapshot
from behave_pool.shard import (
    ShardConfig,
    ShardError,
    parse_shard_string,
    select_shard_work_units,
    split_shards,
    validate_shard,
)
from behave_pool.work_unit import WorkUnit


def _make_feature(
    filename: str,
    name: str | None = None,
) -> Feature:
    return Feature(
        filename=filename,
        line=1,
        keyword="Feature",
        name=name or filename,
        tags=[],
    )


def _make_work_unit(unit_id: str) -> WorkUnit:
    return WorkUnit(
        id=unit_id,
        config=ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="environment.py",
            lang="en",
            stop=False,
        ),
        feature_path=f"{unit_id}.feature",
    )


# ── validate_shard ──────────────────────────────────────────────────


class TestValidateShard:
    def test_valid_shard(self) -> None:
        validate_shard(1, 3)
        validate_shard(3, 3)
        validate_shard(1, 1)

    def test_total_shards_zero_raises(self) -> None:
        with pytest.raises(ShardError, match="total_shards must be >= 1"):
            validate_shard(1, 0)

    def test_total_shards_negative_raises(self) -> None:
        with pytest.raises(ShardError, match="total_shards must be >= 1"):
            validate_shard(1, -1)

    def test_shard_index_zero_raises(self) -> None:
        with pytest.raises(ShardError, match="shard_index must be >= 1"):
            validate_shard(0, 3)

    def test_shard_index_negative_raises(self) -> None:
        with pytest.raises(ShardError, match="shard_index must be >= 1"):
            validate_shard(-1, 3)

    def test_shard_index_exceeds_total_raises(self) -> None:
        with pytest.raises(ShardError, match="shard_index .* must be <= total_shards"):
            validate_shard(4, 3)


# ── parse_shard_string ──────────────────────────────────────────────


class TestParseShardString:
    def test_valid_string(self) -> None:
        config = parse_shard_string("1/3")
        assert config.shard_index == 1
        assert config.total_shards == 3

    def test_valid_string_with_spaces(self) -> None:
        config = parse_shard_string("  2/5  ")
        assert config.shard_index == 2
        assert config.total_shards == 5

    def test_single_shard(self) -> None:
        config = parse_shard_string("1/1")
        assert config.shard_index == 1
        assert config.total_shards == 1

    def test_missing_slash_raises(self) -> None:
        with pytest.raises(ShardError, match="Invalid shard format"):
            parse_shard_string("13")

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ShardError, match="Invalid shard format"):
            parse_shard_string("a/3")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ShardError, match="Invalid shard format"):
            parse_shard_string("")

    def test_zero_index_raises(self) -> None:
        with pytest.raises(ShardError, match="shard_index must be >= 1"):
            parse_shard_string("0/3")

    def test_index_exceeds_total_raises(self) -> None:
        with pytest.raises(ShardError, match="shard_index .* must be <= total_shards"):
            parse_shard_string("5/3")


# ── split_shards ────────────────────────────────────────────────────


class TestSplitShards:
    def test_even_split(self) -> None:
        items = list(range(9))
        shard1 = split_shards(items, 1, 3)
        shard2 = split_shards(items, 2, 3)
        shard3 = split_shards(items, 3, 3)
        assert shard1 == [0, 1, 2]
        assert shard2 == [3, 4, 5]
        assert shard3 == [6, 7, 8]

    def test_uneven_split_first_shards_get_extra(self) -> None:
        items = list(range(10))
        shard1 = split_shards(items, 1, 3)
        shard2 = split_shards(items, 2, 3)
        shard3 = split_shards(items, 3, 3)
        assert len(shard1) == 4
        assert len(shard2) == 3
        assert len(shard3) == 3
        assert shard1 == [0, 1, 2, 3]
        assert shard2 == [4, 5, 6]
        assert shard3 == [7, 8, 9]

    def test_single_shard_returns_all(self) -> None:
        items = list(range(5))
        shard1 = split_shards(items, 1, 1)
        assert shard1 == items

    def test_more_shards_than_items(self) -> None:
        items = [1, 2]
        shard1 = split_shards(items, 1, 5)
        shard2 = split_shards(items, 2, 5)
        shard3 = split_shards(items, 3, 5)
        shard4 = split_shards(items, 4, 5)
        shard5 = split_shards(items, 5, 5)
        assert shard1 == [1]
        assert shard2 == [2]
        assert shard3 == []
        assert shard4 == []
        assert shard5 == []

    def test_empty_list(self) -> None:
        assert split_shards([], 1, 3) == []
        assert split_shards([], 2, 3) == []
        assert split_shards([], 3, 3) == []

    def test_all_shards_cover_all_items(self) -> None:
        items = list(range(10))
        all_shards: list[int] = []
        for i in range(1, 4):
            all_shards.extend(split_shards(items, i, 3))
        assert all_shards == items

    def test_no_overlap_between_shards(self) -> None:
        items = list(range(10))
        shard1 = set(split_shards(items, 1, 3))
        shard2 = set(split_shards(items, 2, 3))
        shard3 = set(split_shards(items, 3, 3))
        assert shard1.isdisjoint(shard2)
        assert shard1.isdisjoint(shard3)
        assert shard2.isdisjoint(shard3)

    def test_invalid_shard_raises(self) -> None:
        with pytest.raises(ShardError):
            split_shards([1, 2, 3], 0, 3)

    def test_invalid_total_raises(self) -> None:
        with pytest.raises(ShardError):
            split_shards([1, 2, 3], 1, 0)


# ── select_shard_work_units ─────────────────────────────────────────


class TestSelectShardWorkUnits:
    def test_selects_correct_subset(self) -> None:
        units = [_make_work_unit(f"feature:{c}.feature") for c in "abcdefghij"]
        shard1 = select_shard_work_units(units, 1, 3)
        shard2 = select_shard_work_units(units, 2, 3)
        shard3 = select_shard_work_units(units, 3, 3)
        assert len(shard1) == 4
        assert len(shard2) == 3
        assert len(shard3) == 3

    def test_all_shards_cover_all_units(self) -> None:
        units = [_make_work_unit(f"feature:{c}.feature") for c in "abcdefghij"]
        all_selected: list[WorkUnit] = []
        for i in range(1, 4):
            all_selected.extend(select_shard_work_units(units, i, 3))
        assert len(all_selected) == len(units)
        assert {u.id for u in all_selected} == {u.id for u in units}

    def test_no_overlap(self) -> None:
        units = [_make_work_unit(f"feature:{c}.feature") for c in "abcdefghij"]
        shard1 = {u.id for u in select_shard_work_units(units, 1, 3)}
        shard2 = {u.id for u in select_shard_work_units(units, 2, 3)}
        shard3 = {u.id for u in select_shard_work_units(units, 3, 3)}
        assert shard1.isdisjoint(shard2)
        assert shard1.isdisjoint(shard3)
        assert shard2.isdisjoint(shard3)

    def test_deterministic_selection(self) -> None:
        units = [_make_work_unit(f"feature:{c}.feature") for c in "abcdefghij"]
        # Reversed input must produce the same shard membership (the
        # returned order follows the input order, e.g. LPT balancing).
        reversed_units = list(reversed(units))
        shard1_a = select_shard_work_units(units, 1, 3)
        shard1_b = select_shard_work_units(reversed_units, 1, 3)
        assert {u.id for u in shard1_a} == {u.id for u in shard1_b}

    def test_input_order_preserved(self) -> None:
        """Selection preserves the incoming order (LPT) inside the shard."""
        units = [_make_work_unit(f"feature:{c}.feature") for c in "abcdefghij"]
        reversed_units = list(reversed(units))
        shard1 = select_shard_work_units(reversed_units, 1, 3)
        expected_order = [u.id for u in reversed_units if u in shard1]
        assert [u.id for u in shard1] == expected_order

    def test_empty_units(self) -> None:
        assert select_shard_work_units([], 1, 3) == []


# ── ShardConfig ─────────────────────────────────────────────────────


class TestShardConfig:
    def test_defaults(self) -> None:
        config = ShardConfig(shard_index=1, total_shards=3)
        assert config.shard_index == 1
        assert config.total_shards == 3
        assert config.features_dir == "features/"
        assert config.parallel == 1

    def test_custom_values(self) -> None:
        config = ShardConfig(
            shard_index=2,
            total_shards=5,
            features_dir="tests/features/",
            parallel=4,
        )
        assert config.shard_index == 2
        assert config.total_shards == 5
        assert config.features_dir == "tests/features/"
        assert config.parallel == 4

    def test_frozen(self) -> None:
        config = ShardConfig(shard_index=1, total_shards=3)
        with pytest.raises(AttributeError):
            config.shard_index = 2  # type: ignore[misc]


# ── Runner integration ──────────────────────────────────────────────


class TestRunnerShardIntegration:
    @pytest.fixture
    def mock_config(self) -> MagicMock:
        config = MagicMock()
        config.jobs = 1
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.base_dir = "features"
        config.environment_file = "environment.py"
        config.steps_dir = "steps"
        config.stop = False
        config.reporters = []
        config.lang = "en"
        config.outputs = []
        config.paths = ["features"]
        config.verbose = False
        config.dry_run = False
        config.use_nested_step_modules = False
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".behave-pool-timing.json"
        config.parallel_report = "behave-pool-report.json"
        config.shard = None
        config.shard_index = None
        config.total_shards = None
        config.exclude = MagicMock(return_value=False)
        return config

    def test_is_sharding_active_false_when_none(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.shard_index = None
        mock_config.total_shards = None
        runner = ParallelRunner(mock_config)
        assert runner._is_sharding_active() is False

    def test_is_sharding_active_true_when_set(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.shard_index = 1
        mock_config.total_shards = 3
        runner = ParallelRunner(mock_config)
        assert runner._is_sharding_active() is True

    def test_apply_shard_filters_work_units(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.jobs = 2
        mock_config.parallel = 2
        mock_config.shard_index = 1
        mock_config.total_shards = 3
        runner = ParallelRunner(mock_config)

        units = [_make_work_unit(f"feature:{c}.feature") for c in "abcdefghij"]
        selected = runner._apply_shard(units)
        assert len(selected) == 4
        assert all(u in units for u in selected)

    def test_apply_shard_logs_info(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.jobs = 2
        mock_config.parallel = 2
        mock_config.shard_index = 2
        mock_config.total_shards = 3
        runner = ParallelRunner(mock_config)

        units = [_make_work_unit(f"feature:{c}.feature") for c in "abcdefghij"]
        with patch("behave_pool.runner.logger") as mock_logger:
            runner._apply_shard(units)
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "Shard %d/%d - %d work units selected (of %d total)"
            assert call_args[0][1:] == (2, 3, 3, 10)

    def test_filter_features_by_shard(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.shard_index = 1
        mock_config.total_shards = 2
        runner = ParallelRunner(mock_config)

        f1 = _make_feature("a.feature", name="Alpha")
        f2 = _make_feature("b.feature", name="Beta")
        f3 = _make_feature("c.feature", name="Gamma")
        features = [f3, f1, f2]

        selected = runner._filter_features_by_shard(features)
        assert len(selected) == 2
        # Sorted by filename: a.feature, b.feature, c.feature
        # Shard 1 of 2 gets first 2 (ceil(3/2)=2)
        assert selected[0].filename == "a.feature"
        assert selected[1].filename == "b.feature"

    def test_log_shard_info_with_total(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.shard_index = 1
        mock_config.total_shards = 3
        runner = ParallelRunner(mock_config)
        with patch("behave_pool.runner.logger") as mock_logger:
            runner._log_shard_info(4, total=10)
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "Shard %d/%d - %d work units selected (of %d total)"
            assert call_args[0][1:] == (1, 3, 4, 10)

    def test_log_shard_info_without_total(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.shard_index = 2
        mock_config.total_shards = 3
        runner = ParallelRunner(mock_config)
        with patch("behave_pool.runner.logger") as mock_logger:
            runner._log_shard_info(3)
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "Shard %d/%d - %d features selected"
            assert call_args[0][1:] == (2, 3, 3)

    def test_log_shard_info_noop_when_no_shard(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.shard_index = None
        mock_config.total_shards = None
        runner = ParallelRunner(mock_config)
        with patch("behave_pool.runner.logger") as mock_logger:
            runner._log_shard_info(5)
            mock_logger.info.assert_not_called()

    def test_run_parallel_applies_shard(self, mock_config: MagicMock) -> None:
        from behave_pool.runner import ParallelRunner

        mock_config.jobs = 2
        mock_config.parallel = 2
        mock_config.shard_index = 1
        mock_config.total_shards = 3
        runner = ParallelRunner(mock_config)

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(id=f"feature:{c}.feature", config=snap, feature_path=f"{c}.feature")
            for c in "abc"
        ]

        with (
            patch.object(runner, "_plan", return_value=units),
            patch.object(runner, "_is_sharding_active", return_value=True),
            patch.object(runner, "_apply_shard", return_value=units[:1]) as mock_shard,
            patch.object(runner, "_split_by_serial_tag", return_value=(units[:1], [])),
            patch.object(runner, "_dispatch", return_value=units[:1]),
            patch.object(runner, "_collect", return_value=False),
        ):
            runner._run_parallel()
            mock_shard.assert_called_once_with(units)


# ── Config integration ──────────────────────────────────────────────


class TestConfigShardIntegration:
    def test_add_parallel_options_parses_shard_string(self) -> None:
        from behave_pool.config import add_parallel_options

        config = MagicMock()
        config.jobs = 1
        config.shard = "2/3"
        del config.parallel_scheme
        del config.parallel_balance
        del config.parallel_timing_file
        del config.parallel_report
        del config.use_nested_step_modules
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.shard_index == 2
        assert config.total_shards == 3

    def test_add_parallel_options_no_shard_sets_none(self) -> None:
        from behave_pool.config import add_parallel_options

        config = MagicMock()
        config.jobs = 1
        config.shard = None
        del config.parallel_scheme
        del config.parallel_balance
        del config.parallel_timing_file
        del config.parallel_report
        del config.use_nested_step_modules
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.shard_index is None
        assert config.total_shards is None

    def test_add_parallel_options_invalid_shard_raises(self) -> None:
        from behave_pool.config import add_parallel_options

        config = MagicMock()
        config.jobs = 1
        config.shard = "invalid"
        del config.parallel_scheme
        del config.parallel_balance
        del config.parallel_timing_file
        del config.parallel_report
        del config.use_nested_step_modules
        del config.shard_index
        del config.total_shards
        with pytest.raises(ShardError):
            add_parallel_options(config)

    def test_snapshot_config_includes_shard_fields(self) -> None:
        from behave_pool.config import snapshot_config

        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = "en"
        config.stop = False
        config.paths = []
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".timing.json"
        config.parallel_report = "report.json"
        config.shard_index = 2
        config.total_shards = 5
        config.dry_run = False
        config.use_nested_step_modules = False

        snap = snapshot_config(config)
        assert snap.shard_index == 2
        assert snap.total_shards == 5

    def test_snapshot_config_shard_defaults_to_none(self) -> None:
        from behave_pool.config import snapshot_config

        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = "en"
        config.stop = False
        config.paths = []
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".timing.json"
        config.parallel_report = "report.json"
        config.shard_index = None
        config.total_shards = None
        config.dry_run = False
        config.use_nested_step_modules = False

        snap = snapshot_config(config)
        assert snap.shard_index is None
        assert snap.total_shards is None


# ── Import test ──────────────────────────────────────────────────────


class TestImports:
    def test_shard_config_importable_from_package(self) -> None:
        from behave_pool import ShardConfig as ImportedShardConfig

        assert ImportedShardConfig is ShardConfig

    def test_run_with_shard_importable_from_package(self) -> None:
        from behave_pool import run_with_shard as imported_run

        assert callable(imported_run)

    def test_shard_error_importable(self) -> None:
        from behave_pool.shard import ShardError as ImportedError

        assert ImportedError is ShardError


# ── Regression tests ─────────────────────────────────────────────────


class TestShardErrorIsConfigError:
    """Regression: ShardError must be caught by behave's main() as a ConfigError."""

    def test_shard_error_is_config_error(self) -> None:
        from behave.exception import ConfigError

        assert issubclass(ShardError, ConfigError)

    def test_shard_error_is_value_error(self) -> None:
        assert issubclass(ShardError, ValueError)

    def test_shard_error_instance_is_config_error(self) -> None:
        from behave.exception import ConfigError

        err = ShardError("test")
        assert isinstance(err, ConfigError)
        assert isinstance(err, ValueError)


class TestShardConfigValidation:
    """Regression: ShardConfig must validate on construction."""

    def test_invalid_index_exceeds_total_raises_on_construction(self) -> None:
        with pytest.raises(ShardError, match="shard_index .* must be <= total_shards"):
            ShardConfig(shard_index=5, total_shards=3)

    def test_zero_index_raises_on_construction(self) -> None:
        with pytest.raises(ShardError, match="shard_index must be >= 1"):
            ShardConfig(shard_index=0, total_shards=3)

    def test_zero_total_raises_on_construction(self) -> None:
        with pytest.raises(ShardError, match="total_shards must be >= 1"):
            ShardConfig(shard_index=1, total_shards=0)

    def test_negative_values_raise_on_construction(self) -> None:
        with pytest.raises(ShardError):
            ShardConfig(shard_index=-1, total_shards=3)
        with pytest.raises(ShardError):
            ShardConfig(shard_index=1, total_shards=-1)


class TestRunWithShardConfig:
    """Regression: run_with_shard must not parse sys.argv or load config files."""

    def test_run_with_shard_uses_load_config_false(self) -> None:
        """run_with_shard should pass load_config=False to Configuration."""
        from unittest.mock import MagicMock, patch

        from behave_pool.shard import run_with_shard

        mock_config = MagicMock()
        mock_config.shard_index = 1
        mock_config.total_shards = 1
        mock_config.features_dir = "features/"
        mock_config.parallel = 1

        with (
            patch("behave.configuration.Configuration") as mock_config_cls,
            patch("behave_pool.runner.ParallelRunner") as mock_runner_cls,
        ):
            mock_instance = MagicMock()
            mock_config_cls.return_value = mock_instance
            mock_instance.run.return_value = False

            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run.return_value = False

            run_with_shard(mock_config)

            # Verify Configuration was called with load_config=False
            _, kwargs = mock_config_cls.call_args
            assert kwargs.get("load_config") is False

    def test_run_with_shard_does_not_use_sys_argv(self) -> None:
        """run_with_shard should pass command_args=[] not None to avoid sys.argv parsing."""
        from unittest.mock import MagicMock, patch

        from behave_pool.shard import run_with_shard

        mock_config = MagicMock()
        mock_config.shard_index = 1
        mock_config.total_shards = 1
        mock_config.features_dir = "features/"
        mock_config.parallel = 1

        with (
            patch("behave.configuration.Configuration") as mock_config_cls,
            patch("behave_pool.runner.ParallelRunner") as mock_runner_cls,
        ):
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run.return_value = False

            run_with_shard(mock_config)

            # Verify command_args was explicitly passed (not None)
            args, kwargs = mock_config_cls.call_args
            # command_args should be a list, not None
            if "command_args" in kwargs:
                assert kwargs["command_args"] is not None
            else:
                # First positional arg is command_args
                assert args[0] is not None


class TestShardSortingConsistency:
    """Regression: sequential and parallel shard sorting must use the same key.

    Sequential mode sorts features by ``filename``.
    Parallel mode sorts work units by ``id`` which is ``feature:{filename}``.
    Both must produce the same feature ordering so that the same shard index
    selects the same features regardless of ``--parallel`` value.
    """

    def test_sequential_and_parallel_select_same_features(self) -> None:
        from behave_pool.runner import ParallelRunner

        config = MagicMock()
        config.jobs = 1
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.base_dir = "features"
        config.environment_file = "environment.py"
        config.steps_dir = "steps"
        config.stop = False
        config.reporters = []
        config.lang = "en"
        config.outputs = []
        config.paths = ["features"]
        config.verbose = False
        config.dry_run = False
        config.use_nested_step_modules = False
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".behave-pool-timing.json"
        config.parallel_report = "behave-pool-report.json"
        config.shard = None
        config.shard_index = None
        config.total_shards = None
        config.exclude = MagicMock(return_value=False)

        # Features where name and filename orderings differ
        f1 = _make_feature("z.feature", name="Alpha")
        f2 = _make_feature("a.feature", name="Zeta")
        f3 = _make_feature("m.feature", name="Mid")
        features = [f1, f2, f3]

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="environment.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(
                id=f"feature:{f.filename}",
                config=snap,
                feature_path=f.filename,
            )
            for f in features
        ]

        runner = ParallelRunner(config)

        # Test for each shard
        for shard_index in range(1, 4):
            config.shard_index = shard_index
            config.total_shards = 3

            # Sequential path
            seq_selected = runner._filter_features_by_shard(features)
            seq_filenames = {f.filename for f in seq_selected}

            # Parallel path
            par_selected = select_shard_work_units(units, shard_index, 3)
            par_filenames = {u.feature_path for u in par_selected}

            assert seq_filenames == par_filenames, (
                f"Shard {shard_index}/3: sequential selected {seq_filenames}, "
                f"parallel selected {par_filenames}"
            )
