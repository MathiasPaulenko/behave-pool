"""ParallelRunner: coordinator that orchestrates parallel feature execution."""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
import queue
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from behave.runner import Runner, make_formatters, parse_features

from behave_pool.config import add_parallel_options, snapshot_config
from behave_pool.iterator import WorkUnitIterator
from behave_pool.result import WorkerResult
from behave_pool.shard import select_shard_work_units
from behave_pool.timing import TimingStore
from behave_pool.worker import WorkerProcess

if TYPE_CHECKING:
    from behave.configuration import Configuration

    from behave_pool.work_unit import WorkUnit

logger = logging.getLogger(__name__)


_SENSITIVE_KEY_RE = re.compile(r"(password|passwd|secret|token|apikey|api_key|credential)", re.I)


def _sanitize_url(url: str) -> str:
    """Remove credentials embedded in a URL (``scheme://user:pass@host``)."""
    if "://" not in url or "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    authority, _, path = rest.partition("/")
    if "@" not in authority:
        return url
    host = authority.rsplit("@", 1)[1]
    return f"{scheme}://{host}/{path}"


def _sanitize_command(cmd: str) -> str:
    """Mask ``-D key=value`` values whose key looks like a credential."""
    import re as _re

    def _mask(match: _re.Match[str]) -> str:
        key = match.group(2)
        if _SENSITIVE_KEY_RE.search(key):
            return f"{match.group(1)}{key}=***"
        return match.group(0)

    return _re.sub(r"(-D\s+|--define\s+)([^\s=]+)=\S+", _mask, cmd)


# Per-work-unit timeout in seconds.  If no result arrives for a pending
# work unit within this window, the involved workers are terminated and
# the remaining units count as failed (missing results).
RESULT_TIMEOUT = 300.0

# Grace period for workers to exit on their own (sentinel consumed)
# before they are terminated forcibly.
WORKER_SHUTDOWN_TIMEOUT = 30.0

# How often _await_results wakes up to check worker liveness/stop event.
_POLL_INTERVAL = 2.0


class ParallelRunner(Runner):  # type: ignore[misc]
    """Coordinator that dispatches work units to worker processes.

    When ``config.parallel <= 1`` it falls back to the standard Behave
    sequential runner.  Otherwise it plans, dispatches, and collects
    results from N worker processes.
    """

    def __init__(self, config: Configuration) -> None:
        super().__init__(config)
        add_parallel_options(config)
        self._early_results: list[WorkerResult] = []
        self._exec_started_at: Any = None
        self._exec_ended_at: Any = None
        self._exec_wall_duration: float | None = None

    def run(self) -> bool:
        """Run the test suite — parallel or sequential depending on config."""
        with self.path_manager:
            self.setup_paths()
            return self.run_with_paths()

    def run_with_paths(self) -> bool:
        """Run tests with configured paths.

        If ``config.parallel <= 1`` delegates to the standard sequential
        runner.  Otherwise enters the parallel pipeline.
        """
        if self.config.parallel <= 1:
            return self._run_sequential()

        return self._run_parallel()

    def _run_sequential(self) -> bool:
        """Standard Behave sequential execution."""
        from behave.runner import Context

        self.context = Context(self)
        self.load_hooks()
        self.load_step_definitions()

        feature_locations = [
            filename for filename in self.feature_locations() if not self.config.exclude(filename)
        ]
        features = parse_features(feature_locations, language=self.config.lang)

        if self._is_sharding_active():
            features = self._filter_features_by_shard(features)
            self._log_shard_info(len(features))

        self.features.extend(features)

        stream_openers = self.config.outputs
        self.formatters = make_formatters(self.config, stream_openers)
        failed: bool = self.run_model()
        return failed

    def _run_parallel(self) -> bool:
        """Execute the parallel pipeline: plan -> shard -> split -> dispatch -> collect."""
        from datetime import UTC, datetime

        ctx = multiprocessing.get_context("spawn")
        task_queue: Any = ctx.JoinableQueue()
        result_queue: Any = ctx.Queue()
        stop_event: Any = ctx.Event()

        self._exec_started_at = datetime.now(UTC)
        started = time.monotonic()
        self._early_results = []
        try:
            work_units = self._plan()
            if self._is_sharding_active():
                work_units = self._apply_shard(work_units)
            parallel_batch, serial_batch = self._split_by_serial_tag(work_units)
            dispatched = self._dispatch(
                task_queue, result_queue, stop_event, parallel_batch, serial_batch, ctx
            )
            return self._collect(result_queue, dispatched)
        finally:
            self._exec_ended_at = datetime.now(UTC)
            self._exec_wall_duration = time.monotonic() - started
            stop_event.set()
            task_queue.close()
            result_queue.close()

    def _plan(self) -> list[WorkUnit]:
        """Parse features and create work units.

        Returns:
            List of work units to execute.
        """
        from behave.runner import Context

        self.context = Context(self)
        self.load_hooks()

        feature_locations = [
            filename for filename in self.feature_locations() if not self.config.exclude(filename)
        ]
        features = parse_features(feature_locations, language=self.config.lang)
        self.features.extend(features)

        iterator = WorkUnitIterator.for_scheme(
            scheme=self.config.parallel_scheme,
            features=features,
            config=self.config,
        )
        work_units = list(iterator.iterate())
        work_units = self._sort_by_duration(work_units)

        return work_units

    def _is_sharding_active(self) -> bool:
        """Check whether sharding is enabled for this run."""
        shard_index = getattr(self.config, "shard_index", None)
        total_shards = getattr(self.config, "total_shards", None)
        return shard_index is not None and total_shards is not None

    def _apply_shard(self, work_units: list[WorkUnit]) -> list[WorkUnit]:
        """Filter work units to only those in the current shard.

        Shard membership is computed on ids sorted deterministically, but
        the returned list preserves the planned (LPT/FIFO) order.

        Args:
            work_units: All planned work units.

        Returns:
            Work units belonging to the current shard.
        """
        shard_index = int(getattr(self.config, "shard_index", 0))
        total_shards = int(getattr(self.config, "total_shards", 0))
        selected = select_shard_work_units(work_units, shard_index, total_shards)
        self._log_shard_info(len(selected), total=len(work_units))
        return selected

    def _filter_features_by_shard(self, features: list[Any]) -> list[Any]:
        """Filter parsed features to only those in the current shard.

        In sequential mode, sharding operates at feature level: features are
        sorted by ``filename`` (matching the parallel mode's work-unit id sort)
        and split into shards.  Only features in the current shard are kept.

        Args:
            features: All parsed features.

        Returns:
            Features belonging to the current shard.
        """
        shard_index = int(getattr(self.config, "shard_index", 0))
        total_shards = int(getattr(self.config, "total_shards", 0))
        sorted_features = sorted(features, key=lambda f: getattr(f, "filename", "") or "")
        from behave_pool.shard import split_shards

        return split_shards(sorted_features, shard_index, total_shards)

    def _log_shard_info(self, selected_count: int, total: int | None = None) -> None:
        """Log shard metadata for visibility in CI output."""
        shard_index = getattr(self.config, "shard_index", None)
        total_shards = getattr(self.config, "total_shards", None)
        if shard_index is None or total_shards is None:
            return
        if total is not None:
            logger.info(
                "Shard %d/%d - %d work units selected (of %d total)",
                shard_index,
                total_shards,
                selected_count,
                total,
            )
        else:
            logger.info(
                "Shard %d/%d - %d features selected",
                shard_index,
                total_shards,
                selected_count,
            )

    def _sort_by_duration(self, units: list[WorkUnit]) -> list[WorkUnit]:
        """Sort work units by historical duration (LPT) or keep FIFO order.

        When ``config.parallel_balance`` is ``"lpt"``, units are sorted
        descending by their stored duration in the TimingStore so that
        the longest jobs start first, improving overall wall-clock time.

        When ``config.parallel_balance`` is ``"fifo"``, the original
        order is preserved.

        Args:
            units: Work units to sort.

        Returns:
            Sorted list of work units.
        """
        balance = getattr(self.config, "parallel_balance", "lpt")
        if balance == "fifo":
            return units

        timing_file = (
            getattr(self.config, "parallel_timing_file", None) or ".behave-pool-timing.json"
        )
        store = TimingStore(path=Path(timing_file))
        store.load()
        return sorted(units, key=lambda u: store.get_duration(u.id), reverse=True)

    @staticmethod
    def _split_by_serial_tag(
        units: list[WorkUnit],
    ) -> tuple[list[WorkUnit], list[WorkUnit]]:
        """Split work units into parallel and serial batches.

        Args:
            units: All work units to split.

        Returns:
            Tuple of (parallel_batch, serial_batch).
        """
        parallel_batch = [u for u in units if not u.is_serial]
        serial_batch = [u for u in units if u.is_serial]
        return parallel_batch, serial_batch

    def _dispatch(
        self,
        task_queue: Any,
        result_queue: Any,
        stop_event: Any,
        parallel_batch: list[WorkUnit],
        serial_batch: list[WorkUnit],
        ctx: Any,
    ) -> list[WorkUnit]:
        """Two-phase dispatch: parallel first, then serial.

        Phase 1: enqueue parallel_batch, launch up to N workers (never more
        than there are work units), collect each result as it arrives.
        Phase 2: enqueue serial_batch, launch 1 worker, collect results.

        Results are collected while dispatching so that the per-unit
        timeout (:data:`RESULT_TIMEOUT`) applies to each work unit rather
        than to a whole phase.

        Returns:
            List of work units that were actually enqueued (dispatched).
        """
        config_snapshot = snapshot_config(self.config)
        dispatched: list[WorkUnit] = []

        # -- Phase 1: parallel batch with N workers.
        if parallel_batch:
            n_workers = min(self.config.parallel, len(parallel_batch))
            for unit in parallel_batch:
                task_queue.put(unit)
            for _ in range(n_workers):
                task_queue.put(None)
            dispatched.extend(parallel_batch)

            workers: list[WorkerProcess] = []
            for worker_id in range(n_workers):
                worker = WorkerProcess(
                    worker_id=worker_id,
                    task_queue=task_queue,
                    result_queue=result_queue,
                    stop_event=stop_event,
                    config_snapshot=config_snapshot,
                    ctx=ctx,
                )
                worker.start()
                workers.append(worker)

            self._early_results.extend(
                self._await_results(result_queue, stop_event, parallel_batch, workers)
            )
            self._shutdown_workers(workers, stop_event)
            self._drain_queue(task_queue)

        # -- Phase 2: serial batch with 1 worker.
        if serial_batch and not stop_event.is_set():
            for unit in serial_batch:
                task_queue.put(unit)
            task_queue.put(None)
            dispatched.extend(serial_batch)

            serial_worker = WorkerProcess(
                worker_id=0,
                task_queue=task_queue,
                result_queue=result_queue,
                stop_event=stop_event,
                config_snapshot=config_snapshot,
                ctx=ctx,
            )
            serial_worker.start()

            self._early_results.extend(
                self._await_results(result_queue, stop_event, serial_batch, [serial_worker])
            )
            self._shutdown_workers([serial_worker], stop_event)
            self._drain_queue(task_queue)

        return dispatched

    def _await_results(
        self,
        result_queue: Any,
        stop_event: Any,
        units: list[WorkUnit],
        workers: list[WorkerProcess],
    ) -> list[WorkerResult]:
        """Collect results for ``units`` while the workers are running.

        Each work unit may take up to :data:`RESULT_TIMEOUT` seconds; the
        clock restarts with every received result.  When a unit times out,
        the workers are terminated and the pending units count as missing.
        If ``config.stop`` is set, the first failure sets ``stop_event`` so
        workers drop all queued units.
        """
        pending = {u.id for u in units}
        results: list[WorkerResult] = []
        last_result_at = time.monotonic()
        while pending:
            try:
                result = result_queue.get(timeout=_POLL_INTERVAL)
            except queue.Empty:
                result = None
            except (EOFError, OSError):
                break
            if result is not None:
                results.append(result)
                pending.discard(result.work_unit_id)
                last_result_at = time.monotonic()
                self._print_progress(result)
                if result.failed and self.config.stop:
                    stop_event.set()
            if not pending:
                break
            if time.monotonic() - last_result_at >= RESULT_TIMEOUT:
                logger.warning(
                    "No worker result within %ds; terminating worker(s).",
                    int(RESULT_TIMEOUT),
                )
                stop_event.set()
                break
            if all(not w.is_alive() for w in workers):
                # All workers exited/crashed — drain anything still in flight.
                results.extend(self._drain_results(result_queue, pending))
                break
        return results

    def _drain_results(self, result_queue: Any, pending: set[str]) -> list[WorkerResult]:
        """Drain already-produced results after workers exited."""
        results: list[WorkerResult] = []
        deadline = time.monotonic() + 5.0
        while pending and time.monotonic() < deadline:
            try:
                result = result_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                break
            results.append(result)
            pending.discard(result.work_unit_id)
            self._print_progress(result)
        return results

    def _shutdown_workers(self, workers: list[WorkerProcess], stop_event: Any) -> None:
        """Wait briefly for workers to exit, then terminate stragglers."""
        for worker in workers:
            worker.join(timeout=WORKER_SHUTDOWN_TIMEOUT)
            if worker.is_alive():
                logger.warning(
                    "Worker %d did not terminate; setting stop event and terminating.",
                    worker.worker_id,
                )
                stop_event.set()
                worker.terminate()

    @staticmethod
    def _drain_queue(task_queue: Any) -> None:
        """Drain any unconsumed items so the queue is empty for the next phase."""
        while not task_queue.empty():
            try:
                task_queue.get_nowait()
                task_queue.task_done()
            except queue.Empty:
                break

    @staticmethod
    def _print_progress(result: WorkerResult) -> None:
        """Print one line per finished work unit (replaces formatter output)."""
        status = "FAILED" if result.failed else "passed"
        if result.error:
            status = f"ERROR ({result.error})"
        print(f"{result.work_unit_id} ... {status} ({result.duration:.2f}s)")

    def _collect(
        self,
        result_queue: Any,
        work_units: list[WorkUnit],
        deadline_seconds: float = 30,
    ) -> bool:
        """Drain result queue, merge results, and compute exit code.

        Returns:
            True if any test failed (Behave convention).
        """
        expected = len(work_units)
        results: list[WorkerResult] = list(self._early_results)
        received_ids: set[str] = {r.work_unit_id for r in results}

        # Drain all available results, waiting up to deadline_seconds for late arrivals.
        deadline = time.monotonic() + deadline_seconds
        while len(results) < expected and time.monotonic() < deadline:
            try:
                result = result_queue.get(timeout=1)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                break
            if result.work_unit_id in received_ids:
                continue
            results.append(result)
            received_ids.add(result.work_unit_id)

        # Detect missing results from crashed or timed-out workers.
        missing = [u.id for u in work_units if u.id not in received_ids]
        if missing:
            logger.warning(
                "Missing %d result(s) from worker(s): %s",
                len(missing),
                ", ".join(missing),
            )

        any_failed = any(r.failed for r in results)

        # Missing results indicate worker crashes — treat as failures.
        if missing:
            any_failed = True

        # Propagate undefined steps so --show-snippets works in parallel.
        seen_undefined: set[str] = set()
        for r in results:
            for step_text in r.undefined_steps:
                if step_text not in seen_undefined:
                    seen_undefined.add(step_text)
                    self.undefined_steps.append(step_text)

        self._update_timings(results, work_units)

        statistics = self._merge_reports(results)
        if statistics is not None:
            print(
                f"{statistics['features']} features, {statistics['scenarios']} scenarios, "
                f"{statistics['steps']} steps - "
                f"passed: {statistics['passed']}, failed: {statistics['failed']}, "
                f"skipped: {statistics['skipped']}, undefined: {statistics['undefined']}"
            )

        logger.info(
            "Parallel run complete: %d work units, %d results, failed=%s",
            len(work_units),
            len(results),
            any_failed,
        )

        return any_failed

    def _update_timings(
        self, results: list[WorkerResult], work_units: list[WorkUnit] | None = None
    ) -> None:
        """Update the TimingStore with observed durations from results.

        Entries whose feature file no longer exists are pruned so that
        renamed or deleted features do not accumulate forever.

        Timing persistence is best-effort: any failure is logged and
        does not affect the test run outcome.

        Args:
            results: Worker results containing durations to persist.
            work_units: Dispatched work units (unused; kept for
                backward compatibility of the method signature).
        """
        timing_file = (
            getattr(self.config, "parallel_timing_file", None) or ".behave-pool-timing.json"
        )
        try:
            store = TimingStore(path=Path(timing_file))
            store.load()
            for result in results:
                store.update(result.work_unit_id, result.duration)
            store.prune_stale()
            store.save_if_changed()
        except Exception:
            logger.warning(
                "Failed to update timing file %s; timings will not persist.", timing_file
            )

    def _merge_reports(self, results: list[WorkerResult]) -> dict[str, Any] | None:
        """Merge per-worker JSON reports into a unified Behave-compatible JSON.

        Reads each worker's report file (pointed to by WorkerResult.report_path),
        collects all feature dicts, computes aggregate statistics, detects the
        runtime environment, and writes a full behave-modern-json-report
        ExecutionReport JSON to the path specified by ``--parallel-report``.

        After merging, the temporary ``tmp/`` directory is cleaned up.

        Args:
            results: Worker results with report paths to merge.

        Returns:
            The computed statistics dict, or None if writing failed.
        """
        import json

        all_features: list[dict[str, Any]] = []

        for result in results:
            if not result.report_path:
                continue
            try:
                report_file = Path(result.report_path)
                if report_file.exists():
                    data = json.loads(report_file.read_text(encoding="utf-8"))
                    all_features.extend(data.get("features", []))
            except Exception:
                logger.warning("Failed to read worker report %s; skipping.", result.report_path)

        # Same file may appear in several work units (scenario scheme or a
        # mixed feature split into parallel/serial halves) — merge those
        # partial entries into a single feature dict.
        all_features = self._merge_feature_dicts(all_features)

        statistics: dict[str, Any] | None = self._compute_statistics(all_features)
        environment = self._detect_environment()
        execution = self._build_execution(results)

        report = {
            "schemaVersion": "1.1.0",
            "execution": execution,
            "statistics": statistics,
            "environment": environment,
            "features": all_features,
            "metadata": {},
        }

        report_path = Path(
            getattr(self.config, "parallel_report", None) or "behave-pool-report.json"
        )
        try:
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Unified report written to %s", report_path)
        except Exception:
            logger.warning("Failed to write unified report to %s", report_path)
            statistics = None

        tmp_dir = Path("tmp")
        if tmp_dir.is_dir():
            for report_file in tmp_dir.glob("worker_*.json"):
                with contextlib.suppress(OSError):
                    report_file.unlink()
            if not any(tmp_dir.iterdir()):
                with contextlib.suppress(OSError):
                    tmp_dir.rmdir()

        return statistics

    @staticmethod
    def _merge_feature_dicts(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge partial feature dicts that share the same ``filename``.

        Work units that split a feature (``#serial`` halves or per-scenario
        units under ``--parallel-scheme scenario``) produce one report entry
        each; they are combined so every file appears once, with all its
        scenarios, summed duration, and the worst scenario status.
        """
        severity = {
            "untested": 0,
            "skipped": 1,
            "passed": 2,
            "pending": 3,
            "undefined": 3,
            "failed": 4,
            "error": 4,
            "hook_error": 4,
            "cleanup_error": 4,
        }
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for feature in features:
            key = str(feature.get("filename") or feature.get("id") or id(feature))
            if key not in merged:
                entry = dict(feature)
                entry["scenarios"] = list(feature.get("scenarios") or [])
                merged[key] = entry
                order.append(key)
                continue
            entry = merged[key]
            entry["scenarios"].extend(feature.get("scenarios") or [])
            entry["duration"] = (entry.get("duration") or 0.0) + (feature.get("duration") or 0.0)
        for key in order:
            entry = merged[key]
            scenarios = entry["scenarios"]
            if not scenarios:
                continue
            worst = max(
                (str(s.get("status", "untested")) for s in scenarios),
                key=lambda s: severity.get(s, 0),
            )
            entry["status"] = worst if worst in severity else "untested"
        return [merged[k] for k in order]

    def _compute_statistics(self, features: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate statistics from merged feature dicts."""
        _status_fields = {
            "passed": "passed",
            "failed": "failed",
            "skipped": "skipped",
            "undefined": "undefined",
            "pending": "pending",
        }
        _failed_statuses = frozenset({"failed", "error", "hook_error", "cleanup_error"})

        feature_count = 0
        scenario_count = 0
        step_count = 0
        counts: dict[str, int] = dict.fromkeys(_status_fields.values(), 0)
        total_duration = 0.0
        error_count = 0
        slowest_step_duration = 0.0
        all_durations: list[float] = []
        exception_counts: dict[str, int] = {}
        by_tag: dict[str, dict[str, Any]] = {}

        for feature in features:
            feature_count += 1
            feature_duration = 0.0

            for scenario in feature.get("scenarios", []) or []:
                scenario_count += 1
                scenario_duration = 0.0

                for step in scenario.get("steps", []) or []:
                    step_count += 1
                    status = step.get("status", "untested")
                    field_name = _status_fields.get(status)
                    if field_name is not None:
                        counts[field_name] += 1
                    step_duration = step.get("duration", 0.0) or 0.0
                    scenario_duration += step_duration
                    if status in _failed_statuses:
                        error_count += 1
                    slowest_step_duration = max(slowest_step_duration, step_duration)
                    error = step.get("error")
                    if error and error.get("type"):
                        etype = error["type"]
                        exception_counts[etype] = exception_counts.get(etype, 0) + 1

                scenario_duration = scenario.get("duration", 0.0) or scenario_duration
                all_durations.append(scenario_duration)
                feature_duration += scenario_duration

                scenario_tags = set(scenario.get("tags", []) or [])
                feature_tags = set(feature.get("tags", []) or [])
                for tag in scenario_tags | feature_tags:
                    tag_data = by_tag.setdefault(
                        tag,
                        {
                            "count": 0,
                            "duration": 0.0,
                            "passed": 0,
                            "failed": 0,
                            "skipped": 0,
                            "undefined": 0,
                            "pending": 0,
                            "untested": 0,
                            "error": 0,
                            "hook_error": 0,
                            "cleanup_error": 0,
                            "xfailed": 0,
                            "xpassed": 0,
                        },
                    )
                    tag_data["count"] += 1
                    tag_data["duration"] += scenario_duration
                    s = scenario.get("status", "passed")
                    if s in tag_data:
                        tag_data[s] += 1

            total_duration += feature.get("duration", 0.0) or feature_duration

        total_terminal = counts["passed"] + counts["failed"]
        pass_rate = (counts["passed"] / total_terminal) if total_terminal else 0.0
        avg_scenario_duration = sum(all_durations) / len(all_durations) if all_durations else 0.0
        common_exception_type = (
            max(exception_counts, key=lambda k: exception_counts.get(k, 0))
            if exception_counts
            else None
        )

        stats: dict[str, Any] = {
            "features": feature_count,
            "scenarios": scenario_count,
            "steps": step_count,
            "passed": counts["passed"],
            "failed": counts["failed"],
            "skipped": counts["skipped"],
            "undefined": counts["undefined"],
            "pending": counts["pending"],
            "passRate": round(pass_rate, 6),
            "duration": round(total_duration, 6),
            "errorCount": error_count,
            "totalAttachments": 0,
            "totalLogs": 0,
            "slowestStepDuration": round(slowest_step_duration, 6),
            "avgScenarioDuration": round(avg_scenario_duration, 6),
            "byTag": by_tag,
        }
        if common_exception_type is not None:
            stats["commonExceptionType"] = common_exception_type
        return stats

    def _detect_environment(self) -> dict[str, Any]:
        """Detect runtime environment for the report."""
        import os
        import platform as _platform
        import socket
        import subprocess
        import sys

        env: dict[str, Any] = {}

        env["pythonVersion"] = sys.version.split(" ", 1)[0]
        env["platform"] = sys.platform
        env["os"] = _platform.system() or "Unknown"
        env["osVersion"] = _platform.release() or "Unknown"

        try:
            env["hostname"] = socket.gethostname() or "unknown"
        except Exception:
            env["hostname"] = "unknown"

        ci_env = os.environ
        if ci_env.get("GITHUB_ACTIONS") == "true":
            env["ciProvider"] = "github-actions"
        elif ci_env.get("GITLAB_CI"):
            env["ciProvider"] = "gitlab-ci"
        elif ci_env.get("JENKINS_URL"):
            env["ciProvider"] = "jenkins"
        elif ci_env.get("CI"):
            env["ciProvider"] = "ci"

        cwd = os.getcwd()
        if cwd:
            env["cwd"] = cwd

        cmd = _sanitize_command(" ".join(sys.argv))
        if cmd:
            env["command"] = cmd

        try:
            import getpass

            env["user"] = getpass.getuser()
        except Exception:
            pass

        cpu = os.cpu_count()
        if cpu:
            env["cpuCount"] = cpu

        try:
            import behave

            bv = str(getattr(behave, "__version__", "") or "")
            if bv:
                env["behaveVersion"] = bv
        except Exception:
            pass

        git_info: dict[str, str] = {}
        try:
            for key, git_cmd in [
                ("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
                ("commit", ["git", "rev-parse", "--short", "HEAD"]),
                ("remote", ["git", "remote", "get-url", "origin"]),
            ]:
                result = subprocess.run(
                    git_cmd, capture_output=True, text=True, timeout=2, check=False
                )
                if result.returncode == 0:
                    git_info[key] = result.stdout.strip()
        except Exception:
            pass

        if git_info.get("branch"):
            env["gitBranch"] = git_info["branch"]
        if git_info.get("commit"):
            env["gitCommit"] = git_info["commit"]
        if git_info.get("remote"):
            env["gitRemote"] = _sanitize_url(git_info["remote"])

        return env

    def _build_execution(self, results: list[WorkerResult]) -> dict[str, Any]:
        """Build the execution metadata block."""
        import uuid
        from datetime import UTC, datetime

        started_at = getattr(self, "_exec_started_at", None)
        ended_at = getattr(self, "_exec_ended_at", None) or datetime.now(UTC)
        if started_at is None:
            started_at = ended_at
        wall_duration = getattr(self, "_exec_wall_duration", None)
        if wall_duration is None:
            wall_duration = sum(r.duration for r in results)
        any_failed = any(r.failed for r in results)

        execution: dict[str, Any] = {
            "executionId": f"exec-{uuid.uuid4().hex}",
            "status": "failed" if any_failed else "passed",
            "duration": round(wall_duration, 6),
            "startTime": started_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "endTime": ended_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        return execution
