"""Device state tracker modülü: kritik hata bitmask'ini, durum bilgisini ve göstergeleri yönetir."""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum, IntFlag, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from libs.config_manager import AppConfig

TAG = "DeviceStateTracker"
log = logging.getLogger(TAG)

LOOP_PERIOD_SEC = 0.1
LAMP_TEST_MS = 300
BLINK_FAST_MS = 200
BLINK_SLOW_MS = 1000
MS_PER_SEC = 1000


class DeviceError(IntFlag):
    """Kritik hatalar. Her hata tek bittir, en fazla 8 hata tanımlanır."""

    NO_ERROR = 0x00
    CAMERA_INIT_ERROR = 0x01  # Kamera açılamadı
    CAMERA_READ_ERROR = 0x02  # Kameradan frame okunamıyor (bağlantı koptu)
    MODEL_LOAD_ERROR = 0x04  # FaceLandmarker modeli yüklenemedi
    AUDIO_INIT_ERROR = 0x08  # pygame.mixer başlatılamadı veya ses dosyası yok
    GIT_ERROR = 0x10  # Git bulunamadı / repo geçersiz
    CONFIG_ERROR = 0x20  # Config okunamadı, varsayılana dönüldü
    # 0x40                  rezerve
    # 0x80                  rezerve


class Indicator(Enum):
    """Paneldeki durum göstergeleri (alt sistem başına bir tane)."""

    VISION = auto()  # Görüntü: kamera + model
    ALERT = auto()  # Uyarı: ses / medya
    INTEGRATION = auto()  # Entegrasyon: git + config


class Pattern(Enum):
    """Gösterge yanma deseni."""

    SOLID = auto()
    BLINK_FAST = auto()
    BLINK_SLOW = auto()


@dataclass(frozen=True)
class _ErrorDisplay:
    indicator: Indicator
    pattern: Pattern
    priority: int  # 1 = gösterge içindeki en kritik hata


_ERROR_DISPLAY: dict[DeviceError, _ErrorDisplay] = {
    DeviceError.CAMERA_INIT_ERROR: _ErrorDisplay(Indicator.VISION, Pattern.SOLID, 1),
    DeviceError.CAMERA_READ_ERROR: _ErrorDisplay(Indicator.VISION, Pattern.BLINK_FAST, 2),
    DeviceError.MODEL_LOAD_ERROR: _ErrorDisplay(Indicator.VISION, Pattern.BLINK_SLOW, 3),
    DeviceError.AUDIO_INIT_ERROR: _ErrorDisplay(Indicator.ALERT, Pattern.SOLID, 1),
    DeviceError.GIT_ERROR: _ErrorDisplay(Indicator.INTEGRATION, Pattern.BLINK_FAST, 2),
    DeviceError.CONFIG_ERROR: _ErrorDisplay(Indicator.INTEGRATION, Pattern.SOLID, 1),
}


@dataclass
class DeviceState:
    """Hata olmayan uygulama durum bilgileri."""

    calibrated: bool = False
    alarm_active: bool = False


_lock = threading.Lock()
_error_mask: DeviceError = DeviceError.NO_ERROR
_device_state = DeviceState()
_indicator_states: dict[Indicator, bool] = dict.fromkeys(Indicator, False)
_lamp_test_until_ms = 0


def raise_error(error: DeviceError) -> None:
    """Verilen hata bit(ler)ini set eder.

    Args:
        error: Set edilecek hata.
    """
    global _error_mask
    with _lock:
        old_mask = _error_mask
        _error_mask = old_mask | error
        new_mask = _error_mask
    if new_mask != old_mask:
        log.warning(
            "Hata kaldırıldı: %s (maske 0x%02X -> 0x%02X)",
            _describe(error),
            old_mask,
            new_mask,
        )


def clear_error(error: DeviceError) -> None:
    """Verilen hata bit(ler)ini temizler.

    Args:
        error: Temizlenecek hata.
    """
    global _error_mask
    with _lock:
        old_mask = _error_mask
        _error_mask = old_mask & ~error
        new_mask = _error_mask
    if new_mask != old_mask:
        log.warning(
            "Hata temizlendi: %s (maske 0x%02X -> 0x%02X)",
            _describe(error & old_mask),
            old_mask,
            new_mask,
        )


def get_error_status(error: DeviceError) -> bool:
    """Verilen hatanın şu an set olup olmadığını döner.

    Args:
        error: Sorgulanacak hata.

    Returns:
        Hata set ise True.
    """
    with _lock:
        return bool(_error_mask & error)


def get_error_mask() -> DeviceError:
    """Tüm hata bitmask'ini döner."""
    with _lock:
        return _error_mask


def get_device_state() -> DeviceState:
    """Durum bilgisinin bir kopyasını döner."""
    with _lock:
        return dataclasses.replace(_device_state)


def update_device_state(**changes: Any) -> None:
    """Durum bilgisinin verilen alanlarını günceller (ör. alarm_active=True).

    Args:
        **changes: DeviceState alan adı → yeni değer.

    Raises:
        TypeError: Bilinmeyen bir alan verilirse.
    """
    global _device_state
    with _lock:
        _device_state = dataclasses.replace(_device_state, **changes)


def request_lamp_test() -> None:
    """Tüm göstergeleri LAMP_TEST_MS boyunca yakar (pencere açıldığında görünsün diye)."""
    global _lamp_test_until_ms
    with _lock:
        _lamp_test_until_ms = _now_ms() + LAMP_TEST_MS


def get_indicator_states() -> dict[Indicator, bool]:
    """Her göstergenin şu anki yanık/sönük durumunu döner. UI her döngüde okur."""
    with _lock:
        return dict(_indicator_states)


def compute_indicator_states(mask: DeviceError, now_ms: int) -> dict[Indicator, bool]:
    """Hata maskesine ve zamana göre göstergelerin yanık/sönük durumunu hesaplar.

    Bir göstergede birden çok hata varsa önceliği en yüksek olanın deseni kullanılır.

    Args:
        mask: Hata bitmask'i.
        now_ms: Monoton zaman (ms).

    Returns:
        Gösterge → yanık mı.
    """
    states = dict.fromkeys(Indicator, False)
    for indicator in Indicator:
        active = [
            display
            for error, display in _ERROR_DISPLAY.items()
            if display.indicator is indicator and mask & error
        ]
        if active:
            top = min(active, key=lambda display: display.priority)
            states[indicator] = _pattern_is_on(top.pattern, now_ms)
    return states


def device_state_tracker_task(stop_event: threading.Event, config: AppConfig) -> None:
    """Device state tracker task'ı. Lamba testini yapar, sonra göstergeleri günceller.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları (bu modül kullanmaz, task imzası için alınır).
    """
    try:
        request_lamp_test()
        while not stop_event.is_set():
            now_ms = _now_ms()
            with _lock:
                lamp_test_active = now_ms < _lamp_test_until_ms
            if lamp_test_active:
                _set_indicator_states(dict.fromkeys(Indicator, True))
            else:
                _set_indicator_states(compute_indicator_states(get_error_mask(), now_ms))
            stop_event.wait(LOOP_PERIOD_SEC)
    except Exception:
        log.exception("Beklenmeyen hata, task sonlandırılıyor.")
    finally:
        _set_indicator_states(dict.fromkeys(Indicator, False))
        log.info("Task durdu.")


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _set_indicator_states(states: dict[Indicator, bool]) -> None:
    global _indicator_states
    with _lock:
        _indicator_states = states


def _pattern_is_on(pattern: Pattern, now_ms: int) -> bool:
    if pattern is Pattern.BLINK_FAST:
        return (now_ms // BLINK_FAST_MS) % 2 == 0
    if pattern is Pattern.BLINK_SLOW:
        return (now_ms // BLINK_SLOW_MS) % 2 == 0
    return True


def _describe(mask: DeviceError) -> str:
    names = [error.name for error in _ERROR_DISPLAY if mask & error]
    return "|".join(names) if names else DeviceError.NO_ERROR.name
