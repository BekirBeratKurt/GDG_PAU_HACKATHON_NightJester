"""Tray: system tray ikonu (durum rengi), mod menüsü, göster/gizle ve çıkış."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

import pystray
from PIL import Image, ImageDraw

from libs.communicator.topics import AppMode, FatigueLevel

TAG = "Tray"
log = logging.getLogger(TAG)

APP_NAME = "NightJester"
ICON_SIZE_PX = 64
ICON_MARGIN_PX = 4
BADGE_SIZE_PX = 26
BADGE_COLOR = "#ff8c00"
BADGE_MARK_COLOR = "#ffffff"
BADGE_MARK_WIDTH_PX = 4
TRANSPARENT = (0, 0, 0, 0)

COLOR_AWAKE = "#3cb371"
COLOR_DROWSY = "#e6b800"
COLOR_ASLEEP = "#e04040"
COLOR_INACTIVE = "#8a8a8a"
LEVEL_COLORS: dict[FatigueLevel, str] = {
    FatigueLevel.AWAKE: COLOR_AWAKE,
    FatigueLevel.DROWSY: COLOR_DROWSY,
    FatigueLevel.ASLEEP: COLOR_ASLEEP,
}
MODE_MENU_LABELS: dict[AppMode, str] = {
    AppMode.NORMAL: "Normal mod",
    AppMode.DEADLINE: "Deadline modu",
    AppMode.PAUSED: "Duraklat",
}
LEVEL_TOOLTIPS: dict[FatigueLevel, str] = {
    FatigueLevel.AWAKE: "Uyanık",
    FatigueLevel.DROWSY: "Uykulu",
    FatigueLevel.ASLEEP: "Uyuyor",
    FatigueLevel.NO_FACE: "Yüz yok",
    FatigueLevel.CALIBRATING: "Kalibre ediliyor",
}


@dataclass
class TrayCallbacks:
    """Tray menüsünden çağrılacak fonksiyonlar. Tray thread'inden çağrılırlar."""

    on_show: Callable[[], None]
    on_mode_change: Callable[[AppMode], None]
    on_wake: Callable[[], None]
    on_exit: Callable[[], None]


def tray_color(level: FatigueLevel | None, mode: AppMode) -> str:
    """Duruma ve moda göre tray ikonunun rengini döner.

    Args:
        level: Son yorgunluk seviyesi (bilinmiyorsa None).
        mode: Uygulama modu.

    Returns:
        Renk kodu. Duraklatılmışsa, yüz yoksa veya kalibre ediliyorsa gri.
    """
    if mode is AppMode.PAUSED or level is None:
        return COLOR_INACTIVE
    return LEVEL_COLORS.get(level, COLOR_INACTIVE)


def make_icon_image(color: str, has_error: bool) -> Image.Image:
    """Renkli daire ikon üretir. Kritik hata varsa köşeye ünlem rozeti çizer.

    Args:
        color: Dairenin rengi.
        has_error: Kritik hata var mı.

    Returns:
        RGBA ikon görüntüsü.
    """
    image = Image.new("RGBA", (ICON_SIZE_PX, ICON_SIZE_PX), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        (
            ICON_MARGIN_PX,
            ICON_MARGIN_PX,
            ICON_SIZE_PX - ICON_MARGIN_PX,
            ICON_SIZE_PX - ICON_MARGIN_PX,
        ),
        fill=color,
    )
    if has_error:
        left = ICON_SIZE_PX - BADGE_SIZE_PX
        draw.ellipse((left, 0, ICON_SIZE_PX - 1, BADGE_SIZE_PX - 1), fill=BADGE_COLOR)
        center_x = left + BADGE_SIZE_PX // 2
        quarter = BADGE_SIZE_PX // 4
        draw.line(
            (center_x, quarter, center_x, BADGE_SIZE_PX - quarter - BADGE_MARK_WIDTH_PX),
            fill=BADGE_MARK_COLOR,
            width=BADGE_MARK_WIDTH_PX,
        )
        dot_y = BADGE_SIZE_PX - quarter
        draw.point((center_x, dot_y), fill=BADGE_MARK_COLOR)
        draw.rectangle((center_x - 1, dot_y - 1, center_x + 1, dot_y + 1), fill=BADGE_MARK_COLOR)
    return image


class Tray:
    """System tray ikonu. update() ana thread'den, menü callback'leri tray thread'inden çalışır."""

    def __init__(self, initial_mode: AppMode, callbacks: TrayCallbacks) -> None:
        """Tray ikonunu oluşturur (henüz göstermez).

        Args:
            initial_mode: Başlangıç modu (menüdeki işaret için).
            callbacks: Menü fonksiyonları.
        """
        self._callbacks = callbacks
        self._mode = initial_mode
        self._level: FatigueLevel | None = None
        self._has_error = False
        self._lock = threading.Lock()
        self._icon = pystray.Icon(
            APP_NAME,
            icon=make_icon_image(tray_color(None, initial_mode), has_error=False),
            title=APP_NAME,
            menu=self._build_menu(),
        )

    def start(self) -> bool:
        """Tray ikonunu ayrı thread'de gösterir.

        Returns:
            Başarılıysa True. Başarısızsa pencere kapatılınca uygulama kapanmalıdır.
        """
        try:
            self._icon.run_detached()
        except (OSError, RuntimeError, NotImplementedError) as err:
            log.error("Tray ikonu başlatılamadı: %s", err)
            return False
        log.info("Tray ikonu başlatıldı.")
        return True

    def stop(self) -> None:
        """Tray ikonunu kaldırır. Tray thread'i daemon olmadığı için kapanışta şarttır."""
        try:
            self._icon.stop()
        except (OSError, RuntimeError) as err:
            log.error("Tray ikonu kapatılamadı: %s", err)

    def update(self, level: FatigueLevel | None, mode: AppMode, has_error: bool) -> None:
        """Durum değiştiyse ikon rengini, ipucunu ve menü işaretini günceller.

        Args:
            level: Son yorgunluk seviyesi.
            mode: Uygulama modu.
            has_error: Kritik hata var mı.
        """
        with self._lock:
            if (level, mode, has_error) == (self._level, self._mode, self._has_error):
                return
            mode_changed = mode is not self._mode
            self._level, self._mode, self._has_error = level, mode, has_error
        self._icon.icon = make_icon_image(tray_color(level, mode), has_error)
        status = LEVEL_TOOLTIPS.get(level, "-") if level else "-"
        self._icon.title = f"{APP_NAME}: {status} ({MODE_MENU_LABELS[mode]})"
        if mode_changed:
            self._icon.update_menu()

    def notify(self, message: str) -> None:
        """Tray balonu ile kısa bilgi gösterir.

        Args:
            message: Gösterilecek mesaj.
        """
        try:
            self._icon.notify(message, APP_NAME)
        except (OSError, RuntimeError, NotImplementedError) as err:
            log.error("Tray bildirimi gösterilemedi: %s", err)

    def _build_menu(self) -> pystray.Menu:
        mode_items = [
            pystray.MenuItem(
                label,
                self._make_mode_handler(mode),
                checked=self._make_mode_checker(mode),
                radio=True,
            )
            for mode, label in MODE_MENU_LABELS.items()
        ]
        return pystray.Menu(
            pystray.MenuItem("Göster", lambda: self._callbacks.on_show(), default=True),
            pystray.Menu.SEPARATOR,
            *mode_items,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Uyandım (alarmı durdur)", lambda: self._callbacks.on_wake()),
            pystray.MenuItem("Çıkış", lambda: self._callbacks.on_exit()),
        )

    def _make_mode_handler(self, mode: AppMode) -> Callable[[], None]:
        def handler() -> None:
            self._callbacks.on_mode_change(mode)

        return handler

    def _make_mode_checker(self, mode: AppMode) -> Callable[[pystray.MenuItem], bool]:
        def checker(_item: pystray.MenuItem) -> bool:
            return self._mode is mode

        return checker
