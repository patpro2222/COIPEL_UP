"""Panel de administrador: modificar por cuenta lo que se presenta en el Estado de Resultados
y el Balance General (nombre, rubro e importe). Los importes se ajustan con pólizas de Ajuste
automáticas, así la contabilidad sigue cuadrando y el PDF y el Excel reflejan los cambios."""
from __future__ import annotations

import hmac

import pandas as pd
import streamlit as st

from coi import engine
from coi.db import RUBROS, RUBROS_BALANCE, BaseDatos, IntegridadError, estado_de_rubro
from coi.formato import fecha_corta, mxn
from coi.ui import avisar, banda, contrasena_admin, es_admin, fila_kpis, kpi, md, mostrar_aviso

ETIQUETA_RUBRO = {"Gastos de Operacion": "Gastos de Operación"}
REFERENCIA = "Ajuste administrativo"


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
