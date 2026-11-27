"""Face analyzer modülü: MediaPipe FaceLandmarker ile EAR, MAR ve yüz var/yok hesaplar."""

from __future__ import annotations

import logging
import threading

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from libs.communicator import orb_copy, orb_publish, orb_subscribe, topics
from libs.communicator.topics import FaceMetrics, Frame
from libs.config_manager import AppConfig, project_path
from libs.device_state_tracker import DeviceError, clear_error, raise_error

TAG = "FaceAnalyzer"
log = logging.getLogger(TAG)

IDLE_WAIT_SEC = 0.005
NUM_FACES = 1

# 478 noktalı Face Mesh indeksleri. EAR sırası: p1, p2, p3, p4, p5, p6.
LEFT_EYE_IDX = (33, 160, 158, 133, 153, 144)
RIGHT_EYE_IDX = (362, 385, 387, 263, 373, 380)
# MAR sırası: üst dudak, alt dudak, sol köşe, sağ köşe.
MOUTH_IDX = (13, 14, 61, 291)
_OVERLAY_IDX = np.array(LEFT_EYE_IDX + RIGHT_EYE_IDX + MOUTH_IDX)

_MODEL_PATH: str = ""
_MIN_DETECTION_CONFIDENCE: float = 0.0
_landmarker: vision.FaceLandmarker | None = None
_frame_sub = None
_last_timestamp_ms: int = -1


def face_analyzer_task(stop_event: threading.Event, config: AppConfig) -> None:
    """Face analyzer task'ı. Her yeni karede yüz noktalarını bulur ve ölçümleri yayınlar.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    if not _init(config):
        log.error("Yüz analizi başlatılamadı, task sonlandırılıyor.")
        return

    try:
        while not stop_event.is_set():
            updated, frame = orb_copy(_frame_sub)
            if not updated:
                stop_event.wait(IDLE_WAIT_SEC)
                continue
            orb_publish(topics.face_metrics_topic, _analyze(frame))
    except Exception:
        log.exception("Beklenmeyen hata, task sonlandırılıyor.")
    finally:
        _deinit()


def compute_ear(points_px: np.ndarray, eye_idx: tuple[int, ...]) -> float:
    """Göz açıklık oranını (EAR) hesaplar.

    EAR = (|p2 − p6| + |p3 − p5|) / (2 · |p1 − p4|)

    Args:
        points_px: Piksel cinsinden yüz noktaları, şekil (N, 2).
        eye_idx: Gözün p1…p6 nokta indeksleri.

    Returns:
        EAR değeri. Göz kapandıkça 0'a yaklaşır.
    """
    p1, p2, p3, p4, p5, p6 = (points_px[i] for i in eye_idx)
    horizontal = np.linalg.norm(p1 - p4)
    if horizontal == 0:
        return 0.0
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2.0 * horizontal))


def compute_mar(points_px: np.ndarray, mouth_idx: tuple[int, ...]) -> float:
    """Ağız açıklık oranını (MAR) hesaplar.

    Args:
        points_px: Piksel cinsinden yüz noktaları, şekil (N, 2).
        mouth_idx: Üst dudak, alt dudak, sol köşe, sağ köşe indeksleri.

    Returns:
        MAR değeri. Ağız açıldıkça artar.
    """
    top, bottom, left, right = (points_px[i] for i in mouth_idx)
    width = np.linalg.norm(left - right)
    if width == 0:
        return 0.0
    return float(np.linalg.norm(top - bottom) / width)


def _init(config: AppConfig) -> bool:
    global _landmarker, _frame_sub
    _load_settings(config)
    model_path = project_path(_MODEL_PATH)
    if not model_path.is_file():
        log.error("Model dosyası bulunamadı: %s", model_path)
        raise_error(DeviceError.MODEL_LOAD_ERROR)
        return False
    try:
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=NUM_FACES,
            min_face_detection_confidence=_MIN_DETECTION_CONFIDENCE,
        )
        _landmarker = vision.FaceLandmarker.create_from_options(options)
    except (RuntimeError, ValueError, OSError) as err:
        log.error("Model yüklenemedi: %s", err)
        raise_error(DeviceError.MODEL_LOAD_ERROR)
        return False
    _frame_sub = orb_subscribe(topics.frame_topic)
    clear_error(DeviceError.MODEL_LOAD_ERROR)
    log.info("FaceLandmarker modeli yüklendi.")
    return True


def _load_settings(config: AppConfig) -> None:
    global _MODEL_PATH, _MIN_DETECTION_CONFIDENCE
    _MODEL_PATH = config.face_analyzer.model_path
    _MIN_DETECTION_CONFIDENCE = config.face_analyzer.min_detection_confidence


def _analyze(frame: Frame) -> FaceMetrics:
    global _last_timestamp_ms
    # VIDEO modu kesin artan zaman damgası ister, aynı ms'de iki kare gelirse hata verir.
    timestamp_ms = max(frame.timestamp_ms, _last_timestamp_ms + 1)
    _last_timestamp_ms = timestamp_ms

    rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = _landmarker.detect_for_video(image, timestamp_ms)
    if not result.face_landmarks:
        return FaceMetrics(face_present=False, ear=0.0, mar=0.0, timestamp_ms=frame.timestamp_ms)

    # Noktalar normalize gelir. En-boy oranı EAR'ı bozmasın diye önce piksele çevrilir.
    height_px, width_px = frame.image.shape[:2]
    points_px = np.array(
        [(lm.x * width_px, lm.y * height_px) for lm in result.face_landmarks[0]],
        dtype=np.float32,
    )
    ear = (compute_ear(points_px, LEFT_EYE_IDX) + compute_ear(points_px, RIGHT_EYE_IDX)) / 2.0
    mar = compute_mar(points_px, MOUTH_IDX)
    return FaceMetrics(
        face_present=True,
        ear=ear,
        mar=mar,
        timestamp_ms=frame.timestamp_ms,
        landmarks_px=points_px[_OVERLAY_IDX],
    )


def _deinit() -> None:
    """Modeli kapatır."""
    global _landmarker
    if _landmarker is not None:
        _landmarker.close()
        _landmarker = None
        log.info("FaceLandmarker kapatıldı.")
