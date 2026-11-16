"""Captura y consulta de pólizas con compuerta de partida doble."""
from __future__ import annotations

from datetime import date
import uuid

import pandas as pd
import streamlit as st

from coi import engine, exportar
from coi.db import TIPOS_POLIZA, BaseDatos, IntegridadError
from coi.formato import mxn
from coi.ui import avisar, fila_kpis, kpi, md, mostrar_aviso, selector_periodo

VISTAS = ["✍️ Captura", "🔎 Consulta", "📚 Libro diario"]


def _fila(cuenta: str | None = None, referencia: str = "", cargo: float = 0.0, abono: float = 0.0) -> dict:
    return {"uid": uuid.uuid4().hex[:10], "cuenta": cuenta, "referencia": referencia, "cargo": cargo, "abono": abono}


def _iniciar_estado() -> None:
    ss = st.session_state
    ss.setdefault("pol_ver", 0)
    ss.setdefault("pol_editando", None)
    ss.setdefault("pol_filas", [_fila(), _fila()])
    ss.setdefault("pol_encabezado", {"fecha": date.today(), "tipo": "Diario", "concepto": ""})


def _cargar_en_captura(db: BaseDatos, poliza_id: str, duplicar: bool) -> None:
    """Callback: copia una póliza existente al formulario de captura."""
    ss = st.session_state
    pol = db.tablas["polizas"].set_index("id").loc[poliza_id]
    movs = db.movimientos_de(poliza_id)
    nombres = db.tablas["catalogoCuentas"].set_index("codigo")["nombre"]
    ss["pol_filas"] = [
        _fila(f"{m['cuentaCodigo']} · {nombres.get(m['cuentaCodigo'], '')}", m["referencia"], float(m["cargo"]),
              float(m["abono"]))
        for _, m in movs.iterrows()
    ]
    ss["pol_encabezado"] = {
        "fecha": date.today() if duplicar else date.fromisoformat(pol["fecha"]),
        "tipo": pol["tipo"],
        "concepto": pol["concepto"] + (" (copia)" if duplicar else ""),
    }
    ss["pol_editando"] = None if duplicar else poliza_id
    ss["pol_ver"] += 1
    ss["pol_vista"] = VISTAS[0]


def _limpiar_captura() -> None:
    ss = st.session_state
    ss["pol_filas"] = [_fila(), _fila()]
    ss["pol_encabezado"] = {"fecha": date.today(), "tipo": "Diario", "concepto": ""}
    ss["pol_editando"] = None
    ss["pol_ver"] += 1


def _agregar_renglon() -> None:
    st.session_state["pol_filas"].append(_fila())


def _quitar_renglon(uid: str) -> None:
    ss = st.session_state
    ss["pol_filas"] = [f for f in ss["pol_filas"] if f["uid"] != uid]
    if not ss["pol_filas"]:
        ss["pol_filas"] = [_fila()]


def render(db: BaseDatos) -> None:
    _iniciar_estado()
    st.title("🧾 Pólizas")
    mostrar_aviso()
    vista = st.radio("Sección", VISTAS, horizontal=True, label_visibility="collapsed", key="pol_vista")
    if vista == VISTAS[0]:
        _captura(db)
    elif vista == VISTAS[1]:
        _consulta(db)
    else:
        _diario(db)


# ------------------------------------------------------------------ captura
def _captura(db: BaseDatos) -> None:
    ss = st.session_state
    ver = ss["pol_ver"]
    enc = ss["pol_encabezado"]
    cat = db.tablas["catalogoCuentas"]
    opciones = [f"{c} · {n}" for c, n in zip(cat["codigo"], cat["nombre"])]

    if ss["pol_editando"]:
        c1, c2 = st.columns([3, 1])
        c1.info(f"✏️ Modificando la póliza **{ss['pol_editando']}**. Al guardar se reemplazará su detalle.")
        c2.button("Cancelar edición", on_click=_limpiar_captura, use_container_width=True)

    with st.container(border=True):
        st.markdown("**Encabezado de la póliza**")
        c1, c2, c3 = st.columns(3)
        folio = ss["pol_editando"] or db.siguiente_id_poliza()
        c1.text_input("Folio", value=folio, disabled=True, key=f"pol_folio_{ver}_{folio}")
        fecha = c2.date_input("Fecha", value=enc["fecha"], format="DD/MM/YYYY", key=f"pol_fecha_{ver}")
        tipo = c3.selectbox("Tipo de póliza", TIPOS_POLIZA, index=TIPOS_POLIZA.index(enc["tipo"]), key=f"pol_tipo_{ver}")
        concepto = st.text_input("Concepto *", value=enc["concepto"], placeholder="Ej. Venta de contado factura A-1052",
                                 key=f"pol_concepto_{ver}")

    st.markdown("**Movimientos (detalle de la póliza)**")
    movimientos = []
    for n, fila in enumerate(ss["pol_filas"], start=1):
        base = f"pol_{ver}_{fila['uid']}"
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([3, 1.6, 1.8, 1.8, 0.6], vertical_alignment="bottom")
            indice = opciones.index(fila["cuenta"]) if fila["cuenta"] in opciones else None
            cuenta = c1.selectbox(f"Cuenta (renglón {n})", opciones, index=indice, placeholder="Selecciona la cuenta…",
                                  key=f"{base}_cuenta")
            referencia = c2.text_input("Referencia", value=fila["referencia"], max_chars=80, key=f"{base}_ref")
            cargo = c3.number_input("Cargo $", min_value=0.0, value=float(fila["cargo"]), step=100.0, format="%.2f",
                                    key=f"{base}_cargo")
            abono = c4.number_input("Abono $", min_value=0.0, value=float(fila["abono"]), step=100.0, format="%.2f",
                                    key=f"{base}_abono")
            c5.button("🗑️", key=f"{base}_quitar", on_click=_quitar_renglon, args=(fila["uid"],),
                      help="Quitar este renglón", use_container_width=True)
        movimientos.append({"cuenta": cuenta, "referencia": referencia, "cargo": cargo, "abono": abono})
    st.button("➕ Agregar renglón", on_click=_agregar_renglon, use_container_width=True)

    val = engine.validar_poliza(movimientos, set(cat["codigo"]))
    cuadrada = val["cuadrada"]
    fila_kpis(
        [
            kpi("Total cargos", mxn(val["total_cargos"]), f"{sum(1 for f in val['filas'] if f['cargo'])} renglón(es)"),
            kpi("Total abonos", mxn(val["total_abonos"]), f"{sum(1 for f in val['filas'] if f['abono'])} renglón(es)"),
            kpi("Diferencia", mxn(val["diferencia"]), "Debe ser $0.00", "ok" if cuadrada else "mal"),
        ],
        por_fila=3,
    )
    if val["total_cargos"] == 0 and val["total_abonos"] == 0:
        st.warning("⚠️ Captura importes: no se puede guardar una póliza con Total Cargos y Total Abonos en 0.")
    elif not cuadrada:
        st.error(md(
            f"🚫 PÓLIZA DESCUADRADA: los cargos ({mxn(val['total_cargos'])}) y los abonos "
            f"({mxn(val['total_abonos'])}) difieren por {mxn(val['diferencia'])}. El botón Guardar está bloqueado."
        ))
    else:
        st.success("✅ Póliza cuadrada: Total Cargos = Total Abonos.")

    otros = [e for e in val["errores"] if not e.startswith(("Póliza descuadrada", "La póliza no tiene importes"))]
    if not concepto.strip():
        otros.append("Captura el concepto de la póliza.")
    if otros:
        with st.expander(f"Revisa {len(otros)} observación(es) antes de guardar", expanded=cuadrada):
            for e in otros:
                st.write("• " + e)

    puede_guardar = val["valida"] and bool(concepto.strip())
    c1, c2 = st.columns([2, 1])
    guardar = c1.button(
        "💾 Guardar cambios" if ss["pol_editando"] else "💾 Guardar póliza",
        type="primary",
        disabled=not puede_guardar,
        use_container_width=True,
    )
    c2.button("🧹 Limpiar", on_click=_limpiar_captura, use_container_width=True)
    if guardar:
        try:
            pid = db.guardar_poliza(fecha, tipo, concepto, movimientos, poliza_id=ss["pol_editando"])
            avisar("success", f"Póliza {pid} guardada: {mxn(val['total_cargos'])} en cargos y abonos.")
            _limpiar_captura()
            st.rerun()
        except IntegridadError as exc:
            st.error(str(exc))


# ------------------------------------------------------------------ consulta
def _consulta(db: BaseDatos) -> None:
    t = db.tablas
    desde, hasta = selector_periodo(t, "pol")
    c1, c2 = st.columns([1, 2])
    tipos = c1.multiselect("Tipo", TIPOS_POLIZA)
    buscar = c2.text_input("Buscar en concepto o folio", placeholder="Ej. venta, POL-004…")
    resumen = engine.resumen_polizas(t, desde, hasta)
    if tipos:
        resumen = resumen[resumen["tipo"].isin(tipos)]
    if buscar:
        patron = buscar.strip().lower()
        resumen = resumen[
            resumen["concepto"].str.lower().str.contains(patron, regex=False)
            | resumen["id"].str.lower().str.contains(patron, regex=False)
        ]
    if resumen.empty:
        st.info("No hay pólizas con esos filtros.")
        return

    tabla = pd.DataFrame(
        {
            "Póliza": resumen["id"],
            "Fecha": pd.to_datetime(resumen["fecha"]).dt.strftime("%d/%m/%Y"),
            "Tipo": resumen["tipo"],
            "Concepto": resumen["concepto"],
            "Movs.": resumen["movimientos"],
            "Cargos": resumen["cargos"],
            "Abonos": resumen["abonos"],
            "Estatus": resumen["cuadrada"].map({True: "✅ Cuadrada", False: "⚠️ Descuadrada"}),
        }
    )
    st.dataframe(tabla.style.format({"Cargos": mxn, "Abonos": mxn}), hide_index=True, use_container_width=True)
    st.caption(md(f"{len(tabla)} póliza(s) · Total cargos {mxn(resumen['cargos'].sum())} · "
                  f"Total abonos {mxn(resumen['abonos'].sum())}"))

    st.divider()
    por_id = resumen.set_index("id")
    elegida = st.selectbox(
        "Ver detalle de la póliza",
        resumen["id"].tolist(),
        format_func=lambda pid: f"{pid} · {por_id.loc[pid, 'concepto']}",
        key=f"pol_detalle_{db.version}",
    )
    enc = por_id.loc[elegida]
    movs = db.movimientos_de(elegida).merge(
        t["catalogoCuentas"][["codigo", "nombre"]], left_on="cuentaCodigo", right_on="codigo", how="left"
    )
    with st.container(border=True):
        st.markdown(
            f"**{elegida}** · {enc['tipo']} · {pd.Timestamp(enc['fecha']).strftime('%d/%m/%Y')}  \n{enc['concepto']}"
        )
        detalle = pd.DataFrame(
            {
                "Cuenta": movs["cuentaCodigo"],
                "Nombre": movs["nombre"],
                "Referencia": movs["referencia"],
                "Cargo": movs["cargo"],
                "Abono": movs["abono"],
            }
        )
        total = pd.DataFrame([{"Cuenta": "", "Nombre": "SUMAS", "Referencia": "",
                               "Cargo": detalle["Cargo"].sum(), "Abono": detalle["Abono"].sum()}])
        detalle = pd.concat([detalle, total], ignore_index=True)
        ultimo = len(detalle) - 1
        st.dataframe(
            detalle.style.format({"Cargo": mxn, "Abono": mxn}).apply(
                lambda fila: ["font-weight:700; background-color:#DBEAFE" if fila.name == ultimo else ""
                              for _ in fila], axis=1),
            hide_index=True,
            use_container_width=True,
        )
        c1, c2 = st.columns(2)
        c1.button("✏️ Editar póliza", on_click=_cargar_en_captura, args=(db, elegida, False), use_container_width=True)
        c2.button("📄 Duplicar como nueva", on_click=_cargar_en_captura, args=(db, elegida, True),
                  use_container_width=True)
        with st.expander("🗑️ Eliminar póliza"):
            st.write("Se eliminarán el encabezado y **todos sus movimientos** (borrado en cascada).")
            confirmar = st.checkbox(f"Confirmo eliminar la póliza {elegida}", key=f"conf_pol_{elegida}")
            if st.button("Eliminar definitivamente", disabled=not confirmar, use_container_width=True):
                db.eliminar_poliza(elegida)
                if st.session_state.get("pol_editando") == elegida:
                    _limpiar_captura()
                avisar("success", f"Póliza {elegida} eliminada.")
                st.rerun()


# ------------------------------------------------------------------ libro diario
def _diario(db: BaseDatos) -> None:
    t = db.tablas
    desde, hasta = selector_periodo(t, "diario")
    tipos = st.multiselect("Tipos de póliza", TIPOS_POLIZA, key="diario_tipos")
    df = engine.libro_diario(t, desde, hasta, tipos)
    if df.empty:
        st.info("No hay movimientos en el periodo.")
        return
    vista = pd.DataFrame(
        {
            "Fecha": df["fecha"].dt.strftime("%d/%m/%Y"),
            "Póliza": df["polizaId"],
            "Tipo": df["tipo"],
            "Cuenta": df["cuentaCodigo"],
            "Nombre": df["nombre"],
            "Referencia": df["referencia"],
            "Cargo": df["cargo"],
            "Abono": df["abono"],
        }
    )
    st.dataframe(vista.style.format({"Cargo": mxn, "Abono": mxn}), hide_index=True, use_container_width=True,
                 height=520)
    fila_kpis([kpi("Total cargos", mxn(df["cargo"].sum())), kpi("Total abonos", mxn(df["abono"].sum())),
               kpi("Movimientos", f"{len(df):,}")], por_fila=3)
    empresa = db.datos_empresa()
    rep = exportar.reporte_diario(df, desde, hasta)
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Libro diario en PDF", exportar.generar_pdf(empresa, [rep]), "libro_diario.pdf",
                       mime="application/pdf", use_container_width=True)
    c2.download_button("⬇️ Libro diario en Excel", exportar.generar_excel(empresa, [rep]), "libro_diario.xlsx",
                       use_container_width=True)
