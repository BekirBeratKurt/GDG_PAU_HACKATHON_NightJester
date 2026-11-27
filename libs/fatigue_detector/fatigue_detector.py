"""Fatigue detector modülü: kalibrasyon ve uyanık / uykulu / uyuyor durum makinesi."""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections import deque

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
# Skor ağırlıkları (toplam 1). Kapalı göz en güçlü işaret olduğu için en yüksek ağırlıkta.
SCORE_WEIGHT_CLOSED = 0.5
SCORE_WEIGHT_PERCLOS = 0.3
SCORE_WEIGHT_YAWN = 0.2
# Seviye için en düşük skor: panelde "Uykulu" yazarken skorun düşük görünmemesi için.
SCORE_FLOOR: dict[FatigueLevel, int] = {FatigueLevel.DROWSY: 60, FatigueLevel.ASLEEP: 100}

_face_metrics_sub = None
_app_mode_sub = None
_calibration_request_sub = None
_config_updated_sub = None


class FatigueStateMachine:
    """Yüz ölçümlerinden yorgunluk seviyesini çıkaran durum makinesi.

    İşaretler: kesintisiz kapalı göz süresi, PERCLOS, esneme sayısı ve yüzün kaybolması.
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
        self._face_missing_since_ms: int | None = None
        self._perclos_samples: deque[tuple[int, bool]] = deque()
        self._perclos_start_ms: int | None = None
        self._yawn_times_ms: deque[int] = deque()
        self._mouth_open_since_ms: int | None = None
        self._yawn_counted = False
        self._now_ms = 0
        self.start_calibration()

    @property
    def level(self) -> FatigueLevel:
        """Şu anki yorgunluk seviyesi."""
        return self._level

    @property
    def ear_threshold(self) -> float:
        """Kalibrasyonla belirlenen göz kapalı eşiği (kalibrasyon yoksa 0)."""
        return self._ear_threshold

    @property
    def perclos(self) -> float:
        """Pencere içinde gözlerin kapalı olduğu örnek oranı (0.0–1.0)."""
        if not self._perclos_samples:
            return 0.0
        closed = sum(1 for _, is_closed in self._perclos_samples if is_closed)
        return closed / len(self._perclos_samples)

    @property
    def perclos_ready(self) -> bool:
        """PERCLOS penceresi dolu mu. Dolmadan PERCLOS tetiklemez."""
        if self._perclos_start_ms is None:
            return False
        return (self._now_ms - self._perclos_start_ms) / MS_PER_SEC >= self._perclos_window_sec

    @property
    def yawn_count(self) -> int:
        """Son yawn_window_sec içindeki esneme sayısı."""
        return len(self._yawn_times_ms)

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
        self._perclos_window_sec = cfg.perclos_window_sec
        self._perclos_drowsy_threshold = cfg.perclos_drowsy_threshold
        self._yawn_mar_threshold = cfg.yawn_mar_threshold
        self._yawn_min_duration_sec = cfg.yawn_min_duration_sec
        self._yawn_window_sec = cfg.yawn_window_sec
        self._yawn_count_drowsy = cfg.yawn_count_drowsy
        self._no_face_timeout_sec = cfg.no_face_timeout_sec
        self._head_drop_no_face_sec = cfg.head_drop_no_face_sec

    def start_calibration(self) -> None:
        """Kalibrasyonu (yeniden) başlatır. Bitene kadar tespit yapılmaz."""
        self._level = FatigueLevel.CALIBRATING
        self._ear_threshold = 0.0
        self._calibration_samples = []
        self._calibration_start_ms = None
        self._closed_since_ms = None
        self._open_since_ms = None
        self._face_missing_since_ms = None
        # Eşik değiştiği için eski PERCLOS örnekleri geçersizdir.
        self._reset_perclos()
        self._yawn_times_ms.clear()
        self._mouth_open_since_ms = None

    def update(self, metrics: FaceMetrics) -> FatigueState:
        """Yeni bir ölçümü işler ve güncel durumu döner.

        Args:
            metrics: face_analyzer'dan gelen ölçüm.

        Returns:
            Güncel yorgunluk durumu.
        """
        now_ms = metrics.timestamp_ms
        self._now_ms = now_ms
        if self._level is FatigueLevel.CALIBRATING:
            self._update_calibration(metrics, now_ms)
        elif metrics.face_present:
            self._face_missing_since_ms = None
            if self._level is FatigueLevel.NO_FACE:
                self._level = FatigueLevel.AWAKE
            eyes_closed = metrics.ear < self._ear_threshold
            self._update_perclos(eyes_closed, now_ms)
            self._update_yawns(metrics.mar, now_ms)
            self._update_eyes(eyes_closed, now_ms)
            self._apply_drowsy_signals()
        else:
            self._update_face_missing(now_ms)
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

    def _update_eyes(self, eyes_closed: bool, now_ms: int) -> None:
        if eyes_closed:
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

    def _update_perclos(self, eyes_closed: bool, now_ms: int) -> None:
        if self._perclos_start_ms is None:
            self._perclos_start_ms = now_ms
        self._perclos_samples.append((now_ms, eyes_closed))
        cutoff_ms = now_ms - self._perclos_window_sec * MS_PER_SEC
        while self._perclos_samples and self._perclos_samples[0][0] < cutoff_ms:
            self._perclos_samples.popleft()

    def _reset_perclos(self) -> None:
        self._perclos_samples.clear()
        self._perclos_start_ms = None

    def _update_yawns(self, mar: float, now_ms: int) -> None:
        cutoff_ms = now_ms - self._yawn_window_sec * MS_PER_SEC
        while self._yawn_times_ms and self._yawn_times_ms[0] < cutoff_ms:
            self._yawn_times_ms.popleft()

        if mar <= self._yawn_mar_threshold:
            self._mouth_open_since_ms = None
            return
        if self._mouth_open_since_ms is None:
            self._mouth_open_since_ms = now_ms
            self._yawn_counted = False
        open_sec = (now_ms - self._mouth_open_since_ms) / MS_PER_SEC
        if not self._yawn_counted and open_sec >= self._yawn_min_duration_sec:
            self._yawn_counted = True
            self._yawn_times_ms.append(now_ms)
            log.info("Esneme algılandı (%d / %d)", self.yawn_count, self._yawn_count_drowsy)

    def _apply_drowsy_signals(self) -> None:
        if self._level is not FatigueLevel.AWAKE:
            return
        # Tetikleyen kanıt tüketilir. Yoksa gözler açılıp AWAKE'e dönülünce hâlâ yüksek olan
        # PERCLOS / esneme sayısı hemen tekrar DROWSY yapar ve durum gidip gelir.
        if self.perclos_ready and self.perclos > self._perclos_drowsy_threshold:
            log.info("PERCLOS eşiği aşıldı: %%%.0f", self.perclos * 100)
            self._level = FatigueLevel.DROWSY
            self._reset_perclos()
        elif self.yawn_count >= self._yawn_count_drowsy:
            log.info("Esneme eşiği aşıldı: %d esneme", self.yawn_count)
            self._level = FatigueLevel.DROWSY
            self._yawn_times_ms.clear()
        else:
            return
        # Gözler zaten uzun süredir açık olabilir. Sıfırlanmazsa bir sonraki örnekte
        # "açık göz ≥ awake_recovery_sec" kuralı DROWSY'yi anında geri alır.
        self._open_since_ms = None

    def _update_face_missing(self, now_ms: int) -> None:
        self._closed_since_ms = None
        self._open_since_ms = None
        self._mouth_open_since_ms = None
        if self._face_missing_since_ms is None:
            self._face_missing_since_ms = now_ms
        missing_sec = (now_ms - self._face_missing_since_ms) / MS_PER_SEC
        if self._level is FatigueLevel.DROWSY and missing_sec >= self._head_drop_no_face_sec:
            log.info("Uykulu iken yüz kayboldu, kafa düşmüş olabilir.")
            self._level = FatigueLevel.ASLEEP
        elif self._level is FatigueLevel.AWAKE and missing_sec >= self._no_face_timeout_sec:
            self._level = FatigueLevel.NO_FACE
        # ASLEEP iken yüz kaybolursa ASLEEP kalınır: kafa masada olabilir, alarm susmamalı.

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
            perclos=self.perclos,
            ear_threshold=self._ear_threshold,
            timestamp_ms=now_ms,
            yawn_count=self.yawn_count,
        )

    def _score(self, eyes_closed_sec: float) -> int:
        if self._level is FatigueLevel.CALIBRATING:
            return 0
        closed_part = _ratio(eyes_closed_sec, self._asleep_closed_sec)
        # Pencere dolmadan PERCLOS güvenilir değil, skora katılmaz.
        perclos_part = (
            _ratio(self.perclos, self._perclos_drowsy_threshold) if self.perclos_ready else 0.0
        )
        yawn_part = _ratio(self.yawn_count, self._yawn_count_drowsy)
        raw = (
            SCORE_WEIGHT_CLOSED * closed_part
            + SCORE_WEIGHT_PERCLOS * perclos_part
            + SCORE_WEIGHT_YAWN * yawn_part
        )
        return max(round(raw * SCORE_MAX), SCORE_FLOOR.get(self._level, 0))


def _ratio(value: float, limit: float) -> float:
    if limit <= 0:
        return 0.0
    return min(1.0, value / limit)


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

            config_updated, new_config = orb_copy(_config_updated_sub)
            if config_updated and isinstance(new_config, AppConfig):
                machine.apply_settings(new_config.fatigue_detector)
                log.info("Tespit ayarları güncellendi.")

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
    global _face_metrics_sub, _app_mode_sub, _calibration_request_sub, _config_updated_sub
    _face_metrics_sub = orb_subscribe(topics.face_metrics_topic)
    _app_mode_sub = orb_subscribe(topics.app_mode_topic)
    _calibration_request_sub = orb_subscribe(topics.calibration_request_topic)
    _config_updated_sub = orb_subscribe(topics.config_updated_topic)


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
