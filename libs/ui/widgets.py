"""Küçük panel bileşenleri: canlı EAR grafiği ve durum göstergeleri."""

from __future__ import annotations

import tkinter as tk
from collections import deque

import customtkinter as ctk

from libs.device_state_tracker import DeviceError, Indicator

CHART_BG = "#1a1a19"
GRID_COLOR = "#3a3a38"
TEXT_MUTED = "#9a9a9a"
EAR_LINE_COLOR = "#4a90d9"
THRESHOLD_COLOR = "#e04040"
FONT_SMALL = ("Segoe UI", 9)

EAR_GRAPH_WIDTH_PX = 640
EAR_GRAPH_HEIGHT_PX = 80
EAR_GRAPH_MAX = 0.45
EAR_GRAPH_SAMPLES = 300  # UI 30 Hz → ~10 sn
EAR_LINE_WIDTH_PX = 2
THRESHOLD_DASH = (4, 3)
GRAPH_PADDING_PX = 4

INDICATOR_SIZE_PX = 14
INDICATOR_ON_COLOR = "#e04040"
INDICATOR_OFF_COLOR = "#4a4a48"
INDICATOR_LABELS: dict[Indicator, str] = {
    Indicator.VISION: "Görüntü",
    Indicator.ALERT: "Uyarı",
    Indicator.INTEGRATION: "Entegrasyon",
}
ERROR_TEXTS: dict[DeviceError, str] = {
    DeviceError.CAMERA_INIT_ERROR: "Kamera açılamadı",
    DeviceError.CAMERA_READ_ERROR: "Kameradan görüntü okunamıyor",
    DeviceError.MODEL_LOAD_ERROR: "Yüz modeli yüklenemedi",
    DeviceError.AUDIO_INIT_ERROR: "Ses / ses dosyası sorunu",
    DeviceError.GIT_ERROR: "Git / repo yolu sorunu",
    DeviceError.CONFIG_ERROR: "Ayar dosyası bozuk, varsayılanlar kullanılıyor",
}
PADDING_PX = 10


class EarGraph(tk.Canvas):
    """Son ~10 sn'nin EAR çizgisi ve kesikli eşik çizgisi."""

    def __init__(self, master: tk.Misc) -> None:
        """Boş grafiği oluşturur.

        Args:
            master: Üst bileşen.
        """
        super().__init__(
            master,
            width=EAR_GRAPH_WIDTH_PX,
            height=EAR_GRAPH_HEIGHT_PX,
            bg=CHART_BG,
            highlightthickness=0,
        )
        self._values: deque[float | None] = deque(maxlen=EAR_GRAPH_SAMPLES)
        self._threshold = 0.0
        self.create_text(
            GRAPH_PADDING_PX,
            GRAPH_PADDING_PX,
            text="EAR (son 10 sn)",
            anchor="nw",
            fill=TEXT_MUTED,
            font=FONT_SMALL,
        )
        self._line = self.create_line(0, 0, 0, 0, fill=EAR_LINE_COLOR, width=EAR_LINE_WIDTH_PX)
        self._threshold_line = self.create_line(
            0, 0, 0, 0, fill=THRESHOLD_COLOR, dash=THRESHOLD_DASH, state="hidden"
        )
        self._threshold_text = self.create_text(
            0, 0, text="", anchor="se", fill=TEXT_MUTED, font=FONT_SMALL, state="hidden"
        )

    def push(self, ear: float | None) -> None:
        """Yeni bir EAR değeri ekler (yüz yoksa None) ve çizgiyi günceller.

        Args:
            ear: EAR değeri veya None.
        """
        self._values.append(ear)
        points: list[float] = []
        step = EAR_GRAPH_WIDTH_PX / (EAR_GRAPH_SAMPLES - 1)
        offset = EAR_GRAPH_SAMPLES - len(self._values)
        for index, value in enumerate(self._values):
            if value is not None:
                points += [(offset + index) * step, self._y(value)]
        if len(points) >= 4:
            self.coords(self._line, *points)
        else:
            self.coords(self._line, 0, 0, 0, 0)

    def set_threshold(self, threshold: float) -> None:
        """Eşik çizgisini günceller (0 ise gizler).

        Args:
            threshold: Göz kapalı EAR eşiği.
        """
        if threshold == self._threshold:
            return
        self._threshold = threshold
        if threshold <= 0:
            self.itemconfigure(self._threshold_line, state="hidden")
            self.itemconfigure(self._threshold_text, state="hidden")
            return
        y = self._y(threshold)
        self.coords(self._threshold_line, 0, y, EAR_GRAPH_WIDTH_PX, y)
        self.coords(self._threshold_text, EAR_GRAPH_WIDTH_PX - GRAPH_PADDING_PX, y - 2)
        self.itemconfigure(self._threshold_line, state="normal")
        self.itemconfigure(self._threshold_text, state="normal", text=f"eşik {threshold:.3f}")

    def _y(self, ear: float) -> float:
        usable = EAR_GRAPH_HEIGHT_PX - 2 * GRAPH_PADDING_PX
        ratio = min(max(ear / EAR_GRAPH_MAX, 0.0), 1.0)
        return EAR_GRAPH_HEIGHT_PX - GRAPH_PADDING_PX - ratio * usable


class IndicatorBar(ctk.CTkFrame):
    """Alt sistem başına bir gösterge noktası ve aktif hataların metni."""

    def __init__(self, master: tk.Misc) -> None:
        """Göstergeleri sönük olarak oluşturur.

        Args:
            master: Üst bileşen.
        """
        super().__init__(master, fg_color="transparent")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack()
        self._dots: dict[Indicator, tuple[tk.Canvas, int]] = {}
        for indicator, label in INDICATOR_LABELS.items():
            canvas = tk.Canvas(
                row,
                width=INDICATOR_SIZE_PX,
                height=INDICATOR_SIZE_PX,
                highlightthickness=0,
                bg=self._canvas_bg(),
            )
            dot = canvas.create_oval(
                1,
                1,
                INDICATOR_SIZE_PX - 1,
                INDICATOR_SIZE_PX - 1,
                fill=INDICATOR_OFF_COLOR,
                width=0,
            )
            canvas.pack(side="left", padx=(PADDING_PX, 4))
            ctk.CTkLabel(row, text=label, text_color=TEXT_MUTED).pack(side="left")
            self._dots[indicator] = (canvas, dot)
        self._errors_label = ctk.CTkLabel(self, text="", text_color=TEXT_MUTED, wraplength=620)
        self._errors_label.pack()
        self._last_states: dict[Indicator, bool] = {}
        self._last_mask = DeviceError.NO_ERROR

    def show(self, states: dict[Indicator, bool], mask: DeviceError) -> None:
        """Göstergeleri ve hata metnini günceller (sadece değişen kısım çizilir).

        Args:
            states: Gösterge → yanık mı (device_state_tracker hesaplar).
            mask: Aktif hata bitmask'i.
        """
        for indicator, is_on in states.items():
            if self._last_states.get(indicator) == is_on:
                continue
            canvas, dot = self._dots[indicator]
            canvas.itemconfigure(dot, fill=INDICATOR_ON_COLOR if is_on else INDICATOR_OFF_COLOR)
        self._last_states = dict(states)
        if mask != self._last_mask:
            self._last_mask = mask
            texts = [text for error, text in ERROR_TEXTS.items() if mask & error]
            self._errors_label.configure(text=" · ".join(texts))

    def _canvas_bg(self) -> str:
        # tk.Canvas, CTk'nin açık/koyu renk çiftini anlamaz. Koyu tema rengi seçilir.
        color = self.master.cget("fg_color")
        if isinstance(color, (list, tuple)):
            return color[1]
        return color if color != "transparent" else "#2b2b2b"
