"""Yorgunluk raporu: oturumdaki Uykulu / Uyuyor olaylarının saatlere göre dağılımı."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from libs.session_logger import HourlyCount

WINDOW_TITLE = "NightJester Yorgunluk Raporu"
PADDING_PX = 10
CHART_WIDTH_PX = 560
CHART_HEIGHT_PX = 260
CHART_LEFT_PX = 16
CHART_RIGHT_PX = 16
CHART_TOP_PX = 40  # lejant için
CHART_BOTTOM_PX = 30  # saat etiketleri için
BAR_WIDTH_PX = 18
BAR_GAP_PX = 2  # iki çubuk arası yüzey boşluğu
GROUP_GAP_PX = 18
VALUE_LABEL_OFFSET_PX = 8
LEGEND_SWATCH_PX = 10

# Grafik renkleri koyu temada renk körlüğü doğrulayıcısından geçirildi (ΔE 6,6 + doğrudan
# etiketler). Paneldeki daha açık durum renkleri grafik yüzeyinde fazla parlak kalıyor.
CHART_BG = "#1a1a19"
DROWSY_COLOR = "#b88e00"
ASLEEP_COLOR = "#e04040"
AXIS_COLOR = "#4a4a48"
TEXT_PRIMARY = "#dcdcdc"
TEXT_MUTED = "#9a9a9a"
FONT_SMALL = ("Segoe UI", 9)
FONT_LEGEND = ("Segoe UI", 10)

TEXT_EMPTY = "Bu oturumda henüz Uykulu / Uyuyor olayı yok."


class ReportWindow(ctk.CTkToplevel):
    """Rapor penceresi. Veriyi load_report fonksiyonundan alır, "Yenile" ile tazeler."""

    def __init__(self, master: ctk.CTk, load_report: Callable[[], list[HourlyCount]]) -> None:
        """Pencereyi oluşturur ve raporu çizer.

        Args:
            master: Ana pencere.
            load_report: Saatlik sayımları döner.
        """
        super().__init__(master)
        self.title(WINDOW_TITLE)
        self.resizable(False, False)
        self.transient(master)
        self._load_report = load_report

        self._summary = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self._summary.pack(padx=PADDING_PX, pady=(PADDING_PX, 0))
        self._canvas = tk.Canvas(
            self,
            width=CHART_WIDTH_PX,
            height=CHART_HEIGHT_PX,
            bg=CHART_BG,
            highlightthickness=0,
        )
        self._canvas.pack(padx=PADDING_PX, pady=PADDING_PX)
        self._table = ctk.CTkTextbox(self, width=CHART_WIDTH_PX, height=120, font=("Consolas", 12))
        self._table.pack(padx=PADDING_PX)
        ctk.CTkButton(self, text="Yenile", command=self.refresh).pack(pady=PADDING_PX)
        self.refresh()
        self.after(10, self.lift)

    def refresh(self) -> None:
        """Raporu yeniden okur ve çizer."""
        counts = self._load_report()
        total_drowsy = sum(count.drowsy for count in counts)
        total_asleep = sum(count.asleep for count in counts)
        self._summary.configure(text=f"Bu oturum: {total_drowsy} Uykulu, {total_asleep} Uyuyor")
        self._draw_chart(counts)
        self._fill_table(counts)

    def _draw_chart(self, counts: list[HourlyCount]) -> None:
        canvas = self._canvas
        canvas.delete("all")
        self._draw_legend()
        baseline_y = CHART_HEIGHT_PX - CHART_BOTTOM_PX
        canvas.create_line(
            CHART_LEFT_PX, baseline_y, CHART_WIDTH_PX - CHART_RIGHT_PX, baseline_y, fill=AXIS_COLOR
        )
        if not counts:
            canvas.create_text(
                CHART_WIDTH_PX / 2,
                CHART_HEIGHT_PX / 2,
                text=TEXT_EMPTY,
                fill=TEXT_MUTED,
                font=FONT_LEGEND,
            )
            return

        max_value = max(max(count.drowsy, count.asleep) for count in counts)
        plot_height = baseline_y - CHART_TOP_PX - VALUE_LABEL_OFFSET_PX * 2
        group_width = BAR_WIDTH_PX * 2 + BAR_GAP_PX
        x = CHART_LEFT_PX + GROUP_GAP_PX
        for count in counts:
            for offset, value, color in (
                (0, count.drowsy, DROWSY_COLOR),
                (BAR_WIDTH_PX + BAR_GAP_PX, count.asleep, ASLEEP_COLOR),
            ):
                left = x + offset
                height = plot_height * value / max_value if max_value else 0
                if value:
                    canvas.create_rectangle(
                        left,
                        baseline_y - height,
                        left + BAR_WIDTH_PX,
                        baseline_y,
                        fill=color,
                        width=0,
                    )
                canvas.create_text(
                    left + BAR_WIDTH_PX / 2,
                    baseline_y - height - VALUE_LABEL_OFFSET_PX,
                    text=str(value),
                    fill=TEXT_PRIMARY,
                    font=FONT_SMALL,
                )
            canvas.create_text(
                x + group_width / 2,
                baseline_y + CHART_BOTTOM_PX / 2,
                text=f"{count.hour:02d}:00",
                fill=TEXT_MUTED,
                font=FONT_SMALL,
            )
            x += group_width + GROUP_GAP_PX

    def _draw_legend(self) -> None:
        x = CHART_LEFT_PX
        y = CHART_TOP_PX / 2
        for label, color in (("Uykulu", DROWSY_COLOR), ("Uyuyor", ASLEEP_COLOR)):
            self._canvas.create_rectangle(
                x,
                y - LEGEND_SWATCH_PX / 2,
                x + LEGEND_SWATCH_PX,
                y + LEGEND_SWATCH_PX / 2,
                fill=color,
                width=0,
            )
            text_id = self._canvas.create_text(
                x + LEGEND_SWATCH_PX + 6,
                y,
                text=label,
                anchor="w",
                fill=TEXT_PRIMARY,
                font=FONT_LEGEND,
            )
            x = self._canvas.bbox(text_id)[2] + PADDING_PX * 2

    def _fill_table(self, counts: list[HourlyCount]) -> None:
        lines = [f"{'Saat':<8}{'Uykulu':>8}{'Uyuyor':>8}"]
        lines += [f"{count.hour:02d}:00   {count.drowsy:>8}{count.asleep:>8}" for count in counts]
        if not counts:
            lines.append(TEXT_EMPTY)
        self._table.configure(state="normal")
        self._table.delete("1.0", "end")
        self._table.insert("1.0", "\n".join(lines))
        self._table.configure(state="disabled")
