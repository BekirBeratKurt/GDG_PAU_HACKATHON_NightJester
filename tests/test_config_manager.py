"""config_manager birim testleri: varsayılan yükleme, birleştirme, bozuk dosya."""

from __future__ import annotations

from pathlib import Path

import pytest

from libs.config_manager import load_config
from libs.config_manager.config_manager import DEFAULT_CONFIG_PATH
from libs.device_state_tracker import DeviceError, clear_error, get_error_status


@pytest.fixture(autouse=True)
def _clean_error() -> None:
    clear_error(DeviceError.CONFIG_ERROR)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "user_config.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_user_config_missing(tmp_path: Path) -> None:
    config = load_config(DEFAULT_CONFIG_PATH, tmp_path / "yok.json")
    assert config.camera.index == 0
    assert config.fatigue_detector.drowsy_closed_sec == 1.5
    assert not get_error_status(DeviceError.CONFIG_ERROR)


def test_user_values_override_defaults(tmp_path: Path) -> None:
    user = _write(
        tmp_path, '{"camera": {"index": 2}, "fatigue_detector": {"asleep_closed_sec": 4}}'
    )
    config = load_config(DEFAULT_CONFIG_PATH, user)
    assert config.camera.index == 2
    assert config.camera.width_px == 640
    assert config.fatigue_detector.asleep_closed_sec == 4.0
    assert isinstance(config.fatigue_detector.asleep_closed_sec, float)
    assert not get_error_status(DeviceError.CONFIG_ERROR)


def test_broken_json_falls_back_to_defaults(tmp_path: Path) -> None:
    config = load_config(DEFAULT_CONFIG_PATH, _write(tmp_path, '{"camera": {'))
    assert config.camera.index == 0
    assert get_error_status(DeviceError.CONFIG_ERROR)


def test_wrong_type_keeps_default_for_that_key(tmp_path: Path) -> None:
    user = _write(tmp_path, '{"camera": {"index": "bir", "width_px": 1280}}')
    config = load_config(DEFAULT_CONFIG_PATH, user)
    assert config.camera.index == 0
    assert config.camera.width_px == 1280
    assert get_error_status(DeviceError.CONFIG_ERROR)


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    user = _write(tmp_path, '{"camera": {"zoom": 3}, "olmayan_bolum": {}}')
    config = load_config(DEFAULT_CONFIG_PATH, user)
    assert config.camera.index == 0
    assert not get_error_status(DeviceError.CONFIG_ERROR)
