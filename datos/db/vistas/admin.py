"""Panel de administrador: modificar por cuenta lo que se presenta en el Estado de Resultados
y el Balance General (nombre, rubro e importe). Los importes se ajustan con pólizas de Ajuste
automáticas, así la contabilidad sigue cuadrando y el PDF y el Excel reflejan los cambios."""
from __future__ import annotations

import hmac
import uuid
from datetime import date

import pandas as pd
import streamlit as st

from coi import engine
from coi.db import RUBROS, RUBROS_BALANCE, TIPOS_POLIZA, BaseDatos, IntegridadError, estado_de_rubro
from coi.formato import fecha_corta, mxn
from coi.ui import avisar, banda, contrasena_admin, es_admin, fila_kpis, kpi, md, mostrar_aviso

ETIQUETA_RUBRO = {"Gastos de Operacion": "Gastos de Operación"}
REFERENCIA = "Ajuste administrativo"
SECCIONES = ["📊 Cuentas en estados financieros", "🧾 Modificar / eliminar pólizas"]


def _etiqueta(rubro: str) -> str:
    return ETIQUETA_RUBRO.get(rubro, rubro)


def render(db: BaseDatos) -> None:
    st.title("🔐 Panel de administrador")
    mostrar_aviso()
    if not es_admin():
        _acceso()
        return

    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    c1.success("Sesión de administrador activa. Los cambios se reflejan en pantalla, PDF y Excel.", icon="🔓")
    if c2.button("Cerrar sesión", use_container_width=True):
        st.session_state["es_admin"] = False
        st.rerun()

    seccion = st.radio("Sección", SECCIONES, horizontal=True, label_visibility="collapsed", key="adm_seccion")
    if seccion == SECCIONES[1]:
        _polizas(db)
    else:
        _cuentas(db)


def _cuentas(db: BaseDatos) -> None:
    t = db.tablas
    cat = t["catalogoCuentas"]
    if cat.empty:
        st.info("El catálogo está vacío.")
        return
    por_codigo = cat.set_index("codigo")

    def formato_cuenta(codigo: str) -> str:
        fila = por_codigo.loc[codigo]
        siglas = "BG" if fila["estadoFinanciero"] == "Balance General" else "ER"
        return f"[{siglas}] {codigo} · {fila['nombre']}"

    _, ultimo = engine.rango_datos(t)
    c1, c2 = st.columns([2, 1])
    codigo = c1.selectbox("Cuenta a modificar", cat["codigo"].tolist(), format_func=formato_cuenta, key="adm_cuenta")
    fecha = c2.date_input("Fecha de corte / del ajuste", value=(pd.Timestamp(ultimo) + pd.offsets.MonthEnd(0)).date(),
                          format="DD/MM/YYYY", key="adm_fecha")
    fila = por_codigo.loc[codigo]
    info = engine.importe_en_estado(t, codigo, fecha)
    periodo = (f"del {fecha_corta(info['desde'])} al {fecha_corta(info['hasta'])}" if info["desde"]
               else f"al {fecha_corta(info['hasta'])}")
    fila_kpis(
        [
            kpi(f"Importe en {info['estado']}", mxn(info["importe"]), periodo),
            kpi("Se presenta como", fila["nombreReporte"] or fila["nombre"],
                "Nombre personalizado" if fila["nombreReporte"] else "Nombre del catálogo"),
            kpi("Rubro / bloque", _etiqueta(fila["rubro"]), f"Naturaleza {fila['naturaleza']}"),
        ],
        por_fila=3,
    )
    st.write("")
    tab_pres, tab_imp, tab_hist = st.tabs(["✏️ Nombre y rubro", "💲 Ajustar importe", "🧾 Ajustes realizados"])
    with tab_pres:
        _presentacion(db, codigo, fila)
    with tab_imp:
        _importe(db, codigo, fila, fecha, info)
    with tab_hist:
        _historial(db)


def _acceso() -> None:
    contrasena, es_demo = contrasena_admin()
    st.write("Ingresa la contraseña de administrador para modificar los estados financieros.")
    with st.form("form_acceso_admin"):
        intento = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)
    if entrar:
        if hmac.compare_digest(intento.encode("utf-8"), contrasena.encode("utf-8")):
            st.session_state["es_admin"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    if es_demo:
        st.warning(
            "Se está usando la contraseña de demostración (ver README). Antes de publicar la app, define tu propia "
            "contraseña en los Secrets de Streamlit con la sección [admin] y la clave password."
        )


def _presentacion(db: BaseDatos, codigo: str, fila: pd.Series) -> None:
    st.caption("Cambia cómo aparece esta cuenta en el Estado de Resultados y el Balance General (pantalla, PDF y Excel). "
               "El nombre del catálogo y las pólizas no se modifican.")
    with st.form(f"form_presentacion_{codigo}"):
        nombre = st.text_input("Nombre en los estados financieros", value=fila["nombreReporte"],
                               placeholder=f"Vacío = usar «{fila['nombre']}»", max_chars=80)
        rubro = st.selectbox("Bloque / rubro donde se presenta", RUBROS, index=RUBROS.index(fila["rubro"]),
                             format_func=lambda r: f"{_etiqueta(r)}  ({estado_de_rubro(r)})")
        guardar = st.form_submit_button("Guardar presentación", type="primary", use_container_width=True)
    if guardar:
        try:
            cambia_estado = estado_de_rubro(rubro) != fila["estadoFinanciero"]
            db.actualizar_presentacion(codigo, nombre, rubro)
            mensaje = f"Cuenta {codigo}: ahora se presenta como «{nombre.strip() or fila['nombre']}» en {_etiqueta(rubro)}."
            if cambia_estado:
                mensaje += f" Se movió al {estado_de_rubro(rubro)}."
            avisar("success", mensaje)
            st.rerun()
        except IntegridadError as exc:
            st.error(str(exc))
    if fila["rubro"] in RUBROS_BALANCE:
        st.caption("Tip: una cuenta complementaria (p. ej. Depreciación acumulada) puede quedarse en el bloque del "
                   "activo; se restará automáticamente por su naturaleza acreedora.")


def _importe(db: BaseDatos, codigo: str, fila: pd.Series, fecha, info: dict) -> None:
    t = db.tablas
    st.caption(
        "Escribe el importe que debe mostrar la cuenta. El sistema genera una póliza de **Ajuste** contra la cuenta de "
        "contrapartida que elijas, de modo que la balanza y la ecuación contable siguen cuadradas."
    )
    cat = t["catalogoCuentas"]
    otras = [c for c in cat["codigo"] if c != codigo]
    nombres = cat.set_index("codigo")["nombre"]
    c1, c2 = st.columns(2)
    nuevo = c1.number_input("Nuevo importe en el estado ($)", value=float(info["importe"]), step=100.0, format="%.2f",
                            key=f"adm_nuevo_{codigo}_{fecha}_{db.version}")
    contrapartida = c2.selectbox("Cuenta de contrapartida", otras, index=None, placeholder="Selecciona la cuenta…",
                                 format_func=lambda c: f"{c} · {nombres[c]}", key=f"adm_contra_{codigo}")
    concepto = st.text_input("Concepto de la póliza", value=f"{REFERENCIA}: {codigo} {fila['nombre']}",
                             key=f"adm_concepto_{codigo}")

    if contrapartida is None:
        st.info("Elige la cuenta de contrapartida para ver la póliza de ajuste.")
        return
    ajuste = engine.ajuste_a_importe(t, codigo, nuevo, contrapartida, fecha, REFERENCIA)
    if not ajuste["movimientos"]:
        st.info("El importe capturado es igual al actual: no hay nada que ajustar.")
        return

    st.markdown(md(f"**Póliza de ajuste propuesta** · {fecha_corta(fecha)} · diferencia {mxn(ajuste['diferencia'])}"))
    vista = pd.DataFrame(
        [{"Cuenta": m["cuentaCodigo"], "Nombre": nombres[m["cuentaCodigo"]], "Cargo": m["cargo"], "Abono": m["abono"]}
         for m in ajuste["movimientos"]]
    )
    st.dataframe(vista.style.format({"Cargo": mxn, "Abono": mxn}), hide_index=True, use_container_width=True)

    hasta = pd.Timestamp(fecha)
    inicio = pd.Timestamp(year=hasta.year, month=1, day=1)
    antes_er = engine.estado_resultados(t, inicio, hasta)
    antes_bg = engine.balance_general(t, hasta)
    sim = engine.simular(t, fecha, ajuste["movimientos"])
    despues_er = engine.estado_resultados(sim, inicio, hasta)
    despues_bg = engine.balance_general(sim, hasta)
    fila_kpis(
        [
            kpi("Cuenta ajustada", mxn(ajuste["nuevo"]), f"Antes {mxn(ajuste['actual'])}"),
            kpi("Utilidad neta del ejercicio", mxn(despues_er["utilidad_neta"]), f"Antes {mxn(antes_er['utilidad_neta'])}"),
            kpi("Total activo", mxn(despues_bg["total_activo"]), f"Antes {mxn(antes_bg['total_activo'])}"),
            kpi("Pasivo + Capital", mxn(despues_bg["pasivo_mas_capital"]),
                f"Antes {mxn(antes_bg['pasivo_mas_capital'])}", "ok" if despues_bg["cuadra"] else "mal"),
        ],
        por_fila=4,
    )
    banda(despues_bg["cuadra"], "Después del ajuste la ecuación contable sigue cuadrada.",
          "Después del ajuste la ecuación contable NO cuadraría.")
    if st.button("✅ Generar póliza de ajuste", type="primary", use_container_width=True,
                 disabled=not concepto.strip()):
        try:
            pid = db.guardar_poliza(fecha, "Ajuste", concepto, ajuste["movimientos"])
            avisar("success", f"Póliza {pid} generada. {codigo} ahora presenta {mxn(ajuste['nuevo'])}.")
            st.rerun()
        except IntegridadError as exc:
            st.error(str(exc))


def _historial(db: BaseDatos) -> None:
    t = db.tablas
    movs = t["movimientosPoliza"]
    ids = set(movs.loc[movs["referencia"] == REFERENCIA, "polizaId"])
    pol = t["polizas"]
    ajustes = pol[pol["id"].isin(ids) & (pol["tipo"] == "Ajuste")]
    if ajustes.empty:
        st.info("Todavía no hay ajustes hechos desde este panel.")
        return
    resumen = engine.resumen_polizas(t).set_index("id").loc[ajustes["id"]]
    vista = pd.DataFrame(
        {"Póliza": resumen.index, "Fecha": pd.to_datetime(resumen["fecha"]).dt.strftime("%d/%m/%Y").values,
         "Concepto": resumen["concepto"].values, "Importe": resumen["cargos"].values}
    )
    st.dataframe(vista.style.format({"Importe": mxn}), hide_index=True, use_container_width=True)
    eliminar = st.selectbox("Revertir (eliminar) un ajuste", vista["Póliza"].tolist(), index=None,
                            placeholder="Selecciona la póliza…", key=f"adm_revertir_{db.version}")
    if st.button("🗑️ Revertir ajuste seleccionado", disabled=eliminar is None, use_container_width=True):
        db.eliminar_poliza(eliminar)
        avisar("success", f"Ajuste {eliminar} revertido; los estados vuelven a sus importes anteriores.")
        st.rerun()


# ===================================================================== pólizas
def _polizas(db: BaseDatos) -> None:
    t = db.tablas
    resumen = engine.resumen_polizas(t)
    if resumen.empty:
        st.info("No hay pólizas registradas.")
        return
    c1, c2 = st.columns([1, 2])
    tipos = c1.multiselect("Tipo", TIPOS_POLIZA, key="adm_pol_tipos")
    buscar = c2.text_input("Buscar en concepto o folio", placeholder="Ej. POL-001, saldos…", key="adm_pol_buscar")
    if tipos:
        resumen = resumen[resumen["tipo"].isin(tipos)]
    if buscar:
        patron = buscar.strip().lower()
        resumen = resumen[resumen["concepto"].str.lower().str.contains(patron, regex=False)
                          | resumen["id"].str.lower().str.contains(patron, regex=False)]
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

    por_id = resumen.set_index("id")
    opciones = resumen["id"].tolist()
    if st.session_state.get("adm_pol_sel") not in opciones:  # p. ej. después de eliminarla o filtrar
        st.session_state.pop("adm_pol_sel", None)
    pid = st.selectbox("Póliza", opciones,
                       format_func=lambda p: f"{p} · {por_id.loc[p, 'fecha']} · {por_id.loc[p, 'concepto']}",
                       key="adm_pol_sel")
    accion = st.radio("Acción", ["✏️ Modificar", "🗑️ Eliminar"], horizontal=True, key="adm_pol_accion")
    if accion.endswith("Modificar"):
        _editar_poliza(db, pid)
    else:
        _eliminar_poliza(db, pid)


def _fila_poliza(cuenta=None, referencia="", cargo=0.0, abono=0.0) -> dict:
    return {"uid": uuid.uuid4().hex[:10], "cuenta": cuenta, "referencia": referencia,
            "cargo": float(cargo), "abono": float(abono)}


def _estado_edicion(db: BaseDatos, pid: str) -> dict:
    """Copia de trabajo de la póliza; se recarga si cambia la póliza elegida o los datos."""
    ss = st.session_state
    estado = ss.get("adm_pol_edicion")
    if not estado or estado["pid"] != pid or estado["version"] != db.version:
        pol = db.tablas["polizas"].set_index("id").loc[pid]
        nombres = db.tablas["catalogoCuentas"].set_index("codigo")["nombre"]
        movs = db.movimientos_de(pid)
        estado = {
            "pid": pid,
            "version": db.version,
            "clave": uuid.uuid4().hex[:6],
            "fecha": date.fromisoformat(pol["fecha"]),
            "tipo": pol["tipo"],
            "concepto": pol["concepto"],
            "filas": [_fila_poliza(f"{m['cuentaCodigo']} · {nombres.get(m['cuentaCodigo'], '')}", m["referencia"],
                                   m["cargo"], m["abono"]) for _, m in movs.iterrows()] or [_fila_poliza(), _fila_poliza()],
        }
        ss["adm_pol_edicion"] = estado
    return estado


def _agregar_fila_poliza() -> None:
    st.session_state["adm_pol_edicion"]["filas"].append(_fila_poliza())


def _quitar_fila_poliza(uid: str) -> None:
    estado = st.session_state["adm_pol_edicion"]
    estado["filas"] = [f for f in estado["filas"] if f["uid"] != uid] or [_fila_poliza()]


def _descartar_edicion() -> None:
    st.session_state.pop("adm_pol_edicion", None)


def _editar_poliza(db: BaseDatos, pid: str) -> None:
    estado = _estado_edicion(db, pid)
    clave = f"adm_pe_{estado['clave']}"
    cat = db.tablas["catalogoCuentas"]
    opciones = [f"{c} · {n}" for c, n in zip(cat["codigo"], cat["nombre"])]

    with st.container(border=True):
        st.markdown(f"**Encabezado de {pid}**")
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha", value=estado["fecha"], format="DD/MM/YYYY", key=f"{clave}_fecha")
        tipo = c2.selectbox("Tipo de póliza", TIPOS_POLIZA, index=TIPOS_POLIZA.index(estado["tipo"]),
                            key=f"{clave}_tipo")
        concepto = st.text_input("Concepto *", value=estado["concepto"], key=f"{clave}_concepto")

    st.markdown("**Movimientos**")
    movimientos = []
    for n, fila in enumerate(estado["filas"], start=1):
        base = f"{clave}_{fila['uid']}"
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([3, 1.6, 1.8, 1.8, 0.6], vertical_alignment="bottom")
            indice = opciones.index(fila["cuenta"]) if fila["cuenta"] in opciones else None
            cuenta = c1.selectbox(f"Cuenta (renglón {n})", opciones, index=indice,
                                  placeholder="Selecciona la cuenta…", key=f"{base}_cuenta")
            referencia = c2.text_input("Referencia", value=fila["referencia"], max_chars=80, key=f"{base}_ref")
            cargo = c3.number_input("Cargo $", min_value=0.0, value=fila["cargo"], step=100.0, format="%.2f",
                                    key=f"{base}_cargo")
            abono = c4.number_input("Abono $", min_value=0.0, value=fila["abono"], step=100.0, format="%.2f",
                                    key=f"{base}_abono")
            c5.button("🗑️", key=f"{base}_quitar", on_click=_quitar_fila_poliza, args=(fila["uid"],),
                      help="Quitar este renglón", use_container_width=True)
        movimientos.append({"cuenta": cuenta, "referencia": referencia, "cargo": cargo, "abono": abono})
    st.button("➕ Agregar renglón", on_click=_agregar_fila_poliza, use_container_width=True, key=f"{clave}_mas")

    val = engine.validar_poliza(movimientos, set(cat["codigo"]))
    fila_kpis(
        [
            kpi("Total cargos", mxn(val["total_cargos"])),
            kpi("Total abonos", mxn(val["total_abonos"])),
            kpi("Diferencia", mxn(val["diferencia"]), "Debe ser $0.00", "ok" if val["cuadrada"] else "mal"),
        ],
        por_fila=3,
    )
    errores = list(val["errores"])
    if not concepto.strip():
        errores.append("Captura el concepto de la póliza.")
    if val["cuadrada"]:
        st.success("✅ Póliza cuadrada: Total Cargos = Total Abonos.")
    for e in errores:
        st.error(md(e))

    c1, c2 = st.columns([2, 1])
    guardar = c1.button("💾 Guardar cambios en la póliza", type="primary", use_container_width=True,
                        disabled=bool(errores), key=f"{clave}_guardar")
    c2.button("↩️ Descartar cambios", on_click=_descartar_edicion, use_container_width=True, key=f"{clave}_desc")
    if guardar:
        try:
            db.guardar_poliza(fecha, tipo, concepto, movimientos, poliza_id=pid)
            _descartar_edicion()
            avisar("success", f"Póliza {pid} modificada: {mxn(val['total_cargos'])} en cargos y abonos.")
            st.rerun()
        except IntegridadError as exc:
            st.error(str(exc))


def _eliminar_poliza(db: BaseDatos, pid: str) -> None:
    t = db.tablas
    nombres = t["catalogoCuentas"].set_index("codigo")["nombre"]
    movs = db.movimientos_de(pid)
    detalle = pd.DataFrame({"Cuenta": movs["cuentaCodigo"], "Nombre": movs["cuentaCodigo"].map(nombres),
                            "Referencia": movs["referencia"], "Cargo": movs["cargo"], "Abono": movs["abono"]})
    st.dataframe(detalle.style.format({"Cargo": mxn, "Abono": mxn}), hide_index=True, use_container_width=True)

    # Vista previa: cómo quedan los estados sin esta póliza
    sin = dict(t)
    sin["polizas"] = t["polizas"][t["polizas"]["id"] != pid]
    sin["movimientosPoliza"] = t["movimientosPoliza"][t["movimientosPoliza"]["polizaId"] != pid]
    _, ultimo = engine.rango_datos(t)
    hasta = pd.Timestamp(ultimo) + pd.offsets.MonthEnd(0)
    inicio = pd.Timestamp(year=hasta.year, month=1, day=1)
    antes_er, despues_er = engine.estado_resultados(t, inicio, hasta), engine.estado_resultados(sin, inicio, hasta)
    antes_bg, despues_bg = engine.balance_general(t, hasta), engine.balance_general(sin, hasta)
    st.markdown(f"**Efecto de eliminarla** (ejercicio {hasta.year}, corte {fecha_corta(hasta)})")
    fila_kpis(
        [
            kpi("Utilidad neta", mxn(despues_er["utilidad_neta"]), f"Antes {mxn(antes_er['utilidad_neta'])}"),
            kpi("Total activo", mxn(despues_bg["total_activo"]), f"Antes {mxn(antes_bg['total_activo'])}"),
            kpi("Pasivo + Capital", mxn(despues_bg["pasivo_mas_capital"]),
                f"Antes {mxn(antes_bg['pasivo_mas_capital'])}"),
        ],
        por_fila=3,
    )
    if len(t["polizas"]) == 1:
        st.warning("Es la única póliza: los estados financieros quedarán en ceros.")
    st.warning("Se eliminarán el encabezado y todos sus movimientos (borrado en cascada). No se puede deshacer; "
               "descarga un respaldo antes si lo necesitas.")
    confirmar = st.checkbox(f"Confirmo que deseo eliminar la póliza {pid}", key=f"adm_pol_conf_{pid}_{db.version}")
    if st.button("🗑️ Eliminar póliza definitivamente", type="primary", disabled=not confirmar,
                 use_container_width=True, key=f"adm_pol_del_{pid}"):
        db.eliminar_poliza(pid)
        _descartar_edicion()
        avisar("success", f"Póliza {pid} eliminada junto con sus {len(movs)} movimiento(s).")
        st.rerun()