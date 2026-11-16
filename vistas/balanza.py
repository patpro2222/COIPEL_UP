"""Balanza de comprobación y auxiliares (mayor por cuenta)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from coi import engine, exportar
from coi.db import BaseDatos
from coi.formato import mxn
from coi.ui import banda, estilo_moneda, fila_kpis, kpi, selector_periodo


def render(db: BaseDatos) -> None:
    st.title("⚖️ Balanza de Comprobación y Auxiliares")
    t = db.tablas
    desde, hasta = selector_periodo(t, "bal")
    vista = st.radio("Sección", ["📋 Balanza de comprobación", "📒 Auxiliares de cuentas"], horizontal=True,
                     label_visibility="collapsed", key="bal_vista")
    if vista.startswith("📋"):
        _balanza(db, desde, hasta)
    else:
        _auxiliares(db, desde, hasta)


def _balanza(db: BaseDatos, desde, hasta) -> None:
    t = db.tablas
    c1, c2 = st.columns([1, 1])
    todas = c1.toggle("Mostrar también cuentas sin saldo ni movimientos", value=False)
    estado = c2.selectbox("Filtrar por estado financiero", ["Todas", "Balance General", "Estado de Resultados"])
    df, totales, cuadre = engine.balanza(t, desde, hasta, solo_con_saldo=not todas)
    if estado != "Todas":
        df = df[df["codigo"].isin(t["catalogoCuentas"].loc[t["catalogoCuentas"]["estadoFinanciero"] == estado, "codigo"])]
        totales = {c: engine.r2(df[c].sum()) for c in engine.COLUMNAS_BALANZA}
        st.caption("Con filtro por estado financiero las sumas pueden no ser iguales; quita el filtro para verificar el cuadre.")

    banda(cuadre["general"],
          "Sumas iguales: Cargos = Abonos y Saldos Deudores = Saldos Acreedores.",
          "La balanza NO cuadra: revisa pólizas descuadradas o importes incorrectos.")
    fila_kpis(
        [
            kpi("Movimientos deudores", mxn(totales["cargos"]), "Total de cargos del periodo",
                "ok" if cuadre["movimientos"] else "mal"),
            kpi("Movimientos acreedores", mxn(totales["abonos"]), "Total de abonos del periodo",
                "ok" if cuadre["movimientos"] else "mal"),
            kpi("Saldo deudor", mxn(totales["sfDeudor"]), "Saldo final", "ok" if cuadre["saldos_finales"] else "mal"),
            kpi("Saldo acreedor", mxn(totales["sfAcreedor"]), "Saldo final", "ok" if cuadre["saldos_finales"] else "mal"),
        ],
        por_fila=4,
    )
    st.write("")
    tabla = pd.DataFrame(
        {
            "Código": df["codigo"],
            "Nombre": df["nombre"],
            "Saldo inicial deudor": df["siDeudor"],
            "Saldo inicial acreedor": df["siAcreedor"],
            "Movimientos deudores": df["cargos"],
            "Movimientos acreedores": df["abonos"],
            "Saldo deudor": df["sfDeudor"],
            "Saldo acreedor": df["sfAcreedor"],
        }
    )
    sumas = pd.DataFrame([{
        "Código": "", "Nombre": "SUMAS IGUALES",
        "Saldo inicial deudor": totales["siDeudor"], "Saldo inicial acreedor": totales["siAcreedor"],
        "Movimientos deudores": totales["cargos"], "Movimientos acreedores": totales["abonos"],
        "Saldo deudor": totales["sfDeudor"], "Saldo acreedor": totales["sfAcreedor"],
    }])
    tabla = pd.concat([tabla, sumas], ignore_index=True) if len(tabla) else sumas
    numericas = [c for c in tabla.columns if c not in ("Código", "Nombre")]
    st.dataframe(estilo_moneda(tabla, numericas, fila_total=True), hide_index=True, use_container_width=True,
                 height=min(700, 38 + 35 * len(tabla)))

    empresa = db.datos_empresa()
    rep = exportar.reporte_balanza(df, totales, cuadre, desde, hasta)
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Balanza en PDF", exportar.generar_pdf(empresa, [rep]), "balanza_comprobacion.pdf",
                       mime="application/pdf", use_container_width=True)
    c2.download_button("⬇️ Balanza en Excel", exportar.generar_excel(empresa, [rep]), "balanza_comprobacion.xlsx",
                       use_container_width=True)


def _auxiliares(db: BaseDatos, desde, hasta) -> None:
    t = db.tablas
    saldos = engine.saldos_cuentas(t)
    con_movs = saldos[saldos["movimientos"] > 0]
    base = con_movs if len(con_movs) else saldos
    if base.empty:
        st.info("El catálogo está vacío.")
        return
    opciones = [f"{c} · {n}" for c, n in zip(base["codigo"], base["nombre"])]
    eleccion = st.selectbox("Cuenta", opciones, key=f"aux_cuenta_{db.version}")
    cuenta = eleccion.split(" · ")[0]
    aux = engine.auxiliar(t, cuenta, desde, hasta)

    fila_kpis(
        [
            kpi("Saldo inicial", mxn(aux["saldo_inicial"]), f"Naturaleza {aux['naturaleza']}"),
            kpi("Cargos", mxn(aux["total_cargos"])),
            kpi("Abonos", mxn(aux["total_abonos"])),
            kpi("Saldo final", mxn(aux["saldo_final"]), aux["rubro"].replace("Operacion", "Operación")),
        ],
        por_fila=4,
    )
    st.write("")
    m = aux["movimientos"]
    if m.empty:
        st.info("La cuenta no tiene movimientos en el periodo seleccionado.")
    else:
        tabla = pd.DataFrame(
            {
                "Fecha": m["fecha"].dt.strftime("%d/%m/%Y"),
                "Póliza": m["polizaId"],
                "Tipo": m["tipo"],
                "Concepto": m["concepto"],
                "Referencia": m["referencia"],
                "Cargo": m["cargo"],
                "Abono": m["abono"],
                "Saldo": m["saldo"],
            }
        )
        st.dataframe(estilo_moneda(tabla, ["Cargo", "Abono", "Saldo"]), hide_index=True, use_container_width=True)
    empresa = db.datos_empresa()
    rep = exportar.reporte_auxiliar(aux, desde, hasta)
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Auxiliar en PDF", exportar.generar_pdf(empresa, [rep]), f"auxiliar_{cuenta}.pdf",
                       mime="application/pdf", use_container_width=True)
    c2.download_button("⬇️ Auxiliar en Excel", exportar.generar_excel(empresa, [rep]), f"auxiliar_{cuenta}.xlsx",
                       use_container_width=True)
