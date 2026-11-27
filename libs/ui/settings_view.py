"""Ayarlar ekranı: medya seçimi, tespit eşikleri, Kod Koruyucu repoları ve genel ayarlar."""

from __future__ import annotations

import copy
import tkinter.filedialog as filedialog
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import customtkinter as ctk

from libs.config_manager import AppConfig


class FieldKind(Enum):
    """Form alanı türü."""

    FLOAT = auto()
    INT = auto()
    BOOL = auto()
    CHOICE = auto()
    FILE = auto()
    FOLDER_LINES = auto()  # her satıra bir klasör, "Klasör ekle" butonu ile
    LINES = auto()  # her satıra bir değer


@dataclass(frozen=True)
class SettingField:
    """Ayarlar ekranındaki tek bir alan."""

    section: str
    key: str
    label: str
    kind: FieldKind
    min_value: float | None = None
    max_value: float | None = None
    choices: tuple[tuple[str, str], ...] = ()  # (değer, görünen ad)
    restart_required: bool = False


@dataclass(frozen=True)
class SettingsTab:
    """Ayarlar ekranındaki bir sekme."""

    title: str
    fields: tuple[SettingField, ...] = field(default_factory=tuple)


VIDEO_FILE_TYPES = (("Video", "*.mp4 *.mkv *.avi *.mov *.webm"), ("Tümü", "*.*"))
SOUND_FILE_TYPES = (("Ses", "*.wav *.ogg *.mp3"), ("Tümü", "*.*"))

SETTINGS_TABS: tuple[SettingsTab, ...] = (
    SettingsTab(
        "Uyarılar",
        (
            SettingField(
                "alert_manager",
                "voice_gender",
                "Ses",
                FieldKind.CHOICE,
                choices=(("female", "Kadın"), ("male", "Erkek")),
            ),
            SettingField(
                "alert_manager",
                "deadline_media_type",
                "Deadline uyandırma",
                FieldKind.CHOICE,
                choices=(
                    ("sound", "Alarm sesi"),
                    ("video_url", "Video linki (rastgele)"),
                    ("video_file", "Video dosyası"),
                ),
            ),
            SettingField(
                "alert_manager",
                "deadline_video_urls",
                "Video linkleri (her satıra bir link)",
                FieldKind.LINES,
            ),
            SettingField("alert_manager", "deadline_video_path", "Video dosyası", FieldKind.FILE),
            SettingField(
                "alert_manager",
                "deadline_sound_path",
                "Özel alarm sesi (boş = varsayılan)",
                FieldKind.FILE,
            ),
            SettingField(
                "alert_manager",
                "deadline_sound_with_video",
                "Video ile birlikte alarm sesi de çalsın",
                FieldKind.BOOL,
            ),
            SettingField(
                "alert_manager",
                "normal_mode_cooldown_sec",
                "Normal mod hatırlatma aralığı (sn)",
                FieldKind.INT,
                min_value=1,
            ),
        ),
    ),
    SettingsTab(
        "Tespit",
        (
            SettingField(
                "fatigue_detector",
                "drowsy_closed_sec",
                "Uykulu için kapalı göz (sn)",
                FieldKind.FLOAT,
                min_value=0.3,
            ),
            SettingField(
                "fatigue_detector",
                "asleep_closed_sec",
                "Uyuyor için kapalı göz (sn)",
                FieldKind.FLOAT,
                min_value=0.5,
            ),
            SettingField(
                "fatigue_detector",
                "awake_recovery_sec",
                "Uyanık sayılmak için açık göz (sn)",
                FieldKind.FLOAT,
                min_value=0.1,
            ),
            SettingField(
                "fatigue_detector",
                "ear_closed_ratio",
                "Göz kapalı eşiği (baseline oranı)",
                FieldKind.FLOAT,
                min_value=0.3,
                max_value=0.95,
            ),
            SettingField(
                "fatigue_detector",
                "perclos_window_sec",
                "PERCLOS penceresi (sn)",
                FieldKind.FLOAT,
                min_value=5,
            ),
            SettingField(
                "fatigue_detector",
                "perclos_drowsy_threshold",
                "PERCLOS eşiği (0–1)",
                FieldKind.FLOAT,
                min_value=0.05,
                max_value=1.0,
            ),
            SettingField(
                "fatigue_detector",
                "yawn_mar_threshold",
                "Esneme MAR eşiği",
                FieldKind.FLOAT,
                min_value=0.1,
                max_value=2.0,
            ),
            SettingField(
                "fatigue_detector",
                "yawn_count_drowsy",
                "Uykulu için esneme sayısı (5 dk)",
                FieldKind.INT,
                min_value=1,
            ),
        ),
    ),
    SettingsTab(
        "Kod Koruyucu",
        (
            SettingField("code_guardian", "enabled", "Kod Koruyucu açık", FieldKind.BOOL),
            SettingField(
                "code_guardian",
                "repo_paths",
                "Repo klasörleri (her satıra bir yol)",
                FieldKind.FOLDER_LINES,
            ),
            SettingField(
                "code_guardian",
                "min_interval_sec",
                "İki yedek arası en az (sn)",
                FieldKind.INT,
                min_value=0,
            ),
        ),
    ),
    SettingsTab(
        "Genel",
        (
            SettingField(
                "camera",
                "index",
                "Kamera indeksi",
                FieldKind.INT,
                min_value=0,
                restart_required=True,
            ),
            SettingField(
                "ui",
                "start_mode",
                "Başlangıç modu",
                FieldKind.CHOICE,
                choices=(("NORMAL", "Normal"), ("DEADLINE", "Deadline"), ("PAUSED", "Duraklat")),
            ),
            SettingField("ui", "show_landmarks", "Göz/ağız noktalarını göster", FieldKind.BOOL),
            SettingField("ui", "start_minimized", "Tray'de (gizli) başlat", FieldKind.BOOL),
        ),
    ),
)


class SettingsError(ValueError):
    """Formdaki bir değer geçersiz."""


def apply_form_values(
    config: AppConfig, values: dict[tuple[str, str], Any]
) -> tuple[AppConfig, list[str]]:
    """Formdan okunan değerleri doğrulayıp config'in bir kopyasına uygular.

    Args:
        config: Mevcut ayarlar (değiştirilmez).
        values: (bölüm, anahtar) → formdaki ham değer. Sayılar metin, listeler satır listesi.

    Returns:
        (yeni ayarlar, yeniden başlatma gerektiren değişen alanların adları)

    Raises:
        SettingsError: Bir değer geçersizse (mesajda alan adı bulunur).
    """
    new_config = copy.deepcopy(config)
    restart_needed: list[str] = []
    for setting in _all_fields():
        raw = values.get((setting.section, setting.key))
        if raw is None:
            continue
        value = _parse_value(setting, raw)
        section = getattr(new_config, setting.section)
        if setting.restart_required and getattr(section, setting.key) != value:
            restart_needed.append(setting.label)
        setattr(section, setting.key, value)
    return new_config, restart_needed


def _all_fields() -> list[SettingField]:
    return [setting for tab in SETTINGS_TABS for setting in tab.fields]


def _parse_value(setting: SettingField, raw: Any) -> Any:
    if setting.kind in (FieldKind.FLOAT, FieldKind.INT):
        return _parse_number(setting, str(raw))
    if setting.kind is FieldKind.BOOL:
        return bool(raw)
    if setting.kind in (FieldKind.LINES, FieldKind.FOLDER_LINES):
        lines = raw.splitlines() if isinstance(raw, str) else raw
        return [line.strip() for line in lines if line.strip()]
    if setting.kind is FieldKind.CHOICE:
        allowed = [value for value, _ in setting.choices]
        if raw not in allowed:
            raise SettingsError(f"{setting.label}: geçersiz seçim '{raw}'")
        return raw
    return str(raw).strip()


def _parse_number(setting: SettingField, text: str) -> float | int:
    text = text.strip().replace(",", ".")
    try:
        number: float | int = int(text) if setting.kind is FieldKind.INT else float(text)
    except ValueError as err:
        expected = "tam sayı" if setting.kind is FieldKind.INT else "sayı"
        raise SettingsError(f"{setting.label}: '{text}' geçerli bir {expected} değil") from err
    if setting.min_value is not None and number < setting.min_value:
        raise SettingsError(f"{setting.label}: en az {setting.min_value} olmalı")
    if setting.max_value is not None and number > setting.max_value:
        raise SettingsError(f"{setting.label}: en fazla {setting.max_value} olmalı")
    return number


# --- Görünüm (sadece ana thread) ---

WINDOW_TITLE = "NightJester Ayarları"
WINDOW_SIZE = "700x660"
PADDING_PX = 8
LABEL_WIDTH_PX = 250
ENTRY_WIDTH_PX = 320
TEXTBOX_HEIGHT_PX = 90
ERROR_COLOR = "#e04040"
INFO_COLOR = "#e6b800"
OK_COLOR = "#3cb371"


class SettingsWindow(ctk.CTkToplevel):
    """Ayarlar penceresi. Kaydet'e basılınca on_save(yeni_config) çağrılır."""

    def __init__(
        self,
        master: ctk.CTk,
        config: AppConfig,
        on_save: Callable[[AppConfig], bool],
    ) -> None:
        """Pencereyi mevcut ayarlarla doldurur.

        Args:
            master: Ana pencere.
            config: Mevcut ayarlar.
            on_save: Yeni ayarları kaydedip yayınlar. Başarılıysa True döner.
        """
        super().__init__(master)
        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.transient(master)
        self._config = config
        self._on_save = on_save
        self._getters: dict[tuple[str, str], Callable[[], Any]] = {}

        tabview = ctk.CTkTabview(self)
        tabview.pack(fill="both", expand=True, padx=PADDING_PX, pady=PADDING_PX)
        for tab in SETTINGS_TABS:
            frame = ctk.CTkScrollableFrame(tabview.add(tab.title))
            frame.pack(fill="both", expand=True)
            for row, setting in enumerate(tab.fields):
                self._add_field(frame, row, setting)

        self._message = ctk.CTkLabel(self, text="", wraplength=580)
        self._message.pack(padx=PADDING_PX)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(pady=PADDING_PX)
        ctk.CTkButton(buttons, text="Kaydet", command=self._save).pack(side="left", padx=PADDING_PX)
        ctk.CTkButton(buttons, text="Kapat", command=self.destroy).pack(
            side="left", padx=PADDING_PX
        )
        # Ana pencerenin arkasında açılmasın.
        self.after(10, self.lift)

    def _add_field(self, frame: ctk.CTkScrollableFrame, row: int, setting: SettingField) -> None:
        current = getattr(getattr(self._config, setting.section), setting.key)
        label = setting.label + (" *" if setting.restart_required else "")
        ctk.CTkLabel(frame, text=label, width=LABEL_WIDTH_PX, anchor="w", wraplength=240).grid(
            row=row, column=0, sticky="nw", padx=PADDING_PX, pady=PADDING_PX
        )
        cell = ctk.CTkFrame(frame, fg_color="transparent")
        cell.grid(row=row, column=1, sticky="w", padx=PADDING_PX, pady=PADDING_PX)
        key = (setting.section, setting.key)

        if setting.kind is FieldKind.BOOL:
            var = ctk.BooleanVar(value=bool(current))
            ctk.CTkCheckBox(cell, text="", variable=var).pack(anchor="w")
            self._getters[key] = var.get
        elif setting.kind is FieldKind.CHOICE:
            labels = {value: text for value, text in setting.choices}
            values_by_label = {text: value for value, text in setting.choices}
            var = ctk.StringVar(value=labels.get(current, current))
            ctk.CTkOptionMenu(
                cell, values=list(values_by_label), variable=var, width=ENTRY_WIDTH_PX
            ).pack(anchor="w")
            self._getters[key] = lambda: values_by_label.get(var.get(), var.get())
        elif setting.kind in (FieldKind.LINES, FieldKind.FOLDER_LINES):
            textbox = ctk.CTkTextbox(cell, width=ENTRY_WIDTH_PX, height=TEXTBOX_HEIGHT_PX)
            textbox.insert("1.0", "\n".join(current))
            textbox.pack(anchor="w")
            self._getters[key] = lambda: textbox.get("1.0", "end")
            if setting.kind is FieldKind.FOLDER_LINES:
                ctk.CTkButton(
                    cell, text="Klasör ekle", command=lambda: _append_folder(textbox)
                ).pack(anchor="w", pady=(PADDING_PX // 2, 0))
        else:
            entry = ctk.CTkEntry(cell, width=ENTRY_WIDTH_PX)
            entry.insert(0, str(current))
            entry.pack(anchor="w")
            self._getters[key] = entry.get
            if setting.kind is FieldKind.FILE:
                file_types = (
                    SOUND_FILE_TYPES if setting.key == "deadline_sound_path" else VIDEO_FILE_TYPES
                )
                ctk.CTkButton(
                    cell, text="Dosya seç", command=lambda: _choose_file(entry, file_types)
                ).pack(anchor="w", pady=(PADDING_PX // 2, 0))

    def _save(self) -> None:
        values = {key: getter() for key, getter in self._getters.items()}
        try:
            new_config, restart_needed = apply_form_values(self._config, values)
        except SettingsError as err:
            self._message.configure(text=str(err), text_color=ERROR_COLOR)
            return
        if not self._on_save(new_config):
            self._message.configure(
                text="Ayarlar kaydedilemedi, log'a bak.", text_color=ERROR_COLOR
            )
            return
        self._config = new_config
        if restart_needed:
            self._message.configure(
                text="Kaydedildi. Şu değişiklikler için uygulamayı yeniden başlat: "
                + ", ".join(restart_needed),
                text_color=INFO_COLOR,
            )
        else:
            self._message.configure(text="Kaydedildi ve uygulandı.", text_color=OK_COLOR)


def _choose_file(entry: ctk.CTkEntry, file_types: tuple[tuple[str, str], ...]) -> None:
    path = filedialog.askopenfilename(filetypes=file_types)
    if path:
        entry.delete(0, "end")
        entry.insert(0, path)


def _append_folder(textbox: ctk.CTkTextbox) -> None:
    path = filedialog.askdirectory()
    if not path:
        return
    existing = textbox.get("1.0", "end").strip()
    textbox.delete("1.0", "end")
    textbox.insert("1.0", f"{existing}\n{path}" if existing else path)
