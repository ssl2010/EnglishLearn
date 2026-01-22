import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.graphics import renderPDF

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


def _generate_uuid(session_id: int) -> str:
    """Generate a short UUID for the session."""
    # Use session_id to create a deterministic but unique identifier
    # Format: ES-{session_id}-{first 6 chars of UUID}
    short_uuid = str(uuid.uuid4())[:6].upper()
    return f"ES-{session_id:04d}-{short_uuid}"


def render_dictation_pdf(
    out_path: str,
    title: str,
    sections: Dict[str, List[ExerciseRow]],
    show_answers: bool,
    session_id: int,
    footer: Optional[str] = None,
    practice_uuid: Optional[str] = None,
) -> None:
    """生成专业美观的英语默写单/答案单PDF。

    改进：
    - 修复中文提示显示问题（使用zh_text字段）
    - 减小页边距，增加书写空间
    - 横线紧挨冒号，所有横线结束点一致
    - 进一步加大行间距
    - 修复换页后字号问题
    - 句子默写改为一行横线，调整间隔
    """
    _ensure_dir(out_path)

    c = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4

    # Layout constants - 平衡美观与空间利用
    margin_x = (16 if show_answers else 18) * mm  # 答案页略减边距
    margin_y = (12 if show_answers else 15) * mm  # 答案页略减边距
    y = height - margin_y

    # 答题横线的结束点
    # 单词横线：到页面中间位置
    word_line_end_x = margin_x + (width - 2 * margin_x) * 0.55  # 页面宽度的55%
    # 短语和句子横线：到右边距
    line_end_x = width - margin_x

    # 生成UUID
    practice_uuid = practice_uuid or _generate_uuid(session_id)

    font_cn = "STSong-Light"

    # 页码计数器
    page_number = 1
    date_str = datetime.now().strftime("%Y年%m月%d日")

    footer_space_mm = 12 if show_answers else 15

    # 绘制页眉（标题 + 左上角日期 + 右上角条码，对称设计）
    def draw_header(is_first_page=True):
        nonlocal y
        y = height - margin_y

        # 左上角：日期（与右上角条码对称）
        c.setFont(font_cn, 11)
        date_display = f"日期：{date_str}"
        c.drawString(margin_x, height - 8 * mm, date_display)

        # 右上角绘制条码和编号（忽略页边距，紧贴页面角落）
        barcode_width = 60 * mm
        barcode_height = 12 * mm
        barcode_x = width - barcode_width - 3 * mm  # 距离右边缘3mm
        barcode_y = height - barcode_height - 3 * mm  # 距离上边缘3mm

        # 生成条码
        barcode_obj = code128.Code128(practice_uuid, barHeight=10*mm, barWidth=0.8)
        barcode_obj.drawOn(c, barcode_x, barcode_y)

        # 条码下方显示编号文字
        c.setFont(font_cn, 9)
        c.drawCentredString(barcode_x + barcode_width/2, barcode_y - 4*mm, practice_uuid)

        if is_first_page:
            # 第一页：显示标题（居中，在日期和条码下方）
            y -= 6 * mm  # 为顶部日期/条码预留空间（减少以压缩）
            c.setFont(font_cn, 18 if show_answers else 22)
            c.drawCentredString(width / 2, y, title)
            y -= (8 if show_answers else 10) * mm  # 标题后间距
        else:
            # 非首页：为顶部日期/条码预留空间后直接开始内容
            y -= (12 if show_answers else 14) * mm  # 减少以节省空间

    # 绘制页脚（仅页码居中）
    def draw_footer():
        nonlocal page_number
        # 中间：页码
        c.setFont(font_cn, 10)
        c.drawCentredString(width / 2, 12 * mm, f"第 {page_number} 页")
        page_number += 1

    # 初始化第一页
    draw_header(is_first_page=True)

    # Section headings
    section_order = [
        ("WORD", "一、单词默写"),
        ("PHRASE", "二、短语默写"),
        ("SENTENCE", "三、句子默写"),
    ]

    def new_page():
        nonlocal y
        draw_footer()  # 绘制当前页页脚
        c.showPage()
        draw_header(is_first_page=False)

    def ensure_space(min_needed_mm: float):
        nonlocal y
        if y < margin_y + min_needed_mm * mm + footer_space_mm * mm:  # 为页脚预留空间
            new_page()

    # Rendering helpers
    def draw_fill_line(x0, y0, x1):
        """绘制答题横线"""
        c.setLineWidth(0.5)
        c.line(x0, y0 - 2.5 * mm, x1, y0 - 2.5 * mm)

    def truncate_text(text: str, max_width: float, font_size: int) -> str:
        if c.stringWidth(text, font_cn, font_size) <= max_width:
            return text
        trimmed = text
        while trimmed and c.stringWidth(trimmed + "...", font_cn, font_size) > max_width:
            trimmed = trimmed[:-1]
        return trimmed + "..." if trimmed else ""

    def wrap_text(text: str, max_width: float, font_size: int) -> List[str]:
        if not text:
            return [""]
        lines: List[str] = []
        buf = ""
        for ch in text:
            if c.stringWidth(buf + ch, font_cn, font_size) <= max_width:
                buf += ch
            else:
                if buf:
                    lines.append(buf)
                buf = ch
        if buf or not lines:
            lines.append(buf)
        return lines

    def render_answer_sections():
        nonlocal y
        section_title_size = 13
        item_size = 11
        hint_size = 9
        section_gap_mm = 3

        def draw_section_title(label: str, count: int):
            nonlocal y
            ensure_space(12)
            c.setFont(font_cn, section_title_size)
            c.drawString(margin_x, y, f"{label}（{count}题）")
            y -= 6 * mm

        def draw_grid(rows: List[ExerciseRow], columns: int, cell_height_mm: float):
            nonlocal y
            if not rows:
                return
            col_width = (width - 2 * margin_x) / columns
            total_rows = (len(rows) + columns - 1) // columns
            for row_idx in range(total_rows):
                ensure_space(cell_height_mm)
                row_y = y
                for col in range(columns):
                    idx = row_idx * columns + col
                    if idx >= len(rows):
                        break
                    row = rows[idx]
                    x = margin_x + col * col_width
                    num_text = f"{idx + 1}."
                    c.setFont(font_cn, item_size)
                    c.drawString(x, row_y, num_text)
                    prefix_w = c.stringWidth(num_text + " ", font_cn, item_size)
                    max_text_width = col_width - prefix_w - 2 * mm
                    answer = truncate_text(row.answer_en, max_text_width, item_size)
                    c.drawString(x + prefix_w, row_y, answer)
                    hint = row.zh_hint or "(无提示)"
                    c.setFont(font_cn, hint_size)
                    c.drawString(x + prefix_w, row_y - 4.2 * mm, truncate_text(hint, max_text_width, hint_size))
                y -= cell_height_mm * mm

        def draw_sentence_answers(rows: List[ExerciseRow]):
            nonlocal y
            answer_line_mm = 5.2
            hint_line_mm = 4.2
            item_gap_mm = 2.5
            for idx, row in enumerate(rows, start=1):
                prefix = f"{idx}. "
                c.setFont(font_cn, item_size)
                prefix_w = c.stringWidth(prefix, font_cn, item_size)
                max_width = width - 2 * margin_x - prefix_w
                lines = wrap_text(row.answer_en, max_width, item_size)
                hint = row.zh_hint or "(无提示)"
                needed_mm = len(lines) * answer_line_mm + hint_line_mm + item_gap_mm
                ensure_space(needed_mm)
                c.drawString(margin_x, y, prefix + lines[0])
                y -= answer_line_mm * mm
                for extra in lines[1:]:
                    ensure_space(answer_line_mm)
                    c.drawString(margin_x + prefix_w, y, extra)
                    y -= answer_line_mm * mm
                c.setFont(font_cn, hint_size)
                c.drawString(margin_x + prefix_w, y, hint)
                y -= (hint_line_mm + item_gap_mm) * mm

        for key, label in section_order:
            rows = sections.get(key, []) or []
            if not rows:
                continue
            draw_section_title(label, len(rows))
            if key == "WORD":
                draw_grid(rows, 3, 10)
            elif key == "PHRASE":
                draw_grid(rows, 2, 11)
            else:
                draw_sentence_answers(rows)
            y -= section_gap_mm * mm

    # Main body
    if show_answers:
        render_answer_sections()
    else:
        for key, label in section_order:
            rows = sections.get(key, []) or []
            if not rows:
                continue

            ensure_space(20)
            c.setFont(font_cn, 16)
            c.drawString(margin_x, y, f"{label}（共 {len(rows)} 题）")
            y -= 8 * mm  # 章节标题后的间距（减少以压缩）

            if key == "WORD":
                # 单词部分：单列排版（测试两页是否够用）
                c.setFont(font_cn, 14)

                for idx, row in enumerate(rows, start=1):
                    ensure_space(16)
                    # 换页后重新设置字体
                    c.setFont(font_cn, 14)

                    prefix = f"{idx}. {row.zh_hint}："
                    c.drawString(margin_x, y, prefix)

                    # 答题区域或答案 - 横线到页面中间位置
                    prefix_width = c.stringWidth(prefix, font_cn, 14)
                    x_ans = margin_x + prefix_width + 2 * mm
                    draw_fill_line(x_ans, y, word_line_end_x)  # 使用单词专用的横线长度

                    y -= 14 * mm  # 单词行间距（略微增加以改善视觉间隔）

            elif key == "PHRASE":
                # 短语部分：单栏，更大字体和间距
                c.setFont(font_cn, 14)  # 确保字体设置正确
                for idx, row in enumerate(rows, start=1):
                    ensure_space(16)  # 减少所需空间
                    # 换页后重新设置字体（修复换页后字号变小的问题）
                    c.setFont(font_cn, 14)

                    prefix = f"{idx}. {row.zh_hint}："
                    c.drawString(margin_x, y, prefix)

                    # 答题区域或答案 - 横线紧挨冒号，结束点统一
                    prefix_width = c.stringWidth(prefix, font_cn, 14)
                    x_ans = margin_x + prefix_width + 2 * mm
                    draw_fill_line(x_ans, y, line_end_x)
                    y -= 14 * mm  # 短语行间距（略微增加以改善视觉间隔）

            else:
                # 句子部分：只一行横线，横线从题目标号下方开始
                c.setFont(font_cn, 14)
                for idx, row in enumerate(rows, start=1):
                    ensure_space(22)  # 减少所需空间

                    # 中文提示行
                    c.drawString(margin_x, y, f"{idx}. {row.zh_hint}")
                    y -= 8 * mm  # 减少横线和中文提示之间的间隔（从10mm减到8mm）

                    # 只绘制一条横线，从题目标号下方开始
                    draw_fill_line(margin_x, y, line_end_x)
                    y -= 9 * mm  # 句子题目之间的间隔（略微增加以改善视觉间隔）

            y -= 3 * mm  # 各部分之间的间距（减少以压缩）

    # 绘制最后一页的页脚
    draw_footer()

    c.save()
