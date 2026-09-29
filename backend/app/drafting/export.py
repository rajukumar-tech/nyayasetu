"""DOCX and PDF export (English and Kannada). PDF uses HarfBuzz shaping (ReportLab 5 +
uharfbuzz) with a font that has Kannada glyphs: NYAYA_KANNADA_FONT, Noto Sans Kannada, or
Windows Nirmala UI."""
from __future__ import annotations

import io
import os
import re
from pathlib import Path

MARK = re.compile(r"[«»]")
FONT_CANDIDATES = [
    os.environ.get("NYAYA_KANNADA_FONT", ""),
    "/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansKannada-Regular.ttf",
    "C:/Windows/Fonts/Nirmala.ttc",
    "C:/Windows/Fonts/Nirmala.ttf",
    "/System/Library/Fonts/Supplemental/Kannada Sangam MN.ttc",
]


def clean(text: str) -> str:
    return MARK.sub("", text)


def to_docx(title: str, paragraphs: list[str], disclaimer: str, language: str) -> bytes:
    import docx
    from docx.shared import Pt
    d = docx.Document()
    style = d.styles["Normal"]
    style.font.size = Pt(12)
    if language == "kn":
        style.font.name = "Nirmala UI"
        style.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cs", "Nirmala UI")
    p = d.add_paragraph(disclaimer)
    p.runs[0].italic = True
    for i, t in enumerate(paragraphs):
        para = d.add_paragraph(clean(t))
        if i < 2:
            para.alignment = 1
            para.runs[0].bold = True
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _font(language: str) -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if language != "kn":
        return "Helvetica"
    for path in FONT_CANDIDATES:
        if path and Path(path).exists():
            if "NyayaKn" not in pdfmetrics.getRegisteredFontNames():
                kw = {"subfontIndex": 0} if path.lower().endswith(".ttc") else {}
                pdfmetrics.registerFont(TTFont("NyayaKn", path, **kw))
            return "NyayaKn"
    raise RuntimeError("No Kannada font found. Install Noto Sans Kannada or set NYAYA_KANNADA_FONT.")


def to_pdf(title: str, paragraphs: list[str], disclaimer: str, language: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape
    font = _font(language)
    body = ParagraphStyle("b", fontName=font, fontSize=11.5, leading=17, spaceAfter=8)
    head = ParagraphStyle("h", parent=body, alignment=1, fontSize=12.5)
    note = ParagraphStyle("n", parent=body, fontSize=9, textColor="#555555")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.5 * cm, rightMargin=2.5 * cm, topMargin=2 * cm,
                            bottomMargin=2 * cm, title=title)
    flow = [Paragraph(escape(disclaimer), note), Spacer(1, 6)]
    for i, t in enumerate(paragraphs):
        flow.append(Paragraph(escape(clean(t)), head if i < 2 else body))
    doc.build(flow)
    return buf.getvalue()
