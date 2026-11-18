"""Tests for WorkerRunner."""

from __future__ import annotations

import queue
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from behave_pool.result import WorkerResult
from behave_pool.work_unit import WorkUnit
from behave_pool.worker import WorkerRunner


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock()
    config.base_dir = "features"
    config.environment_file = "environment.py"
    config.steps_dir = "steps"
    config.stop = False
    config.reporters = []
    config.use_nested_step_modules = False
    config.lang = "en"
    return config


@pytest.fixture
def mock_stop_event() -> MagicMock:
    event = MagicMock()
    event.is_set.return_value = False
    return event


@pytest.fixture
def mock_result_queue() -> MagicMock:
    return MagicMock()


@pytest.fixture
def worker_runner(
    mock_config: MagicMock,
    mock_result_queue: MagicMock,
    mock_stop_event: MagicMock,
) -> WorkerRunner:
    return WorkerRunner(
        config=mock_config,
        worker_id=0,
        result_queue=mock_result_queue,
        stop_event=mock_stop_event,
    )


@pytest.fixture
def sample_work_unit(mock_config: MagicMock) -> WorkUnit:
    return WorkUnit(
        id="feature:login.feature",
        config=mock_config,
        feature_path="features/login.feature",
        scenario_line=None,
        tags=["@smoke"],
    )


class TestWorkerRunnerInit:
    def test_attributes(
        self,
        mock_config: MagicMock,
        mock_result_queue: MagicMock,
        mock_stop_event: MagicMock,
    ) -> None:
        runner = WorkerRunner(mock_config, 0, mock_result_queue, mock_stop_event)
        assert runner.worker_id == 0
        assert runner.result_queue is mock_result_queue
        assert runner.stop_event is mock_stop_event
        assert runner._last_result is None
        assert runner._setup_done is False

    def test_base_dir_from_config(
        self,
        mock_config: MagicMock,
        mock_result_queue: MagicMock,
        mock_stop_event: MagicMock,
    ) -> None:
        runner = WorkerRunner(mock_config, 0, mock_result_queue, mock_stop_event)
        assert runner.base_dir == "features"

    def test_base_dir_default(
        self,
        mock_result_queue: MagicMock,
        mock_stop_event: MagicMock,
    ) -> None:
        config = MagicMock()
        del config.base_dir
        runner = WorkerRunner(config, 0, mock_result_queue, mock_stop_event)
        assert runner.base_dir == "features"


class TestSetup:
    @patch.object(WorkerRunner, "load_hooks")
    @patch.object(WorkerRunner, "load_step_definitions")
    @patch("behave_pool.worker.Context")
    def test_setup_loads_hooks_and_steps(
        self,
        mock_context_cls: MagicMock,
        mock_load_steps: MagicMock,
        mock_load_hooks: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.setup()
        mock_load_hooks.assert_called_once()
        mock_load_steps.assert_called_once()

    @patch("behave_pool.worker.load_step_modules")
    @patch("behave_pool.worker.os.path.join", return_value="features/steps")
    @patch("behave_pool.worker.os.path.exists", return_value=True)
    def test_load_step_definitions_sets_step_registry(
        self,
        mock_exists: MagicMock,
        mock_join: MagicMock,
        mock_load: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        """load_step_definitions must set self.step_registry from the global registry."""
        assert worker_runner.step_registry is None
        worker_runner.load_step_definitions()
        assert worker_runner.step_registry is not None

    @patch.object(WorkerRunner, "load_hooks")
    @patch.object(WorkerRunner, "load_step_definitions")
    @patch("behave_pool.worker.Context")
    def test_setup_creates_context(
        self,
        mock_context_cls: MagicMock,
        mock_load_steps: MagicMock,
        mock_load_hooks: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.setup()
        mock_context_cls.assert_called_once_with(worker_runner)
        assert worker_runner._setup_done is True

    @patch.object(WorkerRunner, "run_hook")
    @patch.object(WorkerRunner, "load_hooks")
    @patch.object(WorkerRunner, "load_step_definitions")
    @patch("behave_pool.worker.Context")
    def test_setup_runs_before_all(
        self,
        mock_context_cls: MagicMock,
        mock_load_steps: MagicMock,
        mock_load_hooks: MagicMock,
        mock_run_hook: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.setup()
        mock_run_hook.assert_called_once_with("before_all")


class TestRunWorkUnit:
    @patch("behave_pool.worker.parse_features", return_value=[])
    @patch.object(WorkerRunner, "_run_features", return_value=False)
    @patch.object(WorkerRunner, "_write_report", return_value="tmp/report.json")
    def test_successful_run(
        self,
        mock_write: MagicMock,
        mock_run: MagicMock,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        worker_runner._undefined_steps = []
        result = worker_runner.run_work_unit(sample_work_unit)
        assert isinstance(result, WorkerResult)
        assert result.worker_id == 0
        assert result.work_unit_id == "feature:login.feature"
        assert result.failed is False
        assert result.duration >= 0
        assert result.report_path == "tmp/report.json"
        assert result.undefined_steps == []
        assert result.error is None

    @patch("behave_pool.worker.parse_features", return_value=[])
    @patch.object(WorkerRunner, "_run_features", return_value=True)
    @patch.object(WorkerRunner, "_write_report", return_value="tmp/report.json")
    def test_failed_run(
        self,
        mock_write: MagicMock,
        mock_run: MagicMock,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        worker_runner._undefined_steps = []
        result = worker_runner.run_work_unit(sample_work_unit)
        assert result.failed is True

    @patch("behave_pool.worker.parse_features", return_value=[])
    @patch.object(WorkerRunner, "_run_features", side_effect=RuntimeError("Boom!"))
    def test_exception_returns_failed_result(
        self,
        mock_run: MagicMock,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        result = worker_runner.run_work_unit(sample_work_unit)
        assert result.failed is True
        assert "Boom!" in (result.error or "")
        assert result.duration >= 0

    @patch(
        "behave_pool.worker.parse_features",
        side_effect=FileNotFoundError("missing.feature"),
    )
    def test_parse_features_exception_returns_failed_result(
        self,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """When parse_features raises, run_work_unit must return a failed
        WorkerResult with the error message instead of propagating."""
        result = worker_runner.run_work_unit(sample_work_unit)
        assert result.failed is True
        assert "missing.feature" in (result.error or "")
        assert result.duration >= 0

    @patch("behave_pool.worker.parse_features", return_value=[])
    @patch.object(WorkerRunner, "_run_features", return_value=False)
    @patch.object(WorkerRunner, "_write_report", return_value="tmp/report.json")
    def test_collect_result(
        self,
        mock_write: MagicMock,
        mock_run: MagicMock,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        worker_runner._undefined_steps = []
        assert worker_runner.collect_result() is None
        worker_runner.run_work_unit(sample_work_unit)
        result = worker_runner.collect_result()
        assert result is not None
        assert result.work_unit_id == "feature:login.feature"

    @patch("behave_pool.worker.parse_features", return_value=[])
    @patch.object(WorkerRunner, "_run_features", return_value=False)
    @patch.object(WorkerRunner, "_write_report", return_value=None)
    def test_run_work_unit_parses_feature_file(
        self,
        mock_write: MagicMock,
        mock_run: MagicMock,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """run_work_unit must parse the feature file from WorkUnit.feature_path."""
        worker_runner._undefined_steps = []
        worker_runner.run_work_unit(sample_work_unit)
        mock_parse.assert_called_once()
        called_paths = mock_parse.call_args[0][0]
        assert called_paths == ["features/login.feature"]


class TestTeardown:
    @patch.object(WorkerRunner, "run_hook")
    def test_teardown_runs_after_all(
        self,
        mock_run_hook: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        formatter = MagicMock()
        worker_runner.formatters = [formatter]
        worker_runner._setup_done = True
        worker_runner.teardown()
        mock_run_hook.assert_called_once_with("after_all")
        formatter.close.assert_called_once()

    @patch.object(WorkerRunner, "run_hook")
    def test_teardown_closes_all_formatters(
        self,
        mock_run_hook: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        f1, f2 = MagicMock(), MagicMock()
        worker_runner.formatters = [f1, f2]
        worker_runner._setup_done = True
        worker_runner.teardown()
        f1.close.assert_called_once()
        f2.close.assert_called_once()

    @patch.object(WorkerRunner, "run_hook")
    def test_teardown_safe_when_setup_incomplete(
        self,
        mock_run_hook: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        """teardown should not run after_all hooks if setup didn't complete."""
        worker_runner._setup_done = False
        worker_runner.formatters = []
        worker_runner.teardown()
        mock_run_hook.assert_not_called()


def _make_mock_feature(
    name: str = "Login",
    filename: str = "login.feature",
    status: str = "passed",
    scenarios: list | None = None,
) -> MagicMock:
    """Create a MagicMock feature with JSON-serializable attributes."""
    feature = MagicMock()
    feature.name = name
    feature.filename = filename
    feature.status = status
    feature.keyword = "Feature"
    feature.description = ""
    feature.line = 1
    feature.tags = []
    feature.duration = 0.5
    feature.background = None
    feature.scenarios = scenarios or []
    return feature


def _make_mock_scenario(
    name: str = "Scenario 1",
    status: str = "passed",
    steps: list | None = None,
) -> MagicMock:
    """Create a MagicMock scenario with JSON-serializable attributes."""
    scenario = MagicMock()
    scenario.name = name
    scenario.status = status
    scenario.type = "scenario"
    scenario.description = ""
    scenario.line = 3
    scenario.filename = "features/login.feature"
    scenario.tags = []
    scenario.duration = 0.3
    scenario.all_steps = steps or []
    scenario.steps = steps or []
    return scenario


def _make_mock_step(
    name: str = "Given I am logged in",
    status: str = "passed",
) -> MagicMock:
    """Create a MagicMock step with JSON-serializable attributes."""
    step = MagicMock()
    step.name = name
    step.status = status
    step.keyword = "Given "
    step.duration = 0.1
    step.line = 4
    step.filename = "features/login.feature"
    step.error = None
    step.error_message = None
    return step


class TestWriteReport:
    def test_writes_json_report(
        self,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
        tmp_path: Path,
    ) -> None:
        feature = _make_mock_feature(name="Login", filename="login.feature")
        worker_runner.features = [feature]

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text") as mock_write:
            result = worker_runner._write_report(sample_work_unit)
            assert result is not None
            assert "worker_0" in result
            mock_write.assert_called_once()

    def test_returns_none_on_oserror(
        self,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        feature = _make_mock_feature(name="Login", filename="login.feature")
        worker_runner.features = [feature]

        with (
            patch.object(Path, "mkdir"),
            patch.object(Path, "write_text", side_effect=OSError("disk full")),
        ):
            result = worker_runner._write_report(sample_work_unit)
            assert result is None

    def test_returns_none_on_mkdir_oserror(
        self,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """mkdir OSError should not propagate; report writing is best-effort."""
        feature = _make_mock_feature(name="Login", filename="login.feature")
        worker_runner.features = [feature]

        with (
            patch.object(Path, "mkdir", side_effect=PermissionError("no access")),
            patch.object(Path, "write_text"),
        ):
            result = worker_runner._write_report(sample_work_unit)
            assert result is None

    def test_returns_none_on_type_error(
        self,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """Non-OSError exceptions (e.g., TypeError from json.dumps) should not
        propagate and cause the work unit to be incorrectly marked as failed.
        Report writing is best-effort.
        """
        feature = _make_mock_feature(name="Bad", filename="bad.feature", status="passed")
        worker_runner.features = [feature]

        with (
            patch.object(Path, "mkdir"),
            patch("behave_pool.worker.json.dumps", side_effect=TypeError("not serializable")),
        ):
            result = worker_runner._write_report(sample_work_unit)
            assert result is None

    def test_report_reflects_failed_status(
        self,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """Report should contain 'failed' status when a feature has failed."""
        feature = _make_mock_feature(name="Broken", filename="broken.feature", status="failed")
        worker_runner.features = [feature]

        import json as json_module

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text") as mock_write:
            worker_runner._write_report(sample_work_unit)
            written = mock_write.call_args[0][0]
            data = json_module.loads(written)
            assert data["failed"] is True
            assert data["features"][0]["status"] == "failed"

    def test_report_reflects_passed_status(
        self,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """Report should contain 'passed' status when all features pass."""
        feature = _make_mock_feature(name="OK", filename="ok.feature", status="passed")
        worker_runner.features = [feature]

        import json as json_module

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text") as mock_write:
            worker_runner._write_report(sample_work_unit)
            written = mock_write.call_args[0][0]
            data = json_module.loads(written)
            assert data["failed"] is False
            assert data["features"][0]["status"] == "passed"


class TestLoadHooks:
    @patch("behave_pool.worker.os.path.exists", return_value=False)
    def test_load_hooks_no_environment_file(
        self,
        mock_exists: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.hooks = {}
        worker_runner.load_hooks()
        assert "before_all" in worker_runner.hooks

    @patch("behave_pool.worker.exec_file")
    @patch("behave_pool.worker.os.path.exists", return_value=True)
    def test_load_hooks_with_environment_file(
        self,
        mock_exists: MagicMock,
        mock_exec: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.hooks = {"before_all": MagicMock()}
        worker_runner.load_hooks()
        mock_exec.assert_called_once()


class TestLoadStepDefinitions:
    @patch("behave_pool.worker.load_step_modules")
    def test_load_step_definitions(
        self,
        mock_load: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.load_step_definitions()
        mock_load.assert_called_once()

    @patch("behave_pool.worker.load_step_modules")
    def test_load_step_definitions_with_extra_paths(
        self,
        mock_load: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.load_step_definitions(extra_step_paths=["extra/steps"])
        call_args = mock_load.call_args[0][0]
        assert "extra/steps" in call_args


class TestRunFeatures:
    def test_run_features_success(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.context = MagicMock()
        worker_runner.context.aborted = False
        feature = MagicMock()
        feature.run.return_value = False
        feature.filename = "login.feature"
        worker_runner.features = [feature]
        worker_runner.formatters = []
        result = worker_runner._run_features()
        assert result is False
        feature.run.assert_called_once_with(worker_runner)

    def test_run_features_failure(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.context = MagicMock()
        worker_runner.context.aborted = False
        feature = MagicMock()
        feature.run.return_value = True
        feature.filename = "login.feature"
        worker_runner.features = [feature]
        worker_runner.formatters = []
        result = worker_runner._run_features()
        assert result is True

    def test_run_features_stop_on_failure(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        worker_runner.context = MagicMock()
        worker_runner.context.aborted = False
        f1 = MagicMock()
        f1.run.return_value = True
        f1.filename = "f1.feature"
        f2 = MagicMock()
        f2.run.return_value = False
        f2.filename = "f2.feature"
        worker_runner.features = [f1, f2]
        worker_runner.formatters = []
        worker_runner.config.stop = True
        result = worker_runner._run_features()
        assert result is True
        f1.run.assert_called_once()
        f2.run.assert_not_called()


class TestRunFeaturesAborted:
    """Regression tests for _run_features returning True when aborted."""

    def test_run_features_returns_true_when_aborted(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        """_run_features must return True (failed) when self.aborted is True,
        even if no features actually ran."""
        worker_runner.context = MagicMock()
        worker_runner.context.aborted = True
        feature = MagicMock()
        feature.run.return_value = False
        feature.filename = "login.feature"
        worker_runner.features = [feature]
        worker_runner.formatters = []
        result = worker_runner._run_features()
        assert result is True
        feature.run.assert_not_called()

    def test_run_features_returns_true_when_aborted_mid_run(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        """If aborted during feature execution, _run_features must return True."""
        worker_runner.context = MagicMock()
        worker_runner.context.aborted = False

        f1 = MagicMock()
        f1.run.return_value = False
        f1.filename = "f1.feature"

        f2 = MagicMock()
        f2.run.side_effect = lambda runner: setattr(runner.context, "aborted", True) or False
        f2.filename = "f2.feature"

        worker_runner.features = [f1, f2]
        worker_runner.formatters = []
        result = worker_runner._run_features()
        assert result is True


class TestUndefinedStepsReset:
    """Regression tests for undefined_steps being cleared between work units."""

    @patch("behave_pool.worker.parse_features", return_value=[])
    @patch.object(WorkerRunner, "_run_features", return_value=False)
    @patch.object(WorkerRunner, "_write_report", return_value="tmp/report.json")
    def test_undefined_steps_cleared_before_each_work_unit(
        self,
        mock_write: MagicMock,
        mock_run: MagicMock,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """undefined_steps must be cleared before each work unit execution."""
        worker_runner._undefined_steps = ["stale_undefined_step"]
        worker_runner.run_work_unit(sample_work_unit)
        result = worker_runner.collect_result()
        assert result is not None
        assert "stale_undefined_step" not in result.undefined_steps
        assert result.undefined_steps == []

    @patch("behave_pool.worker.parse_features", return_value=[])
    @patch.object(WorkerRunner, "_run_features", return_value=False)
    @patch.object(WorkerRunner, "_write_report", return_value="tmp/report.json")
    def test_hook_failures_reset_before_each_work_unit(
        self,
        mock_write: MagicMock,
        mock_run: MagicMock,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """hook_failures must be reset to 0 before each work unit execution."""
        worker_runner.hook_failures = 5
        worker_runner._undefined_steps = []
        worker_runner.run_work_unit(sample_work_unit)
        assert worker_runner.hook_failures == 0


class TestAbortedReset:
    """Regression tests for self.aborted being reset between work units."""

    @patch("behave_pool.worker.parse_features", return_value=[])
    @patch.object(WorkerRunner, "_run_features", return_value=False)
    @patch.object(WorkerRunner, "_write_report", return_value="tmp/report.json")
    def test_aborted_reset_before_each_work_unit(
        self,
        mock_write: MagicMock,
        mock_run: MagicMock,
        mock_parse: MagicMock,
        worker_runner: WorkerRunner,
        sample_work_unit: WorkUnit,
    ) -> None:
        """aborted must be reset to False before each work unit execution.

        Without this reset, a KeyboardInterrupt or other abort in one work
        unit causes all subsequent work units in the same worker process to
        silently skip all features (because _run_features checks
        ``run_feature = not self.aborted``).
        """

        class FakeContext:
            def __init__(self) -> None:
                self.aborted = False

            def _set_root_attribute(self, name: str, value: object) -> None:
                setattr(self, name, value)

        worker_runner._undefined_steps = []
        worker_runner.context = FakeContext()
        worker_runner.aborted = True
        assert worker_runner.aborted is True
        worker_runner.run_work_unit(sample_work_unit)
        assert worker_runner.aborted is False


class TestWriteReportBackslash:
    """Regression test for safe_id handling backslashes on Windows."""

    def test_report_filename_handles_backslashes(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        """Report filename should not contain backslashes from Windows paths."""
        unit = WorkUnit(
            id="feature:features\\login.feature",
            config=MagicMock(),
            feature_path="features\\login.feature",
        )
        feature = _make_mock_feature(
            name="Login",
            filename="features\\login.feature",
            status="passed",
        )
        worker_runner.features = [feature]

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            result = worker_runner._write_report(unit)
            assert result is not None
            filename = Path(result).name
            assert "\\" not in filename
            assert filename == "worker_0_feature_features_login.feature.json"

    def test_write_report_includes_run_token(self, worker_runner: WorkerRunner) -> None:
        """Run-scoped token prefixes the tmp report file name so concurrent
        behave-pool runs cannot collide or clean each other's files."""
        from behave_pool.work_unit import WorkUnit

        worker_runner._report_token = "tok9"
        unit = WorkUnit(
            id="feature:login.feature",
            config=worker_runner.config,
            feature_path="login.feature",
        )
        worker_runner.features = [
            _make_mock_feature(name="Login", filename="login.feature", status="passed")
        ]

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            result = worker_runner._write_report(unit)
        assert result is not None
        assert Path(result).name == "worker_tok9_0_feature_login.feature.json"

    def test_write_report_anchors_tmp_to_report_parent(
        self, worker_runner: WorkerRunner, tmp_path: Path
    ) -> None:
        """tmp reports are written next to the parallel report path,
        absolute-anchored at worker init so hooks cannot break the path
        with a later chdir()."""
        from behave_pool.work_unit import WorkUnit

        worker_runner._report_dir = tmp_path / "out" / "tmp"
        unit = WorkUnit(
            id="feature:login.feature",
            config=worker_runner.config,
            feature_path="login.feature",
        )
        worker_runner.features = [
            _make_mock_feature(name="Login", filename="login.feature", status="passed")
        ]

        result = worker_runner._write_report(unit)
        assert result is not None
        assert Path(result).parent == tmp_path / "out" / "tmp"
        assert Path(result).exists()


class TestLoadStepDefinitionsNested:
    """Regression test for load_step_definitions with use_nested_step_modules."""

    @patch("behave_pool.worker.select_subdirectories", return_value=["features/steps/sub1"])
    @patch("behave_pool.worker.load_step_modules")
    def test_load_step_definitions_with_nested_modules(
        self,
        mock_load: MagicMock,
        mock_select_sub: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        """Include subdirectories when use_nested_step_modules is True."""
        worker_runner.config.use_nested_step_modules = True
        worker_runner.load_step_definitions()
        mock_select_sub.assert_called_once()
        call_args = mock_load.call_args[0][0]
        assert "features/steps/sub1" in call_args

    @patch("behave_pool.worker.select_subdirectories")
    @patch("behave_pool.worker.load_step_modules")
    def test_load_step_definitions_without_nested_modules(
        self,
        mock_load: MagicMock,
        mock_select_sub: MagicMock,
        worker_runner: WorkerRunner,
    ) -> None:
        """Do not call select_subdirectories when use_nested_step_modules is False."""
        worker_runner.config.use_nested_step_modules = False
        worker_runner.load_step_definitions()
        mock_select_sub.assert_not_called()


class TestRunFeaturesHookFailures:
    """Regression tests for _run_features checking hook_failures."""

    def test_run_features_returns_true_when_hook_failures_occurs(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        """_run_features must return True when hook_failures > 0, even if
        no feature.run() returned failed=True.

        Without this check, a failing before_scenario/after_scenario hook
        would be silently ignored and the work unit reported as passed.
        """
        worker_runner.context = MagicMock()
        worker_runner.context.aborted = False
        worker_runner.hook_failures = 1
        feature = MagicMock()
        feature.run.return_value = False
        feature.filename = "login.feature"
        worker_runner.features = [feature]
        worker_runner.formatters = []
        result = worker_runner._run_features()
        assert result is True

    def test_run_features_returns_true_when_undefined_steps_grow(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        """_run_features must return True when undefined_steps grow during
        execution, matching Behave's run_model failure conditions.
        """
        worker_runner.context = MagicMock()
        worker_runner.context.aborted = False
        worker_runner.hook_failures = 0
        worker_runner._undefined_steps = []
        feature = MagicMock()
        feature.run.side_effect = lambda runner: (
            runner._undefined_steps.append("undefined step") or False
        )
        feature.filename = "login.feature"
        worker_runner.features = [feature]
        worker_runner.formatters = []
        result = worker_runner._run_features()
        assert result is True


class TestBaseDirNoneSafety:
    """Regression test for base_dir being None in WorkerRunner.__init__."""

    def test_base_dir_defaults_when_none(self) -> None:
        """When config.base_dir is None, WorkerRunner must fall back to
        'features' instead of propagating None to os.path.join calls.
        """
        config = MagicMock()
        config.base_dir = None
        config.environment_file = "environment.py"
        config.steps_dir = "steps"
        config.stop = False
        config.reporters = []
        config.use_nested_step_modules = False
        config.lang = "en"
        result_queue = MagicMock()
        stop_event = MagicMock()
        runner = WorkerRunner(
            config=config,
            worker_id=0,
            result_queue=result_queue,
            stop_event=stop_event,
        )
        assert runner.base_dir == "features"


class TestNoneFieldSafety:
    """Regression tests for WorkerRunner handling None environment_file
    and steps_dir without raising TypeError in os.path.join.
    """

    def test_load_hooks_with_none_environment_file(self) -> None:
        """load_hooks must fall back to 'environment.py' when
        config.environment_file is None, not raise TypeError.
        """
        config = MagicMock()
        config.base_dir = "features"
        config.environment_file = None
        config.steps_dir = "steps"
        config.stop = False
        config.reporters = []
        config.use_nested_step_modules = False
        config.lang = "en"
        result_queue = MagicMock()
        stop_event = MagicMock()
        runner = WorkerRunner(
            config=config,
            worker_id=0,
            result_queue=result_queue,
            stop_event=stop_event,
        )
        runner.load_hooks()
        assert "before_all" in runner.hooks

    def test_load_step_definitions_with_none_steps_dir(self) -> None:
        """load_step_definitions must fall back to 'steps' when
        config.steps_dir is None, not raise TypeError.
        """
        config = MagicMock()
        config.base_dir = "features"
        config.environment_file = "environment.py"
        config.steps_dir = None
        config.stop = False
        config.reporters = []
        config.use_nested_step_modules = False
        config.lang = "en"
        result_queue = MagicMock()
        stop_event = MagicMock()
        runner = WorkerRunner(
            config=config,
            worker_id=0,
            result_queue=result_queue,
            stop_event=stop_event,
        )
        with (
            patch("behave_pool.worker.load_step_modules"),
            patch("behave_pool.worker.select_subdirectories", return_value=[]),
        ):
            runner.load_step_definitions()


class TestRunWorkUnitEmptyFeaturePath:
    """Regression test for run_work_unit with falsy feature_path.

    When feature_path is None or empty, run_work_unit must return a failed
    result instead of silently succeeding with no features run.
    """

    def test_run_work_unit_fails_when_feature_path_is_none(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        """run_work_unit must return failed=True when feature_path is None."""
        from behave_pool.work_unit import WorkUnit

        unit = WorkUnit(
            id="feature:None",
            config=worker_runner.config,
            feature_path=None,
        )
        result = worker_runner.run_work_unit(unit)
        assert result.failed is True
        assert result.error is not None

    def test_run_work_unit_fails_when_feature_path_is_empty(
        self,
        worker_runner: WorkerRunner,
    ) -> None:
        """run_work_unit must return failed=True when feature_path is empty string."""
        from behave_pool.work_unit import WorkUnit

        unit = WorkUnit(
            id="feature:empty",
            config=worker_runner.config,
            feature_path="",
        )
        result = worker_runner.run_work_unit(unit)
        assert result.failed is True
        assert result.error is not None


class TestSetupHookFailures:
    """Regression: run_hook() swallows exceptions — before_all failures set
    hook_failures/aborted at setup() and must not be erased by per-unit
    state resets."""

    def test_before_all_failure_marks_unit_failed(
        self, worker_runner: WorkerRunner, sample_work_unit: WorkUnit
    ) -> None:
        worker_runner._setup_hook_failed = True
        worker_runner.context = MagicMock()
        with (
            patch("behave_pool.worker.parse_features", return_value=[]),
            patch.object(worker_runner, "_run_features", return_value=False),
        ):
            result = worker_runner.run_work_unit(sample_work_unit)
        assert result.failed is True

    def test_before_all_failure_preserves_aborted(
        self, worker_runner: WorkerRunner, sample_work_unit: WorkUnit
    ) -> None:
        """aborted set by a failing before_all must NOT be reset per unit."""
        worker_runner._setup_hook_failed = True
        context = MagicMock()
        context.aborted = True
        worker_runner.context = context
        with (
            patch("behave_pool.worker.parse_features", return_value=[]),
            patch.object(worker_runner, "_run_features", return_value=True),
        ):
            worker_runner.run_work_unit(sample_work_unit)
        context._set_root_attribute.assert_not_called()

    def test_clean_setup_resets_aborted_normally(
        self, worker_runner: WorkerRunner, sample_work_unit: WorkUnit
    ) -> None:
        worker_runner.context = MagicMock()
        with (
            patch("behave_pool.worker.parse_features", return_value=[]),
            patch.object(worker_runner, "_run_features", return_value=False),
        ):
            worker_runner.run_work_unit(sample_work_unit)
        worker_runner.context._set_root_attribute.assert_called_with("aborted", False)


class TestWorkerLoopTeardownResult:
    """Regression: after_all/teardown failures were silently lost — the
    worker must emit a synthetic 'teardown' result so the run fails."""

    def _loop(self, runner: MagicMock, task_q: object, result_q: object) -> None:
        from behave_pool.config import ConfigSnapshot
        from behave_pool.worker import _worker_run_loop

        snapshot = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="environment.py",
            lang=None,
            stop=False,
        )
        with (
            patch("behave_pool.worker._make_config", return_value=MagicMock()),
            patch("behave_pool.worker.WorkerRunner", return_value=runner),
        ):
            _worker_run_loop(0, task_q, result_q, MagicMock(), snapshot)

    def test_teardown_hook_failure_emits_result(self) -> None:
        task_q: Any = queue.Queue()
        task_q.put(None)  # sentinel — worker goes straight to teardown
        result_q: Any = queue.Queue()
        runner = MagicMock()
        runner.hook_failures = 0
        runner.teardown.side_effect = lambda: setattr(runner, "hook_failures", 1)

        self._loop(runner, task_q, result_q)

        results = [result_q.get_nowait() for _ in range(result_q.qsize())]
        assert any(r.work_unit_id == "teardown" and r.failed for r in results)

    def test_teardown_exception_emits_result(self) -> None:
        task_q: Any = queue.Queue()
        task_q.put(None)
        result_q: Any = queue.Queue()
        runner = MagicMock()
        runner.hook_failures = 0
        runner.teardown.side_effect = RuntimeError("boom")

        self._loop(runner, task_q, result_q)

        results = [result_q.get_nowait() for _ in range(result_q.qsize())]
        assert any(r.work_unit_id == "teardown" and "boom" in (r.error or "") for r in results)

    def test_clean_teardown_emits_nothing(self) -> None:
        task_q: Any = queue.Queue()
        task_q.put(None)
        result_q: Any = queue.Queue()
        runner = MagicMock()
        runner.hook_failures = 0

        self._loop(runner, task_q, result_q)

        assert result_q.empty()


class TestWriteReportStatusEnum:
    """Regression: _write_report must handle behave Status enum objects, not just strings."""

    def test_failed_status_enum_detected(self, worker_runner: WorkerRunner) -> None:
        """When feature.status is a behave Status enum (not a string),
        _write_report must still detect 'failed' status correctly.
        """
        from behave_pool.work_unit import WorkUnit

        unit = WorkUnit(
            id="feature:broken.feature",
            config=worker_runner.config,
            feature_path="broken.feature",
        )

        feature = _make_mock_feature(name="Broken", filename="broken.feature")
        feature.status = type("Status", (), {"name": "failed"})()
        worker_runner.features = [feature]

        import json as json_module

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text") as mock_write:
            worker_runner._write_report(unit)
            written = mock_write.call_args[0][0]
            data = json_module.loads(written)
            assert data["failed"] is True

    def test_passed_status_enum_detected(self, worker_runner: WorkerRunner) -> None:
        """When feature.status is a behave Status enum with name='passed',
        _write_report must report failed=False.
        """
        from behave_pool.work_unit import WorkUnit

        unit = WorkUnit(
            id="feature:ok.feature",
            config=worker_runner.config,
            feature_path="ok.feature",
        )

        feature = _make_mock_feature(name="OK", filename="ok.feature")
        feature.status = type("Status", (), {"name": "passed"})()
        worker_runner.features = [feature]

        import json as json_module

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text") as mock_write:
            worker_runner._write_report(unit)
            written = mock_write.call_args[0][0]
            data = json_module.loads(written)
            assert data["failed"] is False
