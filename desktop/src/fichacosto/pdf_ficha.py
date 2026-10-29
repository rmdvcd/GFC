"""PDF referencial de la ficha de costos. No constituye certificación normativa.

Datos opcionales del modelo de Anexo I se suministran en:
FichaCosto.extensionData['anexoI'] = {
  'nombreEntidad': str, 'periodoVigencia': str, 'actividadEconomica': str,
  'fechaConfeccion': str,
  'filas': {'2': [linea], '3': [linea], '5': [linea], '6': [linea], '7': [linea], '8': [linea]},
  'margenUtilidad': {'baseAutorizada': str, 'porcentaje': number?, 'importe': {'CUP': number, 'MLC': number}},
  'firmas': {'elaboradoPor': {'nombre': str, 'cargo': str}, ...}
}
Una lista vacía en 'filas' declara cero; una clave ausente queda [PENDIENTE].
Cada linea usa concepto, unidadMedida, cantidad, precioUnitario={valor, moneda}.
"""
from __future__ import annotations

import math
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .dominio import Categoria, FichaCosto, Moneda

# Shared print design constants. Keep these in sync with mobile/lib/data/ficha_costo_pdf.dart.
PAGE_MARGIN = 10 * mm
TITLE_SIZE = 12
SUBTITLE_SIZE = 8
BODY_SIZE = 7
HEADER_FILL = colors.HexColor("#E5E7EB")
GROUP_FILL = colors.HexColor("#F3F4F6")
GRID = colors.HexColor("#6B7280")
INK = colors.HexColor("#111827")
PENDING = "[PENDIENTE]"


def _numero_valido(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


COLUMN_WIDTHS = [34, 265, 78, 50, 170, 188]  # points; sum matches A4 landscape printable width at 10 mm margins.


def _anexo(ficha: FichaCosto) -> dict[str, Any]:
    extension = ficha.extensionData if isinstance(ficha.extensionData, dict) else {}
    raw = extension.get("anexoI", {})
    return raw if isinstance(raw, dict) else {}


def _money(value: float, currency: str) -> str:
    return f"{value:.2f} {currency}"


def _amounts(lines: list[dict[str, Any]]) -> dict[str, float]:
    totals = {m.value: 0.0 for m in Moneda}
    for line in lines:
        amount = line.get("importe")
        if isinstance(amount, dict) and amount.get("moneda") in totals and _numero_valido(amount.get("valor")):
            totals[amount["moneda"]] += float(amount["valor"])
        else:
            price = line.get("precioUnitario")
            if isinstance(price, dict) and price.get("moneda") in totals:
                quantity = line.get("cantidad")
                price_value = price.get("valor")
                if _numero_valido(quantity) and _numero_valido(price_value):
                    totals[price["moneda"]] += float(quantity) * float(price_value)
    return {k: round(v + 1e-9, 2) for k, v in totals.items()}


def _model_lines(ficha: FichaCosto, categoria: Categoria) -> list[dict[str, Any]]:
    return [{
        "concepto": p.descripcion,
        "unidadMedida": p.unidadMedida,
        "cantidad": p.cantidad,
        "precioUnitario": {"valor": p.costoUnitario.valor, "moneda": p.costoUnitario.moneda.value},
        "importe": {"valor": p.subtotal.valor, "moneda": p.subtotal.moneda.value},
    } for p in ficha.partidas if p.categoria == categoria]


def _line_row(no: str, line: dict[str, Any], pending: bool = False) -> list[Any]:
    concept = str(line.get("concepto") or PENDING)
    unit = str(line.get("unidadMedida") or PENDING)
    quantity = line.get("cantidad")
    price = line.get("precioUnitario")
    amount = line.get("importe")
    if pending:
        return [no, concept, unit, PENDING, PENDING, PENDING]
    q = f"{quantity:g}" if _numero_valido(quantity) else PENDING
    if isinstance(price, dict) and price.get("moneda") in ("CUP", "MLC") and _numero_valido(price.get("valor")):
        unit_price = _money(float(price["valor"]), price["moneda"])
    else:
        unit_price = PENDING
    if isinstance(amount, dict) and amount.get("moneda") in ("CUP", "MLC") and _numero_valido(amount.get("valor")):
        total = _money(float(amount["valor"]), amount["moneda"])
    elif isinstance(price, dict) and price.get("moneda") in ("CUP", "MLC") and _numero_valido(quantity) and _numero_valido(price.get("valor")):
        total = _money(float(quantity) * float(price["valor"]), price["moneda"])
    else:
        total = PENDING
    return [no, concept, unit, q, unit_price, total]


def _group_row(number: str, label: str, known: bool, lines: list[dict[str, Any]], subtotals: dict[str, float] | None) -> list[Any]:
    amount = "\n".join(_money(subtotals[m], m) for m in ("CUP", "MLC")) if known and subtotals is not None else PENDING
    return [number, label, "", "", "", amount]


def _pdf_styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=TITLE_SIZE, leading=14, alignment=TA_CENTER, textColor=INK, spaceAfter=3),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=SUBTITLE_SIZE, leading=10, alignment=TA_CENTER, textColor=INK, spaceAfter=8),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=BODY_SIZE, leading=8.2, textColor=INK),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=6.5, leading=7.5, textColor=INK),
        "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=6.7, leading=7.5, alignment=TA_CENTER, textColor=INK),
        "group": ParagraphStyle("group", fontName="Helvetica-Bold", fontSize=7, leading=8, textColor=INK),
        "signature": ParagraphStyle("signature", fontName="Helvetica", fontSize=7, leading=10, textColor=INK),
    }


def _p(value: Any, style: ParagraphStyle) -> Paragraph:
    # Escape user-provided text because ReportLab Paragraph interprets XML-like markup.
    from xml.sax.saxutils import escape
    return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)


def generar_pdf_ficha(ficha: FichaCosto, marca_agua: bool = False) -> bytes:
    """Genera un PDF A4 apaisado y devuelve sus bytes.

    Los datos ajenos al dominio disponible se imprimen como [PENDIENTE], nunca se
    derivan de fórmulas regulatorias no confirmadas.
    """
    buffer = BytesIO()
    page_width, _ = landscape(A4)
    printable = page_width - 2 * PAGE_MARGIN
    widths = [w * printable / sum(COLUMN_WIDTHS) for w in COLUMN_WIDTHS]
    estilos = _pdf_styles()
    anexo = _anexo(ficha)
    filas_anexo = anexo.get("filas", {}) if isinstance(anexo.get("filas", {}), dict) else {}

    def source_for(row_no: str, category: Categoria | None) -> tuple[bool, list[dict[str, Any]]]:
        if row_no in filas_anexo:
            entries = filas_anexo[row_no]
            if isinstance(entries, list) and all(isinstance(x, dict) for x in entries):
                return True, entries
            return False, []
        if category is None:
            return False, []
        entries = _model_lines(ficha, category)
        return (bool(entries), entries)

    sources = {
        "1": source_for("1", Categoria.MATERIAS_PRIMAS_MATERIALES),
        "2": source_for("2", None),
        "3": source_for("3", None),
        "4": source_for("4", Categoria.FUERZA_TRABAJO_DIRECTA),
        "5": source_for("5", Categoria.GASTOS_INDIRECTOS_PRODUCCION),
        "6": source_for("6", None),
        "7": source_for("7", None),
        "8": source_for("8", None),
    }
    other_direct = _model_lines(ficha, Categoria.OTROS_GASTOS_DIRECTOS)
    all_rows_known = all(sources[n][0] for n in map(str, range(1, 9))) and not other_direct
    row_totals = {n: _amounts(lines) for n, (known, lines) in sources.items() if known}
    costs_total = {m: round(sum(row_totals[n][m] for n in map(str, range(1, 9)) if n in row_totals), 2) for m in ("CUP", "MLC")}
    margin = anexo.get("margenUtilidad") if isinstance(anexo.get("margenUtilidad"), dict) else None
    margin_amount = margin.get("importe") if margin else None
    margin_known = bool(margin and str(margin.get("baseAutorizada", "")).strip() and isinstance(margin_amount, dict)
                        and all(_numero_valido(margin_amount.get(m)) for m in ("CUP", "MLC")))
    margin_totals = {m: round(float(margin_amount[m]), 2) for m in ("CUP", "MLC")} if margin_known else None
    price_total = {m: round(costs_total[m] + margin_totals[m], 2) for m in ("CUP", "MLC")} if all_rows_known and margin_known and margin_totals else None

    story: list[Any] = [
        _p("FICHA DE COSTOS Y GASTOS DE PRODUCTOS Y SERVICIOS PARA LA EVALUACIÓN DE PRECIOS Y TARIFAS", estilos["title"]),
        _p("Conforme a la Resolución 148/2023 del Ministerio de Finanzas y Precios · Modelo referencial sujeto a verificación del Anexo I", estilos["subtitle"]),
    ]
    metadata = [
        [_p("Entidad", estilos["group"]), _p(anexo.get("nombreEntidad") or PENDING, estilos["body"]), _p("Código de ficha (UUID)", estilos["group"]), _p(ficha.id or PENDING, estilos["body"])],
        [_p("Fecha de confección", estilos["group"]), _p(anexo.get("fechaConfeccion") or ficha.fechaCreacion or PENDING, estilos["body"]), _p("Período de vigencia", estilos["group"]), _p(anexo.get("periodoVigencia") or PENDING, estilos["body"])],
        [_p("Actividad económica", estilos["group"]), _p(anexo.get("actividadEconomica") or PENDING, estilos["body"]), _p("Producto / servicio", estilos["group"]), _p(ficha.nombre or PENDING, estilos["body"])],
    ]
    mt = Table(metadata, colWidths=[90, printable * 0.36 - 90, 105, printable * 0.64 - 105])
    mt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.35, GRID), ("BACKGROUND", (0, 0), (0, -1), HEADER_FILL), ("BACKGROUND", (2, 0), (2, -1), HEADER_FILL), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [mt, Spacer(1, 8)]

    headings = ["No. de fila", "Concepto / Elemento del Costo", "Unidad de Medida", "Cantidad", "Precio Unitario (CUP/MLC)", "Importe Total (CUP/MLC)"]
    table_data: list[list[Any]] = [[_p(h, estilos["head"]) for h in headings]]
    row_labels = {
        "1": "Materias primas y materiales",
        "2": "Combustibles",
        "3": "Energía",
        "4": "Gastos de fuerza de trabajo (salarios y estimulación, según corresponda)",
        "5": "Gastos indirectos de producción",
        "6": "Gastos generales y de administración",
        "7": "Gastos de distribución y ventas",
        "8": "Gastos bancarios",
    }
    for number in map(str, range(1, 9)):
        known, lines = sources[number]
        group = _group_row(number, row_labels[number], known, lines, row_totals.get(number))
        table_data.append([_p(v, estilos["group"] if i in (0, 1) else estilos["small"]) for i, v in enumerate(group)])
        if known and lines:
            for line in lines:
                table_data.append([_p(v, estilos["small"]) for v in _line_row("", line)])
            if number == "5" and number not in filas_anexo:
                for sublabel in ("Depreciación", "Mantenimiento y reparaciones", "Otros conceptos indirectos"):
                    table_data.append([_p(v, estilos["small"]) for v in ["", f"{sublabel} — {PENDING} (desglose no disponible)", PENDING, PENDING, PENDING, PENDING]])
        elif known:
            table_data.append([_p(v, estilos["small"]) for v in ["", "Sin partidas consignadas", "—", "—", "—", "0.00 CUP\n0.00 MLC"]])
        else:
            if number == "5":
                # Show the missing Annex-I breakdown without attributing values to it.
                for sublabel in ("Depreciación", "Mantenimiento y reparaciones", "Otros conceptos indirectos"):
                    table_data.append([_p(v, estilos["small"]) for v in ["", f"{sublabel} — {PENDING}", PENDING, PENDING, PENDING, PENDING]])
            else:
                table_data.append([_p(v, estilos["small"]) for v in ["", PENDING, PENDING, PENDING, PENDING, PENDING]])

    if other_direct:
        other_totals = _amounts(other_direct)
        # Preserve existing data, but do not misclassify it as an Annex-I row.
        table_data.append([_p(v, estilos["group"] if i in (0, 1) else estilos["small"]) for i, v in enumerate(["—", "Otros gastos directos registrados; pendiente de clasificar en el modelo solicitado", "", "", "", f"{_money(other_totals['CUP'],'CUP')}\n{_money(other_totals['MLC'],'MLC')}"])])

    table_data.append([_p(v, estilos["group"] if i in (0, 1, 5) else estilos["small"]) for i, v in enumerate(["9", "COSTO TOTAL DE PRODUCCIÓN (suma de filas 1 a 8)", "", "", "", f"{_money(costs_total['CUP'],'CUP')}\n{_money(costs_total['MLC'],'MLC')}" if all_rows_known else PENDING])])
    margin_label = "Margen de utilidad sobre base autorizada" + (f": {margin.get('baseAutorizada')}" if margin and margin.get("baseAutorizada") else "")
    margin_unit = f"{margin.get('porcentaje')}%" if margin and isinstance(margin.get("porcentaje"), (float, int)) else PENDING
    table_data.append([_p(v, estilos["group"] if i in (0, 1, 5) else estilos["small"]) for i, v in enumerate(["10", margin_label, "", "", margin_unit, f"{_money(margin_totals['CUP'],'CUP')}\n{_money(margin_totals['MLC'],'MLC')}" if margin_known and margin_totals else PENDING])])
    table_data.append([_p(v, estilos["group"] if i in (0, 1, 5) else estilos["small"]) for i, v in enumerate(["11", "PRECIO O TARIFA TOTAL (costo total + margen)", "", "", "", f"{_money(price_total['CUP'],'CUP')}\n{_money(price_total['MLC'],'MLC')}" if price_total else PENDING])])

    table = LongTable(table_data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    for index in range(1, len(table_data)):
        if table_data[index][0].getPlainText() in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"):
            table.setStyle(TableStyle([("BACKGROUND", (0, index), (-1, index), GROUP_FILL)]))
    story += [table, Spacer(1, 8)]
    if not all_rows_known:
        story.append(_p("Nota: faltan datos o confirmaciones para una o más filas. El costo total y el precio se dejan como [PENDIENTE]; no se presumen como cero.", estilos["small"]))
    if other_direct:
        story.append(_p("Nota: el modelo de datos contiene otros gastos directos sin casilla identificada en la estructura indicada. No se incorporan al subtotal hasta su clasificación.", estilos["small"]))
    story.append(_p("Plantilla referencial generada por FichaCosto. Verificar campos, desglose, base autorizada y metodología contra el texto oficial vigente antes de presentar ante una autoridad.", estilos["small"]))
    story.append(Spacer(1, 12))

    firmas = anexo.get("firmas", {}) if isinstance(anexo.get("firmas", {}), dict) else {}
    signature_cells = []
    for key, label in (("elaboradoPor", "ELABORADO POR"), ("revisadoPor", "REVISADO POR"), ("aprobadoPor", "APROBADO POR")):
        data = firmas.get(key, {}) if isinstance(firmas.get(key, {}), dict) else {}
        signature_cells.append(_p(f"{label}<br/>Nombre: {data.get('nombre') or PENDING}<br/>Cargo: {data.get('cargo') or PENDING}<br/><br/>Firma: __________________________", estilos["signature"]))
    signatures = Table([signature_cells], colWidths=[printable / 3] * 3, rowHeights=[62])
    signatures.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.35, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5)]))
    fecha = anexo.get("fechaConfeccion") or ficha.fechaCreacion or PENDING
    story += [signatures, Spacer(1, 5), _p(f"Fecha de elaboración: {fecha}     Sello de la entidad: [PENDIENTE / SI APLICA]", estilos["small"])]

    def footer(canvas, doc):
        canvas.saveState()
        if marca_agua:
            canvas.translate(page_width / 2, landscape(A4)[1] / 2)
            canvas.rotate(32)
            canvas.setFillColor(colors.Color(0.65, 0.12, 0.12, alpha=0.20))
            canvas.setFont("Helvetica-Bold", 30)
            canvas.drawCentredString(0, 0, "VERSIÓN NO LICENCIADA")
            canvas.restoreState()
            canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(GRID)
        canvas.drawRightString(page_width - PAGE_MARGIN, 5 * mm, f"Ficha {ficha.id} · Página {doc.page}")
        canvas.restoreState()

    pdf = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
                            topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN + 4 * mm, title="Ficha de Costos y Gastos",
                            author="FichaCosto")
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
