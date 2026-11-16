"""Dashboard ejecutivo: KPIs y gráficas."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from coi import engine
from coi.db import BaseDatos, validar_integridad
from coi.formato import fecha_corta, mxn, nombre_periodo, pct, periodo_texto
from coi.ui import PALETA, PLOTLY_CONFIG, config_plotly, fila_kpis, kpi, selector_periodo


def render(db: BaseDatos) -> None:
    t = db.tablas
    st.title("📊 Dashboard Ejecutivo")
    st.caption(db.datos_empresa()["razon_social"])
    desde, hasta = selector_periodo(t, "dash")

    er = engine.estado_resultados(t, desde, hasta)
    bg = engine.balance_general(t, hasta)
    cuadre = engine.estatus_cuadre(t)
    integridad = validar_integridad(t)
    liquidez = engine.dividir(bg["activo_circulante"], bg["pasivo_cp"])
    cuadrado = cuadre["cuadrado"] and bg["cuadra"] and not integridad
    margen = engine.dividir(er["utilidad_neta"], er["ventas_netas"])

    fila_kpis(
        [
            kpi("Ventas netas", mxn(er["ventas_netas"]), periodo_texto(desde, hasta)),
            kpi(
                "Utilidad neta",
                mxn(er["utilidad_neta"]),
                f"Margen neto {pct(margen, es_fraccion=True)}",
                "ok" if er["utilidad_neta"] >= 0 else "mal",
            ),
            kpi("Total activos", mxn(bg["total_activo"]), f"Al {fecha_corta(hasta)}"),
            kpi(
                "Liquidez circulante",
                "N/A" if liquidez is None else f"{liquidez:,.2f} x",
                "Activo circulante / Pasivo CP",
                "" if liquidez is None else ("ok" if liquidez >= 1.5 else ("alerta" if liquidez >= 1 else "mal")),
            ),
            kpi(
                "Cuadre contable",
                "Cuadrado ✔" if cuadrado else "Descuadre ✖",
                f"Cargos {mxn(cuadre['cargos'])} = Abonos {mxn(cuadre['abonos'])}"
                if cuadre["cuadrado"]
                else f"Diferencia {mxn(cuadre['diferencia'])}; pólizas: {', '.join(cuadre['descuadradas'][:3]) or '—'}",
                "ok" if cuadrado else "mal",
            ),
        ],
        por_fila=5,
    )
    if integridad:
        with st.expander("⚠️ Problemas de integridad detectados", expanded=True):
            for e in integridad:
                st.write("• " + e)

    st.write("")
    izq, der = st.columns(2)

    with izq:
        with st.container(border=True):
            st.subheader("Ingresos vs. costos y gastos")
            serie = engine.serie_mensual(t, desde, hasta)
            if serie.empty:
                st.info("No hay movimientos de resultados en el periodo.")
            else:
                meses = [nombre_periodo(m) for m in serie["mes"]]
                fig = go.Figure()
                fig.add_bar(name="Ventas netas", x=meses, y=serie["Ventas Netas"], marker_color=PALETA[0])
                fig.add_bar(name="Costo de ventas", x=meses, y=serie["Costo de Ventas"], marker_color=PALETA[1])
                fig.add_bar(name="Gastos de operación", x=meses, y=serie["Gastos de Operacion"], marker_color=PALETA[3])
                fig.add_scatter(name="Utilidad neta", x=meses, y=serie["Utilidad Neta"], mode="lines+markers",
                                line=dict(color=PALETA[4], width=3), marker=dict(size=9))
                fig.update_layout(barmode="group")
                st.plotly_chart(config_plotly(fig), use_container_width=True, config=PLOTLY_CONFIG)

    with der:
        with st.container(border=True):
            st.subheader("Presupuestado vs. real")
            periodos = [
                p for p in sorted(t["presupuestos"]["periodo"].unique())
                if p and pd.Timestamp(desde).strftime("%Y-%m") <= p <= pd.Timestamp(hasta).strftime("%Y-%m")
            ]
            pvr = engine.presupuesto_vs_real(t, periodos) if periodos else pd.DataFrame()
            if pvr.empty:
                st.info("No hay presupuestos capturados para los meses del periodo seleccionado.")
            else:
                agg = pvr.groupby(["cuentaCodigo", "nombre"], as_index=False)[["montoPresupuestado", "real"]].sum()
                etiquetas = [n if len(n) <= 22 else n[:21] + "…" for n in agg["nombre"]]
                fig = go.Figure()
                fig.add_bar(name="Presupuestado", y=etiquetas, x=agg["montoPresupuestado"], orientation="h",
                            marker_color=PALETA[1])
                fig.add_bar(name="Real", y=etiquetas, x=agg["real"], orientation="h", marker_color=PALETA[0])
                fig.update_layout(barmode="group")
                fig = config_plotly(fig, alto=max(360, 42 * len(agg)))
                fig.update_xaxes(tickprefix="$", separatethousands=True, gridcolor="#E2E8F0")
                fig.update_yaxes(tickprefix="", autorange="reversed", gridcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

    izq, der = st.columns(2)
    with izq:
        with st.container(border=True):
            st.subheader("Cascada del resultado")
            pasos = [
                ("Ventas netas", er["ventas_netas"], "absolute"),
                ("Costo de ventas", -er["costo_ventas"], "relative"),
                ("Utilidad bruta", er["utilidad_bruta"], "total"),
                ("Gastos de operación", -er["gastos_operacion"], "relative"),
                ("RIF", er["rif"], "relative"),
                ("ISR", -er["impuestos"], "relative"),
                ("Utilidad neta", er["utilidad_neta"], "total"),
            ]
            fig = go.Figure(
                go.Waterfall(
                    x=[p[0] for p in pasos],
                    y=[p[1] for p in pasos],
                    measure=[p[2] for p in pasos],
                    connector=dict(line=dict(color="#CBD5E1")),
                    increasing=dict(marker=dict(color=PALETA[4])),
                    decreasing=dict(marker=dict(color=PALETA[5])),
                    totals=dict(marker=dict(color=PALETA[0])),
                    customdata=[mxn(p[1]) for p in pasos],
                    hovertemplate="%{x}: %{customdata}<extra></extra>",
                )
            )
            fig = config_plotly(fig)
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

    with der:
        with st.container(border=True):
            st.subheader("Estructura financiera")
            fig = go.Figure()
            fig.add_bar(name="Activo circulante", x=["Activo"], y=[bg["activo_circulante"]], marker_color=PALETA[0])
            fig.add_bar(name="Activo no circulante", x=["Activo"], y=[bg["activo_no_circulante"]], marker_color=PALETA[2])
            fig.add_bar(name="Pasivo corto plazo", x=["Pasivo + Capital"], y=[bg["pasivo_cp"]], marker_color=PALETA[5])
            fig.add_bar(name="Pasivo largo plazo", x=["Pasivo + Capital"], y=[bg["pasivo_lp"]], marker_color=PALETA[3])
            fig.add_bar(name="Capital contable", x=["Pasivo + Capital"], y=[bg["total_capital"]], marker_color=PALETA[4])
            fig.update_layout(barmode="stack")
            st.plotly_chart(config_plotly(fig), use_container_width=True, config=PLOTLY_CONFIG)

    with st.container(border=True):
        st.subheader("Últimas pólizas registradas")
        resumen = engine.resumen_polizas(t).sort_values(["fecha", "id"], ascending=False).head(8)
        if resumen.empty:
            st.info("Aún no hay pólizas.")
        else:
            vista = pd.DataFrame(
                {
                    "Póliza": resumen["id"],
                    "Fecha": pd.to_datetime(resumen["fecha"]).dt.strftime("%d/%m/%Y"),
                    "Tipo": resumen["tipo"],
                    "Concepto": resumen["concepto"],
                    "Importe": resumen["cargos"].map(mxn),
                    "Estatus": resumen["cuadrada"].map({True: "✅ Cuadrada", False: "⚠️ Descuadrada"}),
                }
            )
            st.dataframe(vista, hide_index=True, use_container_width=True)
