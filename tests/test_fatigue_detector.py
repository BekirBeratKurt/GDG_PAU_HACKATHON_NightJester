"""fatigue_detector birim testleri: sentetik EAR dizileriyle kalibrasyon ve durum geçişleri."""

from __future__ import annotations

import pytest

from libs.communicator.topics import AppMode, FaceMetrics, FatigueLevel, FatigueState
from libs.config_manager import FatigueConfig
from libs.fatigue_detector import FatigueStateMachine, apply_app_mode

STEP_MS = 100  # task 10 Hz çalışır
OPEN_EAR = 0.30
CLOSED_EAR = 0.05
CALIBRATION_SEC = 5.0


def _config() -> FatigueConfig:
    return FatigueConfig(
        calibration_duration_sec=CALIBRATION_SEC,
        ear_closed_ratio=0.75,
        drowsy_closed_sec=1.5,
        asleep_closed_sec=3.0,
        perclos_window_sec=60.0,
        perclos_drowsy_threshold=0.25,
        yawn_mar_threshold=0.6,
        yawn_min_duration_sec=1.0,
        no_face_timeout_sec=5.0,
        awake_recovery_sec=2.0,
    )


class _Feeder:
    """Durum makinesine sabit aralıklı sentetik ölçümler besler.

    Süreler ilk örnekten itibaren sayıldığı için N sn beslemek (N - 0,1) sn kapalı/açık süre üretir.
    """

    def __init__(self, machine: FatigueStateMachine) -> None:
        self.machine = machine
        self.now_ms = 0
        self.state: FatigueState | None = None

    def feed(self, ear: float, duration_sec: float, face_present: bool = True) -> FatigueState:
        steps = round(duration_sec * 1000 / STEP_MS)
        for _ in range(steps):
            self.now_ms += STEP_MS
            metrics = FaceMetrics(
                face_present=face_present, ear=ear, mar=0.0, timestamp_ms=self.now_ms
            )
            self.state = self.machine.update(metrics)
        return self.state


@pytest.fixture
def calibrated() -> _Feeder:
    feeder = _Feeder(FatigueStateMachine(_config()))
    feeder.feed(OPEN_EAR, CALIBRATION_SEC + 0.2)
    assert feeder.machine.level is FatigueLevel.AWAKE
    return feeder


def test_starts_in_calibration() -> None:
    feeder = _Feeder(FatigueStateMachine(_config()))
    state = feeder.feed(OPEN_EAR, 1.0)
    assert state.level is FatigueLevel.CALIBRATING
    assert state.ear_threshold == 0.0


def test_calibration_threshold_is_median_times_ratio() -> None:
    feeder = _Feeder(FatigueStateMachine(_config()))
    feeder.feed(OPEN_EAR, 2.0)
    feeder.feed(CLOSED_EAR, 0.3)  # kalibrasyon sırasında göz kırpma
    state = feeder.feed(OPEN_EAR, 3.2)
    assert state.level is FatigueLevel.AWAKE
    assert state.ear_threshold == pytest.approx(OPEN_EAR * 0.75)


def test_calibration_waits_for_face() -> None:
    feeder = _Feeder(FatigueStateMachine(_config()))
    feeder.feed(0.0, CALIBRATION_SEC + 1.0, face_present=False)
    assert feeder.machine.level is FatigueLevel.CALIBRATING
    feeder.feed(OPEN_EAR, 2.5)
    assert feeder.machine.level is FatigueLevel.AWAKE


def test_normal_blink_stays_awake(calibrated: _Feeder) -> None:
    for _ in range(5):
        calibrated.feed(CLOSED_EAR, 0.3)
        state = calibrated.feed(OPEN_EAR, 3.0)
        assert state.level is FatigueLevel.AWAKE


def test_closed_eyes_drowsy_then_asleep(calibrated: _Feeder) -> None:
    assert calibrated.feed(CLOSED_EAR, 1.5).level is FatigueLevel.AWAKE
    assert calibrated.feed(CLOSED_EAR, 0.1).level is FatigueLevel.DROWSY
    assert calibrated.feed(CLOSED_EAR, 1.4).level is FatigueLevel.DROWSY
    state = calibrated.feed(CLOSED_EAR, 0.1)
    assert state.level is FatigueLevel.ASLEEP
    assert state.eyes_closed_sec == pytest.approx(3.0)
    assert state.score == 100


def test_recovery_needs_continuous_open_eyes(calibrated: _Feeder) -> None:
    calibrated.feed(CLOSED_EAR, 3.1)
    assert calibrated.machine.level is FatigueLevel.ASLEEP
    assert calibrated.feed(OPEN_EAR, 1.0).level is FatigueLevel.ASLEEP
    calibrated.feed(CLOSED_EAR, 0.2)  # tekrar kapandı, açık süre sıfırlanır
    assert calibrated.feed(OPEN_EAR, 2.0).level is FatigueLevel.ASLEEP
    assert calibrated.feed(OPEN_EAR, 0.1).level is FatigueLevel.AWAKE


def test_drowsy_recovers_to_awake(calibrated: _Feeder) -> None:
    calibrated.feed(CLOSED_EAR, 2.0)
    assert calibrated.machine.level is FatigueLevel.DROWSY
    assert calibrated.feed(OPEN_EAR, 2.0).level is FatigueLevel.DROWSY
    assert calibrated.feed(OPEN_EAR, 0.1).level is FatigueLevel.AWAKE


def test_recalibration_resets_state(calibrated: _Feeder) -> None:
    calibrated.feed(CLOSED_EAR, 3.0)
    calibrated.machine.start_calibration()
    state = calibrated.feed(OPEN_EAR, 0.1)
    assert state.level is FatigueLevel.CALIBRATING
    assert state.ear_threshold == 0.0


def test_paused_mode_publishes_awake(calibrated: _Feeder) -> None:
    state = calibrated.feed(CLOSED_EAR, 3.1)
    assert apply_app_mode(state, AppMode.PAUSED).level is FatigueLevel.AWAKE
    assert apply_app_mode(state, AppMode.DEADLINE).level is FatigueLevel.ASLEEP
