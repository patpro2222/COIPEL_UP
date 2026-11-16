"""COI-UP Contabilidad · punto de entrada.

Ejecutar localmente:  streamlit run app.py
"""
from __future__ import annotations

import html

import streamlit as st

st.set_page_config(
    page_title="COI-UP Contabilidad",
    page_icon="📒",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={"About": "COI-UP Contabilidad · Sistema contable y presupuestal estilo Aspel COI, hecho en Python."},
)

from coi import __version__, engine  # noqa: E402
from coi.ui import aplicar_estilos, obtener_bd  # noqa: E402
from vistas import admin, balanza, catalogo, dashboard, datos, estados, polizas, presupuestos  # noqa: E402

aplicar_estilos()
db = obtener_bd()


def pagina_dashboard():
    dashboard.render(db)


def pagina_catalogo():
    catalogo.render(db)


def pagina_polizas():
    polizas.render(db)


def pagina_balanza():
    balanza.render(db)


def pagina_estados():
    estados.render(db)


def pagina_presupuestos():
    presupuestos.render(db)


def pagina_datos():
    datos.render(db)


def pagina_admin():
    admin.render(db)


navegacion = st.navigation(
    {
        "Inicio": [st.Page(pagina_dashboard, title="Dashboard", icon="📊", url_path="dashboard", default=True)],
        "Contabilidad": [
            st.Page(pagina_catalogo, title="Catálogo de cuentas", icon="🗂️", url_path="catalogo"),
            st.Page(pagina_polizas, title="Pólizas", icon="🧾", url_path="polizas"),
            st.Page(pagina_balanza, title="Balanza y auxiliares", icon="⚖️", url_path="balanza"),
        ],
        "Reportes": [
            st.Page(pagina_estados, title="Estados financieros", icon="📑", url_path="estados"),
            st.Page(pagina_presupuestos, title="Control presupuestal", icon="🎯", url_path="presupuestos"),
        ],
        "Administración": [
            st.Page(pagina_admin, title="Panel de administrador", icon="🔐", url_path="admin"),
            st.Page(pagina_datos, title="Base de datos y respaldo", icon="🗄️", url_path="datos"),
        ],
    }
)

with st.sidebar:
    empresa = db.datos_empresa()
    st.markdown(
        f'<div class="coi-marca">📒 COI-UP Contabilidad<small>{html.escape(empresa["razon_social"])}<br>'
        f'RFC {html.escape(empresa["rfc"])}</small></div>',
        unsafe_allow_html=True,
    )
    cuadre = engine.estatus_cuadre(db.tablas)
    if cuadre["cuadrado"]:
        st.success("Contabilidad cuadrada", icon="✅")
    else:
        st.error(f"Descuadre de \\${abs(cuadre['diferencia']):,.2f}", icon="⚠️")
    sync = getattr(db, "sync", None)
    st.caption(("☁️ Respaldo en GitHub activo" if sync else "💾 Datos en CSV locales") + f" · v{__version__}")

navegacion.run()
