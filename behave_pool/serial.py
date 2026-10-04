"""Shared ``@serial`` tag detection and scenario filtering.

The ``@serial`` tag can appear at feature, rule, scenario, scenario-outline,
or examples level.  Both the coordinator (planning) and the workers
(execution) use these helpers so that the two phases agree on which
scenarios are serial.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from behave.model import Feature

SERIAL_TAG = "serial"


def is_serial_tagged(obj: Any) -> bool:
    """Return True if ``serial`` is among the object's effective tags.

    Effective tags include tags inherited from the parent feature or rule.
    """
    tags = getattr(obj, "effective_tags", None)
    if tags is None:
        tags = getattr(obj, "tags", None) or []
    return SERIAL_TAG in {str(t) for t in tags}


def item_is_serial(item: Any) -> bool:
    """Return True if a run item (Scenario/ScenarioOutline/Rule) is serial.

    A rule or outline is serial when it is tagged ``@serial`` itself or when
    any of its contained scenarios are serial.
    """
    from behave.model import Rule, ScenarioOutline

    if isinstance(item, Rule):
        return is_serial_tagged(item) or any(item_is_serial(i) for i in item.run_items)
    if isinstance(item, ScenarioOutline):
        return is_serial_tagged(item) or any(is_serial_tagged(s) for s in item.scenarios)
    return is_serial_tagged(item)


def filter_serial_scenarios(feature: Feature, serial_mode: str) -> None:
    """Remove non-matching scenarios from a feature, in place.

    Args:
        feature: Parsed Behave Feature (freshly parsed by the worker).
        serial_mode: ``"only"`` keeps serial scenarios, ``"exclude"`` drops
            them, ``"all"`` is a no-op.
    """
    if serial_mode == "all":
        return
    _filter_container(feature, serial_mode)


def _filter_container(container: Any, serial_mode: str) -> None:
    """Filter ``container.run_items``/``scenarios`` by serial membership."""
    from behave.model import Rule

    keep = serial_mode == "only"
    kept: list[Any] = []
    for item in container.run_items:
        if isinstance(item, Rule):
            if is_serial_tagged(item):
                if keep:
                    kept.append(item)
                continue
            _filter_container(item, serial_mode)
            if item.run_items:
                kept.append(item)
            continue
        if item_is_serial(item) == keep:
            kept.append(item)
    kept_ids = {id(i) for i in kept}
    container.run_items[:] = kept
    container.scenarios[:] = [s for s in container.scenarios if id(s) in kept_ids]


def filter_scenario_by_line(feature: Feature, line: int) -> None:
    """Keep only the run item declared at ``line``, in place.

    A run item is a Scenario or a whole ScenarioOutline (outlines keep
    all their expanded examples as one unit, since ``feature.scenarios``
    exposes only the outline template anyway).  Rules are traversed
    recursively and dropped when left empty.

    Args:
        feature: Parsed Behave Feature (freshly parsed by the worker).
        line: Declaration line of the scenario/outline to keep.
    """
    _filter_container_by_line(feature, line)


def _filter_container_by_line(container: Any, line: int) -> None:
    """Keep only the run item whose declaration line matches ``line``."""
    from behave.model import Rule

    kept: list[Any] = []
    for item in container.run_items:
        if isinstance(item, Rule):
            _filter_container_by_line(item, line)
            if item.run_items:
                kept.append(item)
            continue
        if getattr(item, "line", None) == line:
            kept.append(item)
    container.run_items[:] = kept
    # ``scenarios`` lists the declaration-line items (plain scenarios and
    # the ScenarioOutline itself), so a plain line match is correct.
    container.scenarios[:] = [s for s in container.scenarios if getattr(s, "line", None) == line]
