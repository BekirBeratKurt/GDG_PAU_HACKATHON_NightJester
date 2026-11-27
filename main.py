"""NightJester giriş noktası. Sadece kurulum ve task başlatma içerir."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from libs.alert_manager import alert_manager_task
from libs.camera_capture import camera_capture_task
from libs.communicator import orb_advertise, topics
from libs.config_manager import AppConfig, load_config
from libs.device_state_tracker import device_state_tracker_task
from libs.face_analyzer import face_analyzer_task
from libs.fatigue_detector import fatigue_detector_task
from libs.ui import run_ui

TAG = "Main"
log = logging.getLogger(TAG)

THREAD_JOIN_TIMEOUT_SEC = 2.0
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

TaskFunction = Callable[[threading.Event, AppConfig], None]


def main() -> None:
    """Uygulamayı kurar, task'ları başlatır ve kapanışta hepsini durdurur."""
    _setup_logging()
    log.info("Uygulama başlatıldı")

    config = load_config()
    _advertise_all_topics()

    stop_event = threading.Event()
    tasks: list[tuple[TaskFunction, str]] = [
        (device_state_tracker_task, "device_state_tracker_task"),  # her zaman ilk
        (camera_capture_task, "camera_capture_task"),
        (face_analyzer_task, "face_analyzer_task"),
        (fatigue_detector_task, "fatigue_detector_task"),
        (alert_manager_task, "alert_manager_task"),
    ]
    threads = [_start_task(fn, name, stop_event, config) for fn, name in tasks]

    run_ui(stop_event, config)  # ana thread burada bloklanır

    stop_event.set()
    for thread in threads:
        thread.join(timeout=THREAD_JOIN_TIMEOUT_SEC)
        if thread.is_alive():
            log.warning("%s zamanında durmadı.", thread.name)
    log.info("Uygulama kapatıldı")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)


def _advertise_all_topics() -> None:
    topics.frame_topic = orb_advertise(topics.FRAME_TOPIC)
    topics.face_metrics_topic = orb_advertise(topics.FACE_METRICS_TOPIC)
    topics.fatigue_state_topic = orb_advertise(topics.FATIGUE_STATE_TOPIC)
    topics.app_mode_topic = orb_advertise(topics.APP_MODE_TOPIC)
    topics.alert_command_topic = orb_advertise(topics.ALERT_COMMAND_TOPIC)
    topics.calibration_request_topic = orb_advertise(topics.CALIBRATION_REQUEST_TOPIC)
    topics.guardian_result_topic = orb_advertise(topics.GUARDIAN_RESULT_TOPIC)
    topics.config_updated_topic = orb_advertise(topics.CONFIG_UPDATED_TOPIC)
    log.info("Tüm topic'ler oluşturuldu.")


def _start_task(
    fn: TaskFunction, name: str, stop_event: threading.Event, config: AppConfig
) -> threading.Thread:
    thread = threading.Thread(target=fn, args=(stop_event, config), name=name, daemon=True)
    thread.start()
    log.info("%s başlatıldı", name)
    return thread


if __name__ == "__main__":
    main()
