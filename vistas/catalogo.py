"""Catálogo de cuentas: consulta, alta, edición y baja."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from coi import engine, exportar
from coi.db import NATURALEZA_SUGERIDA, NATURALEZAS, RUBROS, BaseDatos, IntegridadError, estado_de_rubro
from coi.formato import mxn
from coi.ui import avisar, fila_kpis, kpi, md, mostrar_aviso

ETIQUETA = {"Gastos de Operacion": "Gastos de Operación"}


def _etiqueta_rubro(r: str) -> str:
    return ETIQUETA.get(r, r)


def render(db: BaseDatos) -> None:
    st.title("🗂️ Catálogo de Cuentas")
    mostrar_aviso()
    t = db.tablas
    saldos = engine.saldos_cuentas(t)

    fila_kpis(
        [
            kpi("Cuentas registradas", f"{len(saldos):,}"),
            kpi("Deudoras", f"{(saldos['naturaleza'] == 'Deudora').sum():,}"),
            kpi("Acreedoras", f"{(saldos['naturaleza'] == 'Acreedora').sum():,}"),
            kpi("Con movimientos", f"{(saldos['movimientos'] > 0).sum():,}"),
        ],
        por_fila=4,
    )
    st.write("")
    vista = st.radio("Sección", ["🔎 Consulta", "➕ Alta de cuenta", "✏️ Editar / eliminar"], horizontal=True,
                     label_visibility="collapsed", key="cat_vista")

    if vista == "🔎 Consulta":
        _consulta(db, saldos)
    elif vista == "➕ Alta de cuenta":
        _alta(db)
    else:
        _edicion(db, saldos)


def _consulta(db: BaseDatos, saldos: pd.DataFrame) -> None:
    c1, c2, c3 = st.columns([2, 1.4, 1])
    texto = c1.text_input("Buscar", placeholder="Código, código SAT o nombre…")
    rubros = c2.multiselect("Rubro", RUBROS, format_func=_etiqueta_rubro)
    naturalezas = c3.multiselect("Naturaleza", NATURALEZAS)
    df = saldos.copy()
    if texto:
        patron = texto.strip().lower()
        mascara = (
            df["codigo"].str.lower().str.contains(patron, regex=False)
            | df["codigoSAT"].str.lower().str.contains(patron, regex=False)
            | df["nombre"].str.lower().str.contains(patron, regex=False)
        )
        df = df[mascara]
    if rubros:
        df = df[df["rubro"].isin(rubros)]
    if naturalezas:
        df = df[df["naturaleza"].isin(naturalezas)]

    tabla = pd.DataFrame(
        {
            "Código": df["codigo"],
            "Cód. SAT": df["codigoSAT"],
            "Nombre": df["nombre"],
            "Nombre en estados": df["nombreEstado"],
            "Naturaleza": df["naturaleza"],
            "Estado financiero": df["estadoFinanciero"],
            "Rubro": df["rubro"].map(_etiqueta_rubro),
            "Cargos": df["cargos"],
            "Abonos": df["abonos"],
            "Saldo actual": df["saldo"],
        }
    )
    st.dataframe(
        tabla.style.format({c: mxn for c in ["Cargos", "Abonos", "Saldo actual"]}),
        hide_index=True,
        use_container_width=True,
        height=min(640, 38 + 35 * max(len(tabla), 1)),
    )
    st.caption(
        f"{len(tabla)} cuenta(s). Saldo actual = Cargos − Abonos (deudoras) o Abonos − Cargos (acreedoras), "
        "considerando todas las pólizas registradas."
    )
    empresa = db.datos_empresa()
    rep = exportar.reporte_catalogo(df)
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Catálogo en Excel", exportar.generar_excel(empresa, [rep]), "catalogo_cuentas.xlsx",
                       use_container_width=True)
    c2.download_button("⬇️ Catálogo en PDF", exportar.generar_pdf(empresa, [rep]), "catalogo_cuentas.pdf",
                       mime="application/pdf", use_container_width=True)


def _alta(db: BaseDatos) -> None:
    rubro = st.selectbox("Rubro", RUBROS, format_func=_etiqueta_rubro, key="alta_rubro")
    sugerido = db.sugerir_codigo(rubro)
    st.caption(
        f"Estado financiero: **{estado_de_rubro(rubro)}** · Naturaleza sugerida: **{NATURALEZA_SUGERIDA[rubro]}** · "
        f"Siguiente código libre sugerido: **{sugerido}**"
    )
    with st.form("form_alta_cuenta", clear_on_submit=True):
        c1, c2 = st.columns(2)
        codigo = c1.text_input("Código interno *", value=sugerido, help="Formato 000-00 o 000-00-000. Es la llave primaria.")
        codigo_sat = c2.text_input("Código agrupador SAT", placeholder="Ej. 102.01")
        nombre = st.text_input("Nombre de la cuenta *", placeholder="Ej. Bancos Nacionales")
        naturaleza = st.radio("Naturaleza *", NATURALEZAS, index=NATURALEZAS.index(NATURALEZA_SUGERIDA[rubro]),
                              horizontal=True)
        enviado = st.form_submit_button("Guardar cuenta", type="primary", use_container_width=True)
    if enviado:
        try:
            db.agregar_cuenta(codigo, codigo_sat, nombre, naturaleza, rubro)
            avisar("success", f"Cuenta {codigo.strip()} · {nombre.strip()} dada de alta correctamente.")
            st.rerun()
        except IntegridadError as exc:
            st.error(str(exc))


def _edicion(db: BaseDatos, saldos: pd.DataFrame) -> None:
    if saldos.empty:
        st.info("El catálogo está vacío.")
        return
    opciones = [f"{c} · {n}" for c, n in zip(saldos["codigo"], saldos["nombre"])]
    eleccion = st.selectbox("Cuenta a modificar", opciones, key=f"edit_cuenta_{db.version}")
    codigo = eleccion.split(" · ")[0]
    fila = saldos[saldos["codigo"] == codigo].iloc[0]
    st.caption(md(f"Movimientos registrados: **{fila['movimientos']}** · Saldo actual: **{mxn(fila['saldo'])}**"))

    with st.form(f"form_editar_{codigo}"):
        c1, c2 = st.columns(2)
        c1.text_input("Código (llave primaria, no editable)", value=codigo, disabled=True)
        codigo_sat = c2.text_input("Código agrupador SAT", value=fila["codigoSAT"])
        nombre = st.text_input("Nombre de la cuenta", value=fila["nombre"])
        c3, c4 = st.columns(2)
        naturaleza = c3.radio("Naturaleza", NATURALEZAS, index=NATURALEZAS.index(fila["naturaleza"]), horizontal=True)
        rubro = c4.selectbox("Rubro", RUBROS, index=RUBROS.index(fila["rubro"]), format_func=_etiqueta_rubro)
        guardar = st.form_submit_button("Guardar cambios", type="primary", use_container_width=True)
    if guardar:
        try:
            db.actualizar_cuenta(codigo, codigo_sat, nombre, naturaleza, rubro)
            avisar("success", f"Cuenta {codigo} actualizada.")
            st.rerun()
        except IntegridadError as exc:
            st.error(str(exc))

    with st.expander("🗑️ Eliminar cuenta"):
        st.write(
            "Solo se pueden eliminar cuentas **sin movimientos ni presupuestos** relacionados "
            "(restricción de integridad referencial)."
        )
        confirmar = st.checkbox(f"Confirmo que deseo eliminar la cuenta {codigo}", key=f"conf_del_{codigo}")
        if st.button("Eliminar cuenta", disabled=not confirmar, use_container_width=True):
            try:
                db.eliminar_cuenta(codigo)
                avisar("success", f"Cuenta {codigo} eliminada.")
                st.rerun()
            except IntegridadError as exc:
                st.error(str(exc))
