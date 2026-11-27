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


def _config(**overrides: float) -> FatigueConfig:
    values = {
        "calibration_duration_sec": CALIBRATION_SEC,
        "ear_closed_ratio": 0.75,
        "drowsy_closed_sec": 1.5,
        "asleep_closed_sec": 3.0,
        "perclos_window_sec": 60.0,
        "perclos_drowsy_threshold": 0.25,
        "yawn_mar_threshold": 0.6,
        "yawn_min_duration_sec": 1.0,
        "yawn_window_sec": 300.0,
        "yawn_count_drowsy": 3,
        "no_face_timeout_sec": 5.0,
        "head_drop_no_face_sec": 1.0,
        "awake_recovery_sec": 2.0,
    }
    values.update(overrides)
    return FatigueConfig(**values)


class _Feeder:
    """Durum makinesine sabit aralıklı sentetik ölçümler besler.

    Süreler ilk örnekten itibaren sayıldığı için N sn beslemek (N - 0,1) sn kapalı/açık süre üretir.
    """

    def __init__(self, machine: FatigueStateMachine) -> None:
        self.machine = machine
        self.now_ms = 0
        self.state: FatigueState | None = None

    def feed(
        self, ear: float, duration_sec: float, face_present: bool = True, mar: float = 0.0
    ) -> FatigueState:
        steps = round(duration_sec * 1000 / STEP_MS)
        for _ in range(steps):
            self.now_ms += STEP_MS
            metrics = FaceMetrics(
                face_present=face_present, ear=ear, mar=mar, timestamp_ms=self.now_ms
            )
            self.state = self.machine.update(metrics)
        return self.state


def _calibrated(**overrides: float) -> _Feeder:
    feeder = _Feeder(FatigueStateMachine(_config(**overrides)))
    feeder.feed(OPEN_EAR, CALIBRATION_SEC + 0.2)
    assert feeder.machine.level is FatigueLevel.AWAKE
    return feeder


@pytest.fixture
def calibrated() -> _Feeder:
    return _calibrated()


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


# --- Faz_7: PERCLOS, esneme, yüz yok, kafa düşmesi, skor ---

YAWN_MAR = 0.8
SHORT_PERCLOS_WINDOW_SEC = 10.0


def test_perclos_triggers_drowsy_only_after_window_is_full() -> None:
    feeder = _calibrated(perclos_window_sec=SHORT_PERCLOS_WINDOW_SEC)
    # Her saniyenin 0,4 sn'si kapalı: kısa kapanışlar, tek başına DROWSY yapmaz. PERCLOS ~%40.
    for _ in range(9):
        feeder.feed(CLOSED_EAR, 0.4)
        state = feeder.feed(OPEN_EAR, 0.6)
        assert state.level is FatigueLevel.AWAKE, "pencere dolmadan tetiklememeli"
    assert state.perclos > 0.25
    for _ in range(2):
        feeder.feed(CLOSED_EAR, 0.4)
        state = feeder.feed(OPEN_EAR, 0.6)
        if state.level is FatigueLevel.DROWSY:
            break
    assert feeder.machine.level is FatigueLevel.DROWSY


def test_perclos_evidence_is_consumed_after_trigger() -> None:
    feeder = _calibrated(perclos_window_sec=SHORT_PERCLOS_WINDOW_SEC)
    for _ in range(12):
        feeder.feed(CLOSED_EAR, 0.4)
        feeder.feed(OPEN_EAR, 0.6)
    assert feeder.machine.level is FatigueLevel.DROWSY or feeder.machine.perclos < 0.25
    # Gözler açık: AWAKE'e döner ve hemen tekrar DROWSY olmaz.
    assert feeder.feed(OPEN_EAR, 2.1).level is FatigueLevel.AWAKE
    assert feeder.feed(OPEN_EAR, 3.0).level is FatigueLevel.AWAKE


def test_low_perclos_stays_awake() -> None:
    feeder = _calibrated(perclos_window_sec=SHORT_PERCLOS_WINDOW_SEC)
    for _ in range(15):
        feeder.feed(CLOSED_EAR, 0.2)
        state = feeder.feed(OPEN_EAR, 1.8)
    assert state.level is FatigueLevel.AWAKE
    assert state.perclos < 0.25


def test_yawn_counted_once_per_long_mouth_opening(calibrated: _Feeder) -> None:
    calibrated.feed(OPEN_EAR, 0.5, mar=YAWN_MAR)  # kısa: esneme sayılmaz (konuşma vb.)
    calibrated.feed(OPEN_EAR, 1.0)
    assert calibrated.machine.yawn_count == 0
    calibrated.feed(OPEN_EAR, 3.0, mar=YAWN_MAR)  # uzun: tek esneme
    state = calibrated.feed(OPEN_EAR, 1.0)
    assert state.yawn_count == 1
    assert state.level is FatigueLevel.AWAKE


def test_three_yawns_trigger_drowsy_and_reset_counter(calibrated: _Feeder) -> None:
    for _ in range(2):
        calibrated.feed(OPEN_EAR, 1.5, mar=YAWN_MAR)
        calibrated.feed(OPEN_EAR, 2.0)
    assert calibrated.machine.level is FatigueLevel.AWAKE
    state = calibrated.feed(OPEN_EAR, 1.5, mar=YAWN_MAR)
    assert state.level is FatigueLevel.DROWSY
    assert state.yawn_count == 0
    assert calibrated.feed(OPEN_EAR, 2.1).level is FatigueLevel.AWAKE


def test_old_yawns_expire() -> None:
    feeder = _calibrated(yawn_window_sec=10.0)
    for _ in range(2):
        feeder.feed(OPEN_EAR, 1.5, mar=YAWN_MAR)
        feeder.feed(OPEN_EAR, 1.0)
    assert feeder.machine.yawn_count == 2
    feeder.feed(OPEN_EAR, 10.0)
    assert feeder.machine.yawn_count == 0


def test_awake_face_lost_becomes_no_face_and_recovers(calibrated: _Feeder) -> None:
    assert calibrated.feed(0.0, 4.0, face_present=False).level is FatigueLevel.AWAKE
    assert calibrated.feed(0.0, 1.1, face_present=False).level is FatigueLevel.NO_FACE
    assert calibrated.feed(OPEN_EAR, 0.1).level is FatigueLevel.AWAKE


def test_drowsy_face_lost_becomes_asleep(calibrated: _Feeder) -> None:
    calibrated.feed(CLOSED_EAR, 2.0)
    assert calibrated.machine.level is FatigueLevel.DROWSY
    assert calibrated.feed(0.0, 0.5, face_present=False).level is FatigueLevel.DROWSY
    assert calibrated.feed(0.0, 0.6, face_present=False).level is FatigueLevel.ASLEEP


def test_asleep_stays_asleep_when_face_lost(calibrated: _Feeder) -> None:
    calibrated.feed(CLOSED_EAR, 3.1)
    assert calibrated.feed(0.0, 10.0, face_present=False).level is FatigueLevel.ASLEEP


def test_score_is_consistent_with_level(calibrated: _Feeder) -> None:
    assert calibrated.feed(OPEN_EAR, 1.0).score == 0
    assert 0 < calibrated.feed(CLOSED_EAR, 1.0).score < 60
    assert calibrated.feed(CLOSED_EAR, 0.6).score >= 60  # DROWSY
    assert calibrated.feed(CLOSED_EAR, 1.5).score == 100  # ASLEEP
    calibrated.feed(OPEN_EAR, 2.1)
    calibrated.feed(OPEN_EAR, 1.5, mar=YAWN_MAR)
    assert calibrated.feed(OPEN_EAR, 0.5).score > 0  # bir esneme skoru artırır


def test_score_zero_while_calibrating() -> None:
    feeder = _Feeder(FatigueStateMachine(_config()))
    assert feeder.feed(CLOSED_EAR, 1.0).score == 0
