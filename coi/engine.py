"""Motor contable de COI-UP.

Funciones puras (no dependen de Streamlit) que reciben el diccionario de tablas
``{"catalogoCuentas": df, "polizas": df, "movimientosPoliza": df, "presupuestos": df}``
y calculan:

* Validación de partida doble de una póliza.
* Saldos por cuenta según su naturaleza (Deudora: cargos - abonos; Acreedora: abonos - cargos).
* Balanza de comprobación, auxiliares (mayor) y libro diario.
* Estado de Resultados, Balance General, Estado de Cambios en el Capital Contable.
* Razones financieras y control presupuestal.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

import numpy as np
import pandas as pd

TOL = 0.005

RUBROS_ACTIVO = ["Activo Circulante", "Activo No Circulante"]
RUBROS_PASIVO = ["Pasivo Corto Plazo", "Pasivo Largo Plazo"]
RUBRO_CAPITAL = "Capital Contable"

# Orientación con la que se presenta cada rubro: "acreedor" = abonos - cargos, "deudor" = cargos - abonos.
ORIENTACION = {
    "Activo Circulante": "deudor",
    "Activo No Circulante": "deudor",
    "Pasivo Corto Plazo": "acreedor",
    "Pasivo Largo Plazo": "acreedor",
    "Capital Contable": "acreedor",
    "Ventas Netas": "acreedor",
    "Costo de Ventas": "deudor",
    "Gastos de Operacion": "deudor",
    "RIF": "acreedor",  # positivo = producto financiero neto; negativo = costo financiero neto
    "Impuestos": "deudor",
}
RUBROS_ER = ["Ventas Netas", "Costo de Ventas", "Gastos de Operacion", "RIF", "Impuestos"]


# --------------------------------------------------------------------- utilidades
def r2(valor) -> float:
    v = round(float(valor), 2)
    return 0.0 if v == 0 else v


def dividir(a: float, b: float) -> float | None:
    return None if b is None or abs(b) < TOL else a / b


def _ts(valor) -> pd.Timestamp | None:
    if valor is None:
        return None
    return pd.Timestamp(valor).normalize()


def _dia_anterior(valor) -> pd.Timestamp:
    return pd.Timestamp(pd.Timestamp(valor).date() - timedelta(days=1))


def limites_periodo(periodo: str) -> tuple[date, date]:
    anio, mes = (int(x) for x in periodo.split("-"))
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def rango_datos(t: dict) -> tuple[date, date]:
    """Primer y último día con pólizas (o el mes actual si no hay)."""
    fechas = pd.to_datetime(t["polizas"]["fecha"], errors="coerce").dropna()
    if fechas.empty:
        hoy = date.today()
        return date(hoy.year, hoy.month, 1), hoy
    return fechas.min().date(), fechas.max().date()


def _es_nulo(valor) -> bool:
    if valor is None:
        return True
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def _numero(valor) -> float | None:
    if _es_nulo(valor) or (isinstance(valor, str) and not valor.strip()):
        return 0.0
    try:
        return round(float(str(valor).replace(",", "").replace("$", "").strip()), 2)
    except ValueError:
        return None


def _importe(df: pd.DataFrame, orientacion: str) -> pd.Series:
    if orientacion == "acreedor":
        return (df["abonos"] - df["cargos"]).round(2)
    return (df["cargos"] - df["abonos"]).round(2)


# ------------------------------------------------------------ partida doble
def limpiar_movimientos(filas) -> list[dict]:
    """Normaliza renglones capturados (dicts o DataFrame) e ignora renglones totalmente vacíos.

    Acepta la cuenta como "101-01" o "101-01 · Caja y Efectivo" en la llave
    ``cuentaCodigo`` o ``cuenta``.
    """
    if isinstance(filas, pd.DataFrame):
        filas = filas.to_dict(orient="records")
    limpias = []
    for i, f in enumerate(filas, start=1):
        cuenta = f.get("cuentaCodigo", f.get("cuenta", ""))
        cuenta = "" if _es_nulo(cuenta) else str(cuenta).split(" · ")[0].strip()
        referencia = f.get("referencia", "")
        referencia = "" if _es_nulo(referencia) else str(referencia).strip()
        cargo = _numero(f.get("cargo"))
        abono = _numero(f.get("abono"))
        if not cuenta and not referencia and cargo == 0 and abono == 0:
            continue
        limpias.append(
            {"renglon": i, "cuentaCodigo": cuenta, "referencia": referencia, "cargo": cargo, "abono": abono}
        )
    return limpias


def validar_poliza(filas, cuentas_validas: set[str] | None = None) -> dict:
    """Compuerta de partida doble.

    Devuelve totales, diferencia y la lista de errores. ``valida`` es True solo si
    Total Cargos == Total Abonos, ambos > 0 y cada renglón es correcto.
    """
    movs = limpiar_movimientos(filas)
    errores: list[str] = []
    for m in movs:
        r = m["renglon"]
        if m["cargo"] is None or m["abono"] is None:
            errores.append(f"Renglón {r}: el importe no es numérico.")
            m["cargo"] = m["cargo"] or 0.0
            m["abono"] = m["abono"] or 0.0
            continue
        if not m["cuentaCodigo"]:
            errores.append(f"Renglón {r}: falta seleccionar la cuenta contable.")
        elif cuentas_validas is not None and m["cuentaCodigo"] not in cuentas_validas:
            errores.append(f"Renglón {r}: la cuenta {m['cuentaCodigo']} no existe en el catálogo.")
        if m["cargo"] < 0 or m["abono"] < 0:
            errores.append(f"Renglón {r}: no se permiten importes negativos.")
        if m["cargo"] > 0 and m["abono"] > 0:
            errores.append(f"Renglón {r}: un movimiento no puede tener cargo y abono a la vez.")
        if m["cargo"] == 0 and m["abono"] == 0:
            errores.append(f"Renglón {r}: el movimiento no tiene importe.")
    total_cargos = r2(sum(m["cargo"] for m in movs))
    total_abonos = r2(sum(m["abono"] for m in movs))
    diferencia = r2(total_cargos - total_abonos)
    if len(movs) < 2:
        errores.append("Una póliza requiere al menos dos movimientos (partida doble).")
    if total_cargos == 0 and total_abonos == 0:
        errores.append("La póliza no tiene importes: Total Cargos y Total Abonos son 0.")
    elif abs(diferencia) > TOL:
        errores.append(f"Póliza descuadrada: la diferencia entre cargos y abonos es {diferencia:,.2f}.")
    return {
        "filas": movs,
        "total_cargos": total_cargos,
        "total_abonos": total_abonos,
        "diferencia": diferencia,
        "cuadrada": abs(diferencia) <= TOL and total_cargos > 0,
        "valida": not errores,
        "errores": errores,
    }


# ------------------------------------------------------------------ consultas
def movimientos_detallados(t: dict, desde=None, hasta=None) -> pd.DataFrame:
    """JOIN movimientosPoliza ⋈ polizas ⋈ catalogoCuentas, filtrado por fecha (inclusive)."""
    movs = t["movimientosPoliza"]
    pol = t["polizas"].rename(columns={"id": "_pol"})
    df = movs.merge(pol, left_on="polizaId", right_on="_pol", how="inner").drop(columns="_pol")
    df = df.merge(t["catalogoCuentas"], left_on="cuentaCodigo", right_on="codigo", how="left").drop(columns="codigo")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    if desde is not None:
        df = df[df["fecha"] >= _ts(desde)]
    if hasta is not None:
        df = df[df["fecha"] <= _ts(hasta)]
    return df.sort_values(["fecha", "polizaId", "id"]).reset_index(drop=True)


def saldos_cuentas(t: dict, desde=None, hasta=None) -> pd.DataFrame:
    """Catálogo completo con cargos, abonos, número de movimientos y saldo según naturaleza."""
    cat = t["catalogoCuentas"].copy()
    m = movimientos_detallados(t, desde, hasta)
    agg = m.groupby("cuentaCodigo").agg(
        cargos=("cargo", "sum"), abonos=("abono", "sum"), movimientos=("id", "count")
    )
    cat = cat.merge(agg, left_on="codigo", right_index=True, how="left")
    cat["cargos"] = cat["cargos"].fillna(0.0).astype(float).round(2)
    cat["abonos"] = cat["abonos"].fillna(0.0).astype(float).round(2)
    cat["movimientos"] = cat["movimientos"].fillna(0).astype(int)
    cat["saldo"] = np.where(
        cat["naturaleza"].eq("Deudora"), cat["cargos"] - cat["abonos"], cat["abonos"] - cat["cargos"]
    ).round(2)
    # Nombre con el que la cuenta se presenta en los estados financieros (lo define el administrador).
    if "nombreReporte" in cat.columns:
        personalizado = cat["nombreReporte"].fillna("").astype(str).str.strip()
    else:
        personalizado = pd.Series("", index=cat.index)
    cat["nombreEstado"] = personalizado.where(personalizado.ne(""), cat["nombre"])
    return cat.sort_values("codigo").reset_index(drop=True)


def resumen_polizas(t: dict, desde=None, hasta=None) -> pd.DataFrame:
    pol = t["polizas"].copy()
    movs = t["movimientosPoliza"]
    g = movs.groupby("polizaId").agg(cargos=("cargo", "sum"), abonos=("abono", "sum"), movimientos=("id", "count"))
    pol = pol.merge(g, left_on="id", right_index=True, how="left")
    pol["cargos"] = pol["cargos"].fillna(0.0).round(2)
    pol["abonos"] = pol["abonos"].fillna(0.0).round(2)
    pol["movimientos"] = pol["movimientos"].fillna(0).astype(int)
    pol["diferencia"] = (pol["cargos"] - pol["abonos"]).round(2)
    pol["cuadrada"] = (pol["diferencia"].abs() <= TOL) & (pol["cargos"] > 0)
    fechas = pd.to_datetime(pol["fecha"], errors="coerce")
    if desde is not None:
        pol = pol[fechas >= _ts(desde)]
        fechas = fechas[fechas >= _ts(desde)]
    if hasta is not None:
        pol = pol[fechas <= _ts(hasta)]
    return pol.sort_values(["fecha", "id"]).reset_index(drop=True)


def estatus_cuadre(t: dict) -> dict:
    movs = t["movimientosPoliza"]
    cargos = r2(movs["cargo"].sum())
    abonos = r2(movs["abono"].sum())
    resumen = resumen_polizas(t)
    descuadradas = resumen.loc[~resumen["cuadrada"], "id"].tolist()
    return {
        "cargos": cargos,
        "abonos": abonos,
        "diferencia": r2(cargos - abonos),
        "descuadradas": descuadradas,
        "cuadrado": abs(cargos - abonos) <= TOL and not descuadradas,
    }


def libro_diario(t: dict, desde=None, hasta=None, tipos: list[str] | None = None) -> pd.DataFrame:
    m = movimientos_detallados(t, desde, hasta)
    if tipos:
        m = m[m["tipo"].isin(tipos)]
    return m[["fecha", "polizaId", "tipo", "concepto", "cuentaCodigo", "nombre", "referencia", "cargo", "abono"]]


def auxiliar(t: dict, cuenta: str, desde=None, hasta=None) -> dict:
    """Mayor auxiliar de una cuenta con saldo acumulado renglón por renglón."""
    cat = t["catalogoCuentas"].set_index("codigo")
    naturaleza = cat.loc[cuenta, "naturaleza"]
    saldo_inicial = 0.0
    if desde is not None:
        previo = saldos_cuentas(t, None, _dia_anterior(desde)).set_index("codigo")
        saldo_inicial = float(previo.loc[cuenta, "saldo"])
    m = movimientos_detallados(t, desde, hasta)
    m = m[m["cuentaCodigo"] == cuenta].copy()
    delta = (m["cargo"] - m["abono"]) if naturaleza == "Deudora" else (m["abono"] - m["cargo"])
    m["saldo"] = (saldo_inicial + delta.cumsum()).round(2)
    total_cargos = r2(m["cargo"].sum())
    total_abonos = r2(m["abono"].sum())
    saldo_final = r2(saldo_inicial + float(delta.sum()))
    return {
        "cuenta": cuenta,
        "nombre": cat.loc[cuenta, "nombre"],
        "naturaleza": naturaleza,
        "rubro": cat.loc[cuenta, "rubro"],
        "saldo_inicial": r2(saldo_inicial),
        "movimientos": m[["fecha", "polizaId", "tipo", "concepto", "referencia", "cargo", "abono", "saldo"]].reset_index(
            drop=True
        ),
        "total_cargos": total_cargos,
        "total_abonos": total_abonos,
        "saldo_final": saldo_final,
    }


# ------------------------------------------------------ balanza de comprobación
COLUMNAS_BALANZA = ["siDeudor", "siAcreedor", "cargos", "abonos", "sfDeudor", "sfAcreedor"]


def balanza(t: dict, desde=None, hasta=None, solo_con_saldo: bool = True) -> tuple[pd.DataFrame, dict, dict]:
    """Balanza de comprobación: saldo inicial, movimientos del periodo y saldo final (deudor/acreedor)."""
    per = saldos_cuentas(t, desde, hasta).set_index("codigo")
    if desde is not None:
        ini = saldos_cuentas(t, None, _dia_anterior(desde)).set_index("codigo")
        si = (ini["cargos"] - ini["abonos"]).reindex(per.index).fillna(0.0)
    else:
        si = pd.Series(0.0, index=per.index)
    df = per[["codigoSAT", "nombre", "naturaleza", "rubro"]].copy()
    df["siDeudor"] = si.clip(lower=0).round(2)
    df["siAcreedor"] = (-si).clip(lower=0).round(2)
    df["cargos"] = per["cargos"]
    df["abonos"] = per["abonos"]
    final = si + per["cargos"] - per["abonos"]
    df["sfDeudor"] = final.clip(lower=0).round(2)
    df["sfAcreedor"] = (-final).clip(lower=0).round(2)
    df = df.reset_index()
    if solo_con_saldo:
        df = df[df[COLUMNAS_BALANZA].abs().sum(axis=1) > TOL]
    df = df.reset_index(drop=True)
    totales = {c: r2(df[c].sum()) for c in COLUMNAS_BALANZA}
    cuadre = {
        "saldos_iniciales": abs(totales["siDeudor"] - totales["siAcreedor"]) <= TOL,
        "movimientos": abs(totales["cargos"] - totales["abonos"]) <= TOL,
        "saldos_finales": abs(totales["sfDeudor"] - totales["sfAcreedor"]) <= TOL,
    }
    cuadre["general"] = all(cuadre.values())
    return df, totales, cuadre


# --------------------------------------------------------- estado de resultados
def estado_resultados(t: dict, desde=None, hasta=None) -> dict:
    s = saldos_cuentas(t, desde, hasta)
    detalle: dict[str, pd.DataFrame] = {}
    totales: dict[str, float] = {}
    for rubro in RUBROS_ER:
        sub = s[s["rubro"] == rubro].copy()
        sub["importe"] = _importe(sub, ORIENTACION[rubro])
        sub = sub[(sub["movimientos"] > 0) | (sub["importe"].abs() > TOL)]
        detalle[rubro] = (
            sub[["codigo", "codigoSAT", "nombreEstado", "naturaleza", "importe"]]
            .rename(columns={"nombreEstado": "nombre"})
            .reset_index(drop=True)
        )
        totales[rubro] = r2(sub["importe"].sum())

    ventas = totales["Ventas Netas"]
    costo = totales["Costo de Ventas"]
    gastos = totales["Gastos de Operacion"]
    rif = totales["RIF"]
    isr = totales["Impuestos"]
    bruta = r2(ventas - costo)
    operacion = r2(bruta - gastos)
    antes_imp = r2(operacion + rif)
    neta = r2(antes_imp - isr)

    gop = detalle["Gastos de Operacion"]
    mascara_dep = gop["nombre"].str.contains("deprecia|amortiza", case=False, regex=True)
    depreciacion = r2(gop.loc[mascara_dep, "importe"].sum())

    lineas = [
        {"signo": "(+)", "concepto": "Ventas Netas", "importe": ventas, "tipo": "rubro", "rubro": "Ventas Netas"},
        {"signo": "(-)", "concepto": "Costo de Ventas", "importe": costo, "tipo": "rubro", "rubro": "Costo de Ventas"},
        {"signo": "(=)", "concepto": "Utilidad Bruta", "importe": bruta, "tipo": "subtotal", "rubro": None},
        {
            "signo": "(-)",
            "concepto": "Gastos de Operación",
            "importe": gastos,
            "tipo": "rubro",
            "rubro": "Gastos de Operacion",
        },
        {"signo": "(=)", "concepto": "Utilidad de Operación (EBIT)", "importe": operacion, "tipo": "subtotal", "rubro": None},
        {
            "signo": "(+/-)",
            "concepto": "Resultado Integral de Financiamiento (RIF)",
            "importe": rif,
            "tipo": "rubro",
            "rubro": "RIF",
        },
        {"signo": "(=)", "concepto": "Utilidad Antes de Impuestos", "importe": antes_imp, "tipo": "subtotal", "rubro": None},
        {"signo": "(-)", "concepto": "Impuestos a la Utilidad (ISR)", "importe": isr, "tipo": "rubro", "rubro": "Impuestos"},
        {"signo": "(=)", "concepto": "Utilidad Neta del Ejercicio", "importe": neta, "tipo": "total", "rubro": None},
    ]
    for linea in lineas:
        linea["pct"] = None if abs(ventas) < TOL else linea["importe"] / ventas * 100

    return {
        "desde": desde,
        "hasta": hasta,
        "ventas_netas": ventas,
        "costo_ventas": costo,
        "utilidad_bruta": bruta,
        "gastos_operacion": gastos,
        "utilidad_operacion": operacion,
        "rif": rif,
        "utilidad_antes_impuestos": antes_imp,
        "impuestos": isr,
        "utilidad_neta": neta,
        "depreciacion": depreciacion,
        "ebitda": r2(operacion + depreciacion),
        "detalle": detalle,
        "lineas": lineas,
    }


# -------------------------------------------------------------- balance general
def balance_general(t: dict, hasta=None, solo_con_saldo: bool = True) -> dict:
    """Balance General al corte, enlazando la utilidad neta del ejercicio en el Capital Contable."""
    if hasta is None:
        hasta = rango_datos(t)[1]
    hasta = _ts(hasta)
    s = saldos_cuentas(t, None, hasta)

    def seccion(rubro: str) -> pd.DataFrame:
        sub = s[s["rubro"] == rubro].copy()
        sub["importe"] = _importe(sub, ORIENTACION[rubro])
        if solo_con_saldo:
            sub = sub[sub["importe"].abs() > TOL]
        return (
            sub[["codigo", "codigoSAT", "nombreEstado", "naturaleza", "importe"]]
            .rename(columns={"nombreEstado": "nombre"})
            .reset_index(drop=True)
        )

    secciones = {r: seccion(r) for r in RUBROS_ACTIVO + RUBROS_PASIVO + [RUBRO_CAPITAL]}
    tot = {r: r2(df["importe"].sum()) for r, df in secciones.items()}

    inicio_ejercicio = pd.Timestamp(year=hasta.year, month=1, day=1)
    utilidad_ejercicio = estado_resultados(t, inicio_ejercicio, hasta)["utilidad_neta"]
    utilidad_acumulada = estado_resultados(t, None, hasta)["utilidad_neta"]
    anteriores = r2(utilidad_acumulada - utilidad_ejercicio)

    capital_resultados = [{"concepto": "Utilidad (Pérdida) Neta del Ejercicio", "importe": utilidad_ejercicio}]
    if abs(anteriores) > TOL:
        capital_resultados.append(
            {"concepto": "Resultados de ejercicios anteriores pendientes de traspaso", "importe": anteriores}
        )

    activo_circulante = tot["Activo Circulante"]
    activo_no_circulante = tot["Activo No Circulante"]
    total_activo = r2(activo_circulante + activo_no_circulante)
    pasivo_cp = tot["Pasivo Corto Plazo"]
    pasivo_lp = tot["Pasivo Largo Plazo"]
    total_pasivo = r2(pasivo_cp + pasivo_lp)
    capital_contribuido = tot[RUBRO_CAPITAL]
    total_capital = r2(capital_contribuido + utilidad_ejercicio + anteriores)
    pasivo_mas_capital = r2(total_pasivo + total_capital)
    diferencia = r2(total_activo - pasivo_mas_capital)

    return {
        "hasta": hasta.date(),
        "secciones": secciones,
        "capital_resultados": capital_resultados,
        "activo_circulante": activo_circulante,
        "activo_no_circulante": activo_no_circulante,
        "total_activo": total_activo,
        "pasivo_cp": pasivo_cp,
        "pasivo_lp": pasivo_lp,
        "total_pasivo": total_pasivo,
        "capital_cuentas": capital_contribuido,
        "utilidad_ejercicio": utilidad_ejercicio,
        "resultados_anteriores_pendientes": anteriores,
        "total_capital": total_capital,
        "pasivo_mas_capital": pasivo_mas_capital,
        "diferencia": diferencia,
        "cuadra": abs(diferencia) <= TOL,
    }


# ---------------------------------------- estado de cambios en el capital contable
def estado_cambios_capital(t: dict, desde, hasta) -> pd.DataFrame:
    desde, hasta = _ts(desde), _ts(hasta)
    corte = _dia_anterior(desde)
    ini = saldos_cuentas(t, None, corte).set_index("codigo")
    per = saldos_cuentas(t, desde, hasta).set_index("codigo")
    cuentas = t["catalogoCuentas"]
    cuentas = cuentas[cuentas["rubro"] == RUBRO_CAPITAL].sort_values("codigo")

    columnas: dict[str, list[float]] = {}
    for _, c in cuentas.iterrows():
        inicial = r2(ini.loc[c["codigo"], "abonos"] - ini.loc[c["codigo"], "cargos"])
        movimiento = r2(per.loc[c["codigo"], "abonos"] - per.loc[c["codigo"], "cargos"])
        if abs(inicial) <= TOL and abs(movimiento) <= TOL:
            continue
        columnas[f"{c['codigo']} {c['nombre']}"] = [inicial, movimiento, 0.0, r2(inicial + movimiento)]

    res_inicial = estado_resultados(t, None, corte)["utilidad_neta"]
    res_periodo = estado_resultados(t, desde, hasta)["utilidad_neta"]
    columnas["Resultado del ejercicio"] = [res_inicial, 0.0, res_periodo, r2(res_inicial + res_periodo)]

    df = pd.DataFrame(
        columnas,
        index=[
            f"Saldo inicial al {corte.strftime('%d/%m/%Y')}",
            "Aportaciones, reembolsos y traspasos del periodo",
            "Utilidad (pérdida) neta del periodo",
            f"Saldo final al {hasta.strftime('%d/%m/%Y')}",
        ],
    )
    df["Total Capital Contable"] = df.sum(axis=1).round(2)
    df.index.name = "Concepto"
    return df


# --------------------------------------------------------- razones financieras
def razones_financieras(bg: dict, er: dict) -> list[dict]:
    ac = bg["activo_circulante"]
    pc = bg["pasivo_cp"]
    inventarios = r2(
        bg["secciones"]["Activo Circulante"]
        .loc[lambda d: d["nombre"].str.contains("inventario|almac", case=False, regex=True), "importe"]
        .sum()
    )
    activo = bg["total_activo"]
    pasivo = bg["total_pasivo"]
    capital = bg["total_capital"]
    ventas = er["ventas_netas"]

    def evalua(valor, bueno, regular, mayor_es_mejor=True):
        if valor is None:
            return "⚪ Sin dato"
        if mayor_es_mejor:
            return "🟢 Sana" if valor >= bueno else ("🟡 Vigilar" if valor >= regular else "🔴 Riesgo")
        return "🟢 Sana" if valor <= bueno else ("🟡 Vigilar" if valor <= regular else "🔴 Riesgo")

    liquidez = dividir(ac, pc)
    acida = dividir(ac - inventarios, pc)
    endeudamiento = dividir(pasivo, activo)
    apalancamiento = dividir(pasivo, capital)
    margen_bruto = dividir(er["utilidad_bruta"], ventas)
    margen_op = dividir(er["utilidad_operacion"], ventas)
    margen_neto = dividir(er["utilidad_neta"], ventas)
    roa = dividir(er["utilidad_neta"], activo)
    roe = dividir(er["utilidad_neta"], capital)

    return [
        {"categoria": "Liquidez", "razon": "Liquidez circulante", "formula": "Activo Circulante / Pasivo a Corto Plazo",
         "valor": liquidez, "formato": "veces", "evaluacion": evalua(liquidez, 1.5, 1.0)},
        {"categoria": "Liquidez", "razon": "Prueba ácida", "formula": "(Activo Circulante - Inventarios) / Pasivo a Corto Plazo",
         "valor": acida, "formato": "veces", "evaluacion": evalua(acida, 1.0, 0.7)},
        {"categoria": "Liquidez", "razon": "Capital de trabajo", "formula": "Activo Circulante - Pasivo a Corto Plazo",
         "valor": r2(ac - pc), "formato": "moneda", "evaluacion": evalua(ac - pc, 0.01, -0.01)},
        {"categoria": "Solvencia", "razon": "Endeudamiento", "formula": "Pasivo Total / Activo Total",
         "valor": endeudamiento, "formato": "porcentaje", "evaluacion": evalua(endeudamiento, 0.5, 0.7, False)},
        {"categoria": "Solvencia", "razon": "Apalancamiento", "formula": "Pasivo Total / Capital Contable",
         "valor": apalancamiento, "formato": "veces", "evaluacion": evalua(apalancamiento, 1.0, 2.0, False)},
        {"categoria": "Rentabilidad", "razon": "Margen bruto", "formula": "Utilidad Bruta / Ventas Netas",
         "valor": margen_bruto, "formato": "porcentaje", "evaluacion": evalua(margen_bruto, 0.30, 0.15)},
        {"categoria": "Rentabilidad", "razon": "Margen de operación", "formula": "Utilidad de Operación / Ventas Netas",
         "valor": margen_op, "formato": "porcentaje", "evaluacion": evalua(margen_op, 0.10, 0.03)},
        {"categoria": "Rentabilidad", "razon": "Margen neto", "formula": "Utilidad Neta / Ventas Netas",
         "valor": margen_neto, "formato": "porcentaje", "evaluacion": evalua(margen_neto, 0.08, 0.02)},
        {"categoria": "Rentabilidad", "razon": "ROA (rendimiento del activo)", "formula": "Utilidad Neta / Activo Total",
         "valor": roa, "formato": "porcentaje", "evaluacion": evalua(roa, 0.01, 0.0)},
        {"categoria": "Rentabilidad", "razon": "ROE (rendimiento del capital)", "formula": "Utilidad Neta / Capital Contable",
         "valor": roe, "formato": "porcentaje", "evaluacion": evalua(roe, 0.015, 0.0)},
        {"categoria": "Rentabilidad", "razon": "EBITDA", "formula": "Utilidad de Operación + Depreciaciones y amortizaciones",
         "valor": er["ebitda"], "formato": "moneda", "evaluacion": evalua(er["ebitda"], 0.01, -0.01)},
    ]


# --------------------------------------------------------- control presupuestal
def _semaforo(tipo: str, ejecucion: float) -> tuple[str, str]:
    if ejecucion is None or np.isnan(ejecucion):
        return "⚪", "Sin presupuesto"
    if tipo == "Ingreso":
        if ejecucion >= 100:
            return "🟢", "Meta alcanzada"
        if ejecucion >= 90:
            return "🟡", "Cerca de la meta"
        return "🔴", "Por debajo de la meta"
    if ejecucion > 100:
        return "🔴", "Sobregiro"
    if ejecucion >= 90:
        return "🟡", "Al límite"
    return "🟢", "Dentro de presupuesto"


COLUMNAS_PRESUPUESTO = [
    "id", "periodo", "cuentaCodigo", "nombre", "rubro", "tipo", "montoPresupuestado",
    "real", "variacion", "ejecucion", "semaforo", "estatus",
]


def presupuesto_vs_real(t: dict, periodos: list[str] | None = None) -> pd.DataFrame:
    pres = t["presupuestos"].copy()
    if periodos:
        pres = pres[pres["periodo"].isin(periodos)]
    pres = pres[pres["periodo"].str.match(r"^\d{4}-\d{2}$")]
    if pres.empty:
        return pd.DataFrame(columns=COLUMNAS_PRESUPUESTO)
    cat = t["catalogoCuentas"].set_index("codigo")
    reales = {}
    for periodo in pres["periodo"].unique():
        d, h = limites_periodo(periodo)
        reales[periodo] = saldos_cuentas(t, d, h).set_index("codigo")["saldo"]
    pres["nombre"] = pres["cuentaCodigo"].map(cat["nombre"])
    pres["rubro"] = pres["cuentaCodigo"].map(cat["rubro"])
    naturaleza = pres["cuentaCodigo"].map(cat["naturaleza"])
    pres["tipo"] = np.where(naturaleza.eq("Acreedora"), "Ingreso", "Gasto")
    pres["real"] = [r2(reales[p].get(c, 0.0)) for p, c in zip(pres["periodo"], pres["cuentaCodigo"])]
    pres["variacion"] = (pres["real"] - pres["montoPresupuestado"]).round(2)
    pres["ejecucion"] = [
        (r / m * 100) if abs(m) > TOL else np.nan for r, m in zip(pres["real"], pres["montoPresupuestado"])
    ]
    semaforos = [_semaforo(tp, ej) for tp, ej in zip(pres["tipo"], pres["ejecucion"])]
    pres["semaforo"] = [s[0] for s in semaforos]
    pres["estatus"] = [s[1] for s in semaforos]
    return pres[COLUMNAS_PRESUPUESTO].sort_values(["periodo", "cuentaCodigo"]).reset_index(drop=True)


# ----------------------------------------------------------- series para gráficas
def serie_mensual(t: dict, desde=None, hasta=None) -> pd.DataFrame:
    columnas = ["mes"] + RUBROS_ER + ["Costos y Gastos", "Utilidad Neta"]
    m = movimientos_detallados(t, desde, hasta)
    m = m[m["rubro"].isin(RUBROS_ER)].copy()
    if m.empty:
        return pd.DataFrame(columns=columnas)
    m["mes"] = m["fecha"].dt.strftime("%Y-%m")
    orient = m["rubro"].map(ORIENTACION)
    m["importe"] = np.where(orient.eq("acreedor"), m["abono"] - m["cargo"], m["cargo"] - m["abono"])
    piv = m.pivot_table(index="mes", columns="rubro", values="importe", aggfunc="sum", fill_value=0.0)
    for rubro in RUBROS_ER:
        if rubro not in piv.columns:
            piv[rubro] = 0.0
    piv["Costos y Gastos"] = piv["Costo de Ventas"] + piv["Gastos de Operacion"]
    piv["Utilidad Neta"] = (
        piv["Ventas Netas"] - piv["Costo de Ventas"] - piv["Gastos de Operacion"] + piv["RIF"] - piv["Impuestos"]
    )
    piv = piv.reset_index()
    piv.columns.name = None
    return piv[columnas].round(2)


# ------------------------------------------------- ajustes desde el panel de administrador
RUBROS_BALANCE_GENERAL = RUBROS_ACTIVO + RUBROS_PASIVO + [RUBRO_CAPITAL]


def importe_en_estado(t: dict, cuenta: str, fecha) -> dict:
    """Importe con el que la cuenta aparece en su estado financiero a la fecha indicada.

    Balance General: saldo acumulado a la fecha. Estado de Resultados: del 1 de enero a la fecha.
    El signo sigue la orientación del bloque (p. ej. Ventas en positivo, Depreciación acumulada en negativo).
    """
    fecha = _ts(fecha)
    cat = t["catalogoCuentas"].set_index("codigo")
    rubro = cat.loc[cuenta, "rubro"]
    es_balance = rubro in RUBROS_BALANCE_GENERAL
    desde = None if es_balance else pd.Timestamp(year=fecha.year, month=1, day=1)
    fila = saldos_cuentas(t, desde, fecha).set_index("codigo").loc[cuenta]
    orientacion = ORIENTACION[rubro]
    importe = fila["abonos"] - fila["cargos"] if orientacion == "acreedor" else fila["cargos"] - fila["abonos"]
    return {
        "importe": r2(importe),
        "rubro": rubro,
        "orientacion": orientacion,
        "estado": "Balance General" if es_balance else "Estado de Resultados",
        "desde": None if desde is None else desde.date(),
        "hasta": fecha.date(),
    }


def ajuste_a_importe(t: dict, cuenta: str, nuevo_importe: float, contrapartida: str, fecha,
                     referencia: str = "Ajuste administrativo") -> dict:
    """Calcula la póliza de ajuste (partida doble) que lleva la cuenta al importe deseado en su estado."""
    if cuenta == contrapartida:
        raise ValueError("La cuenta de contrapartida debe ser distinta de la cuenta ajustada.")
    info = importe_en_estado(t, cuenta, fecha)
    diferencia = r2(float(nuevo_importe) - info["importe"])
    monto = abs(diferencia)
    # En bloques de orientación deudora un cargo aumenta el importe presentado; en los acreedores, un abono.
    cargo_a_cuenta = (diferencia > 0) == (info["orientacion"] == "deudor")
    movimientos = []
    if monto > TOL:
        movimientos = [
            {"cuentaCodigo": cuenta, "referencia": referencia,
             "cargo": monto if cargo_a_cuenta else 0.0, "abono": 0.0 if cargo_a_cuenta else monto},
            {"cuentaCodigo": contrapartida, "referencia": referencia,
             "cargo": 0.0 if cargo_a_cuenta else monto, "abono": monto if cargo_a_cuenta else 0.0},
        ]
    return {**info, "actual": info["importe"], "nuevo": r2(nuevo_importe), "diferencia": diferencia,
            "movimientos": movimientos}


def simular(t: dict, fecha, movimientos: list[dict], tipo: str = "Ajuste") -> dict:
    """Devuelve una copia de las tablas con una póliza adicional (no guarda nada)."""
    copia = dict(t)
    pol = pd.DataFrame([{"id": "SIMULADA", "fecha": _ts(fecha).strftime("%Y-%m-%d"), "tipo": tipo,
                         "concepto": "Simulación"}])
    movs = pd.DataFrame(
        [{"id": f"SIM-{i}", "polizaId": "SIMULADA", **m} for i, m in enumerate(movimientos)],
        columns=t["movimientosPoliza"].columns,
    )
    copia["polizas"] = pd.concat([t["polizas"], pol], ignore_index=True)
    copia["movimientosPoliza"] = pd.concat([t["movimientosPoliza"], movs], ignore_index=True) if len(movs) else t["movimientosPoliza"]
    return copia