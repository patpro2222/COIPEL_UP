"""Formatos de presentación (moneda, porcentajes, fechas en español)."""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _vacio(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def mxn(v, simbolo: bool = True) -> str:
    if _vacio(v):
        return ""
    v = round(float(v), 2)
    texto = f"{abs(v):,.2f}"
    if simbolo:
        texto = "$" + texto
    return f"-{texto}" if v < 0 else texto


def pct(v, decimales: int = 1, es_fraccion: bool = False) -> str:
    if _vacio(v):
        return "N/A"
    valor = float(v) * (100 if es_fraccion else 1)
    return f"{valor:,.{decimales}f}%"


def veces(v) -> str:
    return "N/A" if _vacio(v) else f"{float(v):,.2f} x"


def valor_razon(r: dict) -> str:
    if r["formato"] == "moneda":
        return mxn(r["valor"])
    if r["formato"] == "porcentaje":
        return pct(r["valor"], es_fraccion=True)
    return veces(r["valor"])


def fecha_larga(d) -> str:
    d = pd.Timestamp(d).date() if not isinstance(d, date) else d
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_corta(d) -> str:
    return pd.Timestamp(d).strftime("%d/%m/%Y")


def periodo_texto(desde, hasta) -> str:
    return f"Del {fecha_larga(desde)} al {fecha_larga(hasta)}"


def nombre_periodo(periodo: str) -> str:
    anio, mes = periodo.split("-")
    return f"{MESES[int(mes) - 1].capitalize()} {anio}"
