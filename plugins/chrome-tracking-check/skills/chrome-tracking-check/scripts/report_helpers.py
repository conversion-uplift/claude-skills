#!/usr/bin/env python3
"""Shared python-docx helpers for the Chrome Tracking Check report.

Plain, unbranded styling with direct formatting, so the report renders the same
in Word, LibreOffice and Google Docs without relying on template styles. Pass
your own .docx to build_report.py with --template if you want your letterhead:
its header, footer and page setup are kept and only the body is replaced.
"""

from __future__ import annotations
import subprocess, sys
from pathlib import Path

FONT = "Arial"
BRAND_DARK = (0x1F, 0x29, 0x37)     # body and headings
BRAND_ORANGE = (0x1D, 0x4E, 0xD8)   # accent (blue); name kept for compatibility
BRAND_GREY = (0x6B, 0x72, 0x80)     # secondary text
BRAND_RED = (0xB9, 0x1C, 0x1C)      # Critical
TINT_FILL = "EEF2F7"
INK_FILL = "1F2937"

def _ensure_python_docx():
    try:
        import docx  # noqa: F401
        return True
    except ImportError:
        pass
    for extra in ([], ["--user"], ["--break-system-packages"]):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install",
                                   "python-docx", "--quiet", *extra],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import docx  # noqa: F401
            return True
        except Exception:
            continue
    sys.stderr.write("Could not install python-docx. Fix: `pip install python-docx` "
                     "and re-run.\n")
    return False

# ---------------------------------------------------------------------------
# Low-level helpers (no reliance on template styles — the reference template
# has no Normal/Heading/List styles, so everything is direct formatting)
# ---------------------------------------------------------------------------

def _run(para, text, bold=False, italic=False, size=11, color=None):
    from docx.shared import Pt, RGBColor
    r = para.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.name = FONT
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGBColor(*color)
    return r


def _p(doc, text="", bold=False, italic=False, size=11, color=None,
       align=None, space_after=6, space_before=0):
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(space_after)
    para.paragraph_format.space_before = Pt(space_before)
    if align == "center":
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if text:
        _run(para, text, bold=bold, italic=italic, size=size, color=color)
    return para


def _h1(doc, text):
    return _p(doc, text, bold=True, size=15, color=BRAND_DARK,
              space_before=15, space_after=7)


def _h2(doc, text, color=None):
    return _p(doc, text, bold=True, size=12.5, color=color or BRAND_ORANGE,
              space_before=11, space_after=4.5)


def _bullet(doc, lead=None, text="", size=11, bold_all=False):
    """Bulleted paragraph with optional bold lead-in (reference-report style)."""
    from docx.shared import Pt
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(3.5)
    para.paragraph_format.left_indent = Pt(18)
    _run(para, "•  ", size=size)
    if lead:
        _run(para, lead + " ", bold=True, size=size)
    if text:
        _run(para, text, bold=bold_all, size=size)
    return para


def _bullets(doc, items, size=11):
    for it in items:
        if isinstance(it, (list, tuple)) and len(it) == 2:
            _bullet(doc, lead=it[0], text=it[1], size=size)
        else:
            _bullet(doc, text=str(it), size=size)


def _labelled(doc, label, text, size=11):
    """Run-in bold label paragraph: 'Why it matters: xxx'."""
    from docx.shared import Pt
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(6)
    _run(para, label, bold=True, size=size)
    _run(para, " " + text, size=size)
    return para


def _set_table_borders(table):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tbl = table._tbl
    tblPr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), "CCCCCC")
        borders.append(el)
    tblPr.append(borders)


def _tight_margins(t):
    from docx.oxml.ns import qn as _qn
    from docx.oxml import OxmlElement as _OE
    tblPr = t._tbl.tblPr
    mar = _OE("w:tblCellMar")
    for edge, w in (("left", "10"), ("right", "10")):
        el = _OE(f"w:{edge}")
        el.set(_qn("w:w"), w); el.set(_qn("w:type"), "dxa")
        mar.append(el)
    tblPr.append(mar)


def _shade_cell(cell, fill):
    from docx.oxml.ns import qn as _qn
    from docx.oxml import OxmlElement as _OE
    shd = _OE("w:shd"); shd.set(_qn("w:val"), "clear")
    shd.set(_qn("w:color"), "auto"); shd.set(_qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _table(doc, headers, rows, size=10.5, variant="ink", body_size=None):
    """Benchmark-style table: ink (262223) header fill with white 10.5pt text,
    or 'tint' variant (FBF4EF fill, ink text) for the at-a-glance strip.
    Compact 10-dxa side cell margins; 1pt paragraph spacing in cells."""
    from docx.shared import Pt
    t = doc.add_table(rows=1, cols=max(1, len(headers)))
    _set_table_borders(t)
    _tight_margins(t)
    hdr_color = (0xFF, 0xFF, 0xFF) if variant == "ink" else BRAND_DARK
    fill = INK_FILL if variant == "ink" else TINT_FILL
    for i, htxt in enumerate(headers):
        cell = t.rows[0].cells[i]
        _shade_cell(cell, fill)
        cell.paragraphs[0].paragraph_format.space_after = Pt(1)
        _run(cell.paragraphs[0], str(htxt), bold=True, size=size,
             color=hdr_color)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row[:len(headers)]):
            cells[i].paragraphs[0].paragraph_format.space_after = Pt(1)
            _run(cells[i].paragraphs[0], "" if val is None else str(val),
                 size=body_size or size)
    return t


def _kv_table(doc, pairs, size=10):
    return _table(doc, [pairs[0][0], pairs[0][1]],
                  [[k, v] for k, v in pairs[1:]], size=size) if pairs else None


def _callout(doc, title, body):
    from docx.shared import Pt
    t = doc.add_table(rows=1, cols=1)
    _set_table_borders(t)
    _tight_margins(t)
    cell = t.rows[0].cells[0]
    _shade_cell(cell, TINT_FILL)
    para = cell.paragraphs[0]
    para.paragraph_format.space_after = Pt(2)
    _run(para, title, bold=True, size=12, color=BRAND_ORANGE)
    body_p = cell.add_paragraph()
    body_p.paragraph_format.space_after = Pt(1)
    _run(body_p, body, size=10.5)
    _p(doc, "", space_after=2)
    return t


def _hyperlink(para, text, url, size=11, bold=False, color=None):
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    part = para.part
    r_id = part.relate_to(
        url, "http://schemas.openxmlformats.org/officeDocument/2006/"
             "relationships/hyperlink", is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), r_id)
    r = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    for a in ("w:ascii", "w:hAnsi", "w:cs"):
        fonts.set(qn(a), FONT)
    rPr.append(fonts)
    if bold:
        rPr.append(OxmlElement("w:b"))
    sz = OxmlElement("w:sz"); sz.set(qn("w:val"), str(int(size * 2)))
    rPr.append(sz)
    c = OxmlElement("w:color")
    c.set(qn("w:val"), "%02X%02X%02X" % (color or BRAND_ORANGE))
    rPr.append(c)
    u = OxmlElement("w:u"); u.set(qn("w:val"), "single")
    rPr.append(u)
    r.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    h.append(r)
    para._p.append(h)
    return h


def _page_break(doc):
    from docx.enum.text import WD_BREAK
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)




def _open_document(template_path=None, audit_date=None):
    """Open the user's own template (body cleared) or a blank document."""
    from docx import Document
    if template_path and Path(template_path).is_file():
        doc = Document(str(template_path))
        body = doc.element.body
        for child in list(body):
            if not child.tag.endswith("}sectPr"):
                body.remove(child)
        return doc, True
    doc = Document()
    from docx.shared import Cm
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2)
        s.top_margin = s.bottom_margin = Cm(2)
    return doc, False
