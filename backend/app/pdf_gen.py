import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# Register a Chinese-capable font shipped with ReportLab (no extra font files needed).
# STSong-Light supports Chinese and ASCII; avoids garbled Chinese in PDFs.
try:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
except Exception:
    # In case of double-registration or environment quirks.
    pass


@dataclass
class ExerciseRow:
    position: int
    zh_hint: str
    answer_en: str
    item_type: str  # WORD / PHRASE / SENTENCE


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


_CN_WEEKDAY = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _today_meta(weather: str = "") -> Dict[str, str]:
    now = datetime.now()
    w = _CN_WEEKDAY[now.weekday()]
    date_str = now.strftime("%Y-%m-%d")
    weather_str = weather or "____（武汉）"
    return {"date": date_str, "weekday": w, "weather": weather_str}


def render_dictation_pdf(
    out_path: str,
    title: str,
    sections: Dict[str, List[ExerciseRow]],
    show_answers: bool,
    weather: str = "",
    footer: Optional[str] = None,
) -> None:
    """生成“英语默写单/答案单”PDF（中文友好版）。

    版式参考你提供的 Word 样式：
    - 顶部标题 + 日期/星期/天气行
    - 三个分区：单词、短语、句子（按存在与否显示）
    - 默写单：中文提示 + 留白；答案单：中文提示 + 英文答案

    注意：为了兼容“多模板/内容变动”，本函数不依赖固定坐标，只做排版。
    """
    _ensure_dir(out_path)

    c = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4

    # Layout constants
    margin_x = 18 * mm
    margin_y = 16 * mm
    y = height - margin_y

    font_cn = "STSong-Light"

    # Title
    c.setFont(font_cn, 16)
    c.drawString(margin_x, y, title)
    y -= 9 * mm

    meta = _today_meta(weather)
    c.setFont(font_cn, 11)
    c.drawString(margin_x, y, f"日期：{meta['date']}  {meta['weekday']}   天气：{meta['weather']}")
    y -= 9 * mm

    # Section headings
    section_order = [
        ("WORD", "一、单词默写"),
        ("PHRASE", "二、短语默写"),
        ("SENTENCE", "三、句子默写"),
    ]

    def new_page():
        nonlocal y
        c.showPage()
        y = height - margin_y
        c.setFont(font_cn, 11)
        c.drawString(margin_x, y, f"日期：{meta['date']}  {meta['weekday']}   天气：{meta['weather']}")
        y -= 9 * mm

    def ensure_space(min_needed_mm: float):
        nonlocal y
        if y < margin_y + min_needed_mm * mm:
            new_page()

    # Rendering helpers
    def draw_fill_line(x0, y0, x1):
        c.line(x0, y0 - 1.8 * mm, x1, y0 - 1.8 * mm)

    # Main body
    for key, label in section_order:
        rows = sections.get(key, []) or []
        if not rows:
            continue

        ensure_space(18)
        c.setFont(font_cn, 12)
        c.drawString(margin_x, y, f"{label}（{len(rows)} 个）")
        y -= 8 * mm

        c.setFont(font_cn, 11)

        if key in ("WORD", "PHRASE"):
            # One line per item
            for idx, row in enumerate(rows, start=1):
                ensure_space(12)
                prefix = f"{idx}. {row.zh_hint}："
                c.drawString(margin_x, y, prefix)

                # writing area or answer
                x_ans = margin_x + 60 * mm
                if show_answers:
                    c.drawString(x_ans, y, row.answer_en)
                else:
                    draw_fill_line(x_ans, y, width - margin_x)
                y -= 8.5 * mm

        else:
            # SENTENCE: two lines per item (prompt line + "英文：" line)
            for idx, row in enumerate(rows, start=1):
                ensure_space(22)
                # prompt line
                c.drawString(margin_x, y, f"{idx}. {row.zh_hint}")
                y -= 7.5 * mm
                # answer line
                x_ans = margin_x
                if show_answers:
                    c.drawString(margin_x, y, "英文：")
                    x_ans = margin_x + 18 * mm
                if show_answers:
                    # allow longer sentences: wrap roughly by max width
                    # simple wrapping by character count for MVP
                    text = row.answer_en
                    max_chars = 65
                    lines = [text[i : i + max_chars] for i in range(0, len(text), max_chars)] or [""]
                    c.drawString(x_ans, y, lines[0])
                    y -= 7.5 * mm
                    for extra in lines[1:]:
                        ensure_space(12)
                        c.drawString(x_ans, y, extra)
                        y -= 7.5 * mm
                    y -= 2 * mm
                else:
                    draw_fill_line(x_ans, y, width - margin_x)
                    y -= 12 * mm

        y -= 2 * mm

    if footer:
        c.setFont(font_cn, 9)
        c.drawString(margin_x, 10 * mm, footer)

    c.save()
