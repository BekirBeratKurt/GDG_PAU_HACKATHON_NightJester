"""UI modülü: ana pencereyi kurar ve ana thread'de periyodik olarak günceller."""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

from libs.communicator import orb_copy, orb_publish, orb_subscribe, topics
from libs.communicator.topics import AlertCommand, AppMode, GuardianResult
from libs.config_manager import AppConfig
from libs.device_state_tracker import get_device_state

from .dashboard import Dashboard, DashboardCallbacks

TAG = "UI"
log = logging.getLogger(TAG)

UI_PERIOD_MS = 33
NO_FRAME_TIMEOUT_SEC = 2.0
WINDOW_TITLE = "NightJester"
APPEARANCE_MODE = "dark"
GUARDIAN_TIME_FORMAT = "%H:%M:%S"


def run_ui(stop_event: threading.Event, config: AppConfig) -> None:
    """Ana pencereyi açar ve kapanana kadar ana thread'i bloklar.

    Pencere kapatıldığında veya Ctrl+C'ye basıldığında stop_event set edilir.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    ctk.set_appearance_mode(APPEARANCE_MODE)
    root = ctk.CTk()
    root.title(WINDOW_TITLE)
    initial_mode = _parse_mode(config.ui.start_mode)
    callbacks = DashboardCallbacks(
        on_calibrate=_request_calibration,
        on_mode_change=_publish_mode,
        on_wake=_request_alarm_stop,
        on_test_alarm=_request_test_alarm,
    )
    dashboard = Dashboard(
        root,
        show_landmarks=config.ui.show_landmarks,
        initial_mode=initial_mode,
        callbacks=callbacks,
    )
    dashboard.pack(fill="both", expand=True)
    dashboard.show_guardian_info(_initial_guardian_text(config))
    # Başlangıç modu bir kez yayınlanır, böylece tüm modüller aynı modla başlar.
    _publish_mode(initial_mode)

    frame_sub = orb_subscribe(topics.frame_topic)
    metrics_sub = orb_subscribe(topics.face_metrics_topic)
    fatigue_sub = orb_subscribe(topics.fatigue_state_topic)
    guardian_sub = orb_subscribe(topics.guardian_result_topic)
    last_frame_time = time.monotonic()
    camera_lost = False

    def tick() -> None:
        nonlocal last_frame_time, camera_lost
        if stop_event.is_set():
            root.quit()
            return
        frame_updated, frame = orb_copy(frame_sub)
        metrics_updated, metrics = orb_copy(metrics_sub)
        now = time.monotonic()
        if frame_updated:
            last_frame_time = now
            camera_lost = False
            dashboard.show_frame(frame.image, metrics)
        elif not camera_lost and now - last_frame_time > NO_FRAME_TIMEOUT_SEC:
            camera_lost = True
            dashboard.show_no_camera()
        if metrics_updated:
            dashboard.show_metrics(metrics)
        fatigue_updated, fatigue_state = orb_copy(fatigue_sub)
        if fatigue_updated:
            dashboard.show_state(fatigue_state)
        guardian_updated, guardian_result = orb_copy(guardian_sub)
        if guardian_updated and isinstance(guardian_result, GuardianResult):
            dashboard.show_guardian_info(
                _guardian_result_text(guardian_result), ok=guardian_result.success
            )
        dashboard.show_alarm_active(get_device_state().alarm_active)
        root.after(UI_PERIOD_MS, tick)

    root.protocol("WM_DELETE_WINDOW", stop_event.set)
    # Tk ana döngüsü Ctrl+C'yi kendisi işlemez. Olayı set edip tick'in kapatmasını sağlıyoruz.
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop_event.set())

    root.after(UI_PERIOD_MS, tick)
    log.info("Arayüz açıldı.")
    root.mainloop()
    root.destroy()
    log.info("Arayüz kapandı.")


def _request_calibration() -> None:
    log.info("Kullanıcı kalibrasyon istedi.")
    orb_publish(topics.calibration_request_topic, True)


def _publish_mode(mode: AppMode) -> None:
    log.info("Mod seçildi: %s", mode.name)
    orb_publish(topics.app_mode_topic, mode)


def _request_alarm_stop() -> None:
    log.info("Kullanıcı 'Uyandım' butonuna bastı.")
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
