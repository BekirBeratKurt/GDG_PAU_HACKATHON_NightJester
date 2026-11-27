"""Dashboard: kamera önizlemesi, yüz noktası overlay'i ve ölçüm değerleri."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

from libs.communicator.topics import AppMode, FaceMetrics, FatigueLevel, FatigueState

PADDING_PX = 10
PREVIEW_BG = "#1a1a1a"
PREVIEW_TEXT_COLOR = "#9a9a9a"
METRICS_FONT_SIZE = 18
STATUS_FONT_SIZE = 28
DETAIL_FONT_SIZE = 14
LANDMARK_RADIUS_PX = 2
LANDMARK_COLOR_BGR = (0, 255, 0)
FILLED = -1

TEXT_WAITING_CAMERA = "Kamera bekleniyor…"
TEXT_NO_CAMERA = "Kamera görüntüsü yok"
TEXT_WAITING_ANALYSIS = "Yüz analizi bekleniyor…"
TEXT_NO_FACE = "Yüz algılanmadı"
TEXT_WAITING_STATE = "Durum bekleniyor…"
TEXT_CALIBRATE_BUTTON = "Kalibre et"
TEXT_TEST_ALARM_BUTTON = "Test alarmı"
TEXT_WAKE_BUTTON = "Uyandım"
TEXT_CALIBRATING_HINT = "Ekrana normal şekilde bak, gözlerini açık tut."

MODE_LABELS: dict[AppMode, str] = {
    AppMode.NORMAL: "Normal",
    AppMode.DEADLINE: "Deadline",
    AppMode.PAUSED: "Duraklat",
}
WAKE_BUTTON_ALARM_COLOR = "#c0392b"
WAKE_BUTTON_ALARM_HOVER_COLOR = "#a93226"

# Seviye → (etiket, renk)
LEVEL_DISPLAY: dict[FatigueLevel, tuple[str, str]] = {
    FatigueLevel.CALIBRATING: ("Kalibre ediliyor…", "#4a90d9"),
    FatigueLevel.AWAKE: ("Uyanık", "#3cb371"),
    FatigueLevel.DROWSY: ("Uykulu", "#e6b800"),
    FatigueLevel.ASLEEP: ("Uyuyor", "#e04040"),
    FatigueLevel.NO_FACE: ("Yüz yok", "#8a8a8a"),
}
DEFAULT_TEXT_COLOR = "#dcdcdc"


@dataclass
class DashboardCallbacks:
    """Panel butonlarına basılınca çağrılacak fonksiyonlar."""

    on_calibrate: Callable[[], None]
    on_mode_change: Callable[[AppMode], None]
    on_wake: Callable[[], None]
    on_test_alarm: Callable[[], None]


class Dashboard(ctk.CTkFrame):
    """Ana paneldeki önizleme, ölçüm ve kontrol alanı. Sadece ana thread'den çağrılır."""

    def __init__(
        self,
        master: ctk.CTk,
        show_landmarks: bool,
        initial_mode: AppMode,
        callbacks: DashboardCallbacks,
    ) -> None:
        """Paneli oluşturur.

        Args:
            master: Ana pencere.
            show_landmarks: Göz ve ağız noktaları önizlemeye çizilsin mi.
            initial_mode: Mod anahtarının başlangıç değeri.
            callbacks: Buton fonksiyonları.
        """
        super().__init__(master)
        self._show_landmarks = show_landmarks
        self._photo: ImageTk.PhotoImage | None = None
        self._alarm_shown = False
        self._label_to_mode = {label: mode for mode, label in MODE_LABELS.items()}
        self._on_mode_change = callbacks.on_mode_change

        self._mode_switch = ctk.CTkSegmentedButton(
            self, values=list(MODE_LABELS.values()), command=self._handle_mode_selected
        )
        self._mode_switch.set(MODE_LABELS[initial_mode])
        self._mode_switch.pack(padx=PADDING_PX, pady=(PADDING_PX, 0))

        self._status_label = ctk.CTkLabel(
            self,
            text=TEXT_WAITING_STATE,
            text_color=DEFAULT_TEXT_COLOR,
            font=ctk.CTkFont(size=STATUS_FONT_SIZE, weight="bold"),
        )
        self._status_label.pack(padx=PADDING_PX, pady=(PADDING_PX, 0))

        self._detail_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=DETAIL_FONT_SIZE))
        self._detail_label.pack(padx=PADDING_PX)

        self._preview = tk.Label(
            self,
            text=TEXT_WAITING_CAMERA,
            bg=PREVIEW_BG,
            fg=PREVIEW_TEXT_COLOR,
            compound="center",
        )
        self._preview.pack(padx=PADDING_PX, pady=PADDING_PX)

        self._metrics_label = ctk.CTkLabel(
            self, text=TEXT_WAITING_ANALYSIS, font=ctk.CTkFont(size=METRICS_FONT_SIZE)
        )
        self._metrics_label.pack(padx=PADDING_PX, pady=(0, PADDING_PX))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(padx=PADDING_PX, pady=(0, PADDING_PX))
        ctk.CTkButton(buttons, text=TEXT_CALIBRATE_BUTTON, command=callbacks.on_calibrate).pack(
            side="left", padx=PADDING_PX
        )
        ctk.CTkButton(buttons, text=TEXT_TEST_ALARM_BUTTON, command=callbacks.on_test_alarm).pack(
            side="left", padx=PADDING_PX
        )
        self._wake_button = ctk.CTkButton(buttons, text=TEXT_WAKE_BUTTON, command=callbacks.on_wake)
        self._wake_button.pack(side="left", padx=PADDING_PX)
        self._wake_default_colors = (
            self._wake_button.cget("fg_color"),
            self._wake_button.cget("hover_color"),
        )

    def set_mode(self, mode: AppMode) -> None:
        """Mod anahtarını dışarıdan (ör. tray) gelen moda ayarlar.

        Args:
            mode: Gösterilecek mod.
        """
        self._mode_switch.set(MODE_LABELS[mode])

    def show_alarm_active(self, active: bool) -> None:
        """Alarm çalarken "Uyandım" butonunu kırmızı yapar.

        Args:
            active: Alarm çalıyor mu.
        """
        if active == self._alarm_shown:
            return
        self._alarm_shown = active
        if active:
            colors = (WAKE_BUTTON_ALARM_COLOR, WAKE_BUTTON_ALARM_HOVER_COLOR)
        else:
            colors = self._wake_default_colors
        self._wake_button.configure(fg_color=colors[0], hover_color=colors[1])

    def _handle_mode_selected(self, label: str) -> None:
        self._on_mode_change(self._label_to_mode[label])

    def show_state(self, state: FatigueState | None) -> None:
        """Yorgunluk seviyesini renkli etiketle ve ayrıntılarını gösterir.

        Args:
            state: Son yorgunluk durumu.
        """
        if state is None:
            self._status_label.configure(text=TEXT_WAITING_STATE, text_color=DEFAULT_TEXT_COLOR)
            self._detail_label.configure(text="")
            return
        label, color = LEVEL_DISPLAY[state.level]
        self._status_label.configure(text=label, text_color=color)
        if state.level is FatigueLevel.CALIBRATING:
            detail = TEXT_CALIBRATING_HINT
        else:
            detail = (
                f"Eşik: {state.ear_threshold:.3f}    "
                f"Kapalı göz: {state.eyes_closed_sec:.1f} sn    "
                f"Skor: {state.score}"
            )
        self._detail_label.configure(text=detail)

    def show_frame(self, image_bgr: np.ndarray, metrics: FaceMetrics | None) -> None:
        """Kareyi (gerekirse overlay ile) önizlemede gösterir.

        Args:
            image_bgr: Gösterilecek kare. Üzerine çizim yapılır, kopyası verilmelidir.
            metrics: Son yüz ölçümü (overlay noktaları için).
        """
        if (
            self._show_landmarks
            and metrics is not None
            and metrics.face_present
            and metrics.landmarks_px is not None
        ):
            for x, y in metrics.landmarks_px:
                cv2.circle(
                    image_bgr, (int(x), int(y)), LANDMARK_RADIUS_PX, LANDMARK_COLOR_BGR, FILLED
                )
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        # PhotoImage referansı tutulmazsa Tk görüntüyü çöpe atar ve önizleme boş kalır.
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self._preview.configure(image=self._photo, text="")

    def show_no_camera(self) -> None:
        """Kamera görüntüsü gelmiyorsa önizlemede uyarı metni gösterir."""
        self._photo = None
        self._preview.configure(image="", text=TEXT_NO_CAMERA)

    def show_metrics(self, metrics: FaceMetrics | None) -> None:
        """EAR / MAR değerlerini veya yüz durumunu gösterir.

        Args:
            metrics: Son yüz ölçümü. None ise analiz henüz gelmemiştir.
        """
        if metrics is None:
            text = TEXT_WAITING_ANALYSIS
        elif not metrics.face_present:
            text = TEXT_NO_FACE
        else:
            text = f"EAR: {metrics.ear:.3f}    MAR: {metrics.mar:.3f}"
        self._metrics_label.configure(text=text)
