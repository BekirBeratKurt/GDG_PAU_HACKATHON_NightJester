"""Config manager modülü: varsayılan ve kullanıcı ayarlarını birleştirip tipli ayarlar üretir."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from libs.device_state_tracker import DeviceError, clear_error, raise_error

TAG = "ConfigManager"
log = logging.getLogger(TAG)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default_config.json"
USER_CONFIG_PATH = PROJECT_ROOT / "config" / "user_config.json"
CONFIG_ENCODING = "utf-8"
JSON_INDENT = 2


@dataclass
class CameraConfig:
    """Kamera ayarları."""

    index: int
    width_px: int
    height_px: int
    target_fps: int


@dataclass
class FaceAnalyzerConfig:
    """Yüz analizi ayarları."""

    model_path: str
    min_detection_confidence: float


@dataclass
class FatigueConfig:
    """Yorgunluk tespiti ayarları."""

    calibration_duration_sec: float
    ear_closed_ratio: float
    drowsy_closed_sec: float
    asleep_closed_sec: float
    perclos_window_sec: float
    perclos_drowsy_threshold: float
    yawn_mar_threshold: float
    yawn_min_duration_sec: float
    no_face_timeout_sec: float
    awake_recovery_sec: float


@dataclass
class AlertConfig:
    """Uyarı ayarları."""

    normal_mode_cooldown_sec: int
    voice_dir: str
    voice_gender: str
    deadline_media_type: str
    deadline_sound_path: str
    deadline_video_urls: list[str]
    deadline_video_path: str
    deadline_sound_with_video: bool
    volume_start: float
    volume_step: float
    volume_step_interval_sec: float


@dataclass
class CodeGuardianConfig:
    """Kod Koruyucu ayarları."""

    enabled: bool
    repo_paths: list[str]
    min_interval_sec: int


@dataclass
class SessionLoggerConfig:
    """Oturum kaydı ayarları."""

    db_path: str


@dataclass
class UiConfig:
    """Arayüz ayarları."""

    start_mode: str
    show_landmarks: bool
    start_minimized: bool


@dataclass
class AppConfig:
    """Tüm uygulama ayarları. default_config.json'daki her bölüm bir alandır."""

    camera: CameraConfig
    face_analyzer: FaceAnalyzerConfig
    fatigue_detector: FatigueConfig
    alert_manager: AlertConfig
    code_guardian: CodeGuardianConfig
    session_logger: SessionLoggerConfig
    ui: UiConfig


_SECTION_TYPES: dict[str, type] = {
    "camera": CameraConfig,
    "face_analyzer": FaceAnalyzerConfig,
    "fatigue_detector": FatigueConfig,
    "alert_manager": AlertConfig,
    "code_guardian": CodeGuardianConfig,
    "session_logger": SessionLoggerConfig,
    "ui": UiConfig,
}


def load_config(
    default_path: Path = DEFAULT_CONFIG_PATH,
    user_path: Path = USER_CONFIG_PATH,
) -> AppConfig:
    """Varsayılan ayarları okur, varsa kullanıcı ayarlarını üstüne yazar.

    Kullanıcı ayar dosyası bozuksa veya hatalı değer içeriyorsa ilgili kısım için
    varsayılan kullanılır ve CONFIG_ERROR kaldırılır. Uygulama çökmez.

    Args:
        default_path: Varsayılan ayar dosyası.
        user_path: Kullanıcı ayar dosyası.

    Returns:
        Tipli uygulama ayarları.

    Raises:
        OSError, json.JSONDecodeError: Varsayılan ayar dosyası okunamazsa (kurulum hatası).
    """
    defaults = _read_json(default_path)
    user_data, user_ok = _read_user_config(user_path)
    merged, merge_ok = _merge_user_values(defaults, user_data)
    config = AppConfig(
        **{name: section_type(**merged[name]) for name, section_type in _SECTION_TYPES.items()}
    )

    if user_ok and merge_ok:
        clear_error(DeviceError.CONFIG_ERROR)
    else:
        raise_error(DeviceError.CONFIG_ERROR)
    log.info("Ayarlar yüklendi.")
    return config


def save_user_config(config: AppConfig, user_path: Path = USER_CONFIG_PATH) -> bool:
    """Ayarları kullanıcı ayar dosyasına yazar (ayarlar ekranı kullanır).

    Args:
        config: Kaydedilecek ayarlar.
        user_path: Kullanıcı ayar dosyası.

    Returns:
        Yazma başarılıysa True.
    """
    try:
        user_path.parent.mkdir(parents=True, exist_ok=True)
        user_path.write_text(
            json.dumps(asdict(config), indent=JSON_INDENT, ensure_ascii=False),
            encoding=CONFIG_ENCODING,
        )
    except OSError as err:
        log.error("Kullanıcı ayarları kaydedilemedi: %s", err)
        return False
    log.info("Kullanıcı ayarları kaydedildi: %s", user_path)
    return True


def project_path(path: str | Path) -> Path:
    """Göreli yolu proje köküne göre çözer. Mutlak yol olduğu gibi döner.

    Args:
        path: Ayarlardaki dosya yolu.

    Returns:
        Mutlak yol.
    """
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding=CONFIG_ENCODING))


def _read_user_config(user_path: Path) -> tuple[dict[str, Any], bool]:
    if not user_path.exists():
        log.info("Kullanıcı ayar dosyası yok, varsayılan ayarlar kullanılıyor.")
        return {}, True
    try:
        data = _read_json(user_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        log.warning("Kullanıcı ayar dosyası okunamadı, varsayılan ayarlar kullanılıyor: %s", err)
        return {}, False
    if not isinstance(data, dict):
        log.warning("Kullanıcı ayar dosyası bir JSON nesnesi değil, varsayılanlar kullanılıyor.")
        return {}, False
    return data, True


def _merge_user_values(
    defaults: dict[str, Any], user_data: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    merged = {section: dict(values) for section, values in defaults.items()}
    all_ok = True
    for section, user_values in user_data.items():
        if section not in merged:
            log.warning("Bilinmeyen ayar bölümü yok sayıldı: %s", section)
            continue
        if not isinstance(user_values, dict):
            log.warning("Ayar bölümü nesne değil, varsayılan kullanılıyor: %s", section)
            all_ok = False
            continue
        for key, value in user_values.items():
            if key not in merged[section]:
                log.warning("Bilinmeyen ayar yok sayıldı: %s.%s", section, key)
                continue
            default_value = defaults[section][key]
            if not _is_compatible(default_value, value):
                log.warning(
                    "Ayar tipi hatalı, varsayılan kullanılıyor: %s.%s = %r (beklenen: %s)",
                    section,
                    key,
                    value,
                    type(default_value).__name__,
                )
                all_ok = False
                continue
            merged[section][key] = float(value) if isinstance(default_value, float) else value
    return merged, all_ok


def _is_compatible(default_value: Any, value: Any) -> bool:
    # bool, int'in alt sınıfı olduğu için önce kontrol edilir.
    if isinstance(default_value, bool) or isinstance(value, bool):
        return isinstance(default_value, bool) and isinstance(value, bool)
    if isinstance(default_value, float):
        return isinstance(value, int | float)
    if isinstance(default_value, list):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return isinstance(value, type(default_value))
