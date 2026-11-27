"""UI modülü: ana pencereyi ve tray'i kurar, ana thread'de periyodik olarak günceller."""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

from libs.communicator import orb_copy, orb_publish, orb_subscribe, topics
from libs.communicator.topics import AlertCommand, AppMode, FatigueLevel, GuardianResult
from libs.config_manager import AppConfig, save_user_config
from libs.device_state_tracker import (
    DeviceError,
    get_device_state,
    get_error_mask,
    get_indicator_states,
    request_lamp_test,
)
from libs.session_logger import get_hourly_report

from .dashboard import Dashboard, DashboardCallbacks
from .report_view import ReportWindow
from .settings_view import SettingsWindow
from .tray import Tray, TrayCallbacks

TAG = "UI"
log = logging.getLogger(TAG)

UI_PERIOD_MS = 33
NO_FRAME_TIMEOUT_SEC = 2.0
WINDOW_TITLE = "NightJester"
APPEARANCE_MODE = "dark"
GUARDIAN_TIME_FORMAT = "%H:%M:%S"
TEXT_RUNNING_IN_BACKGROUND = (
    "NightJester arka planda çalışmaya devam ediyor. Açmak için tray ikonuna tıkla."
)


def run_ui(stop_event: threading.Event, config: AppConfig) -> None:
    """Ana pencereyi ve tray ikonunu açar, uygulama kapanana kadar ana thread'i bloklar.

    Pencere kapatılınca uygulama tray'e küçülür. Tray'den "Çıkış" seçilince veya Ctrl+C'ye
    basılınca stop_event set edilir.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    _App(stop_event, config).run()


class _App:
    """Pencere, panel ve tray'i bir arada tutar. Tüm metotlar ana thread'de çalışır."""

    def __init__(self, stop_event: threading.Event, config: AppConfig) -> None:
        self._stop_event = stop_event
        self._config = config
        self._mode = _parse_mode(config.ui.start_mode)
        self._level: FatigueLevel | None = None
        self._hidden = False
        self._background_hint_shown = False
        self._last_frame_time = time.monotonic()
        self._camera_lost = False
        # Tray thread'i Tk'ye dokunamaz. İsteği bu olayla bırakır, tick ana thread'de işler.
        self._show_request = threading.Event()
        self._settings_window: SettingsWindow | None = None
        self._report_window: ReportWindow | None = None

        ctk.set_appearance_mode(APPEARANCE_MODE)
        self._root = ctk.CTk()
        self._root.title(WINDOW_TITLE)
        self._dashboard = Dashboard(
            self._root,
            show_landmarks=config.ui.show_landmarks,
            initial_mode=self._mode,
            callbacks=DashboardCallbacks(
                on_calibrate=_request_calibration,
                on_mode_change=_publish_mode,
                on_wake=_request_alarm_stop,
                on_test_alarm=_request_test_alarm,
                on_settings=self._open_settings,
                on_report=self._open_report,
            ),
        )
        self._dashboard.pack(fill="both", expand=True)
        self._dashboard.show_guardian_info(_initial_guardian_text(config))

        self._tray = Tray(
            self._mode,
            TrayCallbacks(
                on_show=self._show_request.set,
                on_mode_change=_publish_mode,
                on_wake=_request_alarm_stop,
                on_exit=stop_event.set,
            ),
        )

        self._frame_sub = orb_subscribe(topics.frame_topic)
        self._metrics_sub = orb_subscribe(topics.face_metrics_topic)
        self._fatigue_sub = orb_subscribe(topics.fatigue_state_topic)
        self._guardian_sub = orb_subscribe(topics.guardian_result_topic)
        self._mode_sub = orb_subscribe(topics.app_mode_topic)

    def run(self) -> None:
        """Tray'i başlatır ve Tk ana döngüsünü çalıştırır."""
        tray_ok = self._tray.start()
        if tray_ok:
            self._root.protocol("WM_DELETE_WINDOW", self._hide_window)
        else:
            log.warning("Tray yok, pencere kapatılınca uygulama kapanacak.")
            self._root.protocol("WM_DELETE_WINDOW", self._stop_event.set)
        # Tk ana döngüsü Ctrl+C'yi kendisi işlemez. Olayı set edip tick'in kapatmasını sağlıyoruz.
        signal.signal(signal.SIGINT, lambda _signum, _frame: self._stop_event.set())

        # Başlangıç modu bir kez yayınlanır, böylece tüm modüller aynı modla başlar.
        _publish_mode(self._mode)
        if tray_ok and self._config.ui.start_minimized:
            self._hide_window()

        self._root.after(UI_PERIOD_MS, self._tick)
        # Görev başlarken yapılan lamba testi pencere açılmadan bitebiliyor, burada tekrarlanır.
        request_lamp_test()
        log.info("Arayüz açıldı.")
        try:
            self._root.mainloop()
        finally:
            # Tray thread'i daemon değil. Durdurulmazsa uygulama kapanmaz.
            self._tray.stop()
            self._root.destroy()
            log.info("Arayüz kapandı.")

    def _tick(self) -> None:
        if self._stop_event.is_set():
            self._root.quit()
            return
        if self._show_request.is_set():
            self._show_request.clear()
            self._show_window()

        self._update_mode()
        self._update_preview()
        fatigue_updated, fatigue_state = orb_copy(self._fatigue_sub)
        if fatigue_updated:
            self._level = fatigue_state.level
            self._dashboard.show_state(fatigue_state)
        guardian_updated, guardian_result = orb_copy(self._guardian_sub)
        if guardian_updated and isinstance(guardian_result, GuardianResult):
            self._dashboard.show_guardian_info(
                _guardian_result_text(guardian_result), ok=guardian_result.success
            )
        self._dashboard.show_alarm_active(get_device_state().alarm_active)
        error_mask = get_error_mask()
        self._dashboard.show_indicators(get_indicator_states(), error_mask)
        self._tray.update(self._level, self._mode, error_mask != DeviceError.NO_ERROR)
        self._root.after(UI_PERIOD_MS, self._tick)

    def _open_settings(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return
        self._settings_window = SettingsWindow(self._root, self._config, self._save_settings)

    def _save_settings(self, new_config: AppConfig) -> bool:
        if not save_user_config(new_config):
            return False
        self._config = new_config
        orb_publish(topics.config_updated_topic, new_config)
        self._dashboard.set_show_landmarks(new_config.ui.show_landmarks)
        self._dashboard.show_guardian_info(_initial_guardian_text(new_config))
        log.info("Ayarlar kaydedildi ve yayınlandı.")
        return True

    def _open_report(self) -> None:
        if self._report_window is not None and self._report_window.winfo_exists():
            self._report_window.refresh()
            self._report_window.lift()
            return
        self._report_window = ReportWindow(self._root, get_hourly_report)

    def _update_mode(self) -> None:
        updated, mode = orb_copy(self._mode_sub)
        if updated and isinstance(mode, AppMode) and mode is not self._mode:
            self._mode = mode
            self._dashboard.set_mode(mode)

    def _update_preview(self) -> None:
        frame_updated, frame = orb_copy(self._frame_sub)
        metrics_updated, metrics = orb_copy(self._metrics_sub)
        now = time.monotonic()
        if frame_updated:
            self._last_frame_time = now
            self._camera_lost = False
            # Pencere gizliyken kare çizmek boşa CPU harcar.
            if not self._hidden:
                self._dashboard.show_frame(frame.image, metrics)
        elif not self._camera_lost and now - self._last_frame_time > NO_FRAME_TIMEOUT_SEC:
            self._camera_lost = True
            self._dashboard.show_no_camera()
        if metrics_updated:
            self._dashboard.show_metrics(metrics)

    def _hide_window(self) -> None:
        self._root.withdraw()
        self._hidden = True
        log.info("Pencere gizlendi, uygulama arka planda çalışıyor.")
        if not self._background_hint_shown:
            self._background_hint_shown = True
            self._tray.notify(TEXT_RUNNING_IN_BACKGROUND)

    def _show_window(self) -> None:
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._hidden = False
        log.info("Pencere gösterildi.")


def _request_calibration() -> None:
    log.info("Kullanıcı kalibrasyon istedi.")
    orb_publish(topics.calibration_request_topic, True)


def _publish_mode(mode: AppMode) -> None:
    log.info("Mod seçildi: %s", mode.name)
    orb_publish(topics.app_mode_topic, mode)


def _request_alarm_stop() -> None:
    log.info("Kullanıcı 'Uyandım' dedi.")
    orb_publish(topics.alert_command_topic, AlertCommand(action="stop"))


def _request_test_alarm() -> None:
    log.info("Kullanıcı test alarmı istedi.")
    orb_publish(topics.alert_command_topic, AlertCommand(action="test"))


def _initial_guardian_text(config: AppConfig) -> str:
    cfg = config.code_guardian
    if not cfg.enabled:
        return "Kod Koruyucu: kapalı"
    if not cfg.repo_paths:
        return "Kod Koruyucu: repo eklenmedi (code_guardian.repo_paths)"
    return f"Kod Koruyucu: {len(cfg.repo_paths)} repo izleniyor, henüz yedek alınmadı"


def _guardian_result_text(result: GuardianResult) -> str:
    now = datetime.now().strftime(GUARDIAN_TIME_FORMAT)
    repo_name = Path(result.repo_path).name
    status = "" if result.success else "HATA: "
    return f"Kod Koruyucu [{now}] {repo_name}: {status}{result.message}"


def _parse_mode(name: str) -> AppMode:
    try:
        return AppMode[name]
    except KeyError:
        log.warning("Geçersiz başlangıç modu '%s', NORMAL kullanılıyor.", name)
        return AppMode.NORMAL
