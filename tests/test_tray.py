"""tray birim testleri: duruma göre ikon rengi ve hata rozeti."""

from __future__ import annotations

from libs.communicator.topics import AppMode, FatigueLevel
from libs.ui.tray import (
    COLOR_ASLEEP,
    COLOR_AWAKE,
    COLOR_DROWSY,
    COLOR_INACTIVE,
    ICON_SIZE_PX,
    make_icon_image,
    tray_color,
)


def test_level_colors() -> None:
    assert tray_color(FatigueLevel.AWAKE, AppMode.NORMAL) == COLOR_AWAKE
    assert tray_color(FatigueLevel.DROWSY, AppMode.DEADLINE) == COLOR_DROWSY
    assert tray_color(FatigueLevel.ASLEEP, AppMode.DEADLINE) == COLOR_ASLEEP


def test_inactive_states_are_gray() -> None:
    assert tray_color(None, AppMode.NORMAL) == COLOR_INACTIVE
    assert tray_color(FatigueLevel.NO_FACE, AppMode.NORMAL) == COLOR_INACTIVE
    assert tray_color(FatigueLevel.CALIBRATING, AppMode.NORMAL) == COLOR_INACTIVE
    assert tray_color(FatigueLevel.ASLEEP, AppMode.PAUSED) == COLOR_INACTIVE


def test_icon_image_has_badge_only_on_error() -> None:
    corner = (ICON_SIZE_PX - 6, 6)  # rozetin içi, dairenin dışı
    plain = make_icon_image(COLOR_AWAKE, has_error=False)
    with_error = make_icon_image(COLOR_AWAKE, has_error=True)
    assert plain.size == (ICON_SIZE_PX, ICON_SIZE_PX)
    assert plain.getpixel(corner)[3] == 0
    assert with_error.getpixel(corner)[3] == 255
