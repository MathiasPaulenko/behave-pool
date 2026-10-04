"""Unit tests for config.add_parallel_options and snapshot_config."""

from __future__ import annotations

from unittest.mock import MagicMock

from behave_pool.config import ConfigSnapshot, add_parallel_options, snapshot_config


class TestAddParallelOptions:
    def test_sets_defaults_on_plain_config(self) -> None:
        config = MagicMock()
        config.jobs = 1
        config.shard = None
        del config.parallel_scheme
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.parallel == 1
        assert config.parallel_scheme == "feature"

    def test_preserves_existing_jobs(self) -> None:
        config = MagicMock()
        config.jobs = 4
        config.shard = None
        config.parallel_scheme = "scenario"
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.parallel == 4
        assert config.parallel_scheme == "scenario"

    def test_sets_parallel_scheme_default_when_only_jobs_set(self) -> None:
        config = MagicMock()
        config.jobs = 2
        config.shard = None
        del config.parallel_scheme
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.parallel == 2
        assert config.parallel_scheme == "feature"

    def test_jobs_none_defaults_to_1(self) -> None:
        config = MagicMock()
        config.jobs = None
        config.shard = None
        del config.parallel_scheme
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.parallel == 1

    def test_sets_parallel_balance_default(self) -> None:
        config = MagicMock()
        config.jobs = 1
        config.shard = None
        del config.parallel_scheme
        del config.parallel_balance
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.parallel_balance == "lpt"

    def test_preserves_existing_parallel_balance(self) -> None:
        config = MagicMock()
        config.jobs = 1
        config.shard = None
        config.parallel_scheme = "feature"
        config.parallel_balance = "fifo"
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.parallel_balance == "fifo"

    def test_sets_parallel_timing_file_default(self) -> None:
        config = MagicMock()
        config.jobs = 1
        config.shard = None
        del config.parallel_scheme
        del config.parallel_timing_file
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.parallel_timing_file == ".behave-pool-timing.json"

    def test_preserves_existing_parallel_timing_file(self) -> None:
        config = MagicMock()
        config.jobs = 1
        config.shard = None
        config.parallel_scheme = "feature"
        config.parallel_timing_file = "custom.json"
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.parallel_timing_file == "custom.json"

    def test_sets_use_nested_step_modules_default(self) -> None:
        config = MagicMock()
        config.jobs = 1
        config.shard = None
        del config.parallel_scheme
        del config.use_nested_step_modules
        del config.shard_index
        del config.total_shards
        add_parallel_options(config)
        assert config.use_nested_step_modules is False


class TestSnapshotConfig:
    def test_snapshot_captures_essential_fields(self) -> None:
        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = "en"
        config.stop = False
        config.paths = ["features/login.feature"]
        config.parallel = 4
        config.parallel_scheme = "feature"
        config.parallel_balance = "fifo"
        config.parallel_timing_file = "custom.json"
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert snap.base_dir == "features"
        assert snap.steps_dir == "steps"
        assert snap.environment_file == "environment.py"
        assert snap.lang == "en"
        assert snap.stop is False
        assert snap.paths == ["features/login.feature"]
        assert snap.parallel == 4
        assert snap.parallel_scheme == "feature"
        assert snap.parallel_balance == "fifo"
        assert snap.parallel_timing_file == "custom.json"

    def test_snapshot_is_picklable(self) -> None:
        import pickle

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="environment.py",
            lang="en",
            stop=False,
        )
        data = pickle.dumps(snap)
        restored = pickle.loads(data)
        assert restored.base_dir == "features"
        assert restored.steps_dir == "steps"


class TestSnapshotConfigNoneBaseDir:
    """Regression test for snapshot_config handling None base_dir."""

    def test_snapshot_config_defaults_when_base_dir_is_none(self) -> None:
        """When config.base_dir is None, snapshot_config must default to
        'features' instead of propagating None into the ConfigSnapshot.
        """
        from unittest.mock import MagicMock

        config = MagicMock()
        config.base_dir = None
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = "en"
        config.stop = False
        config.paths = []
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".behave-pool-timing.json"
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert snap.base_dir == "features"


class TestSnapshotConfigLangNone:
    """Regression test for ConfigSnapshot.lang accepting None.

    Behave's Configuration.lang defaults to None, so ConfigSnapshot.lang
    must accept None as a valid value (type annotation: str | None).
    """

    def test_snapshot_config_lang_none(self) -> None:
        """snapshot_config must not fail when config.lang is None."""
        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = None
        config.stop = False
        config.paths = []
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".behave-pool-timing.json"
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert snap.lang is None


class TestSnapshotConfigPathObjects:
    """Regression test for snapshot_config converting Path objects to strings.

    config.paths may contain pathlib.Path objects. ConfigSnapshot.paths is
    typed as list[str], so snapshot_config must convert them to strings.
    """

    def test_paths_with_path_objects_are_converted_to_strings(self) -> None:
        from pathlib import Path

        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = None
        config.stop = False
        config.paths = [Path("/tmp/features/foo.feature"), Path("bar.feature")]
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".behave-pool-timing.json"
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert all(isinstance(p, str) for p in snap.paths)
        assert snap.paths == [str(Path("/tmp/features/foo.feature")), str(Path("bar.feature"))]


class TestSnapshotConfigBaseDirPath:
    """Regression test for snapshot_config converting Path base_dir to str.

    config.base_dir may be a pathlib.Path. ConfigSnapshot.base_dir is typed
    as str, so snapshot_config must convert it.
    """

    def test_base_dir_path_converted_to_str(self) -> None:
        from pathlib import Path

        config = MagicMock()
        config.base_dir = Path("/tmp/features")
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = None
        config.stop = False
        config.paths = []
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".behave-pool-timing.json"
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert isinstance(snap.base_dir, str)
        assert snap.base_dir == str(Path("/tmp/features"))


class TestSnapshotConfigPathFields:
    """Regression test for snapshot_config converting Path objects in all
    string-typed fields.

    config.steps_dir, config.environment_file, and config.parallel_timing_file
    may be pathlib.Path objects. ConfigSnapshot types them as str, so
    snapshot_config must convert them.
    """

    def test_all_path_fields_converted_to_str(self) -> None:
        from pathlib import Path

        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = Path("steps")
        config.environment_file = Path("environment.py")
        config.lang = None
        config.stop = False
        config.paths = []
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = Path(".timing.json")
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert isinstance(snap.steps_dir, str)
        assert snap.steps_dir == "steps"
        assert isinstance(snap.environment_file, str)
        assert snap.environment_file == "environment.py"
        assert isinstance(snap.parallel_timing_file, str)
        assert snap.parallel_timing_file == ".timing.json"

    def test_none_fields_get_defaults(self) -> None:
        """When config.steps_dir, config.environment_file, or
        config.parallel_timing_file is None, snapshot_config must use
        sensible defaults instead of producing the string 'None'.
        """
        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = None
        config.environment_file = None
        config.lang = None
        config.stop = False
        config.paths = []
        config.parallel = 1
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = None
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert snap.steps_dir == "steps"
        assert snap.environment_file == "environment.py"
        assert snap.parallel_timing_file == ".behave-pool-timing.json"

    def test_parallel_none_falls_back_to_jobs(self) -> None:
        """When config.parallel is None, snapshot_config must fall back
        to config.jobs, then to 1.
        """
        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = None
        config.stop = False
        config.paths = []
        config.parallel = None
        config.jobs = 4
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".timing.json"
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert snap.parallel == 4

    def test_parallel_and_jobs_none_defaults_to_1(self) -> None:
        """When both config.parallel and config.jobs are None,
        snapshot_config must default to 1.
        """
        config = MagicMock()
        config.base_dir = "features"
        config.steps_dir = "steps"
        config.environment_file = "environment.py"
        config.lang = None
        config.stop = False
        config.paths = []
        config.parallel = None
        config.jobs = None
        config.parallel_scheme = "feature"
        config.parallel_balance = "lpt"
        config.parallel_timing_file = ".timing.json"
        config.dry_run = False
        config.use_nested_step_modules = False
        config.shard_index = None
        config.total_shards = None

        snap = snapshot_config(config)
        assert snap.parallel == 1


class TestUserdataFallback:
    """pool.* userdata keys provide options when using plain behave."""

    def _bare_config(self, userdata: dict | None = None) -> MagicMock:
        config = MagicMock()
        config.jobs = 1
        config.shard = None
        config.userdata = userdata or {}
        for attr in (
            "parallel_scheme",
            "parallel_balance",
            "parallel_timing_file",
            "parallel_report",
            "shard_index",
            "total_shards",
            "use_nested_step_modules",
        ):
            delattr(config, attr)
        return config

    def test_userdata_balance_applied(self) -> None:
        config = self._bare_config({"pool.balance": "fifo"})
        add_parallel_options(config)
        assert config.parallel_balance == "fifo"

    def test_userdata_jobs_applied(self) -> None:
        config = self._bare_config({"pool.jobs": "4"})
        add_parallel_options(config)
        assert config.parallel == 4

    def test_userdata_shard_applied(self) -> None:
        config = self._bare_config({"pool.shard": "2/3"})
        add_parallel_options(config)
        assert config.shard_index == 2
        assert config.total_shards == 3

    def test_explicit_nondefault_wins_over_userdata(self) -> None:
        config = self._bare_config({"pool.balance": "lpt"})
        config.parallel_balance = "fifo"
        add_parallel_options(config)
        assert config.parallel_balance == "fifo"

    def test_non_string_userdata_ignored(self) -> None:
        config = self._bare_config({"pool.balance": MagicMock()})
        add_parallel_options(config)
        assert config.parallel_balance == "lpt"
