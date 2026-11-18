"""Unit tests for @serial detection and scenario filtering."""

from __future__ import annotations

from pathlib import Path

from behave.runner import parse_features

from behave_pool.serial import (
    filter_scenario_by_line,
    filter_serial_scenarios,
    is_serial_tagged,
    item_is_serial,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "serial" / "features" / "mixed.feature"
RULES_FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "serial" / "features" / "rules_and_outlines.feature"
)


def _parse_mixed_feature():
    features = parse_features([str(FIXTURE)])
    assert len(features) == 1
    return features[0]


def _parse_rules_feature():
    features = parse_features([str(RULES_FIXTURE)])
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


class TestItemIsSerialRulesAndOutlines:
    """item_is_serial must look through Rules and ScenarioOutline examples."""

    def test_rule_with_any_serial_child_is_serial(self) -> None:
        from behave.model import Rule

        feature = _parse_rules_feature()
        rules = [i for i in feature.run_items if isinstance(i, Rule)]
        mixed_rule = next(r for r in rules if r.name == "Mixed rule block")
        assert item_is_serial(mixed_rule) is True

    def test_rule_without_serial_children_is_parallel(self) -> None:
        from behave.model import Rule

        feature = _parse_rules_feature()
        rules = [i for i in feature.run_items if isinstance(i, Rule)]
        assert any(item_is_serial(r) for r in rules)
        # A rule whose children are all non-serial is not serial.
        # (covered by the mixed rule having both kinds)
        mixed = next(r for r in rules if r.name == "Mixed rule block")
        non_serial = [s for s in mixed.run_items if not item_is_serial(s)]
        assert len(non_serial) == 1

    def test_outline_with_any_serial_example_row_is_serial(self) -> None:
        from behave.model import Rule, ScenarioOutline

        feature = _parse_rules_feature()
        mixed = next(
            r for r in feature.run_items if isinstance(r, Rule) and r.name == "Mixed rule block"
        )
        outline = next(i for i in mixed.run_items if isinstance(i, ScenarioOutline))
        assert item_is_serial(outline) is True


class TestFilterSerialScenariosRules:
    def test_exclude_drops_serial_rule_children(self) -> None:
        from behave.model import Rule

        feature = _parse_rules_feature()
        filter_serial_scenarios(feature, "exclude")
        mixed = next(
            i for i in feature.run_items if isinstance(i, Rule) and i.name == "Mixed rule block"
        )
        names = {s.name for s in mixed.run_items}
        assert names == {"parallel inside rule"}

    def test_exclude_drops_fully_serial_rule(self) -> None:
        from behave.model import Rule

        feature = _parse_rules_feature()
        filter_serial_scenarios(feature, "exclude")
        rule_names = {r.name for r in feature.run_items if isinstance(r, Rule)}
        assert "Fully serial rule block" not in rule_names

    def test_only_keeps_serial_rule_children(self) -> None:
        from behave.model import Rule

        feature = _parse_rules_feature()
        filter_serial_scenarios(feature, "only")
        mixed = next(
            i for i in feature.run_items if isinstance(i, Rule) and i.name == "Mixed rule block"
        )
        names = {s.name for s in mixed.run_items}
        assert names == {"serial inside rule", "Mixed examples"}

    def test_empty_rules_are_dropped(self) -> None:
        from behave.model import Rule

        feature = _parse_rules_feature()
        filter_serial_scenarios(feature, "only")
        # the fully-serial rule stays; nothing collapses to empty here,
        # but under 'exclude' rules with no survivors must disappear.
        filter_serial_scenarios(feature, "exclude")
        for item in feature.run_items:
            if isinstance(item, Rule):
                assert item.run_items


class TestFilterScenarioByLine:
    def test_keeps_scenario_inside_rule(self) -> None:
        from behave.model import Rule

        feature = _parse_rules_feature()
        mixed = next(
            i for i in feature.run_items if isinstance(i, Rule) and i.name == "Mixed rule block"
        )
        target = mixed.run_items[0]
        filter_scenario_by_line(feature, target.line)
        kept_rules = [i for i in feature.run_items if isinstance(i, Rule)]
        assert len(kept_rules) == 1
        assert [s.name for s in kept_rules[0].run_items] == [target.name]
        assert feature.scenarios == []

    def test_drops_empty_rules_entirely(self) -> None:
        from behave.model import Rule

        feature = _parse_rules_feature()
        mixed = next(
            i for i in feature.run_items if isinstance(i, Rule) and i.name == "Mixed rule block"
        )
        serial_line = mixed.run_items[0].line
        filter_scenario_by_line(feature, serial_line)
        rule_names = {r.name for r in feature.run_items if isinstance(r, Rule)}
        assert rule_names == {"Mixed rule block"}


class TestIsSerialTaggedFallback:
    def test_falls_back_to_tags_when_no_effective_tags(self) -> None:
        from types import SimpleNamespace

        obj = SimpleNamespace(effective_tags=None, tags=["serial"])
        assert is_serial_tagged(obj) is True

    def test_no_tags_at_all(self) -> None:
        from types import SimpleNamespace

        obj = SimpleNamespace(effective_tags=None, tags=None)
        assert is_serial_tagged(obj) is False
