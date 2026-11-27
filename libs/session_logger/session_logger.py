"""Session logger modülü: yorgunluk seviye geçişlerini ve Kod Koruyucu sonuçlarını kaydeder."""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from libs.communicator import orb_copy, orb_subscribe, topics
from libs.communicator.topics import FatigueLevel, FatigueState, GuardianResult
from libs.config_manager import AppConfig, project_path

TAG = "SessionLogger"
log = logging.getLogger(TAG)

LOOP_PERIOD_SEC = 1.0
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
KIND_LEVEL = "level"
KIND_GUARDIAN = "guardian"
# Kalibrasyon bir yorgunluk olayı değil, kaydı gereksiz kalabalık eder.
_IGNORED_LEVELS = {FatigueLevel.CALIBRATING}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    level TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
"""

_db_path: Path | None = None
_session_id: int | None = None
_session_lock = threading.Lock()


@dataclass
class HourlyCount:
    """Bir saat dilimindeki olay sayıları."""

    hour: int
    drowsy: int
    asleep: int


def open_database(db_path: Path) -> sqlite3.Connection:
    """Veritabanını açar (yoksa oluşturur) ve şemayı hazırlar.

    Args:
        db_path: SQLite dosyası.

    Returns:
        Açık bağlantı. Açan thread kullanmalıdır.

    Raises:
        sqlite3.Error, OSError: Dosya açılamazsa.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(_SCHEMA)
    return connection


def start_session(connection: sqlite3.Connection, now: datetime) -> int:
    """Yeni bir oturum kaydı açar.

    Args:
        connection: Açık bağlantı.
        now: Oturum başlangıç zamanı.

    Returns:
        Oturum kimliği.
    """
    cursor = connection.execute(
        "INSERT INTO sessions (started_at) VALUES (?)", (now.strftime(TIME_FORMAT),)
    )
    connection.commit()
    return int(cursor.lastrowid)


def record_event(
    connection: sqlite3.Connection,
    session_id: int,
    now: datetime,
    kind: str,
    level: str | None = None,
    detail: str | None = None,
) -> None:
    """Bir olayı kaydeder.

    Args:
        connection: Açık bağlantı.
        session_id: Oturum kimliği.
        now: Olay zamanı.
        kind: Olay türü (KIND_LEVEL / KIND_GUARDIAN).
        level: Seviye adı (seviye olaylarında).
        detail: Ek açıklama.
    """
    connection.execute(
        "INSERT INTO events (session_id, ts, kind, level, detail) VALUES (?, ?, ?, ?, ?)",
        (session_id, now.strftime(TIME_FORMAT), kind, level, detail),
    )
    connection.commit()


def query_hourly_report(connection: sqlite3.Connection, session_id: int) -> list[HourlyCount]:
    """Oturumdaki DROWSY ve ASLEEP geçişlerini saatlere göre sayar.

    Args:
        connection: Açık bağlantı.
        session_id: Oturum kimliği.

    Returns:
        Saat sırasına göre sayımlar (olay olmayan saatler yer almaz).
    """
    rows = connection.execute(
        """
        SELECT CAST(strftime('%H', ts) AS INTEGER) AS hour,
               SUM(level = ?) AS drowsy,
               SUM(level = ?) AS asleep
        FROM events
        WHERE session_id = ? AND kind = ? AND level IN (?, ?)
        GROUP BY hour
        ORDER BY hour
        """,
        (
            FatigueLevel.DROWSY.name,
            FatigueLevel.ASLEEP.name,
            session_id,
            KIND_LEVEL,
            FatigueLevel.DROWSY.name,
            FatigueLevel.ASLEEP.name,
        ),
    ).fetchall()
    return [HourlyCount(hour=row[0], drowsy=row[1], asleep=row[2]) for row in rows]


def get_hourly_report() -> list[HourlyCount]:
    """Bu oturumun saatlik raporunu döner. Her thread'den çağrılabilir (kendi bağlantısını açar).

    Returns:
        Saat sırasına göre sayımlar. Kayıt yoksa veya veritabanı açılamadıysa boş liste.
    """
    with _session_lock:
        db_path, session_id = _db_path, _session_id
    if db_path is None or session_id is None:
        return []
    try:
        connection = sqlite3.connect(db_path)
        try:
            return query_hourly_report(connection, session_id)
        finally:
            connection.close()
    except sqlite3.Error as err:
        log.error("Rapor okunamadı: %s", err)
        return []


def session_logger_task(stop_event: threading.Event, config: AppConfig) -> None:
    """Session logger task'ı. Seviye geçişlerini ve Kod Koruyucu sonuçlarını kaydeder.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    global _db_path, _session_id
    db_path = project_path(config.session_logger.db_path)
    try:
        # SQLite bağlantısı onu açan thread'e aittir, bu yüzden task içinde açılır.
        connection = open_database(db_path)
        session_id = start_session(connection, datetime.now())
    except (sqlite3.Error, OSError) as err:
        log.error("Oturum veritabanı açılamadı (%s): %s", db_path, err)
        return
    with _session_lock:
        _db_path, _session_id = db_path, session_id
    log.info("Oturum kaydı başladı (#%d): %s", session_id, db_path)

    fatigue_sub = orb_subscribe(topics.fatigue_state_topic)
    guardian_sub = orb_subscribe(topics.guardian_result_topic)
    last_level: FatigueLevel | None = None
    try:
        while not stop_event.is_set():
            updated, state = orb_copy(fatigue_sub)
            if updated and isinstance(state, FatigueState) and state.level is not last_level:
                last_level = state.level
                if state.level not in _IGNORED_LEVELS:
                    record_event(
                        connection,
                        session_id,
                        datetime.now(),
                        KIND_LEVEL,
                        level=state.level.name,
                        detail=f"skor {state.score}",
                    )
            updated, result = orb_copy(guardian_sub)
            if updated and isinstance(result, GuardianResult):
                record_event(
                    connection,
                    session_id,
                    datetime.now(),
                    KIND_GUARDIAN,
                    detail=f"{'OK' if result.success else 'HATA'} {result.repo_path}: "
                    f"{result.message}",
                )
            stop_event.wait(LOOP_PERIOD_SEC)
    except sqlite3.Error as err:
        log.error("Olay kaydedilemedi, task sonlandırılıyor: %s", err)
    except Exception:
        log.exception("Beklenmeyen hata, task sonlandırılıyor.")
    finally:
        connection.close()
        log.info("Oturum kaydı kapatıldı.")
