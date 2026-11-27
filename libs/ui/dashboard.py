"""Dashboard: kamera önizlemesi, yüz noktası overlay'i ve ölçüm değerleri."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

from libs.communicator.topics import FaceMetrics

PADDING_PX = 10
PREVIEW_BG = "#1a1a1a"
PREVIEW_TEXT_COLOR = "#9a9a9a"
METRICS_FONT_SIZE = 18
LANDMARK_RADIUS_PX = 2
LANDMARK_COLOR_BGR = (0, 255, 0)
FILLED = -1

TEXT_WAITING_CAMERA = "Kamera bekleniyor…"
TEXT_NO_CAMERA = "Kamera görüntüsü yok"
TEXT_WAITING_ANALYSIS = "Yüz analizi bekleniyor…"
TEXT_NO_FACE = "Yüz algılanmadı"


class Dashboard(ctk.CTkFrame):
    """Ana paneldeki önizleme ve ölçüm alanı. Sadece ana thread'den çağrılır."""

    def __init__(self, master: ctk.CTk, show_landmarks: bool) -> None:
        """Paneli oluşturur.

        Args:
            master: Ana pencere.
            show_landmarks: Göz ve ağız noktaları önizlemeye çizilsin mi.
        """
        super().__init__(master)
        self._show_landmarks = show_landmarks
        self._photo: ImageTk.PhotoImage | None = None

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
