"""face_analyzer birim testleri: EAR ve MAR formülleri."""

from __future__ import annotations

import numpy as np
import pytest

from libs.face_analyzer import compute_ear, compute_mar

EYE_IDX = (0, 1, 2, 3, 4, 5)
MOUTH_IDX = (0, 1, 2, 3)


def _eye(opening_px: float) -> np.ndarray:
    # p1 sol köşe, p4 sağ köşe (genişlik 30 px). p2/p3 üstte, p6/p5 altta.
    half = opening_px / 2
    return np.array(
        [[0, 0], [10, -half], [20, -half], [30, 0], [20, half], [10, half]], dtype=np.float32
    )


def test_ear_open_eye() -> None:
    assert compute_ear(_eye(10.0), EYE_IDX) == pytest.approx(10.0 / 30.0)


def test_ear_closed_eye_is_zero() -> None:
    assert compute_ear(_eye(0.0), EYE_IDX) == pytest.approx(0.0)


def test_ear_decreases_when_eye_closes() -> None:
    assert compute_ear(_eye(4.0), EYE_IDX) < compute_ear(_eye(10.0), EYE_IDX)


def test_ear_zero_width_does_not_divide_by_zero() -> None:
    assert compute_ear(np.zeros((6, 2), dtype=np.float32), EYE_IDX) == 0.0


def test_mar_open_and_closed_mouth() -> None:
    closed = np.array([[25, 0], [25, 0], [0, 0], [50, 0]], dtype=np.float32)
    opened = np.array([[25, -15], [25, 15], [0, 0], [50, 0]], dtype=np.float32)
    assert compute_mar(closed, MOUTH_IDX) == pytest.approx(0.0)
    assert compute_mar(opened, MOUTH_IDX) == pytest.approx(30.0 / 50.0)
