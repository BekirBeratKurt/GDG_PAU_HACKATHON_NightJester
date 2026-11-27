"""NightJester giriş noktası. Sadece kurulum ve task başlatma içerir."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from libs.communicator import orb_advertise, topics
from libs.config_manager import AppConfig, load_config
from libs.device_state_tracker import device_state_tracker_task

TAG = "Main"
log = logging.getLogger(TAG)

THREAD_JOIN_TIMEOUT_SEC = 2.0
MAIN_WAIT_PERIOD_SEC = 0.5
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
    ]
    threads = [_start_task(fn, name, stop_event, config) for fn, name in tasks]

    _wait_until_stopped(stop_event)

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


def _wait_until_stopped(stop_event: threading.Event) -> None:
    # Geçici: Faz_2'de UI gelince ana thread run_ui içinde bloklanacak.
    log.info("Kapatmak için Ctrl+C'ye bas.")
    try:
        while not stop_event.wait(MAIN_WAIT_PERIOD_SEC):
            pass
    except KeyboardInterrupt:
        log.info("Ctrl+C alındı, kapatılıyor.")


if __name__ == "__main__":
    main()
