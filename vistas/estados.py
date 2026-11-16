"""Estados financieros automáticos: Estado de Resultados y Balance General."""
from __future__ import annotations

import streamlit as st

from coi import engine, exportar
from coi.db import BaseDatos
from coi.engine import RUBROS_ACTIVO, RUBRO_CAPITAL
from coi.formato import fecha_larga, mxn, periodo_texto
from coi.ui import banda, fila_kpis, kpi, selector_periodo, tabla_financiera


@st.cache_data(show_spinner="Generando reportes…", max_entries=20)
def _paquete(_db: BaseDatos, version: int, desde, hasta, formato: str, cuales: tuple[str, ...]) -> bytes:
    """Genera PDF o Excel. ``version`` invalida la caché cuando cambian los datos (incluidos los del admin)."""
    t = _db.tablas
    reportes = []
    if "er" in cuales:
        reportes.append(exportar.reporte_estado_resultados(engine.estado_resultados(t, desde, hasta)))
    if "bg" in cuales:
        reportes.append(exportar.reporte_balance_general(engine.balance_general(t, hasta)))
    empresa = _db.datos_empresa()
    return exportar.generar_pdf(empresa, reportes) if formato == "pdf" else exportar.generar_excel(empresa, reportes)


def _botones(db: BaseDatos, desde, hasta, cuales: tuple[str, ...], nombre: str, clave: str) -> None:
    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇️ Exportar a PDF",
        _paquete(db, db.version, desde, hasta, "pdf", cuales),
        f"{nombre}.pdf",
        mime="application/pdf",
        use_container_width=True,
        key=f"pdf_{clave}",
    )
    c2.download_button(
        "⬇️ Exportar a Excel (.xlsx)",
        _paquete(db, db.version, desde, hasta, "xlsx", cuales),
        f"{nombre}.xlsx",
        use_container_width=True,
        key=f"xlsx_{clave}",
    )


def render(db: BaseDatos) -> None:
    st.title("📑 Estados Financieros")
    t = db.tablas
    empresa = db.datos_empresa()
    desde, hasta = selector_periodo(t, "ef")
    er = engine.estado_resultados(t, desde, hasta)
    bg = engine.balance_general(t, hasta)

    with st.container(border=True):
        st.markdown(f"**Paquete completo de estados financieros** · {empresa['razon_social']}")
        st.caption("Incluye Estado de Resultados y Balance General, con los ajustes hechos en el Panel de administrador.")
        _botones(db, desde, hasta, ("er", "bg"), f"estados_financieros_{hasta:%Y%m%d}", "todo")

    detalle = st.toggle("Mostrar detalle por cuenta", value=True, key="ef_detalle")
    tab_a, tab_b = st.tabs(["A · Estado de Resultados", "B · Balance General"])
    with tab_a:
        _estado_resultados(db, er, desde, hasta, detalle)
    with tab_b:
        _balance_general(db, bg, desde, hasta, detalle)


def _estado_resultados(db: BaseDatos, er: dict, desde, hasta, detalle: bool) -> None:
    st.subheader("Estado de Resultados")
    st.caption(periodo_texto(desde, hasta) + " · Cifras en pesos mexicanos")
    fila_kpis(
        [
            kpi("Ventas netas", mxn(er["ventas_netas"])),
            kpi("Utilidad bruta", mxn(er["utilidad_bruta"])),
            kpi("Utilidad de operación", mxn(er["utilidad_operacion"])),
            kpi("Utilidad neta", mxn(er["utilidad_neta"]), "", "ok" if er["utilidad_neta"] >= 0 else "mal"),
        ],
        por_fila=4,
    )
    st.write("")
    ventas = er["ventas_netas"]
    filas, estilos = [], []
    for linea in er["lineas"]:
        porcentaje = "" if linea["pct"] is None else f"{linea['pct']:,.1f}%"
        filas.append([f"{linea['signo']}  {linea['concepto']}", None, linea["importe"], porcentaje])
        estilos.append({"rubro": "seccion", "subtotal": "sub", "total": "total"}[linea["tipo"]])
        if detalle and linea["tipo"] == "rubro":
            for _, d in er["detalle"][linea["rubro"]].iterrows():
                p = "" if abs(ventas) < 0.005 else f"{d['importe'] / ventas * 100:,.1f}%"
                filas.append([f"{d['codigo']}  {d['nombre']}", d["importe"], None, p])
                estilos.append("detalle")
    tabla_financiera(["Concepto", "Parcial", "Importe", "% s/Ventas"], filas, estilos, {1, 2, 3})
    st.markdown(
        f'<div class="coi-pie">EBITDA: {mxn(er["ebitda"])} (utilidad de operación + depreciaciones de '
        f'{mxn(er["depreciacion"])}). El RIF positivo indica producto financiero neto; negativo, costo neto.</div>',
        unsafe_allow_html=True,
    )
    st.write("")
    _botones(db, desde, hasta, ("er",), f"estado_resultados_{hasta:%Y%m%d}", "er")


def _balance_general(db: BaseDatos, bg: dict, desde, hasta, detalle: bool) -> None:
    st.subheader("Balance General")
    st.caption(f"Al {fecha_larga(hasta)} · Cifras en pesos mexicanos")
    banda(
        bg["cuadra"],
        f"Ecuación Contable Cuadrada (Activo = Pasivo + Capital): {mxn(bg['total_activo'])} = {mxn(bg['pasivo_mas_capital'])}",
        f"Ecuación contable descuadrada: Activo {mxn(bg['total_activo'])} ≠ Pasivo + Capital "
        f"{mxn(bg['pasivo_mas_capital'])} (diferencia {mxn(bg['diferencia'])})",
    )

    def bloque(filas, estilos, rubro, etiqueta=None):
        etiqueta = etiqueta or rubro
        filas.append([etiqueta, None, None])
        estilos.append("grupo")
        sec = bg["secciones"][rubro]
        if detalle:
            for _, d in sec.iterrows():
                filas.append([f"{d['codigo']}  {d['nombre']}", d["importe"], None])
                estilos.append("detalle")
        filas.append([f"Total {etiqueta.lower()}", None, engine.r2(sec["importe"].sum())])
        estilos.append("sub")

    izq, der = st.columns(2)
    with izq:
        filas, estilos = [["ACTIVO", None, None]], ["seccion"]
        for rubro in RUBROS_ACTIVO:
            bloque(filas, estilos, rubro)
        filas.append(["TOTAL ACTIVO", None, bg["total_activo"]])
        estilos.append("total")
        tabla_financiera(["Concepto", "Parcial", "Importe"], filas, estilos, {1, 2})
    with der:
        filas, estilos = [["PASIVO", None, None]], ["seccion"]
        bloque(filas, estilos, "Pasivo Corto Plazo", "Pasivo a Corto Plazo")
        bloque(filas, estilos, "Pasivo Largo Plazo", "Pasivo a Largo Plazo")
        filas.append(["TOTAL PASIVO", None, bg["total_pasivo"]])
        estilos.append("total")
        filas.append(["CAPITAL CONTABLE", None, None])
        estilos.append("seccion")
        for _, d in bg["secciones"][RUBRO_CAPITAL].iterrows():
            filas.append([f"{d['codigo']}  {d['nombre']}", d["importe"], None])
            estilos.append("detalle")
        for extra in bg["capital_resultados"]:
            filas.append([extra["concepto"], extra["importe"], None])
            estilos.append("detalle")
        filas.append(["TOTAL CAPITAL CONTABLE", None, bg["total_capital"]])
        estilos.append("total")
        filas.append(["TOTAL PASIVO + CAPITAL", None, bg["pasivo_mas_capital"]])
        estilos.append("total")
        tabla_financiera(["Concepto", "Parcial", "Importe"], filas, estilos, {1, 2})
    st.markdown(
        '<div class="coi-pie">La utilidad neta del ejercicio proviene del Estado de Resultados del 1 de enero a la '
        "fecha de corte y se integra automáticamente al Capital Contable.</div>",
        unsafe_allow_html=True,
    )
    st.write("")
    _botones(db, desde, hasta, ("bg",), f"balance_general_{hasta:%Y%m%d}", "bg")
