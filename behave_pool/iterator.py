"""Strategy pattern for iterating work units from Behave features."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from behave_pool.config import snapshot_config
from behave_pool.work_unit import WorkUnit

if TYPE_CHECKING:
    from behave.configuration import Configuration
    from behave.model import Feature


class WorkUnitIterator(ABC):
    """Abstract strategy for generating WorkUnits from parsed features."""

    @abstractmethod
    def iterate(self) -> Iterator[WorkUnit]:
        """Yield WorkUnit instances one at a time."""
        ...

    @staticmethod
    def for_scheme(
        scheme: str,
        features: list[Feature],
        config: Configuration,
    ) -> WorkUnitIterator:
        """Factory: return the iterator for the given parallel scheme.

        Args:
            scheme: "feature" or "scenario".
            features: Parsed Behave Feature objects.
            config: Coordinator's Configuration (will be deep-copied per unit).

        Returns:
            A WorkUnitIterator instance for the requested scheme.

        Raises:
            ValueError: If scheme is not recognised.
        """
        if scheme == "feature":
            return FeatureIterator(features, config)
        if scheme == "scenario":
            return ScenarioIterator(features, config)
        msg = f"Unknown parallel scheme: {scheme!r}. Use 'feature' or 'scenario'."
        raise ValueError(msg)


class FeatureIterator(WorkUnitIterator):
    """Generate one WorkUnit per feature file.

    Each WorkUnit contains an isolated deep copy of the Configuration
    so that workers can execute independently without shared mutable state.

    When a feature mixes ``@serial`` and non-serial scenarios, it is split
    into two work units: a parallel unit that runs the non-serial
    scenarios (``serial_mode="exclude"``) and a serial unit that runs only
    the ``@serial`` scenarios (``serial_mode="only"``).
    """

    def __init__(self, features: list[Feature], config: Configuration) -> None:
        self._features = features
        self._config = config

    def iterate(self) -> Iterator[WorkUnit]:
        """Yield work units per feature, splitting on the ``@serial`` tag.

        A feature tagged ``@serial`` at feature level produces a single
        serial work unit.  A feature with a mix of ``@serial`` and
        non-serial scenarios produces up to two work units.  Otherwise
        one parallel work unit is produced per feature.
        """
        from behave_pool.serial import is_serial_tagged, item_is_serial

        for feature in self._features:
            feature_tags = {str(t) for t in (getattr(feature, "tags", None) or [])}
            run_items = list(getattr(feature, "run_items", None) or [])
            base_id = f"feature:{feature.filename}"

            if is_serial_tagged(feature):
                tags = set(feature_tags)
                for scenario in getattr(feature, "scenarios", None) or []:
                    tags.update(str(t) for t in (getattr(scenario, "tags", None) or []))
                tags.add("serial")
                yield WorkUnit(
                    id=base_id,
                    config=snapshot_config(self._config),
                    feature_path=feature.filename,
                    scenario_line=None,
                    tags=sorted(tags),
                    serial_mode="all",
                )
                continue

            serial_items = [i for i in run_items if item_is_serial(i)]
            if not serial_items:
                tags = set(feature_tags)
                for scenario in getattr(feature, "scenarios", None) or []:
                    tags.update(str(t) for t in (getattr(scenario, "tags", None) or []))
                yield WorkUnit(
                    id=base_id,
                    config=snapshot_config(self._config),
                    feature_path=feature.filename,
                    scenario_line=None,
                    tags=sorted(tags),
                )
                continue

            # -- MIXED FEATURE: split into parallel + serial units.
            all_tags = set(feature_tags)
            for scenario in getattr(feature, "scenarios", None) or []:
                all_tags.update(str(t) for t in (getattr(scenario, "tags", None) or []))

            parallel_tags = {t for t in all_tags if t != "serial"}
            if any(not item_is_serial(i) for i in run_items):
                yield WorkUnit(
                    id=base_id,
                    config=snapshot_config(self._config),
                    feature_path=feature.filename,
                    scenario_line=None,
                    tags=sorted(parallel_tags),
                    serial_mode="exclude",
                )
            yield WorkUnit(
                id=f"{base_id}#serial",
                config=snapshot_config(self._config),
                feature_path=feature.filename,
                scenario_line=None,
                tags=sorted(all_tags | {"serial"}),
                serial_mode="only",
            )


class ScenarioIterator(WorkUnitIterator):
    """Generate one WorkUnit per scenario run item.

    A unit maps to a single run item: a Scenario or a whole
    ScenarioOutline (all its examples run together — outlines are the
    declaration-level unit).  Scenarios inside ``Rule`` blocks are
    flattened to individual units.

    Items that carry the ``@serial`` tag (directly, via the feature/rule,
    or — for outlines — via any generated example) are produced as serial
    units and run in the serial phase.  In particular, an outline with
    only *some* ``@serial`` example rows runs its whole outline serially:
    conservative, but correct.
    """

    def __init__(self, features: list[Feature], config: Configuration) -> None:
        self._features = features
        self._config = config

    def iterate(self) -> Iterator[WorkUnit]:
        """Yield one work unit per scenario or scenario outline."""
        from behave.model import Rule

        from behave_pool.serial import is_serial_tagged, item_is_serial

        def _items(container: Any) -> Iterator[Any]:
            for item in getattr(container, "run_items", None) or []:
                if isinstance(item, Rule):
                    yield from _items(item)
                else:
                    yield item

        for feature in self._features:
            feature_tags = {str(t) for t in (getattr(feature, "tags", None) or [])}
            feature_serial = is_serial_tagged(feature)
            for item in _items(feature):
                line = getattr(item, "line", None)
                if line is None:
                    continue
                tags = set(feature_tags)
                item_tags = (
                    getattr(item, "effective_tags", None) or getattr(item, "tags", None) or []
                )
                tags.update(str(t) for t in item_tags)
                if feature_serial or item_is_serial(item):
                    tags.add("serial")
                yield WorkUnit(
                    id=f"scenario:{feature.filename}:{line}",
                    config=snapshot_config(self._config),
                    feature_path=feature.filename,
                    scenario_line=line,
                    tags=sorted(tags),
                    serial_mode="all",
                )
