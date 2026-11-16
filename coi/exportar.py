"""Exportación de reportes contables a PDF (fpdf2) y Excel (openpyxl).

Cada reporte se describe primero con una estructura neutral (encabezados,
filas con valores numéricos, estilo por fila y formato por columna) y luego
se dibuja en PDF o en Excel. Así ambos formatos muestran exactamente lo mismo.
"""
from __future__ import annotations

import io
import math
from datetime import datetime

import pandas as pd
from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from . import __version__
from .engine import RUBROS_ACTIVO, RUBROS_PASIVO, RUBRO_CAPITAL
from .formato import fecha_corta, fecha_larga, mxn, pct, periodo_texto, valor_razon

ANCHO_UTIL = 185.9  # carta vertical con márgenes de 15 mm
AZUL = (30, 58, 138)
PIZARRA = (51, 65, 85)
TINTA = (15, 23, 42)
GRIS = (226, 232, 240)
CEBRA = (248, 250, 252)
AZUL_CLARO = (219, 234, 254)
VERDE = (21, 128, 61)
ROJO = (185, 28, 28)

ETIQUETA_RUBRO = {"Gastos de Operacion": "Gastos de Operación"}


# =============================================================== reportes neutrales
def _reporte(titulo, subtitulo, hoja, encabezados, anchos, formatos, filas, estilos, notas=None, firmas=False, tam=8):
    return {
        "titulo": titulo,
        "subtitulo": subtitulo,
        "hoja": hoja,
        "encabezados": encabezados,
        "anchos": anchos,
        "formatos": formatos,
        "filas": filas,
        "estilos": estilos,
        "notas": notas or [],
        "firmas": firmas,
        "tam": tam,
    }


def reporte_estado_resultados(er: dict) -> dict:
    ventas = er["ventas_netas"]
    filas, estilos = [], []
    for linea in er["lineas"]:
        etiqueta = f"{linea['signo']} {linea['concepto']}"
        if linea["tipo"] == "rubro":
            filas.append([etiqueta, None, linea["importe"], linea["pct"]])
            estilos.append("seccion")
            for _, d in er["detalle"][linea["rubro"]].iterrows():
                porcentaje = d["importe"] / ventas * 100 if abs(ventas) > 0.005 else None
                filas.append([f"      {d['codigo']}  {d['nombre']}", d["importe"], None, porcentaje])
                estilos.append("detalle")
        else:
            filas.append([etiqueta, None, linea["importe"], linea["pct"]])
            estilos.append("total" if linea["tipo"] == "total" else "sub")
    return _reporte(
        "Estado de Resultados",
        periodo_texto(er["desde"], er["hasta"]) + " · Cifras en pesos mexicanos",
        "Estado de Resultados",
        ["Concepto", "Parcial", "Importe", "% s/Ventas"],
        [95, 32, 32, 26.9],
        ["texto", "moneda", "moneda", "pct"],
        filas,
        estilos,
        firmas=True,
    )


def reporte_balance_general(bg: dict) -> dict:
    filas, estilos = [], []

    def agregar(fila, estilo):
        filas.append(fila)
        estilos.append(estilo)

    def bloque(rubro, etiqueta=None):
        agregar([etiqueta or rubro, None, None, None], "grupo")
        for _, d in bg["secciones"][rubro].iterrows():
            agregar([f"      {d['codigo']}  {d['nombre']}", d["importe"], None, None], "detalle")
        total = round(bg["secciones"][rubro]["importe"].sum(), 2)
        agregar([f"Total {(etiqueta or rubro).lower()}", None, total, None], "sub")

    agregar(["ACTIVO", None, None, None], "seccion")
    for rubro in RUBROS_ACTIVO:
        bloque(rubro)
    agregar(["TOTAL ACTIVO", None, None, bg["total_activo"]], "total")

    agregar(["PASIVO", None, None, None], "seccion")
    bloque("Pasivo Corto Plazo", "Pasivo a Corto Plazo")
    bloque("Pasivo Largo Plazo", "Pasivo a Largo Plazo")
    agregar(["TOTAL PASIVO", None, None, bg["total_pasivo"]], "total")

    agregar(["CAPITAL CONTABLE", None, None, None], "seccion")
    agregar(["Capital contribuido y ganado", None, None, None], "grupo")
    for _, d in bg["secciones"][RUBRO_CAPITAL].iterrows():
        agregar([f"      {d['codigo']}  {d['nombre']}", d["importe"], None, None], "detalle")
    for extra in bg["capital_resultados"]:
        agregar([f"      {extra['concepto']}", extra["importe"], None, None], "detalle")
    agregar(["TOTAL CAPITAL CONTABLE", None, None, bg["total_capital"]], "total")
    agregar(["TOTAL PASIVO + CAPITAL CONTABLE", None, None, bg["pasivo_mas_capital"]], "total")

    if bg["cuadra"]:
        nota = (f"Ecuación contable cuadrada: Activo ({mxn(bg['total_activo'])}) = "
                f"Pasivo + Capital ({mxn(bg['pasivo_mas_capital'])})", VERDE)
    else:
        nota = (f"Ecuación contable DESCUADRADA por {mxn(bg['diferencia'])}", ROJO)
    return _reporte(
        "Balance General",
        f"Al {fecha_larga(bg['hasta'])} · Cifras en pesos mexicanos",
        "Balance General",
        ["Concepto", "Parcial", "Subtotal", "Total"],
        [94, 30, 30, 31.9],
        ["texto", "moneda", "moneda", "moneda"],
        filas,
        estilos,
        notas=[nota],
        firmas=True,
    )


def reporte_balanza(df: pd.DataFrame, totales: dict, cuadre: dict, desde, hasta) -> dict:
    filas = [
        [r["codigo"], r["nombre"], r["siDeudor"], r["siAcreedor"], r["cargos"], r["abonos"], r["sfDeudor"], r["sfAcreedor"]]
        for _, r in df.iterrows()
    ]
    estilos = ["normal"] * len(filas)
    filas.append(["", "SUMAS IGUALES", totales["siDeudor"], totales["siAcreedor"], totales["cargos"],
                  totales["abonos"], totales["sfDeudor"], totales["sfAcreedor"]])
    estilos.append("total")
    if cuadre["general"]:
        nota = ("Balanza cuadrada: cargos = abonos y saldos deudores = saldos acreedores.", VERDE)
    else:
        nota = ("Balanza DESCUADRADA: revise las pólizas del periodo.", ROJO)
    return _reporte(
        "Balanza de Comprobación",
        periodo_texto(desde, hasta),
        "Balanza",
        ["Cuenta", "Nombre", "S. Inicial Deudor", "S. Inicial Acreedor", "Cargos", "Abonos", "S. Final Deudor", "S. Final Acreedor"],
        [16, 49.9, 20, 20, 20, 20, 20, 20],
        ["texto", "texto", "numero", "numero", "numero", "numero", "numero", "numero"],
        filas,
        estilos,
        notas=[nota],
        tam=7,
    )


def reporte_cambios_capital(df: pd.DataFrame, desde, hasta) -> dict:
    columnas = list(df.columns)
    ancho_concepto = 52.0
    resto = (ANCHO_UTIL - ancho_concepto) / max(len(columnas), 1)
    filas = [[indice] + [float(v) for v in fila] for indice, fila in zip(df.index, df.values)]
    estilos = ["normal"] * (len(filas) - 1) + ["total"]
    return _reporte(
        "Estado de Cambios en el Capital Contable",
        periodo_texto(desde, hasta),
        "Cambios en el Capital",
        ["Concepto"] + columnas,
        [ancho_concepto] + [resto] * len(columnas),
        ["texto"] + ["moneda"] * len(columnas),
        filas,
        estilos,
        tam=7,
    )


def reporte_razones(razones: list[dict], desde, hasta) -> dict:
    filas = [[r["categoria"], r["razon"], r["formula"], valor_razon(r), r["evaluacion"].split(" ", 1)[-1]] for r in razones]
    return _reporte(
        "Razones Financieras",
        periodo_texto(desde, hasta) + " · Referencias generales de interpretación",
        "Razones Financieras",
        ["Categoría", "Razón", "Fórmula", "Valor", "Evaluación"],
        [24, 40, 72, 25, 24.9],
        ["texto", "texto", "texto", "texto_der", "texto"],
        filas,
        ["normal"] * len(filas),
        tam=7.5,
    )


def reporte_presupuesto(df: pd.DataFrame) -> dict:
    filas = [
        [r["periodo"], r["cuentaCodigo"], r["nombre"], r["montoPresupuestado"], r["real"], r["variacion"],
         None if pd.isna(r["ejecucion"]) else r["ejecucion"], r["estatus"]]
        for _, r in df.iterrows()
    ]
    return _reporte(
        "Control Presupuestal: Presupuestado vs. Real",
        "Periodos: " + (", ".join(sorted(df["periodo"].unique())) if len(df) else "sin datos"),
        "Presupuesto",
        ["Periodo", "Cuenta", "Nombre", "Presupuesto", "Real", "Variación", "% Ejec.", "Estatus"],
        [16, 16, 45, 24, 24, 22, 15, 23.9],
        ["texto", "texto", "texto", "moneda", "moneda", "moneda", "pct", "texto"],
        filas,
        ["normal"] * len(filas),
        tam=7,
    )


def reporte_auxiliar(aux: dict, desde, hasta) -> dict:
    filas = [[None, "", "", "Saldo inicial", "", None, None, aux["saldo_inicial"]]]
    estilos = ["grupo"]
    for _, m in aux["movimientos"].iterrows():
        filas.append([fecha_corta(m["fecha"]), m["polizaId"], m["tipo"], m["concepto"], m["referencia"],
                      m["cargo"], m["abono"], m["saldo"]])
        estilos.append("normal")
    filas.append([None, "", "", "Totales y saldo final", "", aux["total_cargos"], aux["total_abonos"], aux["saldo_final"]])
    estilos.append("total")
    return _reporte(
        f"Auxiliar de la cuenta {aux['cuenta']} {aux['nombre']}",
        periodo_texto(desde, hasta) + f" · Naturaleza {aux['naturaleza']}",
        f"Auxiliar {aux['cuenta']}",
        ["Fecha", "Póliza", "Tipo", "Concepto", "Referencia", "Cargo", "Abono", "Saldo"],
        [17, 16, 14, 50, 28.9, 20, 20, 20],
        ["texto", "texto", "texto", "texto", "texto", "numero", "numero", "numero"],
        filas,
        estilos,
        tam=7,
    )


def reporte_diario(df: pd.DataFrame, desde, hasta) -> dict:
    filas = [[fecha_corta(r["fecha"]), r["polizaId"], r["tipo"], r["cuentaCodigo"], r["nombre"], r["referencia"],
              r["cargo"], r["abono"]] for _, r in df.iterrows()]
    estilos = ["normal"] * len(filas)
    filas.append(["", "", "", "", "TOTALES", "", round(df["cargo"].sum(), 2), round(df["abono"].sum(), 2)])
    estilos.append("total")
    return _reporte(
        "Libro Diario",
        periodo_texto(desde, hasta),
        "Libro Diario",
        ["Fecha", "Póliza", "Tipo", "Cuenta", "Nombre", "Referencia", "Cargo", "Abono"],
        [17, 16, 14, 16, 45, 34, 22, 21.9],
        ["texto", "texto", "texto", "texto", "texto", "texto", "numero", "numero"],
        filas,
        estilos,
        tam=7,
    )


def reporte_catalogo(df: pd.DataFrame) -> dict:
    filas = [[r["codigo"], r["codigoSAT"], r["nombre"], r["naturaleza"], ETIQUETA_RUBRO.get(r["rubro"], r["rubro"]),
              r["saldo"]] for _, r in df.iterrows()]
    return _reporte(
        "Catálogo de Cuentas",
        f"Saldos al {fecha_larga(datetime.now().date())}",
        "Catálogo",
        ["Código", "Cód. SAT", "Nombre", "Naturaleza", "Rubro", "Saldo actual"],
        [18, 18, 62, 20, 40, 27.9],
        ["texto", "texto", "texto", "texto", "texto", "moneda"],
        filas,
        ["normal"] * len(filas),
        tam=7.5,
    )


# ======================================================================== PDF
def _txt(valor) -> str:
    texto = str(valor)
    for origen, destino in {"—": "-", "–": "-", "−": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "•": "-", "…": "...",
                            "·": "-", "≥": ">=", "≤": "<="}.items():
        texto = texto.replace(origen, destino)
    # Las fuentes base del PDF son Latin-1: se descartan emojis y símbolos no representables.
    return texto.encode("latin-1", "ignore").decode("latin-1")


def _formatear(valor, formato: str) -> str:
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return ""
    if formato == "moneda":
        return mxn(valor)
    if formato == "numero":
        return mxn(valor, simbolo=False)
    if formato == "pct":
        return pct(valor)
    return str(valor)


class ReportePDF(FPDF):
    def __init__(self, empresa: dict):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.empresa = empresa
        self.titulo = ""
        self.subtitulo = ""
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(True, margin=18)
        self.alias_nb_pages()
        self.set_title(_txt(f"{empresa.get('razon_social', '')} - Estados financieros"))
        self.set_creator("COI-UP Contabilidad")

    def header(self):
        self.set_fill_color(*AZUL)
        self.rect(0, 0, self.w, 4, "F")
        self.set_y(9)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*AZUL)
        self.cell(0, 6, _txt(self.empresa.get("razon_social", "")), align="C")
        self.ln(5.5)
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(*PIZARRA)
        linea = f"RFC: {self.empresa.get('rfc', '')}"
        if self.empresa.get("domicilio"):
            linea += f"   |   {self.empresa['domicilio']}"
        self.cell(0, 4.5, _txt(linea), align="C")
        self.ln(6)
        self.set_font("Helvetica", "B", 11.5)
        self.set_text_color(*TINTA)
        self.cell(0, 6, _txt(self.titulo), align="C")
        self.ln(5.5)
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(*PIZARRA)
        self.cell(0, 4.5, _txt(self.subtitulo), align="C")
        self.ln(5)
        self.set_draw_color(*AZUL)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_line_width(0.2)
        self.ln(3)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(120, 130, 145)
        self.cell(0, 5, _txt(f"COI-UP Contabilidad v{__version__} - Generado el {datetime.now():%d/%m/%Y %H:%M}"), align="L")
        self.set_x(self.l_margin)
        self.cell(0, 5, f"Página {self.page_no()} de {{nb}}", align="R")

    # ------------------------------------------------------------------ tabla
    def _encabezado_tabla(self, encabezados, anchos, tam):
        self.set_font("Helvetica", "B", tam)
        self.set_fill_color(*AZUL)
        self.set_text_color(255, 255, 255)
        for texto, ancho in zip(encabezados, anchos):
            self.cell(ancho, 7, self._ajustar(_txt(texto), ancho), align="C", fill=True)
        self.ln(7)

    def _ajustar(self, texto: str, ancho: float) -> str:
        if self.get_string_width(texto) <= ancho - 1.5:
            return texto
        while len(texto) > 3 and self.get_string_width(texto + "...") > ancho - 1.5:
            texto = texto[:-1]
        return texto.rstrip() + "..."

    def dibujar(self, rep: dict, nueva_pagina: bool = True):
        self.titulo, self.subtitulo = rep["titulo"], rep["subtitulo"]
        if nueva_pagina:
            self.add_page()
        tam = rep["tam"]
        alto = 5.6 if tam <= 7.5 else 6.2
        anchos = rep["anchos"]
        alineaciones = ["L" if f == "texto" else "R" for f in rep["formatos"]]
        self._encabezado_tabla(rep["encabezados"], anchos, tam)
        for i, (fila, estilo) in enumerate(zip(rep["filas"], rep["estilos"])):
            if self.get_y() + alto > self.page_break_trigger:
                self.add_page()
                self._encabezado_tabla(rep["encabezados"], anchos, tam)
            relleno, borde = False, 0
            if estilo == "seccion":
                self.set_font("Helvetica", "B", tam + 0.5)
                self.set_fill_color(*GRIS)
                self.set_text_color(*AZUL)
                relleno = True
            elif estilo == "grupo":
                self.set_font("Helvetica", "B", tam)
                self.set_text_color(*TINTA)
            elif estilo == "sub":
                self.set_font("Helvetica", "B", tam)
                self.set_text_color(*TINTA)
                borde = "T"
            elif estilo == "total":
                self.set_font("Helvetica", "B", tam + 0.5)
                self.set_fill_color(*AZUL_CLARO)
                self.set_text_color(*TINTA)
                relleno, borde = True, "TB"
            elif estilo == "detalle":
                self.set_font("Helvetica", "", tam)
                self.set_text_color(*PIZARRA)
            else:
                self.set_font("Helvetica", "", tam)
                self.set_text_color(*TINTA)
                if i % 2:
                    self.set_fill_color(*CEBRA)
                    relleno = True
            self.set_draw_color(*PIZARRA)
            for valor, ancho, formato, alin in zip(fila, anchos, rep["formatos"], alineaciones):
                texto = self._ajustar(_txt(_formatear(valor, formato)), ancho)
                self.cell(ancho, alto, texto, border=borde, align=alin, fill=relleno)
            self.ln(alto)
        for texto, color in rep["notas"]:
            self.ln(3)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*color)
            self.multi_cell(0, 5, _txt(texto), align="C")
        if rep["firmas"]:
            self._firmas()

    def _firmas(self):
        if self.get_y() + 32 > self.page_break_trigger:
            self.add_page()
        self.ln(20)
        ancho, hueco = 52, (ANCHO_UTIL - 3 * 52) / 2
        y = self.get_y()
        self.set_draw_color(*PIZARRA)
        self.set_text_color(*PIZARRA)
        self.set_font("Helvetica", "", 8)
        for i, etiqueta in enumerate(["Elaboró", "Revisó", "Autorizó"]):
            x = self.l_margin + i * (ancho + hueco)
            self.line(x, y, x + ancho, y)
            self.set_xy(x, y + 1)
            self.cell(ancho, 5, etiqueta, align="C")
        self.ln(8)


def generar_pdf(empresa: dict, reportes: list[dict]) -> bytes:
    pdf = ReportePDF(empresa)
    for rep in reportes:
        pdf.dibujar(rep)
    return bytes(pdf.output())


# ====================================================================== EXCEL
_FMT_MONEDA = '"$"#,##0.00;[Red]-"$"#,##0.00'
_FMT_NUMERO = "#,##0.00;[Red]-#,##0.00"
_FMT_PCT = "0.0%"
_fino = Side(style="thin", color="64748B")
_doble = Side(style="double", color="1E3A8A")


def _hex(rgb) -> str:
    return "{:02X}{:02X}{:02X}".format(*rgb)


def _hoja(wb: Workbook, empresa: dict, rep: dict, nombres_usados: set[str]):
    nombre = "".join(ch for ch in rep["hoja"] if ch not in '[]:*?/\\')[:31] or "Reporte"
    base, n = nombre, 2
    while nombre in nombres_usados:
        nombre = f"{base[:28]} {n}"
        n += 1
    nombres_usados.add(nombre)
    ws = wb.create_sheet(nombre)
    columnas = len(rep["encabezados"])
    ws.sheet_view.showGridLines = False

    titulos = [
        (empresa.get("razon_social", ""), Font(bold=True, size=14, color=_hex(AZUL))),
        (f"RFC: {empresa.get('rfc', '')}", Font(size=9, color=_hex(PIZARRA))),
        (rep["titulo"], Font(bold=True, size=12, color=_hex(TINTA))),
        (rep["subtitulo"], Font(italic=True, size=9, color=_hex(PIZARRA))),
    ]
    for fila, (texto, fuente) in enumerate(titulos, start=1):
        ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=columnas)
        celda = ws.cell(row=fila, column=1, value=texto)
        celda.font = fuente
        celda.alignment = Alignment(horizontal="center")

    fila_enc = 6
    for j, texto in enumerate(rep["encabezados"], start=1):
        c = ws.cell(row=fila_enc, column=j, value=texto)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=_hex(AZUL))
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[fila_enc].height = 30

    for i, (valores, estilo) in enumerate(zip(rep["filas"], rep["estilos"]), start=fila_enc + 1):
        for j, (valor, formato) in enumerate(zip(valores, rep["formatos"]), start=1):
            if isinstance(valor, float) and math.isnan(valor):
                valor = None
            if formato == "pct" and valor is not None:
                valor = valor / 100
            c = ws.cell(row=i, column=j, value=valor)
            if formato == "moneda":
                c.number_format = _FMT_MONEDA
            elif formato == "numero":
                c.number_format = _FMT_NUMERO
            elif formato == "pct":
                c.number_format = _FMT_PCT
            if formato in ("moneda", "numero", "pct", "texto_der"):
                c.alignment = Alignment(horizontal="right")
            if estilo == "seccion":
                c.font = Font(bold=True, color=_hex(AZUL))
                c.fill = PatternFill("solid", fgColor=_hex(GRIS))
            elif estilo in ("grupo", "sub"):
                c.font = Font(bold=True)
                if estilo == "sub":
                    c.border = Border(top=_fino)
            elif estilo == "total":
                c.font = Font(bold=True)
                c.fill = PatternFill("solid", fgColor=_hex(AZUL_CLARO))
                c.border = Border(top=_fino, bottom=_doble)
            elif estilo == "detalle":
                c.font = Font(color=_hex(PIZARRA))
            elif (i - fila_enc) % 2 == 0:
                c.fill = PatternFill("solid", fgColor=_hex(CEBRA))

    ultima = fila_enc + len(rep["filas"])
    for k, (texto, color) in enumerate(rep["notas"], start=2):
        ws.merge_cells(start_row=ultima + k, start_column=1, end_row=ultima + k, end_column=columnas)
        c = ws.cell(row=ultima + k, column=1, value=texto)
        c.font = Font(bold=True, color=_hex(color))
        c.alignment = Alignment(horizontal="center")

    for j, ancho_mm in enumerate(rep["anchos"], start=1):
        letra = ws.cell(row=fila_enc, column=j).column_letter
        ws.column_dimensions[letra].width = max(10, ancho_mm * 0.62)
    ws.freeze_panes = ws.cell(row=fila_enc + 1, column=1)
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{fila_enc}:{fila_enc}"


def generar_excel(empresa: dict, reportes: list[dict]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    usados: set[str] = set()
    for rep in reportes:
        _hoja(wb, empresa, rep, usados)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
