"""WorkerRunner and WorkerProcess for parallel test execution."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import queue
import time
from pathlib import Path
from typing import TYPE_CHECKING

from behave.runner import (
    Context,
    ModelRunner,
    exec_file,
    load_step_modules,
    parse_features,
    select_subdirectories,
)

from behave_pool.result import WorkerResult

if TYPE_CHECKING:
    from multiprocessing import Queue as QueueType
    from typing import Any

    from behave.configuration import Configuration

    from behave_pool.config import ConfigSnapshot
    from behave_pool.work_unit import WorkUnit

logger = logging.getLogger(__name__)


class WorkerRunner(ModelRunner):  # type: ignore[misc]
    """Runner that executes work units in an isolated worker process.

    Lifecycle:
        1. setup() — once at worker start (load hooks, steps, before_all).
        2. run_work_unit(unit) — called per work unit.
        3. teardown() — once at worker end (after_all, close formatters).
    """

    def __init__(
        self,
        config: Configuration,
        worker_id: int,
        result_queue: QueueType[WorkerResult],
        stop_event: Any,
    ) -> None:
        super().__init__(config)
        self.worker_id = worker_id
        self.result_queue = result_queue
        self.stop_event = stop_event
        self._last_result: WorkerResult | None = None
        self._setup_done = False
        self.base_dir = config.base_dir if getattr(config, "base_dir", None) else "features"

    def load_hooks(self, filename: str | None = None) -> None:
        """Load environment hooks from the environment file."""
        env_filename = (
            filename or getattr(self.config, "environment_file", None) or "environment.py"
        )
        hooks_path = os.path.join(self.base_dir, env_filename)
        if os.path.exists(hooks_path):
            exec_file(hooks_path, self.hooks)

        if "before_all" not in self.hooks:
            self.hooks["before_all"] = _noop_hook

    def load_step_definitions(self, extra_step_paths: list[str] | None = None) -> None:
        """Load step definitions from the steps directory."""
        if extra_step_paths is None:
            extra_step_paths = []
        steps_dir = os.path.join(self.base_dir, getattr(self.config, "steps_dir", None) or "steps")
        step_paths = [steps_dir]
        if self.config.use_nested_step_modules:
            step_subdirectories = select_subdirectories(steps_dir)
            step_paths.extend(step_subdirectories)
        step_paths = list(step_paths) + list(extra_step_paths)
        load_step_modules(step_paths)
        from behave.step_registry import registry as global_registry

        self.step_registry = global_registry

    def setup(self) -> None:
        """Load hooks, step definitions, create Context, run before_all."""
        self.load_hooks()
        self.load_step_definitions()
        self.context = Context(self)
        self.run_hook("before_all")
        self._setup_done = True
        logger.debug("WorkerRunner %d setup complete", self.worker_id)

    def run_work_unit(self, unit: WorkUnit) -> WorkerResult:
        """Execute a single work unit and return the result.

        Args:
            unit: The WorkUnit to execute.

        Returns:
            WorkerResult with timing, failure status, and report path.
        """
        start = time.perf_counter()
        try:
            if not unit.feature_path:
                raise ValueError(f"Work unit {unit.id} has no feature_path")
            self.features = parse_features(
                [unit.feature_path],
                language=self.config.lang,
            )
            if unit.serial_mode != "all":
                from behave_pool.serial import filter_serial_scenarios

                for feature in self.features:
                    filter_serial_scenarios(feature, unit.serial_mode)
            if unit.scenario_line is not None:
                from behave_pool.serial import filter_scenario_by_line

                for feature in self.features:
                    filter_scenario_by_line(feature, unit.scenario_line)
            self.undefined_steps.clear()
            self.hook_failures = 0
            if self.context is not None:
                # aborted lives on the Context created in setup()
                self.aborted = False
            failed = self._run_features()
            duration = time.perf_counter() - start
            undefined = list(self.undefined_steps)
            report_path = self._write_report(unit)
            result = WorkerResult(
                worker_id=self.worker_id,
                work_unit_id=unit.id,
                failed=failed,
                duration=duration,
                report_path=report_path,
                undefined_steps=undefined,
            )
        except Exception as exc:
            duration = time.perf_counter() - start
            logger.exception("WorkerRunner %d error in work unit %s", self.worker_id, unit.id)
            result = WorkerResult(
                worker_id=self.worker_id,
                work_unit_id=unit.id,
                failed=True,
                duration=duration,
                error=str(exc),
            )
        self._last_result = result
        return result

    def teardown(self) -> None:
        """Run after_all hooks and close formatters.

        Safe to call even if setup() did not complete: skips hooks
        and formatters that were never initialised.
        """
        if self._setup_done:
            self.run_hook("after_all")
        for formatter in getattr(self, "formatters", []):
            formatter.close()
        logger.debug("WorkerRunner %d teardown complete", self.worker_id)

    def collect_result(self) -> WorkerResult | None:
        """Return the last WorkerResult produced, or None."""
        return self._last_result

    def _run_features(self) -> bool:
        """Run self.features without before_all/after_all hooks.

        Returns:
            True if any feature failed.
        """
        run_feature = not self.aborted
        failed_count = 0
        undefined_steps_initial_size = len(self.undefined_steps)
        for feature in self.features:
            if run_feature:
                try:
                    self.feature = feature
                    for formatter in self.formatters:
                        formatter.uri(feature.filename)
                    failed = feature.run(self)
                    if failed:
                        failed_count += 1
                        if self.config.stop or self.aborted:
                            run_feature = False
                except KeyboardInterrupt:
                    self.abort(reason="KeyboardInterrupt")
                    failed_count += 1
                    run_feature = False
            for reporter in self.config.reporters:
                reporter.feature(feature)
        return (
            failed_count > 0
            or self.aborted
            or self.hook_failures > 0
            or len(self.undefined_steps) > undefined_steps_initial_size
        )

    def _serialize_location(self, obj: Any) -> dict[str, Any] | None:
        """Extract a location dict from a Behave model object."""
        filename = getattr(obj, "filename", None)
        line = getattr(obj, "line", None)
        if filename is None and line is None:
            loc = getattr(obj, "location", None)
            if loc is not None:
                filename = getattr(loc, "filename", None) or str(loc)
                line = getattr(loc, "line", None)
        if filename is None and line is None:
            return None
        result: dict[str, Any] = {
            "filename": str(filename or ""),
            "line": int(line or 0),
        }
        return result

    def _map_status(self, raw: Any) -> str:
        """Map a Behave status to a canonical string."""
        if raw is None:
            return "untested"
        name = getattr(raw, "name", None) or str(raw)
        return name.lower().strip() or "passed"

    def _serialize_error(self, step: Any) -> dict[str, Any] | None:
        """Extract an error dict from a Behave step."""
        exc = getattr(step, "error", None) or getattr(step, "exception", None)
        if exc is not None and isinstance(exc, BaseException):
            import traceback as _tb

            return {
                "id": f"err-{id(step):x}",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": "".join(_tb.format_exception(type(exc), exc, exc.__traceback__)),
                "location": self._serialize_location(step),
            }
        error_message = getattr(step, "error_message", None)
        if error_message:
            return {
                "id": f"err-{id(step):x}",
                "type": "Error",
                "message": str(error_message),
                "traceback": str(getattr(step, "exc_traceback", None) or error_message),
                "location": self._serialize_location(step),
            }
        return None

    def _serialize_step(self, step: Any) -> dict[str, Any]:
        """Convert a Behave Step to a behave-modern-json-report step dict."""
        return {
            "id": f"step-{id(step):x}",
            "keyword": str(getattr(step, "keyword", "")),
            "text": str(getattr(step, "name", "") or ""),
            "status": self._map_status(getattr(step, "status", "passed")),
            "duration": float(getattr(step, "duration", 0.0) or 0.0),
            "location": self._serialize_location(step),
            "error": self._serialize_error(step),
            "attachments": [],
            "logs": [],
        }

    def _serialize_background(self, background: Any) -> dict[str, Any]:
        """Convert a Behave Background to a behave-modern-json-report background dict."""
        steps = [self._serialize_step(s) for s in (getattr(background, "steps", None) or [])]
        return {
            "id": f"bg-{id(background):x}",
            "name": str(getattr(background, "name", "") or ""),
            "keyword": str(getattr(background, "keyword", "Background") or "Background"),
            "location": self._serialize_location(background),
            "steps": steps,
        }

    def _serialize_scenario(self, scenario: Any, feature_id: str) -> dict[str, Any]:
        """Convert a Behave Scenario to a behave-modern-json-report scenario dict."""
        # NOTE: use scenario.steps, not all_steps — all_steps also contains
        # the background steps, which are serialized via feature.background
        # and would otherwise be counted twice.
        steps = []
        for step in getattr(scenario, "steps", None) or []:
            steps.append(self._serialize_step(step))
        scenario_type = str(getattr(scenario, "type", "") or "")
        is_outline = scenario_type in ("scenario_outline", "outline")
        return {
            "id": f"scenario-{id(scenario):x}",
            "name": str(getattr(scenario, "name", "") or "<unnamed>"),
            "featureId": feature_id,
            "description": str(getattr(scenario, "description", "") or "") or None,
            "tags": [str(t) for t in (getattr(scenario, "tags", None) or [])],
            "examples": [],
            "location": self._serialize_location(scenario),
            "status": self._map_status(getattr(scenario, "status", "passed")),
            "duration": float(getattr(scenario, "duration", 0.0) or 0.0),
            "steps": steps,
            "background": None,
            "rule": None,
            "isOutline": is_outline,
            "outlineName": None,
            "retry": None,
        }

    def _serialize_feature(self, feature: Any) -> dict[str, Any]:
        """Convert a Behave Feature to a behave-modern-json-report feature dict.

        The output matches the feature structure of behave-modern-json-report's
        ExecutionReport schema so downstream tools can consume it directly.
        """
        feature_id = f"feature-{id(feature):x}"
        # Walk run_items so ScenarioOutlines contribute their expanded
        # example scenarios (with real statuses), not the untested template
        # that appears in feature.scenarios.
        from behave.model import Rule, ScenarioOutline

        def _iter_scenarios(container: Any) -> Any:
            for item in getattr(container, "run_items", None) or []:
                if isinstance(item, Rule):
                    yield from _iter_scenarios(item)
                elif isinstance(item, ScenarioOutline):
                    yield from item.scenarios
                else:
                    yield item

        scenarios = [self._serialize_scenario(s, feature_id) for s in _iter_scenarios(feature)]
        background = None
        behave_background = getattr(feature, "background", None)
        if behave_background:
            background = self._serialize_background(behave_background)
        return {
            "id": feature_id,
            "name": str(getattr(feature, "name", "") or "<unnamed>"),
            "description": str(getattr(feature, "description", "") or "") or None,
            "tags": [str(t) for t in (getattr(feature, "tags", None) or [])],
            "filename": getattr(feature, "filename", None),
            "line": getattr(feature, "line", None),
            "status": self._map_status(getattr(feature, "status", "passed")),
            "duration": float(getattr(feature, "duration", 0.0) or 0.0),
            "scenarios": scenarios,
            "background": background,
        }

    def _write_report(self, unit: WorkUnit) -> str | None:
        """Write a JSON report for the work unit in behave-modern-json-report format.

        Each report contains a list of feature dicts matching the
        behave-modern-json-report ExecutionReport feature schema. The
        coordinator merges these into a full ExecutionReport.

        Returns:
            Path to the report file, or None if writing failed.
        """
        tmp_dir = Path("tmp")
        safe_id = unit.id.replace(":", "_").replace("/", "_").replace("\\", "_")
        report_path = tmp_dir / f"worker_{self.worker_id}_{safe_id}.json"
        try:
            tmp_dir.mkdir(exist_ok=True)
            report_data = {
                "worker_id": self.worker_id,
                "work_unit_id": unit.id,
                "features": [self._serialize_feature(f) for f in self.features],
                "failed": any(
                    self._map_status(getattr(f, "status", "passed")) == "failed"
                    for f in self.features
                ),
            }
            report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
            return str(report_path)
        except Exception:
            logger.warning("Failed to write report to %s", report_path)
            return None


def _noop_hook(context: object) -> None:
    """Default no-op hook used when before_all is not defined."""


def _make_config(snapshot: ConfigSnapshot) -> Configuration:
    """Reconstruct a behave Configuration from a picklable ConfigSnapshot."""
    from behave.configuration import Configuration

    cmd_args = list(snapshot.paths) if snapshot.paths else [snapshot.base_dir]
    config = Configuration(cmd_args, load_config=False)
    config.base_dir = snapshot.base_dir
    config.steps_dir = snapshot.steps_dir
    config.environment_file = snapshot.environment_file
    config.lang = snapshot.lang
    config.stop = snapshot.stop
    config.dry_run = snapshot.dry_run
    config.use_nested_step_modules = snapshot.use_nested_step_modules
    config.reporters = []
    config.parallel = snapshot.parallel
    config.parallel_scheme = snapshot.parallel_scheme
    config.parallel_balance = snapshot.parallel_balance
    config.parallel_timing_file = snapshot.parallel_timing_file
    config.parallel_report = snapshot.parallel_report

    # -- SELECTION FILTERS: rebuild tag-expression, name pattern and
    #    userdata so --tags/--name/-D behave the same inside workers.
    config.tags = snapshot.tags
    config.config_tags = snapshot.config_tags
    config.default_tags = snapshot.default_tags
    from behave.tag_expression import TagExpressionProtocol

    if isinstance(snapshot.tag_expression_protocol, TagExpressionProtocol):
        config.tag_expression_protocol = snapshot.tag_expression_protocol
    config.setup_tag_expression()
    if snapshot.name:
        config.name = list(snapshot.name)
        config.name_re = Configuration.build_name_re(config.name)
    if snapshot.userdata:
        from behave.userdata import UserData

        config.userdata = UserData(dict(snapshot.userdata))
    return config


def _worker_run_loop(
    worker_id: int,
    task_queue: Any,
    result_queue: QueueType[WorkerResult],
    stop_event: Any,
    config_snapshot: ConfigSnapshot,
) -> None:
    """Top-level worker loop function (picklable for Windows spawn).

    Consumes WorkUnits from task_queue, executes them via WorkerRunner,
    and puts WorkerResults into result_queue. Stops when:
    - A None sentinel is received from the queue.
    - stop_event is set by the coordinator.
    """
    config = _make_config(config_snapshot)
    runner = WorkerRunner(config, worker_id, result_queue, stop_event)
    try:
        try:
            runner.setup()
        except Exception as exc:
            logger.exception("Worker %d: setup failed; stopping all workers.", worker_id)
            stop_event.set()
            result_queue.put(
                WorkerResult(
                    worker_id=worker_id,
                    work_unit_id="setup",
                    failed=True,
                    duration=0.0,
                    error=f"Worker setup failed: {exc}",
                )
            )
            return
        while True:
            if stop_event.is_set():
                break
            try:
                unit = task_queue.get(timeout=5)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                logger.warning(
                    "Worker %d: task queue closed unexpectedly; exiting.",
                    worker_id,
                )
                break
            if unit is None:
                task_queue.task_done()
                break
            if stop_event.is_set():
                task_queue.task_done()
                continue
            result = runner.run_work_unit(unit)
            result_queue.put(result)
            task_queue.task_done()
            if result.failed and config.stop:
                # -- STOP-ON-FAILURE: propagate --stop to other workers.
                stop_event.set()
            if runner.aborted:
                stop_event.set()
                logger.warning(
                    "Worker %d: aborted after work unit %s; stopping all workers.",
                    worker_id,
                    unit.id,
                )
                break
    finally:
        runner.teardown()


class WorkerProcess:
    """Wrapper around multiprocessing.Process for consuming WorkUnits.

    Each WorkerProcess runs _worker_run_loop in a separate process,
    consuming WorkUnits from a JoinableQueue and producing WorkerResults
    in a result Queue.
    """

    def __init__(
        self,
        worker_id: int,
        task_queue: Any,
        result_queue: QueueType[WorkerResult],
        stop_event: Any,
        config_snapshot: ConfigSnapshot,
        ctx: Any | None = None,
    ) -> None:
        self.worker_id = worker_id
        self._task_queue = task_queue
        self._result_queue = result_queue
        self._stop_event = stop_event
        self._config_snapshot = config_snapshot
        self._ctx = ctx or multiprocessing.get_context("spawn")
        self._process: multiprocessing.process.BaseProcess | None = None

    def start(self) -> None:
        """Launch the worker process."""
        self._process = self._ctx.Process(
            target=_worker_run_loop,
            args=(
                self.worker_id,
                self._task_queue,
                self._result_queue,
                self._stop_event,
                self._config_snapshot,
            ),
            daemon=True,
        )
        assert self._process is not None
        self._process.start()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the worker process to terminate."""
        if self._process is not None:
            self._process.join(timeout)

    def is_alive(self) -> bool:
        """Return True if the worker process is still running."""
        if self._process is None:
            return False
        return self._process.is_alive()

    def terminate(self) -> None:
        """Forcefully terminate the worker process.

        Should only be called after ``join(timeout=...)`` returns and
        ``is_alive()`` is still True, as a last resort to avoid
        indefinite hangs from stuck workers.
        """
        if self._process is not None and self._process.is_alive():
            self._process.terminate()
            logger.warning("Worker %d forcibly terminated.", self.worker_id)
