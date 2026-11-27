"""UI modülü: ana pencereyi kurar ve ana thread'de periyodik olarak günceller."""

from __future__ import annotations

import logging
import signal
import threading
import time

import customtkinter as ctk

from libs.communicator import orb_copy, orb_publish, orb_subscribe, topics
from libs.config_manager import AppConfig

from .dashboard import Dashboard

TAG = "UI"
log = logging.getLogger(TAG)

UI_PERIOD_MS = 33
NO_FRAME_TIMEOUT_SEC = 2.0
WINDOW_TITLE = "NightJester"
APPEARANCE_MODE = "dark"


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
    dashboard = Dashboard(
        root, show_landmarks=config.ui.show_landmarks, on_calibrate=_request_calibration
    )
    dashboard.pack(fill="both", expand=True)

    frame_sub = orb_subscribe(topics.frame_topic)
    metrics_sub = orb_subscribe(topics.face_metrics_topic)
    fatigue_sub = orb_subscribe(topics.fatigue_state_topic)
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
