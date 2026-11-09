"""Документ «Обоснование начальной (максимальной) цены контракта» (DOCX).

Ничего не считает заново: берёт расчёт методики (procurement.analysis), цены и доказательства из базы
и раскладывает их на странице. Проект — до утверждения; после утверждения документ сохраняется
как доказательство, его sha256 пишется в журнал.
"""

import io
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.table import Table
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..methodology.engine import profile
from ..models import InboundMessage, JournalEntry, Organization, PriceQuote, Procurement, User
from .words import rubles

CHANNEL = {"site": "Сайт продавца", "email": "Коммерческое предложение (письмо)", "eis_contract": "Контракт ЕИС"}
GREY = RGBColor(0x5D, 0x70, 0x69)
MSK = ZoneInfo("Europe/Moscow")  # часовой пояс заказчика (Грозный)


def rub(v: Decimal | str | None) -> str:
    if v is None:
        return "—"
    d = Decimal(str(v)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    whole, frac = f"{d:.2f}".split(".")
    return f"{int(whole):,}".replace(",", " ") + "," + frac


def _font(doc: Any) -> None:
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    st.paragraph_format.space_after = Pt(4)


def _shade(cell: Any, fill: str) -> None:
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc.append(shd)


def _table(doc: Any, header: list[str], rows: list[list[str]], widths: list[float], size: int = 9) -> Table:
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size = True, Pt(size)
        _shade(c, "E7EEF7")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(v)
            run.font.size = Pt(size)
    _fix_widths(t, widths)
    return t


def _fix_widths(t: Table, widths: list[float]) -> None:
    """Фиксированная раскладка: иначе Word и Pages делят ширину поровну."""
    t.autofit = False
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    t._tbl.tblPr.append(layout)
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)


def _kv(doc: Any, pairs: list[tuple[str, str]]) -> None:
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in pairs:
        cells = t.add_row().cells
        cells[0].text, cells[1].text = k, v
        _shade(cells[0], "F2F5F4")
        for c in cells:
            for p in c.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(10)
    _fix_widths(t, [5.5, 20.5])


def _heading(doc: Any, text: str, level: int = 1) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(13 if level == 1 else 11)
    p.paragraph_format.space_before = Pt(10 if level == 1 else 6)


def build(db: Session, proc: Procurement) -> bytes:
    a: dict[str, Any] = proc.analysis or {}
    if not a.get("items"):
        raise ValueError("Расчёт по методике ещё не выполнен")
    org = db.get(Organization, proc.org_id)
    assert org is not None
    p = profile(proc.profile)
    quotes = list(db.scalars(select(PriceQuote).where(PriceQuote.procurement_id == proc.id).order_by(PriceQuote.id)))
    verdicts: dict[str, Any] = a.get("quotes", {})
    approved = db.scalar(
        select(JournalEntry)
        .where(JournalEntry.procurement_id == proc.id, JournalEntry.action == "status",
               JournalEntry.decision == "approved")
        .order_by(JournalEntry.seq.desc()).limit(1)
    )
    approver = db.get(User, approved.actor_user_id) if approved and approved.actor_user_id else None
    head = db.scalar(select(JournalEntry).where(JournalEntry.org_id == proc.org_id)
                     .order_by(JournalEntry.seq.desc()).limit(1))
    decisions = list(db.scalars(select(JournalEntry).where(JournalEntry.procurement_id == proc.id,
                                                           JournalEntry.action == "quote_decision")
                                .order_by(JournalEntry.seq)))

    doc = Document()
    _font(doc)
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(1.8)
    sec.top_margin = sec.bottom_margin = Cm(1.5)

    if approved is None:
        w = doc.add_paragraph()
        wr = w.add_run("ПРОЕКТ — обоснование не утверждено")
        wr.bold, wr.font.color.rgb = True, RGBColor(0xC4, 0x27, 0x27)
        w.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = t.add_run("Обоснование начальной (максимальной) цены контракта")
    tr.bold, tr.font.size = True, Pt(15)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(f"Заявка {proc.number} · расчёт от "
                     f"{datetime.fromisoformat(a['computed_at']).astimezone(MSK):%d.%m.%Y %H:%M} (МСК)")
    sr.font.color.rgb = GREY

    _heading(doc, "1. Общие сведения")
    _kv(doc, [
        ("Заказчик", f"{org.name}, ИНН {org.inn}"),
        ("Объект закупки", "; ".join(f"{i.name} — {i.quantity.normalize():f} {i.unit}".replace(".", ",")
                                     for i in proc.items if i.quantity)),
        ("Метод", f"{p['title']} (ч. 6 ст. 22 Федерального закона № 44-ФЗ — приоритетный метод)"),
        ("Основание", p["source"]),
        ("Требования методики", f"запрос не менее чем {p['min_requests']} поставщикам; не менее {p['min_prices']} "
                                f"цен на позицию; цены не старше {p['max_age_days']} дней; коэффициент вариации "
                                f"не выше {Decimal(p['cv_max']) * 100:.0f} %"),
        ("Сопоставимость", "Все цены приведены к цене за единицу с НДС 22 %. Цены сайтов — розничные, без доставки; "
                           "цены коммерческих предложений — с доставкой до заказчика, если это указано в письме."),
    ])

    _heading(doc, "2. Расчёт по позициям")
    for it in a["items"]:
        item = next(i for i in proc.items if i.id == it["item_id"])
        _heading(doc, f"{it['line_no']}. {it['name']} — {Decimal(it['quantity']).normalize():f} {item.unit}, "
                      f"КТРУ {item.ktru_code}", level=2)
        rows = []
        n = 0
        for q in (x for x in quotes if x.spec_item_id == item.id):
            v = verdicts.get(str(q.id), {})
            used = v.get("admitted", False)
            n += 1
            why = "учтена" if used else "не учтена: " + "; ".join(
                f"{x['code']} {x['reason']}" for x in v.get("verdicts", []) if x["verdict"] in ("deny", "human"))
            where = f"{q.source_name}, {q.region}" if q.region else q.source_name
            rows.append([str(n), where, CHANNEL.get(q.channel, q.channel), f"{q.captured_at:%d.%m.%Y}",
                         rub(q.unit_price), why])
        _table(doc, ["№", "Источник", "Вид", "Дата цены", "Цена за ед., руб. с НДС", "В расчёте"], rows,
               [1.0, 6.5, 4.2, 2.3, 3.2, 8.8])
        cv = f"{it['cv_pct'].replace('.', ',')} %" if it["cv_pct"] else "—"
        f = doc.add_paragraph()
        f.add_run("Средняя арифметическая цена ⟨ц⟩ = Σцᵢ / n = ").font.size = Pt(10)
        b = f.add_run(f"{rub(it['mean'])} руб.")
        b.bold, b.font.size = True, Pt(10)
        f.add_run(f" (n = {it['admitted']}); коэффициент вариации V = σ / ⟨ц⟩ × 100 % = {cv} "
                  f"(σ — по n − 1); НМЦК позиции = v × ⟨ц⟩ = {Decimal(it['quantity']).normalize():f} × "
                  f"{rub(it['mean'])} = ").font.size = Pt(10)
        b2 = f.add_run(f"{rub(it['nmck'])} руб.")
        b2.bold, b2.font.size = True, Pt(10)

    total = Decimal(a["total_nmck"]) if a.get("total_nmck") else None
    _heading(doc, "3. Начальная (максимальная) цена контракта")
    p3 = doc.add_paragraph()
    r3 = p3.add_run(f"НМЦК = {rub(total)} руб." if total is not None else "НМЦК не рассчитана: расчёт не готов")
    r3.bold, r3.font.size = True, Pt(13)
    if total is not None:
        vat = (total - total / Decimal("1.22")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        doc.add_paragraph(f"{rubles(total)}, в том числе НДС 22 % — {rub(vat)} руб.")

    _heading(doc, "4. Источники ценовой информации и доказательства")
    # Один документ — одна строка: письмо поставщика может подтверждать цены нескольких позиций
    line_of = {i.id: i.line_no for i in proc.items}
    received = {m.evidence_sha256: m.received_at for m in db.scalars(
        select(InboundMessage).where(InboundMessage.procurement_id == proc.id))}
    docs: dict[str, dict[str, Any]] = {}
    for q in quotes:
        sha = q.screenshot_sha256 or q.source_sha256 or q.html_sha256 or f"нет-{q.id}"
        got = received.get(q.source_sha256, q.captured_at).astimezone(MSK)
        ref = q.url if q.channel == "site" else f"письмо, получено {got:%d.%m.%Y}"
        d = docs.setdefault(sha, {"source": q.source_name, "lines": [], "ref": ref})
        d["lines"].append(str(line_of.get(q.spec_item_id, "?")))
    src_rows = [[str(n), d["source"], d["ref"] or "—", ", ".join(sorted(set(d["lines"]))),
                 sha if not sha.startswith("нет-") else "—"] for n, (sha, d) in enumerate(docs.items(), start=1)]
    _table(doc, ["№", "Источник", "Документ", "Позиции", "SHA-256 доказательства (снимок страницы / исходное письмо)"],
           src_rows, [1.0, 5.0, 8.5, 1.8, 9.8], size=8)
    note = doc.add_paragraph()
    nr = note.add_run("Файлы доказательств хранятся в системе по указанному хешу; хеш записан в журнал действий с "
                      "цепочкой хешей, поэтому изменение файла после записи обнаруживается.")
    nr.font.size, nr.font.color.rgb = Pt(9), GREY

    if decisions:
        _heading(doc, "5. Решения ответственного лица по ценам")
        rows = []
        for d in decisions:
            who = db.get(User, d.actor_user_id) if d.actor_user_id else None
            act = {"exclude": "исключена", "include": "допущена", "clear": "решение отменено"}.get(d.decision or "", "")
            rows.append([f"{d.created_at.astimezone(MSK):%d.%m.%Y %H:%M}", who.full_name if who else "—",
                         f"{d.details.get('source')}, {rub(d.details.get('price'))} руб. — {act}",
                         str(d.details.get("reason", ""))])
        _table(doc, ["Когда", "Кто", "Цена", "Причина"], rows, [3.0, 5.0, 8.0, 10.0])

    _heading(doc, "6. Соблюдение требований методики")
    checks = [f"{g['code']}: {g['reason']}" for g in a.get("general", [])]
    for i in a["items"]:
        state = "соответствует (М-02, М-07)" if i["ok"] else "; ".join(v["reason"] for v in i["verdicts"])
        checks.append(f"Позиция {i['line_no']}: {state}")
    for c in checks:
        doc.add_paragraph(c, style="List Bullet")

    doc.add_paragraph()
    sign = doc.add_paragraph()
    if approved is not None:
        sign.add_run(f"Утверждено: {approver.full_name if approver else '—'}, контрактный управляющий, "
                     f"{approved.created_at.astimezone(MSK):%d.%m.%Y %H:%M} МСК (запись журнала № {approved.seq})."
                     ).bold = True
    else:
        sign.add_run("Контрактный управляющий: ____________________ / ____________________ / «___» ________ 2026 г.")
    tail = doc.add_paragraph()
    tr2 = tail.add_run(
        "Документ подготовлен ИИ-агентом «Снабженец». Поиск и разбор источников выполнены с помощью языковой модели; "
        "цены, их проверки по методике и расчёт выполнены программным кодом. "
        f"Журнал действий: запись № {head.seq if head else '—'}, хеш {head.hash[:16] if head else '—'}…; "
        f"сформировано {datetime.now(UTC).astimezone(MSK):%d.%m.%Y %H:%M} МСК.")
    tr2.font.size, tr2.font.color.rgb = Pt(8), GREY

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
