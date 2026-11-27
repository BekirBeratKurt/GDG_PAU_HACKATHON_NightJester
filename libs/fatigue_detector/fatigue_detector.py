"""Fatigue detector modülü: kalibrasyon ve uyanık / uykulu / uyuyor durum makinesi."""

from __future__ import annotations

import dataclasses
import logging
import threading

import numpy as np

from libs.communicator import orb_copy, orb_publish, orb_subscribe, topics
from libs.communicator.topics import AppMode, FaceMetrics, FatigueLevel, FatigueState
from libs.config_manager import AppConfig, FatigueConfig
from libs.device_state_tracker import update_device_state

TAG = "FatigueDetector"
log = logging.getLogger(TAG)

LOOP_PERIOD_SEC = 0.1
MS_PER_SEC = 1000.0
MIN_CALIBRATION_SAMPLES = 20
SCORE_MAX = 100

_face_metrics_sub = None
_app_mode_sub = None
_calibration_request_sub = None


class FatigueStateMachine:
    """Yüz ölçümlerinden yorgunluk seviyesini çıkaran durum makinesi.

    Zaman olarak ölçümlerin kendi zaman damgası kullanılır, böylece sentetik dizilerle
    test edilebilir. Thread-safe değildir, tek bir task'tan kullanılır.
    """

    def __init__(self, cfg: FatigueConfig) -> None:
        """Ayarları bağlar ve kalibrasyonu başlatır.

        Args:
            cfg: Yorgunluk tespiti ayarları.
        """
        self.apply_settings(cfg)
        self._level = FatigueLevel.CALIBRATING
        self._ear_threshold = 0.0
        self._calibration_samples: list[float] = []
        self._calibration_start_ms: int | None = None
        self._closed_since_ms: int | None = None
        self._open_since_ms: int | None = None
        self.start_calibration()

    @property
    def level(self) -> FatigueLevel:
        """Şu anki yorgunluk seviyesi."""
        return self._level

    @property
    def ear_threshold(self) -> float:
        """Kalibrasyonla belirlenen göz kapalı eşiği (kalibrasyon yoksa 0)."""
        return self._ear_threshold

    def apply_settings(self, cfg: FatigueConfig) -> None:
        """Ayar değerlerini durum makinesinin sabitlerine bağlar.

        Args:
            cfg: Yorgunluk tespiti ayarları.
        """
        self._calibration_duration_sec = cfg.calibration_duration_sec
        self._ear_closed_ratio = cfg.ear_closed_ratio
        self._drowsy_closed_sec = cfg.drowsy_closed_sec
        self._asleep_closed_sec = cfg.asleep_closed_sec
        self._awake_recovery_sec = cfg.awake_recovery_sec

    def start_calibration(self) -> None:
        """Kalibrasyonu (yeniden) başlatır. Bitene kadar tespit yapılmaz."""
        self._level = FatigueLevel.CALIBRATING
        self._ear_threshold = 0.0
        self._calibration_samples = []
        self._calibration_start_ms = None
        self._closed_since_ms = None
        self._open_since_ms = None

    def update(self, metrics: FaceMetrics) -> FatigueState:
        """Yeni bir ölçümü işler ve güncel durumu döner.

        Args:
            metrics: face_analyzer'dan gelen ölçüm.

        Returns:
            Güncel yorgunluk durumu.
        """
        now_ms = metrics.timestamp_ms
        if self._level is FatigueLevel.CALIBRATING:
            self._update_calibration(metrics, now_ms)
        elif metrics.face_present:
            self._update_detection(metrics.ear, now_ms)
        else:
            # Yüz yokken göz süresi ölçülemez. NO_FACE ve kafa düşmesi kuralı Faz_7'de.
            self._closed_since_ms = None
            self._open_since_ms = None
        return self._make_state(now_ms)

    def _update_calibration(self, metrics: FaceMetrics, now_ms: int) -> None:
        if self._calibration_start_ms is None:
            self._calibration_start_ms = now_ms
        if metrics.face_present:
            self._calibration_samples.append(metrics.ear)

        elapsed_sec = (now_ms - self._calibration_start_ms) / MS_PER_SEC
        if (
            elapsed_sec < self._calibration_duration_sec
            or len(self._calibration_samples) < MIN_CALIBRATION_SAMPLES
        ):
            return
        # Medyan, kalibrasyon sırasındaki göz kırpmalarından etkilenmez.
        baseline_ear = float(np.median(self._calibration_samples))
        self._ear_threshold = baseline_ear * self._ear_closed_ratio
        self._level = FatigueLevel.AWAKE
        log.info(
            "Kalibrasyon tamamlandı: baseline EAR %.3f, eşik %.3f (%d örnek)",
            baseline_ear,
            self._ear_threshold,
            len(self._calibration_samples),
        )

    def _update_detection(self, ear: float, now_ms: int) -> None:
        if ear < self._ear_threshold:
            self._open_since_ms = None
            if self._closed_since_ms is None:
                self._closed_since_ms = now_ms
            closed_sec = (now_ms - self._closed_since_ms) / MS_PER_SEC
            if closed_sec >= self._asleep_closed_sec:
                self._level = FatigueLevel.ASLEEP
            elif closed_sec >= self._drowsy_closed_sec and self._level is FatigueLevel.AWAKE:
                self._level = FatigueLevel.DROWSY
            return

        self._closed_since_ms = None
        if self._open_since_ms is None:
            self._open_since_ms = now_ms
        open_sec = (now_ms - self._open_since_ms) / MS_PER_SEC
        if self._level is not FatigueLevel.AWAKE and open_sec >= self._awake_recovery_sec:
            self._level = FatigueLevel.AWAKE

    def _eyes_closed_sec(self, now_ms: int) -> float:
        if self._closed_since_ms is None:
            return 0.0
        return (now_ms - self._closed_since_ms) / MS_PER_SEC

    def _make_state(self, now_ms: int) -> FatigueState:
        eyes_closed_sec = self._eyes_closed_sec(now_ms)
        return FatigueState(
            level=self._level,
            score=self._score(eyes_closed_sec),
            eyes_closed_sec=eyes_closed_sec,
            perclos=0.0,
            ear_threshold=self._ear_threshold,
            timestamp_ms=now_ms,
        )

    def _score(self, eyes_closed_sec: float) -> int:
        # Geçici skor: sadece kapalı göz süresi. PERCLOS ve esneme ile Faz_7'de genişletilecek.
        if self._level is FatigueLevel.ASLEEP:
            return SCORE_MAX
        if self._asleep_closed_sec <= 0:
            return 0
        return int(min(1.0, eyes_closed_sec / self._asleep_closed_sec) * SCORE_MAX)


def apply_app_mode(state: FatigueState, mode: AppMode) -> FatigueState:
    """Moda göre yayınlanacak durumu döner. PAUSED'da tespit çalışır ama AWAKE yayınlanır.

    Args:
        state: Durum makinesinin ürettiği durum.
        mode: Uygulama modu.

    Returns:
        Yayınlanacak durum.
    """
    if mode is AppMode.PAUSED and state.level is not FatigueLevel.CALIBRATING:
        return dataclasses.replace(state, level=FatigueLevel.AWAKE, score=0)
    return state


def fatigue_detector_task(stop_event: threading.Event, config: AppConfig) -> None:
    """Fatigue detector task'ı. Yüz ölçümlerini işler ve yorgunluk durumunu yayınlar.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    _init()
    machine = FatigueStateMachine(config.fatigue_detector)
    mode = _initial_mode(config.ui.start_mode)
    update_device_state(calibrated=False)
    last_level: FatigueLevel | None = None
    log.info(
        "Kalibrasyon başladı: %.0f sn ekrana normal şekilde bak.",
        config.fatigue_detector.calibration_duration_sec,
    )

    try:
        while not stop_event.is_set():
            mode_updated, new_mode = orb_copy(_app_mode_sub)
            if mode_updated and isinstance(new_mode, AppMode):
                mode = new_mode
                log.info("Mod: %s", mode.name)

            request_updated, _ = orb_copy(_calibration_request_sub)
            if request_updated:
                machine.start_calibration()
                update_device_state(calibrated=False)
                log.info("Kalibrasyon yeniden başlatıldı.")

            metrics_updated, metrics = orb_copy(_face_metrics_sub)
            if metrics_updated:
                state = machine.update(metrics)
                if state.level is not last_level:
                    _on_level_change(last_level, state.level)
                    last_level = state.level
                orb_publish(topics.fatigue_state_topic, apply_app_mode(state, mode))
            stop_event.wait(LOOP_PERIOD_SEC)
    except Exception:
        log.exception("Beklenmeyen hata, task sonlandırılıyor.")


def _init() -> None:
    global _face_metrics_sub, _app_mode_sub, _calibration_request_sub
    _face_metrics_sub = orb_subscribe(topics.face_metrics_topic)
    _app_mode_sub = orb_subscribe(topics.app_mode_topic)
    _calibration_request_sub = orb_subscribe(topics.calibration_request_topic)


def _initial_mode(name: str) -> AppMode:
    try:
        return AppMode[name]
    except KeyError:
        log.warning("Geçersiz başlangıç modu '%s', NORMAL kullanılıyor.", name)
        return AppMode.NORMAL


def _on_level_change(old: FatigueLevel | None, new: FatigueLevel) -> None:
    if old is FatigueLevel.CALIBRATING:
        update_device_state(calibrated=True)
    log.info("Durum: %s -> %s", old.name if old else "-", new.name)
