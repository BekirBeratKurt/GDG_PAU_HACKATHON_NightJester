"""Faz_8 birim testleri: ayar formu, config farkı kaydetme, oturum kaydı ve rapor, lamba testi."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from libs.communicator.topics import FatigueLevel
from libs.config_manager import config_diff, load_config, save_user_config
from libs.config_manager.config_manager import DEFAULT_CONFIG_PATH
from libs.device_state_tracker import DeviceError, Indicator, clear_error, request_lamp_test
from libs.device_state_tracker import device_state_tracker as dst
from libs.session_logger.session_logger import (
    KIND_GUARDIAN,
    KIND_LEVEL,
    open_database,
    query_hourly_report,
    record_event,
    start_session,
)
from libs.ui.settings_view import SettingsError, apply_form_values


@pytest.fixture
def config(tmp_path: Path):
    clear_error(DeviceError.CONFIG_ERROR)
    return load_config(DEFAULT_CONFIG_PATH, tmp_path / "yok.json")


# --- Ayar formu ---


def test_form_values_are_parsed_and_applied(config) -> None:
    new_config, restart = apply_form_values(
        config,
        {
            ("fatigue_detector", "drowsy_closed_sec"): "2,5",
            ("alert_manager", "deadline_media_type"): "video_url",
            ("alert_manager", "deadline_video_urls"): "https://a\n\n  https://b  \n",
            ("code_guardian", "enabled"): False,
            ("alert_manager", "normal_mode_cooldown_sec"): "15",
        },
    )
    assert new_config.fatigue_detector.drowsy_closed_sec == 2.5
    assert new_config.alert_manager.deadline_media_type == "video_url"
    assert new_config.alert_manager.deadline_video_urls == ["https://a", "https://b"]
    assert new_config.code_guardian.enabled is False
    assert new_config.alert_manager.normal_mode_cooldown_sec == 15
    assert restart == []
    assert config.fatigue_detector.drowsy_closed_sec == 1.5, "orijinal değişmemeli"


def test_camera_index_change_requires_restart(config) -> None:
    _, restart = apply_form_values(config, {("camera", "index"): "1"})
    assert restart == ["Kamera indeksi"]
    _, restart = apply_form_values(config, {("camera", "index"): "0"})
    assert restart == []


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        (("fatigue_detector", "drowsy_closed_sec"), "abc"),
        (("fatigue_detector", "drowsy_closed_sec"), "0.1"),  # en az 0.3
        (("fatigue_detector", "ear_closed_ratio"), "1.5"),  # en fazla 0.95
        (("alert_manager", "normal_mode_cooldown_sec"), "2.5"),  # tam sayı olmalı
        (("alert_manager", "deadline_media_type"), "radyo"),
    ],
)
def test_invalid_form_values_raise(config, key, raw) -> None:
    with pytest.raises(SettingsError):
        apply_form_values(config, {key: raw})


# --- Config farkı kaydetme ---


def test_config_diff_keeps_only_changes() -> None:
    defaults = {"a": {"x": 1, "y": 2}, "b": {"z": 3}}
    values = {"a": {"x": 1, "y": 5}, "b": {"z": 3}}
    assert config_diff(defaults, values) == {"a": {"y": 5}}


def test_save_user_config_writes_diff_and_reloads(config, tmp_path: Path) -> None:
    user_path = tmp_path / "user_config.json"
    config.alert_manager.voice_gender = "male"
    config.code_guardian.repo_paths = ["C:/repo"]
    assert save_user_config(config, user_path)

    saved = json.loads(user_path.read_text(encoding="utf-8"))
    assert saved == {
        "alert_manager": {"voice_gender": "male"},
        "code_guardian": {"repo_paths": ["C:/repo"]},
    }
    reloaded = load_config(DEFAULT_CONFIG_PATH, user_path)
    assert reloaded.alert_manager.voice_gender == "male"
    assert reloaded.code_guardian.repo_paths == ["C:/repo"]


# --- Oturum kaydı ve rapor ---


def test_hourly_report_counts_only_this_session(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "data" / "sessions.db")
    old_session = start_session(connection, datetime(2026, 11, 27, 1, 0))
    record_event(connection, old_session, datetime(2026, 11, 27, 1, 5), KIND_LEVEL, "DROWSY")

    session = start_session(connection, datetime(2026, 11, 27, 2, 0))
    for minute, level in ((5, "DROWSY"), (10, "ASLEEP"), (20, "AWAKE"), (40, "DROWSY")):
        record_event(connection, session, datetime(2026, 11, 27, 2, minute), KIND_LEVEL, level)
    record_event(connection, session, datetime(2026, 11, 27, 3, 1), KIND_LEVEL, "ASLEEP")
    record_event(connection, session, datetime(2026, 11, 27, 3, 2), KIND_GUARDIAN, detail="OK")

    report = query_hourly_report(connection, session)
    connection.close()
    assert [(r.hour, r.drowsy, r.asleep) for r in report] == [(2, 2, 1), (3, 0, 1)]


def test_empty_session_report(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "sessions.db")
    session = start_session(connection, datetime.now())
    assert query_hourly_report(connection, session) == []
    connection.close()


def test_level_names_match_report_query() -> None:
    assert FatigueLevel.DROWSY.name == "DROWSY"
    assert FatigueLevel.ASLEEP.name == "ASLEEP"


# --- Lamba testi ---


def test_request_lamp_test_sets_window() -> None:
    before = dst._now_ms()
    request_lamp_test()
    assert dst._lamp_test_until_ms >= before + dst.LAMP_TEST_MS
    assert set(Indicator) == {Indicator.VISION, Indicator.ALERT, Indicator.INTEGRATION}
