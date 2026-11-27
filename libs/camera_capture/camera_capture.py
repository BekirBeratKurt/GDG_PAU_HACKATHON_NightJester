"""Camera capture modülü: kameradan kare okur, aynalar ve FRAME topic'ine yayınlar."""

from __future__ import annotations

import logging
import threading
import time

import cv2

from libs.communicator import orb_publish, topics
from libs.communicator.topics import Frame
from libs.config_manager import AppConfig
from libs.device_state_tracker import DeviceError, clear_error, raise_error

TAG = "CameraCapture"
log = logging.getLogger(TAG)

READ_FAIL_LIMIT = 30
READ_RETRY_SEC = 0.1
HORIZONTAL_FLIP_CODE = 1
NS_PER_MS = 1_000_000

_CAMERA_INDEX: int = 0
_WIDTH_PX: int = 0
_HEIGHT_PX: int = 0
_TARGET_FPS: int = 0
_capture: cv2.VideoCapture | None = None


def camera_capture_task(stop_event: threading.Event, config: AppConfig) -> None:
    """Camera capture task'ı. Kamerayı açar ve kareleri sürekli yayınlar.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    if not _init(config):
        log.error("Kamera başlatılamadı, task sonlandırılıyor.")
        return

    fail_count = 0
    try:
        while not stop_event.is_set():
            ok, image = _capture.read()
            if not ok:
                fail_count += 1
                if fail_count == READ_FAIL_LIMIT:
                    log.error("Kameradan art arda %d kare okunamadı.", READ_FAIL_LIMIT)
                    raise_error(DeviceError.CAMERA_READ_ERROR)
                stop_event.wait(READ_RETRY_SEC)
                continue
            if fail_count >= READ_FAIL_LIMIT:
                log.info("Kamera okuması düzeldi.")
                clear_error(DeviceError.CAMERA_READ_ERROR)
            fail_count = 0
            frame = Frame(image=cv2.flip(image, HORIZONTAL_FLIP_CODE), timestamp_ms=_now_ms())
            orb_publish(topics.frame_topic, frame)
    except Exception:
        log.exception("Beklenmeyen hata, task sonlandırılıyor.")
    finally:
        _deinit()


def _init(config: AppConfig) -> bool:
    global _capture
    _load_settings(config)
    try:
        # DirectShow, Windows'ta varsayılan MSMF arka ucundan çok daha hızlı açılıyor.
        capture = cv2.VideoCapture(_CAMERA_INDEX, cv2.CAP_DSHOW)
    except cv2.error as err:
        log.error("Kamera açılırken hata: %s", err)
        raise_error(DeviceError.CAMERA_INIT_ERROR)
        return False
    if not capture.isOpened():
        log.error("Kamera açılamadı (indeks %d). İzin, indeks veya başka uygulama?", _CAMERA_INDEX)
        capture.release()
        raise_error(DeviceError.CAMERA_INIT_ERROR)
        return False

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, _WIDTH_PX)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, _HEIGHT_PX)
    capture.set(cv2.CAP_PROP_FPS, _TARGET_FPS)
    _capture = capture
    clear_error(DeviceError.CAMERA_INIT_ERROR)
    log.info(
        "Kamera açıldı: indeks %d, %dx%d",
        _CAMERA_INDEX,
        int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    return True


def _load_settings(config: AppConfig) -> None:
    global _CAMERA_INDEX, _WIDTH_PX, _HEIGHT_PX, _TARGET_FPS
    _CAMERA_INDEX = config.camera.index
    _WIDTH_PX = config.camera.width_px
    _HEIGHT_PX = config.camera.height_px
    _TARGET_FPS = config.camera.target_fps


def _now_ms() -> int:
    return time.monotonic_ns() // NS_PER_MS


def _deinit() -> None:
    """Kamerayı serbest bırakır (kamera ışığı söner)."""
    global _capture
    if _capture is not None:
        _capture.release()
        _capture = None
        log.info("Kamera serbest bırakıldı.")
