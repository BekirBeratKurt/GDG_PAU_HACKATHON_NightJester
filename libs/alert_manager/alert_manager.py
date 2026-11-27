"""Alert manager modülü: moda ve yorgunluk seviyesine göre bildirim, ses ve video uyarıları."""

from __future__ import annotations

import logging
import os
import random
import threading
import time
import webbrowser
from pathlib import Path

import pygame
from plyer import notification

from libs.communicator import orb_copy, orb_subscribe, topics
from libs.communicator.topics import AlertCommand, AppMode, FatigueLevel, GuardianResult
from libs.config_manager import AppConfig, project_path
from libs.device_state_tracker import (
    DeviceError,
    clear_error,
    raise_error,
    update_device_state,
)

TAG = "AlertManager"
log = logging.getLogger(TAG)

LOOP_PERIOD_SEC = 0.1
AUDIO_EXTENSIONS = (".wav", ".ogg", ".mp3")
UNSUPPORTED_AUDIO_EXTENSIONS = (".m4a", ".aac", ".wma", ".flac")
DROWSY_DIR = Path("Drowsy")
SLEEPY_NORMAL_DIR = Path("Sleepy") / "normal"
SLEEPY_DEADLINE_DIR = Path("Sleepy") / "deadline"
VOICE_DIRS = (DROWSY_DIR, SLEEPY_NORMAL_DIR, SLEEPY_DEADLINE_DIR)
VOICE_GENDERS = ("female", "male")
DEFAULT_VOICE_GENDER = "female"
MEDIA_SOUND = "sound"
MEDIA_VIDEO_URL = "video_url"
MEDIA_VIDEO_FILE = "video_file"
COMMAND_STOP = "stop"
COMMAND_TEST = "test"
VOLUME_MAX = 1.0
LOOP_FOREVER = -1
NOTIFICATION_TIMEOUT_SEC = 5
APP_NAME = "NightJester"

TEXT_DROWSY = "Yorgun görünüyorsun, 5 dk mola?"
TEXT_ASLEEP = "Uyumak verimlilik için en iyi yatırım."
TEXT_WELCOME = "Hoş geldin! Alarm durduruldu."
TEXT_WELCOME_CODE_SAFE = "Hoş geldin, kodun güvende."
TEXT_WELCOME_GUARDIAN_FAILED = "Hoş geldin! Kod yedeği alınamadı, log'a bak."

_NORMAL_MODE_COOLDOWN_SEC: float = 0.0
_VOICE_ROOT: Path = Path()
_DEADLINE_MEDIA_TYPE: str = MEDIA_SOUND
_DEADLINE_SOUND_PATH: str = ""
_DEADLINE_VIDEO_URLS: list[str] = []
_DEADLINE_VIDEO_PATH: str = ""
_DEADLINE_SOUND_WITH_VIDEO: bool = True
_VOLUME_START: float = 0.0
_VOLUME_STEP: float = 0.0
_VOLUME_STEP_INTERVAL_SEC: float = 0.0

_fatigue_sub = None
_app_mode_sub = None
_alert_command_sub = None
_guardian_sub = None
_audio_ok = False
_alarm_channel: pygame.mixer.Channel | None = None
_voice_channel: pygame.mixer.Channel | None = None
_sound_cache: dict[Path, pygame.mixer.Sound] = {}

_mode = AppMode.NORMAL
_last_level: FatigueLevel | None = None
_last_notified_at: dict[FatigueLevel, float] = {}
_alarm_active = False
_alarm_volume = 0.0
_next_volume_step_at = 0.0
# Son uyku anında Kod Koruyucu sonuçları: None = sonuç yok.
_guardian_ok: bool | None = None


def alert_manager_task(stop_event: threading.Event, config: AppConfig) -> None:
    """Alert manager task'ı. Seviye geçişlerine ve komutlara göre uyarıları yönetir.

    Ses başlatılamazsa task bitmez, bildirimler ve video çalışmaya devam eder.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    _init(config)
    try:
        while not stop_event.is_set():
            _handle_mode()
            _handle_commands()
            _handle_guardian_results()
            _handle_fatigue()
            _update_alarm_volume()
            stop_event.wait(LOOP_PERIOD_SEC)
    except Exception:
        log.exception("Beklenmeyen hata, task sonlandırılıyor.")
    finally:
        _deinit()


def pick_random_audio_file(directory: Path) -> Path | None:
    """Klasördeki desteklenen ses dosyalarından rastgele birini seçer (alt klasörlere bakmaz).

    Args:
        directory: Ses klasörü.

    Returns:
        Seçilen dosya, klasör yoksa veya ses dosyası yoksa None.
    """
    if not directory.is_dir():
        return None
    candidates = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )
    return random.choice(candidates) if candidates else None


def _init(config: AppConfig) -> None:
    global _fatigue_sub, _app_mode_sub, _alert_command_sub, _guardian_sub
    _load_settings(config)
    _fatigue_sub = orb_subscribe(topics.fatigue_state_topic)
    _app_mode_sub = orb_subscribe(topics.app_mode_topic)
    _alert_command_sub = orb_subscribe(topics.alert_command_topic)
    _guardian_sub = orb_subscribe(topics.guardian_result_topic)
    update_device_state(alarm_active=False)

    if _init_audio() and _check_voice_files():
        clear_error(DeviceError.AUDIO_INIT_ERROR)
    else:
        raise_error(DeviceError.AUDIO_INIT_ERROR)


def _load_settings(config: AppConfig) -> None:
    global _NORMAL_MODE_COOLDOWN_SEC, _VOICE_ROOT, _DEADLINE_MEDIA_TYPE, _DEADLINE_SOUND_PATH
    global _DEADLINE_VIDEO_URLS, _DEADLINE_VIDEO_PATH, _DEADLINE_SOUND_WITH_VIDEO
    global _VOLUME_START, _VOLUME_STEP, _VOLUME_STEP_INTERVAL_SEC
    cfg = config.alert_manager
    gender = cfg.voice_gender
    if gender not in VOICE_GENDERS:
        log.warning("Geçersiz ses tipi '%s', '%s' kullanılıyor.", gender, DEFAULT_VOICE_GENDER)
        gender = DEFAULT_VOICE_GENDER
    _NORMAL_MODE_COOLDOWN_SEC = cfg.normal_mode_cooldown_sec
    _VOICE_ROOT = project_path(cfg.voice_dir) / gender
    _DEADLINE_MEDIA_TYPE = cfg.deadline_media_type
    _DEADLINE_SOUND_PATH = cfg.deadline_sound_path
    _DEADLINE_VIDEO_URLS = [url.strip() for url in cfg.deadline_video_urls if url.strip()]
    _DEADLINE_VIDEO_PATH = cfg.deadline_video_path
    _DEADLINE_SOUND_WITH_VIDEO = cfg.deadline_sound_with_video
    _VOLUME_START = cfg.volume_start
    _VOLUME_STEP = cfg.volume_step
    _VOLUME_STEP_INTERVAL_SEC = cfg.volume_step_interval_sec


def _init_audio() -> bool:
    global _audio_ok, _alarm_channel, _voice_channel
    try:
        pygame.mixer.init()
        _alarm_channel = pygame.mixer.Channel(0)
        _voice_channel = pygame.mixer.Channel(1)
    except pygame.error as err:
        log.error("Ses sistemi başlatılamadı, sadece bildirim ve video kullanılacak: %s", err)
        _audio_ok = False
        return False
    _audio_ok = True
    log.info("Ses sistemi başlatıldı.")
    return True


def find_unconverted_audio_files(directory: Path) -> list[Path]:
    """pygame'in çalamadığı ve yanında çalınabilir kopyası olmayan ses dosyalarını bulur.

    Args:
        directory: Ses klasörü.

    Returns:
        Dönüştürülmesi gereken dosyalar (ör. yanında .ogg'si olmayan .m4a).
    """
    if not directory.is_dir():
        return []
    files = [path for path in directory.iterdir() if path.is_file()]
    playable_stems = {path.stem for path in files if path.suffix.lower() in AUDIO_EXTENSIONS}
    return sorted(
        path
        for path in files
        if path.suffix.lower() in UNSUPPORTED_AUDIO_EXTENSIONS and path.stem not in playable_stems
    )


def _check_voice_files() -> bool:
    all_ok = True
    for sub_dir in VOICE_DIRS:
        directory = _VOICE_ROOT / sub_dir
        for path in find_unconverted_audio_files(directory):
            log.warning("Desteklenmeyen ses formatı yok sayıldı, .ogg/.mp3'e çevir: %s", path)
        if pick_random_audio_file(directory) is None:
            log.error("Ses dosyası bulunamadı: %s (%s)", directory, "/".join(AUDIO_EXTENSIONS))
            all_ok = False
    return all_ok


def _handle_mode() -> None:
    global _mode, _guardian_ok
    updated, mode = orb_copy(_app_mode_sub)
    if not updated or not isinstance(mode, AppMode) or mode is _mode:
        return
    _mode = mode
    _guardian_ok = None
    log.info("Mod: %s", mode.name)
    if mode is not AppMode.DEADLINE:
        _stop_alarm("mod değişti")


def _handle_commands() -> None:
    updated, command = orb_copy(_alert_command_sub)
    if not updated or not isinstance(command, AlertCommand):
        return
    if command.action == COMMAND_STOP:
        _stop_alarm("kullanıcı 'Uyandım' dedi")
        if _voice_channel is not None:
            _voice_channel.stop()
    elif command.action == COMMAND_TEST:
        log.info("Test alarmı istendi.")
        _start_alarm()
    else:
        log.warning("Bilinmeyen uyarı komutu: %s", command.action)


def _handle_guardian_results() -> None:
    global _guardian_ok
    updated, result = orb_copy(_guardian_sub)
    if not updated or not isinstance(result, GuardianResult):
        return
    # Birden çok repo varsa biri bile başarısızsa "güvende" denmez.
    _guardian_ok = result.success if _guardian_ok is None else _guardian_ok and result.success


def _handle_fatigue() -> None:
    global _last_level
    updated, state = orb_copy(_fatigue_sub)
    if not updated or state.level is _last_level:
        return
    previous, _last_level = _last_level, state.level
    if _mode is AppMode.PAUSED:
        return
    if state.level is FatigueLevel.DROWSY:
        _on_drowsy()
    elif state.level is FatigueLevel.ASLEEP:
        _on_asleep()
    elif state.level is FatigueLevel.AWAKE and previous is FatigueLevel.ASLEEP:
        _on_wake_up()


def _on_drowsy() -> None:
    if _mode is AppMode.NORMAL:
        if _cooldown_passed(FatigueLevel.DROWSY):
            _notify(TEXT_DROWSY)
            _play_voice(DROWSY_DIR)
    elif _mode is AppMode.DEADLINE:
        _play_voice(DROWSY_DIR)


def _on_asleep() -> None:
    if _mode is AppMode.NORMAL:
        if _cooldown_passed(FatigueLevel.ASLEEP):
            _notify(TEXT_ASLEEP)
            _play_voice(SLEEPY_NORMAL_DIR)
    elif _mode is AppMode.DEADLINE:
        _start_alarm()


def _on_wake_up() -> None:
    global _guardian_ok
    if _mode is not AppMode.DEADLINE:
        return
    was_active = _alarm_active
    _stop_alarm("kullanıcı uyandı")
    if _guardian_ok is True:
        _notify(TEXT_WELCOME_CODE_SAFE)
    elif _guardian_ok is False:
        _notify(TEXT_WELCOME_GUARDIAN_FAILED)
    elif was_active:
        _notify(TEXT_WELCOME)
    # Sonuç uyanışta tüketilir. Uyku anında sıfırlamak, erken gelen sonucu kaybettirebilirdi.
    _guardian_ok = None


def _cooldown_passed(level: FatigueLevel) -> bool:
    now = time.monotonic()
    last = _last_notified_at.get(level)
    if last is not None and now - last < _NORMAL_MODE_COOLDOWN_SEC:
        log.info("%s hatırlatması bekleme süresinde, atlandı.", level.name)
        return False
    _last_notified_at[level] = now
    return True


def _start_alarm() -> None:
    global _alarm_active
    if _alarm_active:
        return
    video_opened = False
    if _DEADLINE_MEDIA_TYPE == MEDIA_VIDEO_URL:
        video_opened = _open_random_video_url()
    elif _DEADLINE_MEDIA_TYPE == MEDIA_VIDEO_FILE:
        video_opened = _open_video_file()
    elif _DEADLINE_MEDIA_TYPE != MEDIA_SOUND:
        log.warning("Bilinmeyen medya tipi '%s', ses çalınacak.", _DEADLINE_MEDIA_TYPE)

    # Video açılamazsa ya da kullanıcı istiyorsa ses de çalar. Böylece uyandırma garanti olur.
    if video_opened and not _DEADLINE_SOUND_WITH_VIDEO:
        log.info("Alarm: sadece video açıldı.")
        return
    _alarm_active = _start_alarm_sound()
    update_device_state(alarm_active=_alarm_active)


def _start_alarm_sound() -> bool:
    global _alarm_volume, _next_volume_step_at
    sound = _load_sound(_pick_alarm_sound())
    if sound is None or _alarm_channel is None:
        return False
    if _voice_channel is not None:
        _voice_channel.stop()
    _alarm_volume = _VOLUME_START
    _alarm_channel.set_volume(_alarm_volume)
    _alarm_channel.play(sound, loops=LOOP_FOREVER)
    _next_volume_step_at = time.monotonic() + _VOLUME_STEP_INTERVAL_SEC
    log.info("Alarm başladı (ses seviyesi %.2f).", _alarm_volume)
    return True


def _pick_alarm_sound() -> Path | None:
    if _DEADLINE_SOUND_PATH:
        custom = project_path(_DEADLINE_SOUND_PATH)
        if custom.is_file():
            return custom
        log.error("Seçilen alarm sesi bulunamadı, varsayılan ses kullanılıyor: %s", custom)
        raise_error(DeviceError.AUDIO_INIT_ERROR)
    return pick_random_audio_file(_VOICE_ROOT / SLEEPY_DEADLINE_DIR) or pick_random_audio_file(
        _VOICE_ROOT / SLEEPY_NORMAL_DIR
    )


def _update_alarm_volume() -> None:
    global _alarm_volume, _next_volume_step_at
    if not _alarm_active or _alarm_channel is None or _alarm_volume >= VOLUME_MAX:
        return
    now = time.monotonic()
    if now < _next_volume_step_at:
        return
    _alarm_volume = min(VOLUME_MAX, _alarm_volume + _VOLUME_STEP)
    _alarm_channel.set_volume(_alarm_volume)
    _next_volume_step_at = now + _VOLUME_STEP_INTERVAL_SEC
    log.info("Alarm ses seviyesi: %.2f", _alarm_volume)


def _stop_alarm(reason: str) -> None:
    global _alarm_active
    if not _alarm_active:
        return
    if _alarm_channel is not None:
        _alarm_channel.stop()
    _alarm_active = False
    update_device_state(alarm_active=False)
    log.info("Alarm durdu: %s", reason)


def _play_voice(sub_dir: Path) -> None:
    if _voice_channel is None or _alarm_active or _voice_channel.get_busy():
        return
    sound = _load_sound(pick_random_audio_file(_VOICE_ROOT / sub_dir))
    if sound is None:
        return
    _voice_channel.set_volume(VOLUME_MAX)
    _voice_channel.play(sound)


def _load_sound(path: Path | None) -> pygame.mixer.Sound | None:
    if not _audio_ok:
        return None
    if path is None:
        log.error("Çalınacak ses dosyası bulunamadı.")
        raise_error(DeviceError.AUDIO_INIT_ERROR)
        return None
    sound = _sound_cache.get(path)
    if sound is not None:
        return sound
    try:
        sound = pygame.mixer.Sound(str(path))
    except (pygame.error, FileNotFoundError) as err:
        log.error("Ses dosyası yüklenemedi: %s (%s)", path, err)
        raise_error(DeviceError.AUDIO_INIT_ERROR)
        return None
    _sound_cache[path] = sound
    return sound


def _open_random_video_url() -> bool:
    if not _DEADLINE_VIDEO_URLS:
        log.warning("Video linki listesi boş, ses çalınacak.")
        return False
    url = random.choice(_DEADLINE_VIDEO_URLS)
    try:
        opened = webbrowser.open(url)
    except webbrowser.Error as err:
        log.error("Video linki açılamadı: %s (%s)", url, err)
        return False
    if not opened:
        log.error("Tarayıcı açılamadı: %s", url)
        return False
    log.info("Video linki açıldı: %s", url)
    return True


def _open_video_file() -> bool:
    path = project_path(_DEADLINE_VIDEO_PATH) if _DEADLINE_VIDEO_PATH else None
    if path is None or not path.is_file():
        log.error("Video dosyası bulunamadı: %s", path)
        return False
    try:
        os.startfile(path)
    except OSError as err:
        log.error("Video dosyası açılamadı: %s (%s)", path, err)
        return False
    log.info("Video dosyası açıldı: %s", path)
    return True


def _notify(message: str) -> None:
    # plyer Windows'ta bildirim süresi boyunca bekliyor, task'ı bloklamasın diye ayrı thread.
    threading.Thread(
        target=_show_notification, args=(message,), name="notification", daemon=True
    ).start()


def _show_notification(message: str) -> None:
    try:
        notification.notify(
            title=APP_NAME,
            message=message,
            app_name=APP_NAME,
            timeout=NOTIFICATION_TIMEOUT_SEC,
        )
    except Exception:
        # Kısa ömürlü bildirim thread'inin en dış koruması.
        log.exception("Bildirim gösterilemedi.")
        return
    log.info("Bildirim: %s", message)


def _deinit() -> None:
    """Sesi durdurur ve ses sistemini kapatır."""
    _stop_alarm("uygulama kapanıyor")
    if _audio_ok:
        _sound_cache.clear()
        pygame.mixer.quit()
        log.info("Ses sistemi kapatıldı.")
