"""Unit tests for TimingStore."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from behave_pool.timing import TimingStore


class TestLoad:
    def test_load_valid_file(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(
            json.dumps({"feature:login": 1.5, "feature:checkout": 0.3}),
            encoding="utf-8",
        )
        store = TimingStore(path=timing_file)
        data = store.load()
        assert data == {"feature:login": 1.5, "feature:checkout": 0.3}

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        store = TimingStore(path=tmp_path / "nonexistent.json")
        data = store.load()
        assert data == {}

    def test_load_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text("{invalid json", encoding="utf-8")
        store = TimingStore(path=timing_file)
        data = store.load()
        assert data == {}

    def test_load_non_dict_json_returns_empty(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text("[1, 2, 3]", encoding="utf-8")
        store = TimingStore(path=timing_file)
        data = store.load()
        assert data == {}

    def test_load_corrupt_does_not_raise(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text("not json at all", encoding="utf-8")
        store = TimingStore(path=timing_file)
        with caplog.at_level(logging.WARNING):
            data = store.load()
        assert data == {}
        assert "corrupt" in caplog.text.lower()

    def test_load_coerces_values_to_float(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(
            json.dumps({"u1": 1, "u2": "2.5"}),
            encoding="utf-8",
        )
        store = TimingStore(path=timing_file)
        data = store.load()
        assert data == {"u1": 1.0, "u2": 2.5}

    def test_load_non_numeric_values_skips_invalid_entries(self, tmp_path: Path) -> None:
        """Non-numeric JSON values (null, lists) are skipped, not crash load()."""
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(
            json.dumps({"u1": None, "u3": [1, 2]}),
            encoding="utf-8",
        )
        store = TimingStore(path=timing_file)
        data = store.load()
        assert data == {}

    def test_load_mixed_valid_invalid_entries(self, tmp_path: Path) -> None:
        """Valid entries are kept even when some entries are invalid."""
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(
            json.dumps({"u1": None, "u2": 1.5, "u3": [1, 2], "u4": 3.0}),
            encoding="utf-8",
        )
        store = TimingStore(path=timing_file)
        data = store.load()
        assert data == {"u2": 1.5, "u4": 3.0}

    def test_load_filters_non_finite_values(self, tmp_path: Path) -> None:
        """Infinity and NaN values in timing files are filtered out."""
        timing_file = tmp_path / "timing.json"
        timing_file.write_text('{"u1": Infinity, "u2": NaN, "u3": 1.5}', encoding="utf-8")
        store = TimingStore(path=timing_file)
        data = store.load()
        assert data == {"u3": 1.5}


class TestSaveLoadRoundtrip:
    def test_save_then_load(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        store = TimingStore(path=timing_file)
        store.save({"u1": 1.0, "u2": 2.5})
        assert timing_file.exists()

        store2 = TimingStore(path=timing_file)
        data = store2.load()
        assert data == {"u1": 1.0, "u2": 2.5}

    def test_save_uses_indent(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        store = TimingStore(path=timing_file)
        store.save({"u1": 1.0})
        text = timing_file.read_text(encoding="utf-8")
        assert '"u1": 1.0' in text
        assert "\n" in text  # indented JSON has newlines


class TestGetDuration:
    def test_existing_key(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(json.dumps({"u1": 3.14}), encoding="utf-8")
        store = TimingStore(path=timing_file)
        assert store.get_duration("u1") == 3.14

    def test_missing_key_returns_zero(self, tmp_path: Path) -> None:
        store = TimingStore(path=tmp_path / "nonexistent.json")
        assert store.get_duration("unknown") == 0.0

    def test_auto_loads_on_first_call(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(json.dumps({"u1": 2.0}), encoding="utf-8")
        store = TimingStore(path=timing_file)
        # Don't call load() explicitly
        assert store.get_duration("u1") == 2.0


class TestUpdate:
    def test_insert_new(self, tmp_path: Path) -> None:
        store = TimingStore(path=tmp_path / "timing.json")
        store.load()
        store.update("u1", 1.5)
        assert store.get_duration("u1") == 1.5

    def test_update_existing(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(json.dumps({"u1": 1.0}), encoding="utf-8")
        store = TimingStore(path=timing_file)
        store.load()
        store.update("u1", 5.0)
        assert store.get_duration("u1") == 5.0

    def test_auto_loads_on_first_update(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(json.dumps({"u1": 1.0}), encoding="utf-8")
        store = TimingStore(path=timing_file)
        # Don't call load() explicitly
        store.update("u2", 3.0)
        assert store.get_duration("u1") == 1.0
        assert store.get_duration("u2") == 3.0

    def test_rejects_inf_duration(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        store = TimingStore(path=tmp_path / "timing.json")
        store.load()
        with caplog.at_level(logging.WARNING):
            store.update("u1", float("inf"))
        assert store.get_duration("u1") == 0.0
        assert "non-finite" in caplog.text.lower()

    def test_rejects_nan_duration(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        store = TimingStore(path=tmp_path / "timing.json")
        store.load()
        with caplog.at_level(logging.WARNING):
            store.update("u1", float("nan"))
        assert store.get_duration("u1") == 0.0
        assert "non-finite" in caplog.text.lower()

    def test_rejects_negative_inf_duration(self, tmp_path: Path) -> None:
        store = TimingStore(path=tmp_path / "timing.json")
        store.load()
        store.update("u1", float("-inf"))
        assert store.get_duration("u1") == 0.0


class TestSaveIfChanged:
    def test_no_changes_does_not_write(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        original = {"u1": 1.0, "u2": 2.0}
        timing_file.write_text(json.dumps(original, indent=2, sort_keys=True), encoding="utf-8")
        mtime_before = timing_file.stat().st_mtime_ns

        store = TimingStore(path=timing_file)
        store.load()
        result = store.save_if_changed()
        assert result is False
        assert timing_file.stat().st_mtime_ns == mtime_before

    def test_changes_do_write(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(json.dumps({"u1": 1.0}), encoding="utf-8")

        store = TimingStore(path=timing_file)
        store.load()
        store.update("u1", 9.0)
        result = store.save_if_changed()
        assert result is True

        store2 = TimingStore(path=timing_file)
        assert store2.load() == {"u1": 9.0}

    def test_no_file_always_saves(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        store = TimingStore(path=timing_file)
        store.load()
        store.update("u1", 1.0)
        result = store.save_if_changed()
        assert result is True
        assert timing_file.exists()

    def test_auto_loads_when_not_preloaded(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(json.dumps({"u1": 1.0}), encoding="utf-8")
        store = TimingStore(path=timing_file)
        store.update("u1", 2.0)
        result = store.save_if_changed()
        assert result is True
        store2 = TimingStore(path=timing_file)
        assert store2.load() == {"u1": 2.0}

    def test_corrupt_file_treated_as_changed(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text("not valid json", encoding="utf-8")
        store = TimingStore(path=timing_file)
        store.load()
        store.update("u1", 1.0)
        result = store.save_if_changed()
        assert result is True
        assert json.loads(timing_file.read_text(encoding="utf-8")) == {"u1": 1.0}

    def test_auto_loads_in_save_if_changed_without_explicit_load(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        timing_file.write_text(json.dumps({"u1": 1.0}, indent=2, sort_keys=True), encoding="utf-8")
        store = TimingStore(path=timing_file)
        result = store.save_if_changed()
        assert result is False

    def test_save_if_changed_filters_non_finite_in_original(self, tmp_path: Path) -> None:
        """Non-finite values in the existing file are filtered during comparison,
        so a file containing only Infinity/NaN is treated as empty (changed)."""
        timing_file = tmp_path / "timing.json"
        timing_file.write_text('{"u1": Infinity, "u2": NaN}', encoding="utf-8")
        store = TimingStore(path=timing_file)
        store.load()
        store.update("u1", 1.0)
        result = store.save_if_changed()
        assert result is True
        assert json.loads(timing_file.read_text(encoding="utf-8")) == {"u1": 1.0}


class TestSaveErrorHandling:
    def test_save_raises_oserror_when_replace_fails(self, tmp_path: Path) -> None:
        timing_file = tmp_path / "timing.json"
        store = TimingStore(path=timing_file)
        with (
            patch("behave_pool.timing.os.replace", side_effect=OSError("replace failed")),
            pytest.raises(OSError, match="replace failed"),
        ):
            store.save({"u1": 1.0})
        assert not timing_file.exists()


class TestWorkUnitFeaturePath:
    """Regression: _work_unit_feature_path must not truncate at the first
    '.feature' occurrence — directories may legitimately contain it."""

    def test_directory_containing_dot_feature(self) -> None:
        from behave_pool.timing import _work_unit_feature_path

        result = _work_unit_feature_path("feature:my.feature.dir/login.feature")
        assert result == "my.feature.dir/login.feature"

    def test_serial_suffix_stripped(self) -> None:
        from behave_pool.timing import _work_unit_feature_path

        result = _work_unit_feature_path("feature:a.feature/b.feature#serial")
        assert result == "a.feature/b.feature"

    def test_scenario_prefix_with_line(self) -> None:
        from behave_pool.timing import _work_unit_feature_path

        result = _work_unit_feature_path("scenario:dir/x.feature:12")
        assert result == "dir/x.feature"

    def test_unknown_prefix_returns_none(self) -> None:
        from behave_pool.timing import _work_unit_feature_path

        assert _work_unit_feature_path("setup") is None

    def test_store_accepts_string_path(self, tmp_path: Path) -> None:
        """TimingStore must accept plain strings, not only Path objects."""
        target = str(tmp_path / "t.json")
        store = TimingStore(path=target)  # type: ignore[arg-type]
        store.save({"u1": 1.0})
        assert Path(target).exists()


class TestSerialModeValidation:
    def test_filter_rejects_unknown_serial_mode(self) -> None:
        """An invalid serial_mode must raise instead of silently filtering."""
        from unittest.mock import MagicMock

        from behave_pool.serial import filter_serial_scenarios

        with pytest.raises(ValueError, match="serial_mode"):
            filter_serial_scenarios(MagicMock(), "bogus")
