"""Code guardian modülü: uyku anında çalışma alanına dokunmadan git snapshot alır."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from libs.communicator import orb_copy, orb_publish, orb_subscribe, topics
from libs.communicator.topics import AppMode, FatigueLevel, GuardianResult
from libs.config_manager import AppConfig, project_path
from libs.device_state_tracker import DeviceError, clear_error, raise_error

TAG = "CodeGuardian"
log = logging.getLogger(TAG)

LOOP_PERIOD_SEC = 0.5
GIT_TIMEOUT_SEC = 15.0
NS_PER_MS = 1_000_000
STASH_MESSAGE_PREFIX = "nightjester: uyku anı"
STASH_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
UNTRACKED_PREFIX = "??"
# Windows'ta her git çağrısında konsol penceresi yanıp sönmesin diye.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_fatigue_sub = None
_app_mode_sub = None


class GitError(Exception):
    """Git komutu çalıştırılamadı veya hata döndü."""


def run_git(repo: Path, *args: str) -> str:
    """Repo içinde bir git komutu çalıştırır ve çıktısını döner.

    Args:
        repo: Repo klasörü.
        *args: git alt komutu ve argümanları.

    Returns:
        Komutun standart çıktısı (sondaki boşluklar silinmiş).

    Raises:
        GitError: git bulunamazsa, zaman aşımı olursa veya komut hata dönerse.
    """
    command = ["git", "-C", str(repo), *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SEC,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
    except FileNotFoundError as err:
        raise GitError("git bulunamadı. Git for Windows kurulu ve PATH'te mi?") from err
    except subprocess.TimeoutExpired as err:
        raise GitError(f"git zaman aşımı: {' '.join(args)}") from err
    if completed.returncode != 0:
        raise GitError(completed.stderr.strip() or f"git {' '.join(args)} hata döndü")
    return completed.stdout.strip()


def is_git_repo(repo: Path) -> bool:
    """Klasörün bir git çalışma alanı olup olmadığını döner.

    Args:
        repo: Kontrol edilecek klasör.

    Returns:
        Geçerli bir git çalışma alanıysa True.
    """
    if not repo.is_dir():
        return False
    try:
        return run_git(repo, "rev-parse", "--is-inside-work-tree") == "true"
    except GitError:
        return False


def snapshot_repo(repo: Path, label_time: datetime) -> GuardianResult:
    """Çalışma alanını ve index'i değiştirmeden takip edilen değişikliklerin yedeğini alır.

    `git stash create` ile stash commit'i oluşturulur, `git stash store` ile stash listesine
    eklenir. Çalışma alanı ve index değişmez. Takip edilmeyen dosyalar yedeğe girmez.

    Args:
        repo: Repo klasörü.
        label_time: Stash mesajındaki zaman.

    Returns:
        Snapshot sonucu. Değişiklik yoksa success=True ve stash oluşturulmaz.

    Raises:
        GitError: git komutu başarısız olursa.
    """
    timestamp_ms = time.monotonic_ns() // NS_PER_MS
    status_lines = run_git(repo, "status", "--porcelain").splitlines()
    if not status_lines:
        return GuardianResult(True, str(repo), "Değişiklik yok, yedek gerekmedi.", timestamp_ms)

    sha = run_git(repo, "stash", "create")
    if not sha:
        untracked = sum(1 for line in status_lines if line.startswith(UNTRACKED_PREFIX))
        return GuardianResult(
            True,
            str(repo),
            f"Sadece takip edilmeyen dosyalar var ({untracked}), yedek alınmadı.",
            timestamp_ms,
        )

    message = f"{STASH_MESSAGE_PREFIX} {label_time.strftime(STASH_TIME_FORMAT)}"
    run_git(repo, "stash", "store", "-m", message, sha)
    return GuardianResult(True, str(repo), f"Yedek alındı: {message}", timestamp_ms)


class CodeGuardian:
    """Repo listesi için bekleme süresini (min_interval) takip ederek snapshot alır."""

    def __init__(self, repos: list[Path], min_interval_sec: float) -> None:
        """Koruyucuyu oluşturur.

        Args:
            repos: Yedeklenecek (doğrulanmış) repo klasörleri.
            min_interval_sec: Aynı repo için iki snapshot arasındaki en kısa süre.
        """
        self._repos = repos
        self._min_interval_sec = min_interval_sec
        self._last_snapshot_at: dict[Path, float] = {}

    def protect(self, now_sec: float, label_time: datetime) -> list[GuardianResult]:
        """Bekleme süresi dolmuş her repoda snapshot alır.

        Args:
            now_sec: Monoton zaman (sn).
            label_time: Stash mesajındaki zaman.

        Returns:
            Denenen her repo için bir sonuç.
        """
        results = []
        for repo in self._repos:
            last = self._last_snapshot_at.get(repo)
            if last is not None and now_sec - last < self._min_interval_sec:
                log.info("Bekleme süresi dolmadı, atlandı: %s", repo)
                continue
            try:
                result = snapshot_repo(repo, label_time)
            except GitError as err:
                log.error("Snapshot alınamadı (%s): %s", repo, err)
                raise_error(DeviceError.GIT_ERROR)
                results.append(
                    GuardianResult(False, str(repo), str(err), time.monotonic_ns() // NS_PER_MS)
                )
                continue
            self._last_snapshot_at[repo] = now_sec
            log.info("%s: %s", repo, result.message)
            results.append(result)
        return results


def code_guardian_task(stop_event: threading.Event, config: AppConfig) -> None:
    """Code guardian task'ı. Deadline modunda ASLEEP geçişinde repoları yedekler.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    guardian = _init(config)
    if guardian is None:
        return

    mode = AppMode.NORMAL
    last_level: FatigueLevel | None = None
    try:
        while not stop_event.is_set():
            mode_updated, new_mode = orb_copy(_app_mode_sub)
            if mode_updated and isinstance(new_mode, AppMode):
                mode = new_mode

            updated, state = orb_copy(_fatigue_sub)
            if updated and state.level is not last_level:
                last_level = state.level
                if state.level is FatigueLevel.ASLEEP and mode is AppMode.DEADLINE:
                    log.info("Uyku tespit edildi, Kod Koruyucu devrede.")
                    for result in guardian.protect(time.monotonic(), datetime.now()):
                        orb_publish(topics.guardian_result_topic, result)
            stop_event.wait(LOOP_PERIOD_SEC)
    except Exception:
        log.exception("Beklenmeyen hata, task sonlandırılıyor.")


def _init(config: AppConfig) -> CodeGuardian | None:
    global _fatigue_sub, _app_mode_sub
    cfg = config.code_guardian
    if not cfg.enabled:
        log.info("Kod Koruyucu kapalı (enabled=false).")
        return None
    if not cfg.repo_paths:
        log.info("Kod Koruyucu için repo eklenmemiş (code_guardian.repo_paths), pasif.")
        return None

    try:
        version = run_git(Path.cwd(), "--version")
    except GitError as err:
        log.error("Git kullanılamıyor: %s", err)
        raise_error(DeviceError.GIT_ERROR)
        return None

    repos = []
    for raw_path in cfg.repo_paths:
        repo = project_path(raw_path)
        if is_git_repo(repo):
            repos.append(repo)
            log.info("İzlenen repo: %s", repo)
        else:
            log.error("Geçersiz repo yolu (git çalışma alanı değil): %s", repo)
    if len(repos) != len(cfg.repo_paths):
        raise_error(DeviceError.GIT_ERROR)
    else:
        clear_error(DeviceError.GIT_ERROR)
    if not repos:
        log.error("Geçerli repo yok, Kod Koruyucu pasif.")
        return None

    _fatigue_sub = orb_subscribe(topics.fatigue_state_topic)
    _app_mode_sub = orb_subscribe(topics.app_mode_topic)
    log.info("Kod Koruyucu hazır (%s, %d repo).", version, len(repos))
    return CodeGuardian(repos, cfg.min_interval_sec)
