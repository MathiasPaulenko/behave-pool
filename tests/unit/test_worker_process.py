"""Tests for WorkerProcess and _worker_run_loop."""

from __future__ import annotations

import multiprocessing
import queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from behave_pool.config import ConfigSnapshot
from behave_pool.result import WorkerResult
from behave_pool.work_unit import WorkUnit
from behave_pool.worker import WorkerProcess, _worker_run_loop


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


def _make_work_unit(unit_id: str, config: MagicMock) -> WorkUnit:
    return WorkUnit(id=unit_id, config=config, feature_path=f"features/{unit_id}.feature")


@pytest.fixture
def snapshot() -> ConfigSnapshot:
    return ConfigSnapshot(
        base_dir="features",
        steps_dir="steps",
        environment_file="environment.py",
        lang="en",
        stop=False,
    )


class TestWorkerProcessLifecycle:
    def test_process_none_before_start(self, mock_config: MagicMock) -> None:
        task_queue: multiprocessing.JoinableQueue = multiprocessing.JoinableQueue()
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        worker = WorkerProcess(0, task_queue, result_queue, stop_event, mock_config)
        assert worker._process is None
        assert worker.is_alive() is False

    def test_is_alive_false_before_start(self, mock_config: MagicMock) -> None:
        task_queue: multiprocessing.JoinableQueue = multiprocessing.JoinableQueue()
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        worker = WorkerProcess(1, task_queue, result_queue, stop_event, mock_config)
        assert worker.is_alive() is False

    def test_join_without_start_is_noop(self, mock_config: MagicMock) -> None:
        task_queue: multiprocessing.JoinableQueue = multiprocessing.JoinableQueue()
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        worker = WorkerProcess(2, task_queue, result_queue, stop_event, mock_config)
        worker.join(timeout=1)

    def test_terminate_without_start_is_noop(self, mock_config: MagicMock) -> None:
        """terminate() should be a no-op when process hasn't been started."""
        task_queue: multiprocessing.JoinableQueue = multiprocessing.JoinableQueue()
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        worker = WorkerProcess(3, task_queue, result_queue, stop_event, mock_config)
        worker.terminate()  # should not raise

    def test_terminate_calls_process_terminate(self, mock_config: MagicMock) -> None:
        """terminate() should call process.terminate() when process is alive."""
        task_queue: multiprocessing.JoinableQueue = multiprocessing.JoinableQueue()
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        worker = WorkerProcess(4, task_queue, result_queue, stop_event, mock_config)
        mock_process = MagicMock()
        mock_process.is_alive.return_value = True
        worker._process = mock_process

        worker.terminate()
        mock_process.terminate.assert_called_once()


class TestWorkerRunLoop:
    """Test _worker_run_loop in-process using queue.Queue (no pickling needed)."""

    def test_processes_two_units_and_sentinel(
        self, mock_config: MagicMock, snapshot: ConfigSnapshot
    ) -> None:
        """2 work units + 1 sentinel → 2 WorkerResults, queue empty."""
        task_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[WorkerResult] = queue.Queue()
        stop_event = multiprocessing.Event()

        unit1 = _make_work_unit("feature:a.feature", mock_config)
        unit2 = _make_work_unit("feature:b.feature", mock_config)

        task_queue.put(unit1)
        task_queue.put(unit2)
        task_queue.put(None)  # sentinel

        with patch("behave_pool.worker.WorkerRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.aborted = False
            mock_runner.run_work_unit.side_effect = [
                WorkerResult(worker_id=0, work_unit_id=unit1.id, failed=False, duration=0.1),
                WorkerResult(worker_id=0, work_unit_id=unit2.id, failed=False, duration=0.2),
            ]

            _worker_run_loop(0, task_queue, result_queue, stop_event, snapshot)

            results: list[WorkerResult] = []
            while not result_queue.empty():
                results.append(result_queue.get())
            assert len(results) == 2
            assert results[0].work_unit_id == "feature:a.feature"
            assert results[1].work_unit_id == "feature:b.feature"

            assert task_queue.empty()
            mock_runner.setup.assert_called_once()
            mock_runner.teardown.assert_called_once()
            assert mock_runner.run_work_unit.call_count == 2

    def test_stop_event_skips_remaining_units(
        self, mock_config: MagicMock, snapshot: ConfigSnapshot
    ) -> None:
        """When stop_event is set, remaining units are skipped (loop exits early)."""
        task_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[WorkerResult] = queue.Queue()
        stop_event = multiprocessing.Event()
        stop_event.set()

        unit1 = _make_work_unit("feature:skipped.feature", mock_config)
        task_queue.put(unit1)
        task_queue.put(None)

        with patch("behave_pool.worker.WorkerRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner

            _worker_run_loop(0, task_queue, result_queue, stop_event, snapshot)

            results: list[WorkerResult] = []
            while not result_queue.empty():
                results.append(result_queue.get())
            assert len(results) == 0
            mock_runner.run_work_unit.assert_not_called()

    def test_sentinel_breaks_loop(self, mock_config: MagicMock, snapshot: ConfigSnapshot) -> None:
        """Sentinel (None) breaks the loop immediately."""
        task_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[WorkerResult] = queue.Queue()
        stop_event = multiprocessing.Event()

        task_queue.put(None)

        with patch("behave_pool.worker.WorkerRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner

            _worker_run_loop(0, task_queue, result_queue, stop_event, snapshot)

            mock_runner.run_work_unit.assert_not_called()
            mock_runner.setup.assert_called_once()
            mock_runner.teardown.assert_called_once()
            assert task_queue.empty()

    def test_teardown_called_on_exception(
        self, mock_config: MagicMock, snapshot: ConfigSnapshot
    ) -> None:
        """teardown is called even if setup raises, and an error result is queued."""
        task_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[WorkerResult] = queue.Queue()
        stop_event = multiprocessing.Event()

        task_queue.put(None)

        with patch("behave_pool.worker.WorkerRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.setup.side_effect = RuntimeError("setup crash")

            _worker_run_loop(0, task_queue, result_queue, stop_event, snapshot)

            mock_runner.teardown.assert_called_once()
            assert stop_event.is_set()
            result = result_queue.get_nowait()
            assert result.failed is True
            assert "setup crash" in (result.error or "")
            assert result.work_unit_id == "setup"

    def test_worker_loop_exits_on_eoferror(
        self, mock_config: MagicMock, snapshot: ConfigSnapshot
    ) -> None:
        """Worker loop should exit gracefully when queue raises EOFError."""
        task_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[WorkerResult] = queue.Queue()
        stop_event = multiprocessing.Event()

        with patch("behave_pool.worker.WorkerRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner

            with patch.object(task_queue, "get", side_effect=EOFError):
                _worker_run_loop(0, task_queue, result_queue, stop_event, snapshot)

            mock_runner.run_work_unit.assert_not_called()
            mock_runner.teardown.assert_called_once()

    def test_worker_loop_stops_after_abort(
        self, mock_config: MagicMock, snapshot: ConfigSnapshot
    ) -> None:
        """When runner.aborted becomes True after a work unit, the loop should break.

        Regression test: previously, an aborted worker would continue processing
        work units but silently skip all features (returning failed=False).
        """
        task_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[WorkerResult] = queue.Queue()
        stop_event = multiprocessing.Event()

        unit1 = _make_work_unit("feature:a.feature", mock_config)
        unit2 = _make_work_unit("feature:b.feature", mock_config)
        task_queue.put(unit1)
        task_queue.put(unit2)
        task_queue.put(None)

        with patch("behave_pool.worker.WorkerRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run_work_unit.side_effect = [
                WorkerResult(worker_id=0, work_unit_id=unit1.id, failed=True, duration=0.1),
            ]
            mock_runner.aborted = True

            _worker_run_loop(0, task_queue, result_queue, stop_event, snapshot)

            results: list[WorkerResult] = []
            while not result_queue.empty():
                results.append(result_queue.get())
            assert len(results) == 1
            assert results[0].work_unit_id == "feature:a.feature"
            assert mock_runner.run_work_unit.call_count == 1
            mock_runner.teardown.assert_called_once()

    def test_worker_loop_sets_stop_event_on_abort(
        self, mock_config: MagicMock, snapshot: ConfigSnapshot
    ) -> None:
        """When runner.aborted becomes True, stop_event must be set so other
        workers stop cooperatively and the coordinator skips the serial phase.

        Regression test: previously, an aborted worker broke out of the loop
        without setting stop_event, leaving its sentinel in the queue for
        another worker to consume (causing early exit and unprocessed units).
        """
        task_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[WorkerResult] = queue.Queue()
        stop_event = multiprocessing.Event()

        unit1 = _make_work_unit("feature:a.feature", mock_config)
        task_queue.put(unit1)
        task_queue.put(None)

        with patch("behave_pool.worker.WorkerRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run_work_unit.side_effect = [
                WorkerResult(worker_id=0, work_unit_id=unit1.id, failed=True, duration=0.1),
            ]
            mock_runner.aborted = True

            _worker_run_loop(0, task_queue, result_queue, stop_event, snapshot)

            assert stop_event.is_set()


class TestMakeConfig:
    """Test _make_config reconstructs all parallel fields from snapshot."""

    def test_make_config_sets_parallel_fields(self) -> None:
        from behave_pool.config import ConfigSnapshot
        from behave_pool.worker import _make_config

        snapshot = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="environment.py",
            lang="en",
            stop=True,
            paths=["features"],
            parallel=4,
            parallel_scheme="feature",
            parallel_balance="fifo",
            parallel_timing_file="custom-timing.json",
            dry_run=True,
            use_nested_step_modules=False,
        )

        with patch("behave.configuration.Configuration") as mock_config_cls:
            mock_config = MagicMock()
            mock_config_cls.return_value = mock_config

            result = _make_config(snapshot)

            assert result.parallel == 4
            assert result.parallel_scheme == "feature"
            assert result.parallel_balance == "fifo"
            assert result.parallel_timing_file == "custom-timing.json"
            assert result.stop is True
            assert result.dry_run is True


def _simple_worker_loop(
    worker_id: int,
    task_queue: Any,
    result_queue: Any,
    stop_event: Any,
    config: Any,
) -> None:
    """Picklable simple loop for testing WorkerProcess with real processes."""
    try:
        while True:
            unit = task_queue.get()
            if unit is None:
                task_queue.task_done()
                break
            if stop_event.is_set():
                task_queue.task_done()
                continue
            result_queue.put(f"done:{unit}")
            task_queue.task_done()
    except Exception:
        pass


class TestWorkerProcessRealProcess:
    """Test WorkerProcess with real multiprocessing using a simple picklable loop."""

    def test_start_join_and_results(self) -> None:
        """Start a real process, feed it items, verify results."""
        task_queue: multiprocessing.JoinableQueue = multiprocessing.JoinableQueue()
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        task_queue.put("unit1")
        task_queue.put("unit2")
        task_queue.put(None)

        process = multiprocessing.Process(
            target=_simple_worker_loop,
            args=(0, task_queue, result_queue, stop_event, None),
            daemon=True,
        )
        process.start()
        process.join(timeout=10)
        assert not process.is_alive()

        results: list[str] = []
        while not result_queue.empty():
            results.append(result_queue.get())
        assert len(results) == 2
        assert "done:unit1" in results
        assert "done:unit2" in results

    def test_stop_event_with_real_process(self) -> None:
        """stop_event causes the process to skip items."""
        task_queue: multiprocessing.JoinableQueue = multiprocessing.JoinableQueue()
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        stop_event = multiprocessing.Event()
        stop_event.set()

        task_queue.put("skipped")
        task_queue.put(None)

        process = multiprocessing.Process(
            target=_simple_worker_loop,
            args=(0, task_queue, result_queue, stop_event, None),
            daemon=True,
        )
        process.start()
        process.join(timeout=10)
        assert not process.is_alive()

        results: list[str] = []
        while not result_queue.empty():
            results.append(result_queue.get())
        assert len(results) == 0

    def test_worker_process_wrapper_start_join(self) -> None:
        """Test WorkerProcess.start/join/is_alive with a simple target."""
        ctx = multiprocessing.get_context("spawn")
        task_queue: multiprocessing.JoinableQueue = ctx.JoinableQueue()
        result_queue: multiprocessing.Queue = ctx.Queue()
        stop_event = ctx.Event()

        task_queue.put(None)

        with patch("behave_pool.worker._worker_run_loop", _simple_worker_loop):
            worker = WorkerProcess(0, task_queue, result_queue, stop_event, config_snapshot=None)
            worker.start()
            worker.join(timeout=10)
            assert not worker.is_alive()
