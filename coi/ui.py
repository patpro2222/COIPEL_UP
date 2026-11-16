"""Componentes de interfaz compartidos (Streamlit)."""
from __future__ import annotations

import html
from datetime import date

import pandas as pd
import streamlit as st

from .db import DB_DIR, ESQUEMA, BaseDatos
from .engine import rango_datos
from .formato import mxn
from .nube import SincronizadorGitHub

PALETA = ["#1E3A8A", "#94A3B8", "#0EA5E9", "#F59E0B", "#10B981", "#EF4444", "#6366F1"]

CSS = """
<style>
:root { --coi-navy:#1E3A8A; --coi-slate:#334155; --coi-ink:#0F172A; --coi-line:#E2E8F0; --coi-soft:#F8FAFC; }
.block-container { padding-top: 1.6rem; padding-bottom: 4rem; max-width: 1320px; }
h1 { color: var(--coi-ink); font-weight: 750; letter-spacing: -0.02em; }
h2, h3 { color: var(--coi-ink); }
div[data-testid="stVerticalBlockBorderWrapper"] h3 { font-size: 1.15rem !important; padding-top: .2rem; }
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  min-height: 46px; border-radius: 10px; font-weight: 600; }
div[data-baseweb="select"] > div, .stTextInput input, .stNumberInput input, .stDateInput input { min-height: 44px; }
.coi-grid { display:grid; gap:12px; margin-bottom:6px; }
.coi-kpi { background:#FFFFFF; border:1px solid var(--coi-line); border-left:5px solid var(--coi-navy);
  border-radius:14px; padding:14px 16px; box-shadow:0 1px 2px rgba(15,23,42,.05); height:100%; }
.coi-kpi .lbl { font-size:.78rem; text-transform:uppercase; letter-spacing:.05em; color:#64748B; font-weight:600; }
.coi-kpi .val { font-size:1.45rem; font-weight:750; color:var(--coi-ink); margin-top:4px; line-height:1.2;
  font-variant-numeric: tabular-nums; word-break: break-word; }
.coi-kpi .sub { font-size:.8rem; color:#64748B; margin-top:4px; }
.coi-kpi.ok { border-left-color:#16A34A; } .coi-kpi.mal { border-left-color:#DC2626; } .coi-kpi.alerta { border-left-color:#F59E0B; }
.coi-banda { border-radius:12px; padding:12px 16px; font-weight:650; margin:8px 0 14px 0; }
.coi-banda.ok { background:#DCFCE7; color:#14532D; border:1px solid #86EFAC; }
.coi-banda.mal { background:#FEE2E2; color:#7F1D1D; border:1px solid #FCA5A5; }
.coi-tabla-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; border:1px solid var(--coi-line);
  border-radius:12px; background:#FFFFFF; }
table.coi-fin { width:100%; border-collapse:collapse; min-width:560px; font-size:.92rem; color:var(--coi-ink); }
table.coi-fin th { background:var(--coi-navy); color:#FFFFFF; text-align:left; padding:9px 12px; font-weight:600; }
table.coi-fin th.num, table.coi-fin td.num { text-align:right; font-variant-numeric: tabular-nums; white-space:nowrap; }
table.coi-fin td { padding:7px 12px; border-bottom:1px solid #F1F5F9; }
table.coi-fin tr.seccion td { background:#E2E8F0; color:var(--coi-navy); font-weight:700; }
table.coi-fin tr.grupo td { font-weight:700; }
table.coi-fin tr.detalle td { color:#475569; font-size:.86rem; }
table.coi-fin tr.detalle td:first-child { padding-left:28px; }
table.coi-fin tr.sub td { font-weight:700; border-top:1px solid #94A3B8; }
table.coi-fin tr.total td { font-weight:800; background:#DBEAFE; border-top:1px solid #1E3A8A; border-bottom:3px double #1E3A8A; }
table.coi-fin td.neg { color:#B91C1C; }
.coi-pie { color:#64748B; font-size:.8rem; margin-top:6px; }
.coi-marca { font-weight:800; font-size:1.15rem; color:var(--coi-navy); line-height:1.2; }
.coi-marca small { display:block; font-weight:500; color:#64748B; font-size:.78rem; }
@media (max-width: 640px) {
  .block-container { padding-left: .8rem; padding-right: .8rem; padding-top: 1rem; }
  h1 { font-size: 1.55rem !important; }
  .coi-kpi .val { font-size: 1.25rem; }
}
</style>
"""


def aplicar_estilos() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------- base de datos
def _config_github() -> dict | None:
    try:
        # load_if_toml_exists evita que Streamlit muestre un error cuando no hay secrets configurados.
        if not st.secrets.load_if_toml_exists():
            return None
        cfg = st.secrets.get("github")
    except Exception:  # sin archivo de secrets o formato inválido
        return None
    if not cfg or not cfg.get("token") or not cfg.get("repo"):
        return None
    return {
        "token": cfg["token"],
        "repo": cfg["repo"],
        "rama": cfg.get("rama", "datos"),
        "carpeta": cfg.get("carpeta", "datos/db"),
        "automatico": bool(cfg.get("automatico", True)),
    }


@st.cache_resource(show_spinner="Abriendo la base de datos contable…")
def obtener_bd() -> BaseDatos:
    cfg = _config_github()
    sync = SincronizadorGitHub(**cfg) if cfg else None
    if sync:
        try:
            sync.descargar([c["archivo"] for c in ESQUEMA.values()], DB_DIR)
        except Exception as exc:  # la app sigue funcionando con los datos locales
            sync.ultimo_error = f"No se pudo descargar de GitHub: {exc}"

    def al_guardar(rutas):
        if not sync or not sync.automatico:
            return
        try:
            sync.subir(rutas)
        except Exception as exc:
            sync.ultimo_error = f"No se pudo respaldar en GitHub: {exc}"
            try:
                st.toast("⚠️ Guardado localmente, pero falló el respaldo en GitHub.")
            except Exception:
                pass

    db = BaseDatos(DB_DIR, al_guardar=al_guardar)
    db.sync = sync  # type: ignore[attr-defined]
    return db


# ------------------------------------------------------------- administrador
CONTRASENA_DEMO = "admin123"


def contrasena_admin() -> tuple[str, bool]:
    """Contraseña del panel de administrador. Devuelve (contraseña, es_la_de_demostracion)."""
    try:
        if st.secrets.load_if_toml_exists():
            cfg = st.secrets.get("admin")
            if cfg and cfg.get("password"):
                return str(cfg["password"]), False
    except Exception:
        pass
    return CONTRASENA_DEMO, True


def es_admin() -> bool:
    return bool(st.session_state.get("es_admin"))


# ------------------------------------------------------------------- avisos
def md(texto: str) -> str:
    """Escapa el signo $ para que Streamlit no lo interprete como fórmula LaTeX."""
    return texto.replace("$", "\\$")


def avisar(tipo: str, mensaje: str) -> None:
    """Guarda un mensaje para mostrarlo después de st.rerun()."""
    st.session_state["_aviso"] = (tipo, mensaje)


def mostrar_aviso() -> None:
    aviso = st.session_state.pop("_aviso", None)
    if aviso:
        tipo, mensaje = aviso
        {"success": st.success, "error": st.error, "warning": st.warning, "info": st.info}[tipo](md(mensaje))


# --------------------------------------------------------------- selector de periodo
def _fin_de_mes(d: date) -> date:
    return (pd.Timestamp(d) + pd.offsets.MonthEnd(0)).date()


def selector_periodo(t: dict, clave: str, solo_corte: bool = False) -> tuple[date, date]:
    """Selector de periodo compartido entre vistas. Devuelve (desde, hasta)."""
    ss = st.session_state
    primero, ultimo = rango_datos(t)
    if "per_desde" not in ss:
        ss["per_desde"] = date(ultimo.year, 1, 1)
        ss["per_hasta"] = _fin_de_mes(ultimo)
    k_desde, k_hasta, k_atajo = f"{clave}_desde", f"{clave}_hasta", f"{clave}_atajo"
    if k_desde not in ss:
        ss[k_desde] = ss["per_desde"]
    if k_hasta not in ss:
        ss[k_hasta] = ss["per_hasta"]

    def _sincronizar():
        ss["per_desde"], ss["per_hasta"] = ss[k_desde], ss[k_hasta]

    def _atajo():
        opcion = ss.get(k_atajo)
        hoy = date.today()
        if opcion == "Mes de la última póliza":
            d, h = date(ultimo.year, ultimo.month, 1), _fin_de_mes(ultimo)
        elif opcion == "Ejercicio de la última póliza":
            d, h = date(ultimo.year, 1, 1), date(ultimo.year, 12, 31)
        elif opcion == "Mes en curso":
            d, h = date(hoy.year, hoy.month, 1), _fin_de_mes(hoy)
        elif opcion == "Todo el historial":
            d, h = date(primero.year, 1, 1), _fin_de_mes(ultimo)
        else:
            return
        ss["per_desde"], ss["per_hasta"] = d, h
        ss[k_desde], ss[k_hasta] = d, h

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.3, 1, 1])
        c1.selectbox(
            "Periodo rápido",
            ["Mes de la última póliza", "Ejercicio de la última póliza", "Mes en curso", "Todo el historial"],
            index=None,
            placeholder="Elige un atajo…",
            key=k_atajo,
            on_change=_atajo,
        )
        if solo_corte:
            c2.date_input("Ejercicio desde", key=k_desde, format="DD/MM/YYYY", on_change=_sincronizar, disabled=True)
        else:
            c2.date_input("Desde", key=k_desde, format="DD/MM/YYYY", on_change=_sincronizar)
        c3.date_input("Hasta (fecha de corte)", key=k_hasta, format="DD/MM/YYYY", on_change=_sincronizar)
    desde, hasta = ss[k_desde], ss[k_hasta]
    if desde > hasta:
        st.warning("La fecha inicial es posterior a la final; se intercambiaron para el cálculo.")
        desde, hasta = hasta, desde
    return desde, hasta


# ---------------------------------------------------------------- tarjetas
def kpi(etiqueta: str, valor: str, sub: str = "", tono: str = "") -> str:
    return (
        f'<div class="coi-kpi {tono}"><div class="lbl">{html.escape(etiqueta)}</div>'
        f'<div class="val">{html.escape(valor)}</div><div class="sub">{html.escape(sub)}</div></div>'
    )


def fila_kpis(tarjetas: list[str], por_fila: int | None = None) -> None:
    """Rejilla responsiva: se acomoda sola en 1, 2, 3… columnas según el ancho de la pantalla."""
    minimo = 230 if (por_fila or len(tarjetas)) <= 3 else 190
    st.markdown(
        f'<div class="coi-grid" style="grid-template-columns:repeat(auto-fit,minmax({minimo}px,1fr));">'
        + "".join(tarjetas)
        + "</div>",
        unsafe_allow_html=True,
    )


def banda(ok: bool, texto_ok: str, texto_mal: str) -> None:
    clase, texto = ("ok", "✅ " + texto_ok) if ok else ("mal", "⚠️ " + texto_mal)
    st.markdown(f'<div class="coi-banda {clase}">{html.escape(texto)}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------- tablas
def tabla_financiera(encabezados: list[str], filas: list[list], estilos: list[str], numericas: set[int]) -> None:
    """Tabla HTML con formato de estado financiero (sangrías, subtotales y doble subrayado)."""
    partes = ['<div class="coi-tabla-wrap"><table class="coi-fin"><thead><tr>']
    for j, h in enumerate(encabezados):
        partes.append(f'<th class="{"num" if j in numericas else ""}">{html.escape(h)}</th>')
    partes.append("</tr></thead><tbody>")
    for fila, estilo in zip(filas, estilos):
        partes.append(f'<tr class="{estilo}">')
        for j, valor in enumerate(fila):
            clases = []
            if j in numericas:
                clases.append("num")
                if isinstance(valor, (int, float)) and valor < 0:
                    clases.append("neg")
                texto = "" if valor is None else (mxn(valor) if isinstance(valor, (int, float)) else str(valor))
            else:
                texto = "" if valor is None else str(valor)
            partes.append(f'<td class="{" ".join(clases)}">{html.escape(texto)}</td>')
        partes.append("</tr>")
    partes.append("</tbody></table></div>")
    st.markdown("".join(partes), unsafe_allow_html=True)


def estilo_moneda(df: pd.DataFrame, columnas: list[str], pct: list[str] | None = None, fila_total: bool = False):
    """Styler de pandas con formato $ y resaltado opcional de la última fila (totales)."""
    formatos = {c: (lambda v: mxn(v) if pd.notna(v) else "") for c in columnas}
    for c in pct or []:
        formatos[c] = lambda v: f"{v:,.1f}%" if pd.notna(v) else "N/A"
    sty = df.style.format(formatos)
    if fila_total and len(df):
        ultimo = df.index[-1]
        sty = sty.apply(
            lambda fila: ["font-weight:700; background-color:#DBEAFE" if fila.name == ultimo else "" for _ in fila],
            axis=1,
        )
    return sty


def config_plotly(fig, alto: int = 360):
    fig.update_layout(
        height=alto,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#0F172A"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#FFFFFF"),
    )
    fig.update_yaxes(gridcolor="#E2E8F0", zerolinecolor="#CBD5E1", tickprefix="$", separatethousands=True,
                     automargin=True)
    fig.update_xaxes(showgrid=False, automargin=True)
    return fig


PLOTLY_CONFIG = {"displaylogo": False, "responsive": True,
                 "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}
