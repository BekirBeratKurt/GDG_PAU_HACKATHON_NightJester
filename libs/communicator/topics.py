"""Topic isimleri, topic handle'ları ve topic veri tipleri. Tek doğru kaynak bu dosyadır."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import numpy as np

from .communicator import OrbTopic

# TOPIC İSİMLERİ
FRAME_TOPIC = "frame"
FACE_METRICS_TOPIC = "face_metrics"
FATIGUE_STATE_TOPIC = "fatigue_state"
APP_MODE_TOPIC = "app_mode"
ALERT_COMMAND_TOPIC = "alert_command"
CALIBRATION_REQUEST_TOPIC = "calibration_request"
GUARDIAN_RESULT_TOPIC = "guardian_result"
CONFIG_UPDATED_TOPIC = "config_updated"

# TOPICS (main.py'deki _advertise_all_topics içinde atanır)
frame_topic: OrbTopic | None = None  # camera_capture → face_analyzer, ui
face_metrics_topic: OrbTopic | None = None  # face_analyzer → fatigue_detector, ui
# fatigue_detector → alert_manager, code_guardian, session_logger, ui
fatigue_state_topic: OrbTopic | None = None
app_mode_topic: OrbTopic | None = None  # ui, tray → fatigue_detector, alert_manager, code_guardian
alert_command_topic: OrbTopic | None = None  # ui, tray → alert_manager
calibration_request_topic: OrbTopic | None = None  # ui → fatigue_detector
guardian_result_topic: OrbTopic | None = None  # code_guardian → ui, alert_manager, session_logger
config_updated_topic: OrbTopic | None = None  # ui → fatigue_detector, alert_manager, code_guardian


# TYPES
class AppMode(Enum):
    """Uygulamanın çalışma modu."""

    NORMAL = auto()
    DEADLINE = auto()
    PAUSED = auto()


class FatigueLevel(Enum):
    """Yorgunluk seviyesi."""

    AWAKE = auto()
    DROWSY = auto()
    ASLEEP = auto()
    NO_FACE = auto()
    CALIBRATING = auto()


@dataclass
class Frame:
    """Kameradan okunan tek kare."""

    image: np.ndarray  # BGR
    timestamp_ms: int


@dataclass
class FaceMetrics:
    """Tek kare için yüz ölçümleri."""

    face_present: bool
    ear: float  # iki gözün ortalaması
    mar: float
    timestamp_ms: int
    landmarks_px: np.ndarray | None = None  # önizleme overlay'i için


@dataclass
class FatigueState:
    """Yorgunluk durum makinesinin çıktısı."""

    level: FatigueLevel
    score: int  # 0–100
    eyes_closed_sec: float
    perclos: float  # 0.0–1.0
    ear_threshold: float
    timestamp_ms: int


@dataclass
class AlertCommand:
    """UI veya tray'den alert_manager'a gönderilen komut."""

    action: str  # "stop" | "test"


@dataclass
class GuardianResult:
    """Kod Koruyucu snapshot sonucu."""

    success: bool
    repo_path: str
    message: str
    timestamp_ms: int
