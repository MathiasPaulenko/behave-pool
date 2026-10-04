"""Tests for WorkUnitIterator and FeatureIterator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from behave.model import Feature, Scenario

from behave_pool.iterator import FeatureIterator, ScenarioIterator, WorkUnitIterator


def _make_feature(
    filename: str,
    tags: list[str] | None = None,
    scenarios: list[Scenario] | None = None,
) -> Feature:
    feature = Feature(
        filename=filename,
        line=1,
        keyword="Feature",
        name=filename,
        tags=tags or [],
    )
    if scenarios:
        feature.scenarios = scenarios
    return feature


def _make_scenario(name: str, tags: list[str] | None = None) -> Scenario:
    return Scenario(
        filename="",
        line=0,
        keyword="Scenario",
        name=name,
        tags=tags or [],
    )


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock()
    config.paths = ["features/"]
    return config


@pytest.fixture
def sample_features() -> list[Feature]:
    return [
        _make_feature("login.feature", tags=["smoke"]),
        _make_feature("checkout.feature", tags=["regression", "serial"]),
        _make_feature("search.feature"),
    ]


class TestFeatureIterator:
    def test_generates_n_units_for_n_features(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        iterator = FeatureIterator(sample_features, mock_config)
        units = list(iterator.iterate())
        assert len(units) == 3

    def test_unit_ids(self, sample_features: list[Feature], mock_config: MagicMock) -> None:
        iterator = FeatureIterator(sample_features, mock_config)
        units = list(iterator.iterate())
        assert units[0].id == "feature:login.feature"
        assert units[1].id == "feature:checkout.feature"
        assert units[2].id == "feature:search.feature"

    def test_unit_feature_path(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        iterator = FeatureIterator(sample_features, mock_config)
        units = list(iterator.iterate())
        assert units[0].feature_path == "login.feature"
        assert units[1].feature_path == "checkout.feature"

    def test_unit_scenario_line_is_none(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        iterator = FeatureIterator(sample_features, mock_config)
        for unit in iterator.iterate():
            assert unit.scenario_line is None

    def test_unit_tags_propagated(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        iterator = FeatureIterator(sample_features, mock_config)
        units = list(iterator.iterate())
        assert set(units[0].tags) == {"smoke"}
        assert set(units[1].tags) == {"regression", "serial"}
        assert units[2].tags == []

    def test_scenario_tags_propagated(self, mock_config: MagicMock) -> None:
        """Tags from scenarios are collected into the work unit."""
        feature = _make_feature(
            "mixed.feature",
            tags=["smoke"],
            scenarios=[
                _make_scenario("S1", tags=["fast"]),
                _make_scenario("S2", tags=["serial"]),
            ],
        )
        iterator = FeatureIterator([feature], mock_config)
        units = list(iterator.iterate())
        assert "smoke" in units[0].tags
        assert "fast" in units[0].tags
        assert "serial" in units[0].tags
        assert units[0].is_serial

    def test_none_tags_handled_gracefully(self, mock_config: MagicMock) -> None:
        """When feature.tags or scenario.tags is None, iterate must not
        raise TypeError. Tags should be treated as an empty collection.
        """
        feature = _make_feature("notags.feature", tags=None)
        feature.scenarios = [_make_scenario("S1", tags=None)]
        iterator = FeatureIterator([feature], mock_config)
        units = list(iterator.iterate())
        assert len(units) == 1
        assert units[0].tags == []

    def test_config_is_deepcopy(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        iterator = FeatureIterator(sample_features, mock_config)
        units = list(iterator.iterate())
        # Each unit's config must be a distinct object (deep copy)
        assert units[0].config is not mock_config
        assert units[1].config is not mock_config
        assert units[0].config is not units[1].config

    def test_config_paths_deepcopied(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        original_paths = mock_config.paths
        iterator = FeatureIterator(sample_features, mock_config)
        units = list(iterator.iterate())
        # Modifying one unit's config.paths must not affect the original
        units[0].config.paths.append("modified/")
        assert mock_config.paths == original_paths


class TestForScheme:
    def test_feature_scheme_returns_feature_iterator(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        iterator = WorkUnitIterator.for_scheme("feature", sample_features, mock_config)
        assert isinstance(iterator, FeatureIterator)

    def test_invalid_scheme_raises_value_error(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="Unknown parallel scheme"):
            WorkUnitIterator.for_scheme("invalid", sample_features, mock_config)

    def test_scenario_scheme_returns_scenario_iterator(
        self, sample_features: list[Feature], mock_config: MagicMock
    ) -> None:
        iterator = WorkUnitIterator.for_scheme("scenario", sample_features, mock_config)
        assert isinstance(iterator, ScenarioIterator)


class TestSerialSplit:
    """A feature mixing @serial and non-serial scenarios splits in two units."""

    def _mixed_features(self):
        from pathlib import Path

        from behave.runner import parse_features

        fixture = (
            Path(__file__).parent.parent / "fixtures" / "serial" / "features" / "mixed.feature"
        )
        return parse_features([str(fixture)])

    def test_mixed_feature_splits(self, mock_config: MagicMock) -> None:
        features = self._mixed_features()
        units = list(FeatureIterator(features, mock_config).iterate())
        assert len(units) == 2
        parallel, serial = units
        assert parallel.id.endswith("mixed.feature")
        assert parallel.serial_mode == "exclude"
        assert "serial" not in parallel.tags
        assert serial.id == f"{parallel.id}#serial"
        assert serial.serial_mode == "only"
        assert "serial" in serial.tags
        assert serial.is_serial

    def test_serial_only_feature_single_unit(self, mock_config: MagicMock) -> None:
        features = self._mixed_features()
        for f in features:
            f.tags = ["serial"]
        units = list(FeatureIterator(features, mock_config).iterate())
        assert len(units) == 1
        assert units[0].serial_mode == "all"
        assert units[0].is_serial


class TestScenarioIterator:
    """Scenario-level scheme: one work unit per scenario run item."""

    def _parse(self, *names: str):
        from pathlib import Path

        from behave.runner import parse_features

        base = Path(__file__).parent.parent / "fixtures"
        paths = []
        for name in names:
            paths.extend(str(p) for p in base.rglob(name))
        return parse_features(paths)

    def test_one_unit_per_scenario(self, mock_config: MagicMock) -> None:
        features = self._parse("mixed.feature")
        units = list(ScenarioIterator(features, mock_config).iterate())
        # mixed.feature has 4 scenarios: 2 parallel + 2 @serial
        assert len(units) == 4
        assert all(u.scenario_line is not None for u in units)
        assert all(u.id.startswith("scenario:") for u in units)
        assert len({u.id for u in units}) == 4

    def test_serial_scenarios_become_serial_units(self, mock_config: MagicMock) -> None:
        features = self._parse("mixed.feature")
        units = list(ScenarioIterator(features, mock_config).iterate())
        serial_units = [u for u in units if u.is_serial]
        parallel_units = [u for u in units if not u.is_serial]
        assert len(serial_units) == 2
        assert len(parallel_units) == 2

    def test_serial_feature_makes_all_units_serial(self, mock_config: MagicMock) -> None:
        features = self._parse("mixed.feature")
        for f in features:
            f.tags = ["serial"]
            # effective_tags must reflect the change for children
        units = list(ScenarioIterator(features, mock_config).iterate())
        assert len(units) == 4
        assert all(u.is_serial for u in units)

    def test_simple_features_all_parallel(self, mock_config: MagicMock) -> None:
        features = self._parse("checkout.feature", "login.feature")
        units = list(ScenarioIterator(features, mock_config).iterate())
        assert len(units) == 4  # 2 scenarios each
        assert all(not u.is_serial for u in units)
