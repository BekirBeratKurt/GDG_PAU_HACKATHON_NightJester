"""alert_manager birim testleri: klasörden rastgele ses seçimi ve varsayılan ses dosyaları."""

from __future__ import annotations

from pathlib import Path

import pytest

from libs.alert_manager import alert_manager as am
from libs.alert_manager import find_unconverted_audio_files, pick_random_audio_file
from libs.config_manager import load_config, project_path
from libs.config_manager.config_manager import DEFAULT_CONFIG_PATH


def test_missing_directory_returns_none(tmp_path: Path) -> None:
    assert pick_random_audio_file(tmp_path / "yok") is None


def test_only_supported_audio_files_are_picked(tmp_path: Path) -> None:
    for name in ("a.ogg", "b.mp3", "c.wav", "d.m4a", "e.txt"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "deadline").mkdir()
    (tmp_path / "deadline" / "f.ogg").write_bytes(b"")

    picked = {pick_random_audio_file(tmp_path).name for _ in range(200)}
    assert picked == {"a.ogg", "b.mp3", "c.wav"}


def test_empty_directory_returns_none(tmp_path: Path) -> None:
    (tmp_path / "notlar.txt").write_bytes(b"")
    assert pick_random_audio_file(tmp_path) is None


def test_default_voice_files_exist(tmp_path: Path) -> None:
    config = load_config(DEFAULT_CONFIG_PATH, tmp_path / "yok.json")
    voice_root = project_path(config.alert_manager.voice_dir)
    for gender in ("female", "male"):
        for sub_dir in ("Drowsy", "Sleepy/normal", "Sleepy/deadline"):
            directory = voice_root / gender / sub_dir
            assert pick_random_audio_file(directory) is not None, directory
            assert find_unconverted_audio_files(directory) == [], directory


def test_unconverted_files_are_reported(tmp_path: Path) -> None:
    for name in ("a.m4a", "a.ogg", "b.m4a", "c.flac", "d.mp3"):
        (tmp_path / name).write_bytes(b"")
    found = [path.name for path in find_unconverted_audio_files(tmp_path)]
    assert found == ["b.m4a", "c.flac"]


@pytest.mark.parametrize(
    ("browser_opens", "sound_with_video", "expect_sound"),
    [
        (True, False, False),  # varsayılan: sadece video
        (True, True, True),  # ayarla birlikte ses
        (False, False, True),  # tarayıcı açılmadı → yedek ses
    ],
)
def test_video_url_alarm_sound_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    browser_opens: bool,
    sound_with_video: bool,
    expect_sound: bool,
) -> None:
    config = load_config(DEFAULT_CONFIG_PATH, tmp_path / "yok.json")
    config.alert_manager.deadline_media_type = "video_url"
    config.alert_manager.deadline_video_urls = ["https://a", "https://b"]
    config.alert_manager.deadline_sound_with_video = sound_with_video
    am._load_settings(config)

    opened_urls: list[str] = []
    sound_calls: list[bool] = []

    def fake_open(url: str) -> bool:
        opened_urls.append(url)
        return browser_opens

    monkeypatch.setattr(am.webbrowser, "open", fake_open)
    monkeypatch.setattr(am, "_start_alarm_sound", lambda: sound_calls.append(True) or True)
    monkeypatch.setattr(am, "_alarm_active", False)

    am._start_alarm()

    assert len(opened_urls) == 1 and opened_urls[0] in ("https://a", "https://b")
    assert bool(sound_calls) is expect_sound


def test_default_is_video_only(tmp_path: Path) -> None:
    config = load_config(DEFAULT_CONFIG_PATH, tmp_path / "yok.json")
    assert config.alert_manager.deadline_sound_with_video is False


def test_video_urls_list_override(tmp_path: Path) -> None:
    user = tmp_path / "user_config.json"
    user.write_text(
        '{"alert_manager": {"deadline_video_urls": ["https://a", "https://b"]}}', encoding="utf-8"
    )
    config = load_config(DEFAULT_CONFIG_PATH, user)
    assert config.alert_manager.deadline_video_urls == ["https://a", "https://b"]
