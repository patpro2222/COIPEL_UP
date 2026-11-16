"""Base de datos: modelo relacional, integridad, respaldos, empresa y nube."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from coi.db import ESQUEMA, RELACIONES, BaseDatos, IntegridadError
from coi.ui import avisar, banda, mostrar_aviso

DIAGRAMA = """
digraph ER {
  graph [rankdir=LR, bgcolor="transparent", pad="0.2", nodesep="0.5", ranksep="0.9"];
  node  [shape=plaintext, fontname="Helvetica", fontsize=11];
  edge  [color="#1E3A8A", fontname="Helvetica", fontsize=10, fontcolor="#334155"];
  catalogoCuentas [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="5">
    <tr><td bgcolor="#1E3A8A"><font color="white"><b>catalogoCuentas</b></font></td></tr>
    <tr><td align="left">🔑 codigo (PK)</td></tr><tr><td align="left">codigoSAT</td></tr>
    <tr><td align="left">nombre</td></tr><tr><td align="left">naturaleza</td></tr>
    <tr><td align="left">estadoFinanciero</td></tr><tr><td align="left">rubro</td></tr>
    <tr><td align="left">nombreReporte</td></tr></table>>];
  polizas [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="5">
    <tr><td bgcolor="#1E3A8A"><font color="white"><b>polizas</b></font></td></tr>
    <tr><td align="left">🔑 id (PK)</td></tr><tr><td align="left">fecha</td></tr>
    <tr><td align="left">tipo</td></tr><tr><td align="left">concepto</td></tr></table>>];
  movimientosPoliza [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="5">
    <tr><td bgcolor="#334155"><font color="white"><b>movimientosPoliza</b></font></td></tr>
    <tr><td align="left">🔑 id (PK)</td></tr><tr><td align="left">🔗 polizaId (FK)</td></tr>
    <tr><td align="left">🔗 cuentaCodigo (FK)</td></tr><tr><td align="left">referencia</td></tr>
    <tr><td align="left">cargo</td></tr><tr><td align="left">abono</td></tr></table>>];
  presupuestos [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="5">
    <tr><td bgcolor="#334155"><font color="white"><b>presupuestos</b></font></td></tr>
    <tr><td align="left">🔑 id (PK)</td></tr><tr><td align="left">🔗 cuentaCodigo (FK)</td></tr>
    <tr><td align="left">periodo</td></tr><tr><td align="left">montoPresupuestado</td></tr></table>>];
  polizas -> movimientosPoliza [label="1 : N  (cascada)"];
  catalogoCuentas -> movimientosPoliza [label="1 : N  (restringe)"];
  catalogoCuentas -> presupuestos [label="1 : N  (restringe)"];
}
"""


def render(db: BaseDatos) -> None:
    st.title("🗄️ Base de Datos y Respaldo")
    mostrar_aviso()
    tabs = st.tabs(["Modelo e integridad", "Respaldo / restaurar", "Datos de la empresa", "Nube (GitHub)"])
    with tabs[0]:
        _modelo(db)
    with tabs[1]:
        _respaldo(db)
    with tabs[2]:
        _empresa(db)
    with tabs[3]:
        _nube(db)


def _modelo(db: BaseDatos) -> None:
    errores = db.integridad()
    banda(not errores, "Integridad relacional correcta: PK únicas, FK válidas y todas las pólizas cuadradas.",
          f"Se detectaron {len(errores)} problema(s) de integridad.")
    for e in errores:
        st.write("• " + e)
    st.graphviz_chart(DIAGRAMA, use_container_width=True)
    conteos = db.conteos()
    resumen = pd.DataFrame(
        [{"Tabla": n, "Archivo CSV": f"datos/db/{cfg['archivo']}", "Llave primaria": cfg["pk"], "Registros": conteos[n]}
         for n, cfg in ESQUEMA.items()]
    )
    st.dataframe(resumen, hide_index=True, use_container_width=True)
    relaciones = pd.DataFrame(
        [{"Tabla hija": h, "Llave foránea": fk, "Referencia a": f"{p}.{pk}"} for h, fk, p, pk in RELACIONES]
    )
    st.dataframe(relaciones, hide_index=True, use_container_width=True)
    tabla = st.selectbox("Explorar una tabla", list(ESQUEMA), key="explorar_tabla")
    st.dataframe(db.tablas[tabla], hide_index=True, use_container_width=True)


def _respaldo(db: BaseDatos) -> None:
    sello = datetime.now().strftime("%Y%m%d_%H%M")
    st.markdown("**Descargar respaldo completo** (las 5 tablas)")
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇️ Excel (.xlsx)", db.exportar_excel(), f"respaldo_coi_{sello}.xlsx", use_container_width=True)
    c2.download_button("⬇️ CSV en ZIP", db.exportar_zip(), f"respaldo_coi_{sello}.zip", mime="application/zip",
                       use_container_width=True)
    c3.download_button("⬇️ JSON", db.exportar_json(), f"respaldo_coi_{sello}.json", mime="application/json",
                       use_container_width=True)
    st.caption("El Excel tiene una hoja por tabla: puedes editarlo y volver a importarlo. Se valida antes de aplicarse.")

    st.divider()
    st.markdown("**Importar respaldo** (reemplaza todos los datos actuales)")
    ss = st.session_state
    ss.setdefault("import_ver", 0)
    archivo = st.file_uploader("Archivo .xlsx, .zip o .json", type=["xlsx", "zip", "json"],
                               key=f"importar_{ss['import_ver']}")
    if archivo is not None:
        confirmar = st.checkbox("Entiendo que los datos actuales serán reemplazados", key=f"conf_imp_{ss['import_ver']}")
        if st.button("📥 Importar y reemplazar", type="primary", disabled=not confirmar, use_container_width=True):
            try:
                db.importar(archivo.getvalue(), archivo.name)
                ss["import_ver"] += 1
                avisar("success", f"Respaldo «{archivo.name}» importado correctamente.")
                st.rerun()
            except IntegridadError as exc:
                st.error(str(exc))
            except Exception as exc:  # archivo dañado o con formato inesperado
                st.error(f"No se pudo leer el archivo: {exc}")

    st.divider()
    st.markdown("**Restaurar datos de demostración**")
    st.caption("Carga el catálogo, las 6 pólizas y los presupuestos de ejemplo. Descarga antes un respaldo si lo necesitas.")
    confirmar_demo = st.checkbox("Confirmo que deseo borrar mis datos y cargar la demostración", key="conf_demo")
    if st.button("♻️ Restaurar datos de demostración", disabled=not confirmar_demo, use_container_width=True):
        db.restaurar_demo()
        ss.pop("conf_demo", None)
        avisar("success", "Datos de demostración restaurados.")
        st.rerun()


def _empresa(db: BaseDatos) -> None:
    datos = db.datos_empresa()
    with st.form("form_empresa"):
        razon = st.text_input("Razón social *", value=datos["razon_social"])
        c1, c2 = st.columns(2)
        rfc = c1.text_input("RFC", value=datos["rfc"], max_chars=13)
        moneda = c2.text_input("Moneda", value=datos["moneda"], max_chars=5)
        domicilio = st.text_input("Domicilio fiscal", value=datos["domicilio"])
        regimen = st.text_input("Régimen fiscal", value=datos["regimen_fiscal"])
        if st.form_submit_button("Guardar datos de la empresa", type="primary", use_container_width=True):
            try:
                db.actualizar_empresa({"razon_social": razon, "rfc": rfc.upper(), "moneda": moneda.upper(),
                                       "domicilio": domicilio, "regimen_fiscal": regimen})
                avisar("success", "Datos de la empresa actualizados; aparecerán en todos los reportes.")
                st.rerun()
            except IntegridadError as exc:
                st.error(str(exc))


def _nube(db: BaseDatos) -> None:
    sync = getattr(db, "sync", None)
    if sync is None:
        st.info(
            "La sincronización con GitHub no está configurada. Sin ella, en Streamlit Community Cloud los cambios "
            "pueden perderse cuando la app se reinicia. Configúrala en los *Secrets* de la app (ver README, paso 6) "
            "o descarga respaldos periódicamente."
        )
        st.code('[github]\ntoken = "github_pat_..."\nrepo = "tu-usuario/coi-up-contabilidad"\nrama = "datos"\n'
                'carpeta = "datos/db"\nautomatico = true', language="toml")
        return
    st.success(f"Conectado a **{sync.repo}**, rama **{sync.rama}**, carpeta **{sync.carpeta}**.")
    st.caption("Respaldo automático al guardar: " + ("activado ✅" if sync.automatico else "desactivado"))
    if sync.ultima_sincronizacion:
        st.caption(f"Última sincronización: {sync.ultima_sincronizacion:%d/%m/%Y %H:%M:%S}")
    if sync.ultimo_error:
        st.error(sync.ultimo_error)
    c1, c2 = st.columns(2)
    if c1.button("⬆️ Subir ahora a GitHub", use_container_width=True):
        try:
            n = sync.subir(db.rutas, "COI-UP: respaldo manual")
            st.success(f"Listo: {n} archivo(s) actualizados en GitHub (los que no cambiaron se omiten).")
        except Exception as exc:
            st.error(f"No se pudo subir: {exc}")
    if c2.button("⬇️ Descargar desde GitHub", use_container_width=True):
        try:
            archivos = sync.descargar([c["archivo"] for c in ESQUEMA.values()], db.dir)
            db.recargar()
            avisar("success", f"Se descargaron {len(archivos)} archivo(s) desde GitHub.")
            st.rerun()
        except Exception as exc:
            st.error(f"No se pudo descargar: {exc}")
