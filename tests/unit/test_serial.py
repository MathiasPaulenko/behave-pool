"""Unit tests for @serial detection and scenario filtering."""

from __future__ import annotations

from pathlib import Path

from behave.runner import parse_features

from behave_pool.serial import filter_serial_scenarios, is_serial_tagged

FIXTURE = Path(__file__).parent.parent / "fixtures" / "serial" / "features" / "mixed.feature"


def _parse_mixed_feature():
    features = parse_features([str(FIXTURE)])
    assert len(features) == 1
    return features[0]


class TestIsSerialTagged:
    def test_serial_scenario_detected(self) -> None:
        feature = _parse_mixed_feature()
        serial = [s for s in feature.scenarios if "serial" in s.effective_tags]
        assert len(serial) == 2
        assert all(is_serial_tagged(s) for s in serial)

    def test_parallel_scenario_not_detected(self) -> None:
        feature = _parse_mixed_feature()
        parallel = [s for s in feature.scenarios if "serial" not in s.effective_tags]
        assert len(parallel) == 2
        assert all(not is_serial_tagged(s) for s in parallel)


class TestFilterSerialScenarios:
    def test_exclude_drops_serial_scenarios(self) -> None:
        feature = _parse_mixed_feature()
        filter_serial_scenarios(feature, "exclude")
        assert len(feature.scenarios) == 2
        assert all("serial" not in s.effective_tags for s in feature.scenarios)

    def test_only_keeps_serial_scenarios(self) -> None:
        feature = _parse_mixed_feature()
        filter_serial_scenarios(feature, "only")
        assert len(feature.scenarios) == 2
        assert all("serial" in s.effective_tags for s in feature.scenarios)

    def test_all_is_noop(self) -> None:
        feature = _parse_mixed_feature()
        filter_serial_scenarios(feature, "all")
        assert len(feature.scenarios) == 4

    def test_only_and_exclude_partition_the_feature(self) -> None:
        only = _parse_mixed_feature()
        exclude = _parse_mixed_feature()
        filter_serial_scenarios(only, "only")
        filter_serial_scenarios(exclude, "exclude")
        names_only = {s.name for s in only.scenarios}
        names_exclude = {s.name for s in exclude.scenarios}
        original = {s.name for s in _parse_mixed_feature().scenarios}
        assert names_only.isdisjoint(names_exclude)
        assert names_only | names_exclude == original
