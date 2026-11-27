"""device_state_tracker birim testleri: bitmask set/clear, durum bilgisi, gösterge desenleri."""

from __future__ import annotations

import pytest

from libs.device_state_tracker import (
    DeviceError,
    Indicator,
    clear_error,
    get_device_state,
    get_error_mask,
    get_error_status,
    raise_error,
    update_device_state,
)
from libs.device_state_tracker.device_state_tracker import (
    BLINK_FAST_MS,
    BLINK_SLOW_MS,
    compute_indicator_states,
)

ALL_ERRORS = DeviceError(0xFF)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    clear_error(ALL_ERRORS)
    update_device_state(calibrated=False, alarm_active=False)


def test_errors_are_single_bits_within_8_bits() -> None:
    for error in DeviceError:
        if error.value:
            assert error.value & (error.value - 1) == 0
            assert error.value <= 0x80


def test_raise_and_clear_single_error() -> None:
    assert get_error_mask() == DeviceError.NO_ERROR

    raise_error(DeviceError.CAMERA_INIT_ERROR)
    assert get_error_status(DeviceError.CAMERA_INIT_ERROR)
    assert get_error_mask() == DeviceError.CAMERA_INIT_ERROR

    clear_error(DeviceError.CAMERA_INIT_ERROR)
    assert not get_error_status(DeviceError.CAMERA_INIT_ERROR)
    assert get_error_mask() == DeviceError.NO_ERROR


def test_multiple_errors_are_independent() -> None:
    raise_error(DeviceError.GIT_ERROR)
    raise_error(DeviceError.CONFIG_ERROR)
    assert get_error_mask() == DeviceError.GIT_ERROR | DeviceError.CONFIG_ERROR

    clear_error(DeviceError.GIT_ERROR)
    assert get_error_mask() == DeviceError.CONFIG_ERROR
    assert get_error_status(DeviceError.CONFIG_ERROR)


def test_raise_twice_and_clear_unset_error_are_harmless() -> None:
    raise_error(DeviceError.AUDIO_INIT_ERROR)
    raise_error(DeviceError.AUDIO_INIT_ERROR)
    clear_error(DeviceError.MODEL_LOAD_ERROR)
    assert get_error_mask() == DeviceError.AUDIO_INIT_ERROR


def test_device_state_update_and_copy() -> None:
    update_device_state(alarm_active=True)
    state = get_device_state()
    assert state.alarm_active and not state.calibrated

    state.calibrated = True
    assert not get_device_state().calibrated


def test_device_state_unknown_field_raises() -> None:
    with pytest.raises(TypeError):
        update_device_state(unknown_field=True)


def test_indicators_all_off_without_errors() -> None:
    states = compute_indicator_states(DeviceError.NO_ERROR, now_ms=0)
    assert not any(states.values())


def test_solid_error_is_always_on() -> None:
    for now_ms in (0, BLINK_FAST_MS, BLINK_SLOW_MS, 12345):
        states = compute_indicator_states(DeviceError.AUDIO_INIT_ERROR, now_ms)
        assert states == {
            Indicator.VISION: False,
            Indicator.ALERT: True,
            Indicator.INTEGRATION: False,
        }


def test_fast_and_slow_blink_patterns() -> None:
    fast = DeviceError.CAMERA_READ_ERROR
    assert compute_indicator_states(fast, 0)[Indicator.VISION]
    assert not compute_indicator_states(fast, BLINK_FAST_MS)[Indicator.VISION]

    slow = DeviceError.MODEL_LOAD_ERROR
    assert compute_indicator_states(slow, 0)[Indicator.VISION]
    assert compute_indicator_states(slow, BLINK_FAST_MS)[Indicator.VISION]
    assert not compute_indicator_states(slow, BLINK_SLOW_MS)[Indicator.VISION]


def test_higher_priority_error_pattern_wins() -> None:
    mask = DeviceError.CAMERA_INIT_ERROR | DeviceError.CAMERA_READ_ERROR
    # CAMERA_INIT_ERROR (sürekli) önceliklidir, hızlı yanıp sönmenin "sönük" anında da yanık kalır.
    assert compute_indicator_states(mask, BLINK_FAST_MS)[Indicator.VISION]
