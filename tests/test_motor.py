"""Pruebas del motor contable con los datos de demostración.

Ejecutar:  python -m pytest -q      (o simplemente: python tests/test_motor.py)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coi import engine, exportar  # noqa: E402
from coi.db import BaseDatos, IntegridadError, validar_integridad  # noqa: E402


def _bd() -> BaseDatos:
    carpeta = Path(tempfile.mkdtemp(prefix="coi_test_"))
    return BaseDatos(carpeta)


def test_integridad_demo():
    db = _bd()
    assert validar_integridad(db.tablas) == []
    assert len(db.tablas["polizas"]) == 6


def test_estado_resultados():
    er = engine.estado_resultados(_bd().tablas, "2026-11-01", "2026-11-30")
    assert er["ventas_netas"] == 440000.00
    assert er["costo_ventas"] == 264000.00
    assert er["utilidad_bruta"] == 176000.00
    assert er["gastos_operacion"] == 109125.00
    assert er["utilidad_operacion"] == 66875.00
    assert er["rif"] == -8000.00
    assert er["utilidad_antes_impuestos"] == 58875.00
    assert er["impuestos"] == 17662.50
    assert er["utilidad_neta"] == 41212.50


def test_balance_cuadra():
    bg = engine.balance_general(_bd().tablas, "2026-11-30")
    assert bg["activo_circulante"] == 980400.00
    assert bg["total_activo"] == 2619275.00
    assert bg["total_pasivo"] == 863062.50
    assert bg["total_capital"] == 1756212.50
    assert bg["cuadra"]


def test_balanza_sumas_iguales():
    _, tot, cuadre = engine.balanza(_bd().tablas, "2026-11-01", "2026-11-30")
    assert cuadre["general"]
    assert tot["cargos"] == tot["abonos"]


def test_cambios_capital_coincide_con_balance():
    t = _bd().tablas
    eccc = engine.estado_cambios_capital(t, "2026-11-01", "2026-11-30")
    bg = engine.balance_general(t, "2026-11-30")
    assert round(eccc["Total Capital Contable"].iloc[-1], 2) == bg["total_capital"]


def test_compuerta_partida_doble():
    v = engine.validar_poliza([{"cuenta": "101-01 · Caja", "cargo": 100}, {"cuenta": "401-01", "abono": 90}])
    assert not v["valida"] and v["diferencia"] == 10
    v = engine.validar_poliza([{"cuenta": "101-01", "cargo": 0}, {"cuenta": "401-01", "abono": 0}])
    assert not v["valida"]
    v = engine.validar_poliza([{"cuenta": "101-01", "cargo": 100}, {"cuenta": "401-01", "abono": 100}])
    assert v["valida"] and v["cuadrada"]


def test_alta_poliza_y_reglas_relacionales():
    db = _bd()
    pid = db.guardar_poliza("2026-11-30", "Ingreso", "Prueba", [
        {"cuentaCodigo": "102-01", "cargo": 1160}, {"cuentaCodigo": "401-01", "abono": 1000},
        {"cuentaCodigo": "208-01", "abono": 160},
    ])
    assert pid == "POL-007"
    assert validar_integridad(db.tablas) == []
    try:
        db.guardar_poliza("2026-11-30", "Diario", "Descuadrada", [
            {"cuentaCodigo": "102-01", "cargo": 10}, {"cuentaCodigo": "401-01", "abono": 5}])
        raise AssertionError("Debió rechazar la póliza descuadrada")
    except IntegridadError:
        pass
    try:
        db.agregar_cuenta("101-01", "", "Duplicada", "Deudora", "Activo Circulante")
        raise AssertionError("Debió rechazar el código duplicado")
    except IntegridadError:
        pass
    try:
        db.eliminar_cuenta("102-01")
        raise AssertionError("Debió impedir borrar una cuenta con movimientos")
    except IntegridadError:
        pass
    db.eliminar_poliza(pid)
    assert pid not in set(db.tablas["movimientosPoliza"]["polizaId"])
    # recarga desde CSV para comprobar persistencia
    db2 = BaseDatos(db.dir)
    assert len(db2.tablas["polizas"]) == 6


def test_respaldos_ida_y_vuelta():
    db = _bd()
    for contenido, nombre in [(db.exportar_excel(), "r.xlsx"), (db.exportar_zip(), "r.zip"), (db.exportar_json(), "r.json")]:
        tablas = BaseDatos.leer_respaldo(contenido, nombre)
        assert validar_integridad(tablas) == []
        assert len(tablas["movimientosPoliza"]) == 39


def test_presupuesto_y_exportaciones():
    db = _bd()
    t = db.tablas
    pvr = engine.presupuesto_vs_real(t, ["2026-11"])
    ventas = pvr[pvr["cuentaCodigo"] == "401-01"].iloc[0]
    assert ventas["real"] == 440000.00 and ventas["semaforo"] == "🟢"
    er = engine.estado_resultados(t, "2026-11-01", "2026-11-30")
    bg = engine.balance_general(t, "2026-11-30")
    df, tot, cua = engine.balanza(t, "2026-11-01", "2026-11-30")
    reportes = [
        exportar.reporte_estado_resultados(er),
        exportar.reporte_balance_general(bg),
        exportar.reporte_cambios_capital(engine.estado_cambios_capital(t, "2026-11-01", "2026-11-30"),
                                         "2026-11-01", "2026-11-30"),
        exportar.reporte_balanza(df, tot, cua, "2026-11-01", "2026-11-30"),
        exportar.reporte_razones(engine.razones_financieras(bg, er), "2026-11-01", "2026-11-30"),
        exportar.reporte_presupuesto(pvr),
        exportar.reporte_auxiliar(engine.auxiliar(t, "102-01", "2026-11-01", "2026-11-30"), "2026-11-01", "2026-11-30"),
        exportar.reporte_diario(engine.libro_diario(t, "2026-11-01", "2026-11-30"), "2026-11-01", "2026-11-30"),
    ]
    empresa = db.datos_empresa()
    assert exportar.generar_pdf(empresa, reportes)[:4] == b"%PDF"
    assert exportar.generar_excel(empresa, reportes)[:2] == b"PK"


def test_admin_presentacion_y_ajuste():
    db = _bd()
    # Nombre y rubro personalizados se reflejan en los estados y en las exportaciones
    db.actualizar_presentacion("102-01", "Bancos", "Activo Circulante")
    bg = engine.balance_general(db.tablas, "2026-11-30")
    assert "Bancos" in set(bg["secciones"]["Activo Circulante"]["nombre"])
    rep = exportar.reporte_balance_general(bg)
    assert any("Bancos" in str(f[0]) and "Nacionales" not in str(f[0]) for f in rep["filas"])

    # Ajuste de un importe de Balance General (Bancos 589,000 -> 600,000 contra Resultado de ejercicios anteriores)
    aj = engine.ajuste_a_importe(db.tablas, "102-01", 600000, "304-01", "2026-11-30")
    assert aj["actual"] == 589000.00 and aj["diferencia"] == 11000.00
    assert aj["movimientos"][0]["cargo"] == 11000.00 and aj["movimientos"][1]["abono"] == 11000.00
    db.guardar_poliza("2026-11-30", "Ajuste", "Ajuste admin", aj["movimientos"])
    assert engine.importe_en_estado(db.tablas, "102-01", "2026-11-30")["importe"] == 600000.00
    assert engine.balance_general(db.tablas, "2026-11-30")["cuadra"]

    # Ajuste de una cuenta de resultados (Ventas 440,000 -> 450,000 contra Clientes)
    aj = engine.ajuste_a_importe(db.tablas, "401-01", 450000, "105-01", "2026-11-30")
    assert aj["movimientos"][0]["abono"] == 10000.00
    db.guardar_poliza("2026-11-30", "Ajuste", "Ajuste admin ventas", aj["movimientos"])
    er = engine.estado_resultados(db.tablas, "2026-01-01", "2026-11-30")
    assert er["ventas_netas"] == 450000.00
    assert engine.balance_general(db.tablas, "2026-11-30")["cuadra"]

    # Cuenta complementaria: depreciación acumulada se presenta en negativo y también se puede ajustar
    aj = engine.ajuste_a_importe(db.tablas, "171-01", -80000, "604-01", "2026-11-30")
    db.guardar_poliza("2026-11-30", "Ajuste", "Ajuste depreciación", aj["movimientos"])
    assert engine.importe_en_estado(db.tablas, "171-01", "2026-11-30")["importe"] == -80000.00
    assert engine.balance_general(db.tablas, "2026-11-30")["cuadra"]
    assert validar_integridad(db.tablas) == []


if __name__ == "__main__":
    pruebas = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for prueba in pruebas:
        prueba()
        print(f"OK  {prueba.__name__}")
    print(f"\n{len(pruebas)} pruebas superadas.")
    shutil.rmtree(Path(tempfile.gettempdir()) / "coi_test_", ignore_errors=True)
