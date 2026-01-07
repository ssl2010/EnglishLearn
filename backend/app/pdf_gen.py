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
    margin_x = 18 * mm  # 左右边距（保持）
    margin_y = 15 * mm  # 上下边距（减小以节省空间）
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
            c.setFont(font_cn, 22)
            c.drawCentredString(width / 2, y, title)
            y -= 10 * mm  # 标题后间距（减少以压缩）
        else:
            # 非首页：为顶部日期/条码预留空间后直接开始内容
            y -= 14 * mm  # 减少以节省空间

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
        if y < margin_y + min_needed_mm * mm + 15 * mm:  # 为页脚预留空间
            new_page()

    # Rendering helpers
    def draw_fill_line(x0, y0, x1):
        """绘制答题横线"""
        c.setLineWidth(0.5)
        c.line(x0, y0 - 2.5 * mm, x1, y0 - 2.5 * mm)

    # Main body
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
                if show_answers:
                    c.setFont(font_cn, 13)
                    c.drawString(x_ans, y, row.answer_en)
                    c.setFont(font_cn, 14)
                else:
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
                if show_answers:
                    c.setFont(font_cn, 13)
                    c.drawString(x_ans, y, row.answer_en)
                    c.setFont(font_cn, 14)
                else:
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

                # 英文答题/答案行
                if show_answers:
                    c.drawString(margin_x + 5 * mm, y, "英文：")
                    x_ans = margin_x + 23 * mm

                    # 处理长句子换行
                    text = row.answer_en
                    max_chars = 70
                    lines = [text[i : i + max_chars] for i in range(0, len(text), max_chars)] or [""]

                    c.setFont(font_cn, 13)
                    c.drawString(x_ans, y, lines[0])
                    y -= 9 * mm

                    for extra in lines[1:]:
                        ensure_space(14)
                        c.drawString(x_ans, y, extra)
                        y -= 9 * mm

                    c.setFont(font_cn, 14)
                else:
                    # 只绘制一条横线，从题目标号下方开始
                    draw_fill_line(margin_x, y, line_end_x)
                    y -= 9 * mm  # 句子题目之间的间隔（略微增加以改善视觉间隔）

        y -= 3 * mm  # 各部分之间的间距（减少以压缩）

    # 绘制最后一页的页脚
    draw_footer()

    c.save()
