"""Control presupuestal: presupuestado vs. real con semáforo."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from coi import engine, exportar
from coi.db import BaseDatos, IntegridadError
from coi.formato import MESES, mxn, nombre_periodo
from coi.ui import PALETA, PLOTLY_CONFIG, avisar, config_plotly, fila_kpis, kpi, md, mostrar_aviso


def render(db: BaseDatos) -> None:
    st.title("🎯 Control Presupuestal")
    mostrar_aviso()
    vista = st.radio("Sección", ["📈 Seguimiento", "🛠️ Capturar presupuesto"], horizontal=True,
                     label_visibility="collapsed", key="pre_vista")
    if vista.startswith("📈"):
        _seguimiento(db)
    else:
        _captura(db)


def _seguimiento(db: BaseDatos) -> None:
    t = db.tablas
    periodos = sorted(p for p in t["presupuestos"]["periodo"].unique() if p)
    if not periodos:
        st.info("Aún no hay presupuestos. Captúralos en la sección «Capturar presupuesto».")
        return
    _, ultimo = engine.rango_datos(t)
    predeterminado = ultimo.strftime("%Y-%m")
    seleccion = st.multiselect(
        "Periodos a analizar",
        periodos,
        default=[predeterminado] if predeterminado in periodos else periodos[:1],
        format_func=nombre_periodo,
        key=f"pre_periodos_{db.version}",
    )
    if not seleccion:
        st.warning("Selecciona al menos un periodo.")
        return
    df = engine.presupuesto_vs_real(t, seleccion)

    ingresos = df[df["tipo"] == "Ingreso"]
    gastos = df[df["tipo"] == "Gasto"]
    ejec_gastos = engine.dividir(gastos["real"].sum(), gastos["montoPresupuestado"].sum())
    ejec_ingresos = engine.dividir(ingresos["real"].sum(), ingresos["montoPresupuestado"].sum())
    sobregiros = int((df["estatus"] == "Sobregiro").sum())
    fila_kpis(
        [
            kpi("Ingresos: meta vs. real", f"{mxn(ingresos['real'].sum())}",
                f"Meta {mxn(ingresos['montoPresupuestado'].sum())} · "
                + ("N/A" if ejec_ingresos is None else f"{ejec_ingresos * 100:,.1f}% de la meta"),
                "" if ejec_ingresos is None else ("ok" if ejec_ingresos >= 1 else "alerta" if ejec_ingresos >= .9 else "mal")),
            kpi("Gastos: ejercido", f"{mxn(gastos['real'].sum())}",
                f"Presupuesto {mxn(gastos['montoPresupuestado'].sum())} · "
                + ("N/A" if ejec_gastos is None else f"{ejec_gastos * 100:,.1f}% ejercido"),
                "" if ejec_gastos is None else ("mal" if ejec_gastos > 1 else "alerta" if ejec_gastos >= .9 else "ok")),
            kpi("Partidas en sobregiro", f"{sobregiros}", "Gasto real mayor al presupuesto",
                "mal" if sobregiros else "ok"),
        ],
        por_fila=3,
    )
    st.write("")

    tabla = pd.DataFrame(
        {
            "Semáforo": df["semaforo"],
            "Periodo": df["periodo"].map(nombre_periodo),
            "Cuenta": df["cuentaCodigo"],
            "Nombre": df["nombre"],
            "Tipo": df["tipo"],
            "Presupuestado": df["montoPresupuestado"],
            "Real ejercido": df["real"],
            "Variación $": df["variacion"],
            "% Ejecución": df["ejecucion"],
            "Estatus": df["estatus"],
        }
    )
    st.dataframe(
        tabla.style.format({c: mxn for c in ["Presupuestado", "Real ejercido", "Variación $"]}),
        hide_index=True,
        use_container_width=True,
        column_config={
            "% Ejecución": st.column_config.ProgressColumn(
                "% Ejecución", min_value=0, max_value=150, format="%.1f%%",
                help="Real / Presupuestado × 100. La barra llega a 150%.",
            )
        },
    )
    st.caption(
        "Semáforo — Ingresos: 🟢 ≥ 100% de la meta · 🟡 90–99% · 🔴 < 90%.  "
        "Gastos: 🟢 < 90% · 🟡 90–100% · 🔴 > 100% (sobregiro)."
    )

    with st.container(border=True):
        st.subheader("Presupuestado vs. real por cuenta")
        agg = df.groupby(["cuentaCodigo", "nombre"], as_index=False)[["montoPresupuestado", "real"]].sum()
        etiquetas = [f"{c} {n}" for c, n in zip(agg["cuentaCodigo"], agg["nombre"])]
        fig = go.Figure()
        fig.add_bar(name="Presupuestado", x=etiquetas, y=agg["montoPresupuestado"], marker_color=PALETA[1])
        fig.add_bar(name="Real ejercido", x=etiquetas, y=agg["real"], marker_color=PALETA[0])
        fig.update_layout(barmode="group")
        st.plotly_chart(config_plotly(fig, alto=400), use_container_width=True, config=PLOTLY_CONFIG)

    empresa = db.datos_empresa()
    rep = exportar.reporte_presupuesto(df)
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Control presupuestal en PDF", exportar.generar_pdf(empresa, [rep]),
                       "control_presupuestal.pdf", mime="application/pdf", use_container_width=True)
    c2.download_button("⬇️ Control presupuestal en Excel", exportar.generar_excel(empresa, [rep]),
                       "control_presupuestal.xlsx", use_container_width=True)


def _selector_mes(etiqueta: str, clave: str, por_defecto: date) -> str:
    c1, c2 = st.columns(2)
    anios = list(range(por_defecto.year - 3, por_defecto.year + 4))
    anio = c1.selectbox(f"{etiqueta}: año", anios, index=anios.index(por_defecto.year), key=f"{clave}_anio")
    mes = c2.selectbox(f"{etiqueta}: mes", list(range(1, 13)), index=por_defecto.month - 1,
                       format_func=lambda m: MESES[m - 1].capitalize(), key=f"{clave}_mes")
    return f"{anio}-{mes:02d}"


def _captura(db: BaseDatos) -> None:
    t = db.tablas
    cat = t["catalogoCuentas"]
    _, ultimo = engine.rango_datos(t)

    with st.container(border=True):
        st.markdown("**Alta o actualización de un presupuesto mensual**")
        cuentas = [f"{c} · {n}" for c, n in zip(cat["codigo"], cat["nombre"])]
        er = cat[cat["estadoFinanciero"] == "Estado de Resultados"]
        indice = cuentas.index(f"{er['codigo'].iloc[0]} · {er['nombre'].iloc[0]}") if len(er) else 0
        cuenta = st.selectbox("Cuenta", cuentas, index=indice, key="pre_cuenta")
        periodo = _selector_mes("Periodo", "pre_alta", ultimo)
        codigo = cuenta.split(" · ")[0]
        actual = t["presupuestos"]
        existente = actual[(actual["cuentaCodigo"] == codigo) & (actual["periodo"] == periodo)]
        valor = float(existente["montoPresupuestado"].iloc[0]) if len(existente) else 0.0
        monto = st.number_input("Monto presupuestado ($)", min_value=0.0, value=valor, step=1000.0, format="%.2f",
                                key=f"pre_monto_{codigo}_{periodo}")
        if len(existente):
            st.caption(md(f"Ya existe un presupuesto de {mxn(valor)} para esta cuenta y periodo; se actualizará."))
        if st.button("💾 Guardar presupuesto", type="primary", use_container_width=True):
            try:
                pid = db.guardar_presupuesto(codigo, periodo, monto)
                avisar("success", f"Presupuesto {pid} guardado: {codigo} · {nombre_periodo(periodo)} · {mxn(monto)}.")
                st.rerun()
            except IntegridadError as exc:
                st.error(str(exc))

    periodos = sorted(p for p in t["presupuestos"]["periodo"].unique() if p)
    with st.container(border=True):
        st.markdown("**Copiar presupuesto de un mes a otro**")
        if not periodos:
            st.caption("No hay periodos para copiar.")
        else:
            origen = st.selectbox("Periodo origen", periodos, format_func=nombre_periodo, key="pre_origen")
            siguiente = (pd.Timestamp(f"{periodos[-1]}-01") + pd.offsets.MonthBegin(1)).date()
            destino = _selector_mes("Destino", "pre_destino", siguiente)
            factor = st.number_input("Ajuste (%) sobre el origen", value=0.0, step=1.0, format="%.1f",
                                     help="Ej. 5 = incrementar 5%; -10 = reducir 10%.")
            if st.button("📋 Copiar presupuesto", use_container_width=True):
                try:
                    n = db.copiar_presupuesto(origen, destino, 1 + factor / 100)
                    avisar("success", f"Se copiaron {n} partida(s) de {nombre_periodo(origen)} a {nombre_periodo(destino)}.")
                    st.rerun()
                except IntegridadError as exc:
                    st.error(str(exc))

    with st.container(border=True):
        st.markdown("**Presupuestos registrados**")
        pres = t["presupuestos"].merge(cat[["codigo", "nombre"]], left_on="cuentaCodigo", right_on="codigo", how="left")
        if pres.empty:
            st.caption("Sin registros.")
            return
        vista = pd.DataFrame(
            {"ID": pres["id"], "Periodo": pres["periodo"].map(nombre_periodo), "Cuenta": pres["cuentaCodigo"],
             "Nombre": pres["nombre"], "Monto": pres["montoPresupuestado"]}
        )
        st.dataframe(vista.style.format({"Monto": mxn}), hide_index=True, use_container_width=True)
        borrar = st.selectbox(
            "Eliminar presupuesto",
            pres["id"].tolist(),
            index=None,
            placeholder="Selecciona un ID…",
            format_func=lambda i: f"{i} · {pres.set_index('id').loc[i, 'cuentaCodigo']} · "
                                  f"{nombre_periodo(pres.set_index('id').loc[i, 'periodo'])}",
            key=f"pre_borrar_{db.version}",
        )
        if st.button("🗑️ Eliminar seleccionado", disabled=borrar is None, use_container_width=True):
            db.eliminar_presupuesto(borrar)
            avisar("success", f"Presupuesto {borrar} eliminado.")
            st.rerun()
