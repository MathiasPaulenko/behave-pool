"""Parallel configuration options for behave-pool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from behave.configuration import Configuration


def _register_parallel_options() -> None:
    """Register --parallel-scheme and --parallel-balance in behave's OPTIONS list (once)."""
    from behave.configuration import OPTIONS

    existing: set[str] = set()
    for fixed, _ in OPTIONS:
        if fixed:
            existing.add(fixed[0])

    if "--parallel-scheme" not in existing:
        OPTIONS.append(
            (
                ("--parallel-scheme",),
                {
                    "dest": "parallel_scheme",
                    "default": "feature",
                    "help": "Parallelization scheme: feature (default: %(default)s).",
                },
            ),
        )

    if "--parallel-balance" not in existing:
        OPTIONS.append(
            (
                ("--parallel-balance",),
                {
                    "dest": "parallel_balance",
                    "default": "lpt",
                    "choices": ["lpt", "fifo"],
                    "help": (
                        "Work unit ordering: lpt (longest first) or fifo (default: %(default)s)."
                    ),
                },
            ),
        )

    if "--parallel-timing-file" not in existing:
        OPTIONS.append(
            (
                ("--parallel-timing-file",),
                {
                    "dest": "parallel_timing_file",
                    "default": ".behave-pool-timing.json",
                    "help": "Path to timing file for LPT balancing (default: %(default)s).",
                },
            ),
        )

    if "--parallel-report" not in existing:
        OPTIONS.append(
            (
                ("--parallel-report",),
                {
                    "dest": "parallel_report",
                    "default": "behave-pool-report.json",
                    "help": "Path to unified JSON report file (default: %(default)s).",
                },
            ),
        )

    if "--shard" not in existing:
        OPTIONS.append(
            (
                ("--shard",),
                {
                    "dest": "shard",
                    "default": None,
                    "help": (
                        "Shard specification for CI: INDEX/TOTAL (e.g. '1/3'). "
                        "Divides the suite into TOTAL shards and runs shard INDEX."
                    ),
                },
            ),
        )


_register_parallel_options()

# -- CONFIG-FILE OPTION NAMES (behave ini keys must match the option dest,
#    i.e. underscores: "parallel_scheme", not "parallel-scheme").
_USERDATA_PREFIX = "pool."


def _userdata_get(config: Configuration, name: str) -> Any:
    """Return ``userdata['pool.<name>']`` or None.

    Behave's ``-D key=value`` / ``[behave.userdata]`` settings are parsed
    before the runner class is loaded, so they are the only behave-pool
    options reachable when using the plain ``behave`` command.
    """
    userdata = getattr(config, "userdata", None) or {}
    get = getattr(userdata, "get", None)
    if get is None:
        return None
    value = get(_USERDATA_PREFIX + name)
    return value if isinstance(value, str) else None


def _resolve_option(config: Configuration, attr: str, default: Any, userdata_name: str) -> Any:
    """Resolve an option value: explicit config value > userdata > default.

    A userdata override is only applied when the config attribute is unset
    or still equals the registered default (i.e. the user did not provide
    an explicit value via CLI flag or ini key).
    """
    value = getattr(config, attr, None)
    if value is None or value == default:
        override = _userdata_get(config, userdata_name)
        if override is not None:
            value = override
    return default if value is None else value


@dataclass(frozen=True)
class ConfigSnapshot:
    """Picklable snapshot of essential Configuration fields for worker processes.

    The full behave Configuration contains non-picklable objects (file
    handles, reporters).  This snapshot captures only the fields needed
    by WorkerRunner to execute features.
    """

    base_dir: str
    steps_dir: str
    environment_file: str
    lang: str | None
    stop: bool
    paths: list[str] = field(default_factory=list)
    parallel: int = 1
    parallel_scheme: str = "feature"
    parallel_balance: str = "lpt"
    parallel_timing_file: str = ".behave-pool-timing.json"
    parallel_report: str = "behave-pool-report.json"
    shard_index: int | None = None
    total_shards: int | None = None
    dry_run: bool = False
    use_nested_step_modules: bool = False
    tags: list[str] | str | None = None
    config_tags: str | list[str] | None = None
    default_tags: str | None = None
    tag_expression_protocol: str | None = None
    name: list[str] | None = None
    userdata: dict[str, Any] = field(default_factory=dict)


def snapshot_config(config: Configuration) -> ConfigSnapshot:
    """Create a picklable snapshot from a Configuration instance."""
    tags = getattr(config, "tags", None)
    if isinstance(tags, (list, tuple)):
        tags = [str(t) for t in tags]
    elif tags is not None:
        tags = str(tags)
    name = getattr(config, "name", None)
    name_list = [str(n) for n in name] if isinstance(name, (list, tuple)) else None
    userdata = getattr(config, "userdata", None) or {}
    if not isinstance(userdata, dict):
        userdata = {}
    return ConfigSnapshot(
        base_dir=str(getattr(config, "base_dir", None) or "features"),
        steps_dir=str(getattr(config, "steps_dir", None) or "steps"),
        environment_file=str(getattr(config, "environment_file", None) or "environment.py"),
        lang=config.lang,
        stop=config.stop,
        paths=[str(p) for p in config.paths] if config.paths else [],
        parallel=getattr(config, "parallel", None) or getattr(config, "jobs", None) or 1,
        parallel_scheme=getattr(config, "parallel_scheme", "feature"),
        parallel_balance=getattr(config, "parallel_balance", "lpt"),
        parallel_timing_file=str(
            getattr(config, "parallel_timing_file", None) or ".behave-pool-timing.json"
        ),
        parallel_report=str(getattr(config, "parallel_report", None) or "behave-pool-report.json"),
        shard_index=getattr(config, "shard_index", None),
        total_shards=getattr(config, "total_shards", None),
        dry_run=config.dry_run,
        use_nested_step_modules=getattr(config, "use_nested_step_modules", False),
        tags=tags,
        config_tags=getattr(config, "config_tags", None),
        default_tags=getattr(config, "default_tags", None),
        tag_expression_protocol=getattr(config, "tag_expression_protocol", None),
        name=name_list,
        userdata=dict(userdata),
    )


def add_parallel_options(config: Configuration) -> None:
    """Add parallel-related attributes to a Configuration instance.

    Maps behave's ``config.jobs`` (from ``--parallel``/``--jobs``) to
    ``config.parallel`` and resolves the behave-pool options.

    Resolution order for each option:

    1. Explicit config value (CLI flag or ini ``dest`` key — only
       reachable when behave-pool's options were registered before
       argument parsing, e.g. via the ``behave-pool`` command or
       ``python -m behave_pool``).
    2. ``userdata`` entry ``pool.<name>`` (works with plain ``behave``
       via ``-D pool.balance=fifo`` or a ``[behave.userdata]`` section).
    3. Registered default.

    Args:
        config: Behave Configuration instance to augment.
    """
    jobs = getattr(config, "jobs", 1)
    if jobs is None or jobs == 1:
        userdata_jobs = _userdata_get(config, "jobs")
        if userdata_jobs is not None:
            import contextlib

            with contextlib.suppress(TypeError, ValueError):
                jobs = int(str(userdata_jobs))
    config.parallel = jobs if jobs else 1

    config.parallel_scheme = _resolve_option(config, "parallel_scheme", "feature", "scheme")
    config.parallel_balance = _resolve_option(config, "parallel_balance", "lpt", "balance")
    config.parallel_timing_file = _resolve_option(
        config, "parallel_timing_file", ".behave-pool-timing.json", "timing_file"
    )
    config.parallel_report = _resolve_option(
        config, "parallel_report", "behave-pool-report.json", "report"
    )

    if not hasattr(config, "use_nested_step_modules"):
        config.use_nested_step_modules = False

    shard_value = getattr(config, "shard", None)
    if shard_value is None:
        shard_value = _userdata_get(config, "shard")
    if shard_value is not None:
        from behave_pool.shard import parse_shard_string

        shard_cfg = parse_shard_string(str(shard_value))
        config.shard_index = shard_cfg.shard_index
        config.total_shards = shard_cfg.total_shards
    else:
        if not hasattr(config, "shard_index"):
            config.shard_index = None
        if not hasattr(config, "total_shards"):
            config.total_shards = None
