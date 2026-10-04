"""Unit tests for ParallelRunner coordinator."""

from __future__ import annotations

import json
import multiprocessing
import queue
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from behave_pool.config import ConfigSnapshot
from behave_pool.result import WorkerResult
from behave_pool.runner import ParallelRunner
from behave_pool.timing import TimingStore
from behave_pool.work_unit import WorkUnit


@pytest.fixture
def mock_config() -> MagicMock:
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
    config.parallel_report = "behave-pool-report.json"
    config.parallel_timing_file = ".behave-pool-timing.json"
    config.shard = None
    config.shard_index = None
    config.total_shards = None
    config.exclude = MagicMock(return_value=False)
    return config


class TestParallelRunnerInit:
    def test_init_calls_add_parallel_options(self, mock_config: MagicMock) -> None:
        with patch("behave_pool.runner.add_parallel_options") as mock_add:
            ParallelRunner(mock_config)
            mock_add.assert_called_once_with(mock_config)

    def test_init_with_parallel_already_set(self, mock_config: MagicMock) -> None:
        mock_config.jobs = 4
        runner = ParallelRunner(mock_config)
        assert runner.config.parallel == 4


class TestRunSequential:
    def test_parallel_1_calls_run_sequential(self, mock_config: MagicMock) -> None:
        mock_config.parallel = 1
        runner = ParallelRunner(mock_config)
        with (
            patch.object(runner, "path_manager"),
            patch.object(runner, "setup_paths"),
            patch.object(runner, "_run_sequential", return_value=False) as mock_seq,
        ):
            result = runner.run()
            mock_seq.assert_called_once()
            assert result is False

    def test_run_with_paths_parallel_1_calls_sequential(self, mock_config: MagicMock) -> None:
        mock_config.parallel = 1
        runner = ParallelRunner(mock_config)
        with patch.object(runner, "_run_sequential", return_value=False) as mock_seq:
            result = runner.run_with_paths()
            mock_seq.assert_called_once()
            assert result is False

    def test_run_with_paths_parallel_2_calls_parallel(self, mock_config: MagicMock) -> None:
        mock_config.jobs = 2
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)
        with patch.object(runner, "_run_parallel", return_value=False) as mock_par:
            result = runner.run_with_paths()
            mock_par.assert_called_once()
            assert result is False


class TestRunSequentialInternals:
    def test_run_sequential_executes_features(self, mock_config: MagicMock) -> None:
        mock_config.parallel = 1
        runner = ParallelRunner(mock_config)
        with (
            patch("behave.runner.Context"),
            patch.object(runner, "load_hooks"),
            patch.object(runner, "load_step_definitions"),
            patch.object(runner, "feature_locations", return_value=["features/login.feature"]),
            patch("behave_pool.runner.parse_features", return_value=[MagicMock()]),
            patch("behave_pool.runner.make_formatters", return_value=[]),
            patch.object(runner, "run_model", return_value=False),
        ):
            result = runner._run_sequential()
            assert result is False
            assert len(runner.features) == 1


class TestPlan:
    def test_plan_creates_work_units(self, mock_config: MagicMock) -> None:
        mock_config.jobs = 2
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        feature1 = MagicMock()
        feature1.name = "Login"
        feature1.filename = "features/login.feature"
        feature2 = MagicMock()
        feature2.name = "Checkout"
        feature2.filename = "features/checkout.feature"

        with (
            patch("behave.runner.Context"),
            patch.object(runner, "load_hooks"),
            patch.object(runner, "load_step_definitions"),
            patch.object(
                runner,
                "feature_locations",
                return_value=["features/login.feature", "features/checkout.feature"],
            ),
            patch("behave_pool.runner.parse_features", return_value=[feature1, feature2]),
            patch("behave_pool.runner.WorkUnitIterator") as mock_iter_cls,
        ):
            mock_iter = MagicMock()
            mock_iter_cls.for_scheme.return_value = mock_iter
            unit1 = WorkUnit(
                id="feature:login",
                config=ConfigSnapshot(
                    base_dir="features",
                    steps_dir="steps",
                    environment_file="environment.py",
                    lang="en",
                    stop=False,
                ),
                feature_path="features/login.feature",
            )
            unit2 = WorkUnit(
                id="feature:checkout",
                config=ConfigSnapshot(
                    base_dir="features",
                    steps_dir="steps",
                    environment_file="environment.py",
                    lang="en",
                    stop=False,
                ),
                feature_path="features/checkout.feature",
            )
            mock_iter.iterate.return_value = iter([unit1, unit2])

            work_units = runner._plan()

            assert len(work_units) == 2


class TestSplitBySerialTag:
    def test_all_parallel(self) -> None:
        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(
                id="u1",
                config=snap,
                feature_path="a.feature",
            ),
            WorkUnit(
                id="u2",
                config=snap,
                feature_path="b.feature",
            ),
        ]
        parallel, serial = ParallelRunner._split_by_serial_tag(units)
        assert len(parallel) == 2
        assert len(serial) == 0

    def test_all_serial(self) -> None:
        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(
                id="u1",
                config=snap,
                feature_path="a.feature",
                tags=["serial"],
            ),
            WorkUnit(
                id="u2",
                config=snap,
                feature_path="b.feature",
                tags=["serial"],
            ),
        ]
        parallel, serial = ParallelRunner._split_by_serial_tag(units)
        assert len(parallel) == 0
        assert len(serial) == 2

    def test_mixed(self) -> None:
        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(
                id="u1",
                config=snap,
                feature_path="a.feature",
            ),
            WorkUnit(
                id="u2",
                config=snap,
                feature_path="b.feature",
                tags=["serial"],
            ),
            WorkUnit(
                id="u3",
                config=snap,
                feature_path="c.feature",
            ),
            WorkUnit(
                id="u4",
                config=snap,
                feature_path="d.feature",
                tags=["serial"],
            ),
        ]
        parallel, serial = ParallelRunner._split_by_serial_tag(units)
        assert len(parallel) == 2
        assert len(serial) == 2
        assert all(u.is_serial for u in serial)
        assert all(not u.is_serial for u in parallel)

    def test_empty(self) -> None:
        parallel, serial = ParallelRunner._split_by_serial_tag([])
        assert len(parallel) == 0
        assert len(serial) == 0


class TestDispatch:
    def test_dispatch_parallel_only(self, mock_config: MagicMock) -> None:
        mock_config.jobs = 3
        mock_config.parallel = 3
        runner = ParallelRunner(mock_config)

        task_queue: Any = multiprocessing.JoinableQueue()
        result_queue: Any = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        parallel_batch = [
            WorkUnit(id="u1", config=snap, feature_path="a.feature"),
            WorkUnit(id="u2", config=snap, feature_path="b.feature"),
        ]

        with (
            patch("behave_pool.runner.WorkerProcess") as mock_wp_cls,
            patch.object(task_queue, "join"),
            patch.object(runner, "_drain_results", return_value=[]),
        ):
            mock_workers = [MagicMock() for _ in range(3)]
            for mw in mock_workers:
                mw.is_alive.return_value = False
            mock_wp_cls.side_effect = mock_workers

            ctx = multiprocessing.get_context("spawn")
            dispatched = runner._dispatch(
                task_queue, result_queue, stop_event, parallel_batch, [], ctx
            )

            # Only as many workers as there are work units.
            assert mock_wp_cls.call_count == 2
            for w in mock_workers[:2]:
                w.start.assert_called_once()
                w.join.assert_called_once_with(timeout=30.0)
            assert [u.id for u in dispatched] == ["u1", "u2"]

    def test_dispatch_serial_only(self, mock_config: MagicMock) -> None:
        mock_config.jobs = 2
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        task_queue: Any = multiprocessing.JoinableQueue()
        result_queue: Any = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        serial_batch = [
            WorkUnit(id="s1", config=snap, feature_path="a.feature", tags=["serial"]),
            WorkUnit(id="s2", config=snap, feature_path="b.feature", tags=["serial"]),
        ]

        with (
            patch("behave_pool.runner.WorkerProcess") as mock_wp_cls,
            patch.object(task_queue, "join"),
            patch.object(runner, "_drain_results", return_value=[]),
        ):
            mock_workers = [MagicMock() for _ in range(1)]
            for mw in mock_workers:
                mw.is_alive.return_value = False
            mock_wp_cls.side_effect = mock_workers

            ctx = multiprocessing.get_context("spawn")
            dispatched = runner._dispatch(
                task_queue, result_queue, stop_event, [], serial_batch, ctx
            )

            # 0 workers for parallel phase (empty batch) + 1 for serial phase
            assert mock_wp_cls.call_count == 1
            mock_workers[0].join.assert_called_once_with(timeout=30.0)
            assert [u.id for u in dispatched] == ["s1", "s2"]

    def test_dispatch_mixed(self, mock_config: MagicMock) -> None:
        mock_config.jobs = 2
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        task_queue: Any = multiprocessing.JoinableQueue()
        result_queue: Any = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        parallel_batch = [WorkUnit(id="u1", config=snap, feature_path="a.feature")]
        serial_batch = [WorkUnit(id="s1", config=snap, feature_path="b.feature", tags=["serial"])]

        with (
            patch("behave_pool.runner.WorkerProcess") as mock_wp_cls,
            patch.object(task_queue, "join"),
            patch.object(runner, "_drain_results", return_value=[]),
        ):
            mock_workers = [MagicMock() for _ in range(3)]
            for mw in mock_workers:
                mw.is_alive.return_value = False
            mock_wp_cls.side_effect = mock_workers

            ctx = multiprocessing.get_context("spawn")
            dispatched = runner._dispatch(
                task_queue,
                result_queue,
                stop_event,
                parallel_batch,
                serial_batch,
                ctx,
            )

            # min(2 workers, 1 unit) for parallel + 1 for serial
            assert mock_wp_cls.call_count == 2
            for w in mock_workers[:2]:
                w.join.assert_called_once_with(timeout=30.0)
            assert [u.id for u in dispatched] == ["u1", "s1"]

    def test_dispatch_empty_parallel_skips_workers(self, mock_config: MagicMock) -> None:
        """Empty parallel batch should not launch any parallel workers."""
        mock_config.jobs = 3
        mock_config.parallel = 3
        runner = ParallelRunner(mock_config)

        task_queue: Any = multiprocessing.JoinableQueue()
        result_queue: Any = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        with (
            patch("behave_pool.runner.WorkerProcess") as mock_wp_cls,
            patch.object(task_queue, "join"),
        ):
            ctx = multiprocessing.get_context("spawn")
            dispatched = runner._dispatch(task_queue, result_queue, stop_event, [], [], ctx)

            # No parallel batch and no serial batch = 0 workers
            assert mock_wp_cls.call_count == 0
            assert dispatched == []

    def test_dispatch_serial_skipped_when_stop_event_set(self, mock_config: MagicMock) -> None:
        """Serial phase should be skipped if stop_event was set during parallel phase."""
        mock_config.jobs = 2
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        task_queue: Any = multiprocessing.JoinableQueue()
        result_queue: Any = multiprocessing.Queue()
        stop_event = multiprocessing.Event()
        stop_event.set()  # Simulate stop_event being set

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        parallel_batch = [WorkUnit(id="u1", config=snap, feature_path="a.feature")]
        serial_batch = [WorkUnit(id="s1", config=snap, feature_path="b.feature", tags=["serial"])]

        with (
            patch("behave_pool.runner.WorkerProcess") as mock_wp_cls,
            patch.object(task_queue, "join"),
            patch.object(runner, "_drain_results", return_value=[]),
        ):
            mock_workers = [MagicMock() for _ in range(2)]
            for mw in mock_workers:
                mw.is_alive.return_value = False
            mock_wp_cls.side_effect = mock_workers

            ctx = multiprocessing.get_context("spawn")
            dispatched = runner._dispatch(
                task_queue,
                result_queue,
                stop_event,
                parallel_batch,
                serial_batch,
                ctx,
            )

            # 1 worker for parallel (1 unit) + 0 for serial (stop_event set)
            assert mock_wp_cls.call_count == 1
            # Serial units not dispatched because stop_event was set
            assert [u.id for u in dispatched] == ["u1"]

    def test_dispatch_join_timeout_sets_stop_event(self, mock_config: MagicMock) -> None:
        """If a worker is still alive after join timeout, stop_event should be set
        and the worker should be terminated."""
        mock_config.jobs = 2
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        task_queue: Any = multiprocessing.JoinableQueue()
        result_queue: Any = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        parallel_batch = [WorkUnit(id="u1", config=snap, feature_path="a.feature")]

        with (
            patch("behave_pool.runner.WorkerProcess") as mock_wp_cls,
            patch.object(task_queue, "join"),
            patch("behave_pool.runner.RESULT_TIMEOUT", 0.01),
            patch("behave_pool.runner._POLL_INTERVAL", 0.01),
        ):
            mock_workers = [MagicMock() for _ in range(2)]
            for mw in mock_workers:
                mw.is_alive.return_value = True
            mock_wp_cls.side_effect = mock_workers

            ctx = multiprocessing.get_context("spawn")
            dispatched = runner._dispatch(
                task_queue, result_queue, stop_event, parallel_batch, [], ctx
            )

            # min(2 workers, 1 unit) = 1 worker spawned
            assert mock_wp_cls.call_count == 1
            mock_workers[0].join.assert_called_once_with(timeout=30.0)
            mock_workers[0].terminate.assert_called_once()
            assert stop_event.is_set()
            assert [u.id for u in dispatched] == ["u1"]

    def test_dispatch_serial_worker_timeout_sets_stop_event(self, mock_config: MagicMock) -> None:
        """If the serial worker is still alive after join timeout, stop_event
        should be set and the worker should be terminated.

        Regression test for the serial-phase timeout path in _dispatch.
        """
        mock_config.jobs = 2
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        task_queue: Any = multiprocessing.JoinableQueue()
        result_queue: Any = multiprocessing.Queue()
        stop_event = multiprocessing.Event()

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        serial_batch = [WorkUnit(id="s1", config=snap, feature_path="a.feature", tags=["serial"])]

        with (
            patch("behave_pool.runner.WorkerProcess") as mock_wp_cls,
            patch.object(task_queue, "join"),
            patch("behave_pool.runner.RESULT_TIMEOUT", 0.01),
            patch("behave_pool.runner._POLL_INTERVAL", 0.01),
        ):
            mock_worker = MagicMock()
            mock_worker.is_alive.return_value = True
            mock_wp_cls.return_value = mock_worker

            ctx = multiprocessing.get_context("spawn")
            dispatched = runner._dispatch(
                task_queue, result_queue, stop_event, [], serial_batch, ctx
            )

            mock_worker.join.assert_called_once_with(timeout=30.0)
            mock_worker.terminate.assert_called_once()
            assert stop_event.is_set()
            # Serial units were dispatched even though worker timed out
            assert [u.id for u in dispatched] == ["s1"]


class TestCollect:
    def test_collect_no_failures(self, mock_config: MagicMock) -> None:
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        result_queue: Any = queue.Queue()
        result_queue.put(WorkerResult(worker_id=0, work_unit_id="u1", failed=False, duration=0.1))
        result_queue.put(WorkerResult(worker_id=1, work_unit_id="u2", failed=False, duration=0.2))

        work_units = [MagicMock(id="u1"), MagicMock(id="u2")]

        result = runner._collect(result_queue, work_units)
        assert result is False

    def test_collect_with_failures(self, mock_config: MagicMock) -> None:
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        result_queue: Any = queue.Queue()
        result_queue.put(WorkerResult(worker_id=0, work_unit_id="u1", failed=False, duration=0.1))
        result_queue.put(WorkerResult(worker_id=1, work_unit_id="u2", failed=True, duration=0.2))

        work_units = [MagicMock(id="u1"), MagicMock(id="u2")]

        result = runner._collect(result_queue, work_units)
        assert result is True

    def test_collect_cleans_tmp_dir(self, mock_config: MagicMock, tmp_path: Path) -> None:
        mock_config.parallel = 1
        runner = ParallelRunner(mock_config)

        result_queue: Any = queue.Queue()

        with (
            patch("behave_pool.runner.Path.is_dir", return_value=True),
            patch("behave_pool.runner.Path.glob", return_value=[]),
            patch("behave_pool.runner.Path.iterdir", return_value=iter([])),
            patch("behave_pool.runner.Path.rmdir") as mock_rmdir,
        ):
            runner._collect(result_queue, [])
            mock_rmdir.assert_called_once()

    def test_collect_missing_results_treated_as_failure(self, mock_config: MagicMock) -> None:
        """Missing results from crashed workers should cause failed=True."""
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        result_queue: Any = queue.Queue()
        result_queue.put(WorkerResult(worker_id=0, work_unit_id="u1", failed=False, duration=0.1))

        work_units = [MagicMock(id="u1"), MagicMock(id="u2")]

        result = runner._collect(result_queue, work_units, deadline_seconds=0.5)
        assert result is True

    def test_collect_all_results_present_no_false_failure(self, mock_config: MagicMock) -> None:
        """When all results are present and none failed, result should be False."""
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        result_queue: Any = queue.Queue()
        result_queue.put(WorkerResult(worker_id=0, work_unit_id="u1", failed=False, duration=0.1))
        result_queue.put(WorkerResult(worker_id=1, work_unit_id="u2", failed=False, duration=0.2))

        work_units = [MagicMock(id="u1"), MagicMock(id="u2")]

        result = runner._collect(result_queue, work_units)
        assert result is False

    def test_collect_eoferror_treated_as_failure(self, mock_config: MagicMock) -> None:
        """When the result queue raises EOFError, _collect should break early
        and treat missing results as failures.

        Regression test for the EOFError/OSError branch in _collect.
        """
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        result_queue: Any = MagicMock()
        result_queue.get.side_effect = EOFError("queue closed")

        work_units = [MagicMock(id="u1"), MagicMock(id="u2")]

        result = runner._collect(result_queue, work_units)
        assert result is True

    def test_collect_oserror_treated_as_failure(self, mock_config: MagicMock) -> None:
        """When the result queue raises OSError, _collect should break early
        and treat missing results as failures.

        Regression test for the OSError branch in _collect.
        """
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        result_queue: Any = MagicMock()
        result_queue.get.side_effect = OSError("pipe broken")

        work_units = [MagicMock(id="u1"), MagicMock(id="u2")]

        result = runner._collect(result_queue, work_units)
        assert result is True

    def test_collect_empty_work_units_no_failure(self, mock_config: MagicMock) -> None:
        """When no work units are dispatched, _collect should return False
        (no failures) without waiting.
        """
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        result_queue: Any = queue.Queue()
        result = runner._collect(result_queue, [])
        assert result is False


class TestRunParallelDispatchedUnits:
    """Regression test for _run_parallel only collecting dispatched units.

    When stop_event is set during the parallel phase, serial units are never
    dispatched. _collect must not wait for or count their results.
    """

    def test_serial_units_not_counted_when_stop_event_set(self, mock_config: MagicMock) -> None:
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        parallel_batch = [
            WorkUnit(id="u1", config=snap, feature_path="a.feature"),
            WorkUnit(id="u2", config=snap, feature_path="b.feature"),
        ]
        serial_batch = [
            WorkUnit(id="s1", config=snap, feature_path="c.feature", tags=["serial"]),
        ]
        all_units = parallel_batch + serial_batch

        with (
            patch.object(runner, "_plan", return_value=all_units),
            patch.object(
                runner,
                "_split_by_serial_tag",
                return_value=(parallel_batch, serial_batch),
            ),
            patch.object(
                runner,
                "_dispatch",
                return_value=parallel_batch,
            ),
            patch.object(runner, "_collect", return_value=True) as mock_collect,
        ):
            runner._run_parallel()

            collect_args = mock_collect.call_args
            dispatched = collect_args[0][1]
            dispatched_ids = [u.id for u in dispatched]
            assert "s1" not in dispatched_ids
            assert "u1" in dispatched_ids
            assert "u2" in dispatched_ids

    def test_serial_units_counted_when_stop_event_not_set(self, mock_config: MagicMock) -> None:
        mock_config.parallel = 2
        runner = ParallelRunner(mock_config)

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        parallel_batch = [
            WorkUnit(id="u1", config=snap, feature_path="a.feature"),
        ]
        serial_batch = [
            WorkUnit(id="s1", config=snap, feature_path="c.feature", tags=["serial"]),
        ]
        all_units = parallel_batch + serial_batch

        with (
            patch.object(runner, "_plan", return_value=all_units),
            patch.object(
                runner,
                "_split_by_serial_tag",
                return_value=(parallel_batch, serial_batch),
            ),
            patch.object(
                runner,
                "_dispatch",
                return_value=all_units,
            ),
            patch.object(runner, "_collect", return_value=False) as mock_collect,
        ):
            runner._run_parallel()

            collect_args = mock_collect.call_args
            dispatched = collect_args[0][1]
            dispatched_ids = [u.id for u in dispatched]
            assert "s1" in dispatched_ids
            assert "u1" in dispatched_ids


class TestSortByDuration:
    def test_fifo_preserves_order(self, mock_config: MagicMock) -> None:
        mock_config.parallel_balance = "fifo"
        runner = ParallelRunner(mock_config)

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(id="u1", config=snap, feature_path="a.feature"),
            WorkUnit(id="u2", config=snap, feature_path="b.feature"),
            WorkUnit(id="u3", config=snap, feature_path="c.feature"),
        ]
        result = runner._sort_by_duration(units)
        assert [u.id for u in result] == ["u1", "u2", "u3"]

    def test_lpt_sorts_descending(self, mock_config: MagicMock, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(
            json.dumps({"u1": 0.1, "u2": 2.0, "u3": 1.0}),
            encoding="utf-8",
        )
        mock_config.parallel_balance = "lpt"
        mock_config.parallel_timing_file = str(timing_file)
        runner = ParallelRunner(mock_config)

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(id="u1", config=snap, feature_path="a.feature"),
            WorkUnit(id="u2", config=snap, feature_path="b.feature"),
            WorkUnit(id="u3", config=snap, feature_path="c.feature"),
        ]
        result = runner._sort_by_duration(units)
        assert [u.id for u in result] == ["u2", "u3", "u1"]

    def test_lpt_unknown_ids_sort_last(self, mock_config: MagicMock, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(
            json.dumps({"u1": 1.5}),
            encoding="utf-8",
        )
        mock_config.parallel_balance = "lpt"
        mock_config.parallel_timing_file = str(timing_file)
        runner = ParallelRunner(mock_config)

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(id="u_unknown", config=snap, feature_path="a.feature"),
            WorkUnit(id="u1", config=snap, feature_path="b.feature"),
        ]
        result = runner._sort_by_duration(units)
        assert [u.id for u in result] == ["u1", "u_unknown"]

    def test_lpt_missing_timing_file(self, mock_config: MagicMock, tmp_path: Path) -> None:
        mock_config.parallel_balance = "lpt"
        mock_config.parallel_timing_file = str(tmp_path / "nonexistent.json")
        runner = ParallelRunner(mock_config)

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="env.py",
            lang="en",
            stop=False,
        )
        units = [
            WorkUnit(id="u1", config=snap, feature_path="a.feature"),
            WorkUnit(id="u2", config=snap, feature_path="b.feature"),
        ]
        result = runner._sort_by_duration(units)
        # All durations 0.0, stable sort preserves order
        assert [u.id for u in result] == ["u1", "u2"]


class TestUpdateTimings:
    def test_updates_and_saves(self, mock_config: MagicMock, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        mock_config.parallel_timing_file = str(timing_file)
        runner = ParallelRunner(mock_config)

        results = [
            WorkerResult(worker_id=0, work_unit_id="u1", failed=False, duration=1.5),
            WorkerResult(worker_id=1, work_unit_id="u2", failed=False, duration=0.3),
        ]
        runner._update_timings(results)

        assert timing_file.exists()
        data = json.loads(timing_file.read_text(encoding="utf-8"))
        assert data["u1"] == 1.5
        assert data["u2"] == 0.3

    def test_no_save_when_no_results(self, mock_config: MagicMock, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        mock_config.parallel_timing_file = str(timing_file)
        runner = ParallelRunner(mock_config)

        runner._update_timings([])
        assert not timing_file.exists()

    def test_updates_existing_timings(self, mock_config: MagicMock, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(
            json.dumps({"u1": 0.5}),
            encoding="utf-8",
        )
        mock_config.parallel_timing_file = str(timing_file)
        runner = ParallelRunner(mock_config)

        results = [
            WorkerResult(worker_id=0, work_unit_id="u1", failed=False, duration=2.0),
        ]
        runner._update_timings(results)

        data = json.loads(timing_file.read_text(encoding="utf-8"))
        assert data["u1"] == 2.0

    def test_save_failure_does_not_raise(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Timing save errors should be logged, not raised."""
        timing_file = tmp_path / "timing.json"
        mock_config.parallel_timing_file = str(timing_file)
        runner = ParallelRunner(mock_config)

        results = [
            WorkerResult(worker_id=0, work_unit_id="u1", failed=False, duration=1.0),
        ]

        with patch.object(TimingStore, "save_if_changed", side_effect=OSError("disk full")):
            runner._update_timings(results)

    def test_update_timings_with_none_timing_file(self, mock_config: MagicMock) -> None:
        """_update_timings must not raise when config.parallel_timing_file
        is None; it should fall back to the default timing file path.
        """
        mock_config.parallel_timing_file = None
        runner = ParallelRunner(mock_config)

        results = [
            WorkerResult(worker_id=0, work_unit_id="u1", failed=False, duration=1.0),
        ]

        # Should not raise TypeError from Path(None)
        runner._update_timings(results)


class TestSortByDurationNoneTimingFile:
    """Regression test for _sort_by_duration handling None timing file."""

    def test_sort_by_duration_with_none_timing_file(self, mock_config: MagicMock) -> None:
        """_sort_by_duration must not raise when config.parallel_timing_file
        is None; it should fall back to the default timing file path.
        """
        from behave_pool.config import ConfigSnapshot
        from behave_pool.work_unit import WorkUnit

        mock_config.parallel_timing_file = None
        mock_config.parallel_balance = "lpt"
        runner = ParallelRunner(mock_config)

        snap = ConfigSnapshot(
            base_dir="features",
            steps_dir="steps",
            environment_file="environment.py",
            lang=None,
            stop=False,
        )
        units = [
            WorkUnit(id="feature:a.feature", config=snap, feature_path="a.feature"),
            WorkUnit(id="feature:b.feature", config=snap, feature_path="b.feature"),
        ]

        # Should not raise TypeError from Path(None)
        result = runner._sort_by_duration(units)
        assert len(result) == 2


class TestComputeStatistics:
    """Tests for ParallelRunner._compute_statistics."""

    def test_empty_features(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        stats = runner._compute_statistics([])
        assert stats["features"] == 0
        assert stats["scenarios"] == 0
        assert stats["steps"] == 0
        assert stats["passed"] == 0
        assert stats["failed"] == 0
        assert stats["passRate"] == 0.0
        assert stats["byTag"] == {}
        assert "commonExceptionType" not in stats

    def test_passed_scenarios(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        features = [
            {
                "tags": [],
                "duration": 0.1,
                "scenarios": [
                    {
                        "status": "passed",
                        "duration": 0.05,
                        "tags": ["smoke"],
                        "steps": [
                            {"status": "passed", "duration": 0.01},
                            {"status": "passed", "duration": 0.02},
                        ],
                    },
                ],
            },
        ]
        stats = runner._compute_statistics(features)
        assert stats["features"] == 1
        assert stats["scenarios"] == 1
        assert stats["steps"] == 2
        assert stats["passed"] == 2
        assert stats["failed"] == 0
        assert stats["passRate"] == 1.0
        assert "smoke" in stats["byTag"]
        assert stats["byTag"]["smoke"]["passed"] == 1
        assert stats["byTag"]["smoke"]["failed"] == 0

    def test_failed_scenarios_with_error(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        features = [
            {
                "tags": [],
                "duration": 0.1,
                "scenarios": [
                    {
                        "status": "failed",
                        "duration": 0.05,
                        "tags": [],
                        "steps": [
                            {"status": "passed", "duration": 0.01},
                            {
                                "status": "failed",
                                "duration": 0.02,
                                "error": {"type": "AssertionError", "message": "x"},
                            },
                        ],
                    },
                ],
            },
        ]
        stats = runner._compute_statistics(features)
        assert stats["passed"] == 1
        assert stats["failed"] == 1
        assert stats["errorCount"] == 1
        assert stats["commonExceptionType"] == "AssertionError"

    def test_tag_inherits_feature_tags(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        features = [
            {
                "tags": ["feature-tag"],
                "duration": 0.0,
                "scenarios": [
                    {
                        "status": "passed",
                        "duration": 0.0,
                        "tags": ["scenario-tag"],
                        "steps": [],
                    },
                ],
            },
        ]
        stats = runner._compute_statistics(features)
        assert "feature-tag" in stats["byTag"]
        assert "scenario-tag" in stats["byTag"]
        assert stats["byTag"]["feature-tag"]["count"] == 1
        assert stats["byTag"]["scenario-tag"]["count"] == 1


class TestDetectEnvironment:
    """Tests for ParallelRunner._detect_environment."""

    def test_returns_dict_with_required_keys(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        env = runner._detect_environment()
        assert "pythonVersion" in env
        assert "platform" in env
        assert "os" in env
        assert "osVersion" in env
        assert "hostname" in env

    def test_ci_provider_detected_when_ci_env_set(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        with patch.dict("os.environ", {"CI": "true"}, clear=False):
            env = runner._detect_environment()
            assert env.get("ciProvider") is not None
            assert env["ciProvider"] in (
                "ci",
                "github-actions",
                "gitlab-ci",
                "circle-ci",
                "travis-ci",
            )

    def test_no_null_values_in_env(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        env = runner._detect_environment()
        for key, value in env.items():
            assert value is not None, f"{key} should not be None"


class TestBuildExecution:
    """Tests for ParallelRunner._build_execution."""

    def test_passed_execution(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        results = [
            WorkerResult(
                worker_id=0,
                work_unit_id="u1",
                failed=False,
                duration=1.5,
                report_path="tmp/worker_0.json",
            ),
        ]
        execution = runner._build_execution(results)
        assert execution["status"] == "passed"
        assert execution["duration"] == 1.5
        assert "executionId" in execution
        assert "startTime" in execution
        assert "endTime" in execution
        assert "command" not in execution
        assert "workingDirectory" not in execution

    def test_failed_execution(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        results = [
            WorkerResult(
                worker_id=0,
                work_unit_id="u1",
                failed=True,
                duration=2.0,
                report_path="tmp/worker_0.json",
            ),
        ]
        execution = runner._build_execution(results)
        assert execution["status"] == "failed"

    def test_duration_sums_all_results(self, mock_config: MagicMock) -> None:
        runner = ParallelRunner(mock_config)
        results = [
            WorkerResult(
                worker_id=0,
                work_unit_id="u1",
                failed=False,
                duration=1.0,
                report_path="tmp/worker_0.json",
            ),
            WorkerResult(
                worker_id=1,
                work_unit_id="u2",
                failed=False,
                duration=2.5,
                report_path="tmp/worker_1.json",
            ),
        ]
        execution = runner._build_execution(results)
        assert execution["duration"] == 3.5
