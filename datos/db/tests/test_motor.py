"""Pruebas del motor contable con los datos de demostración (prototipo de sistema contable).

Ejecutar:  python -m pytest -q      (o simplemente: python tests/test_motor.py)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coi import engine, exportar  # noqa: E402
from coi.db import BaseDatos, IntegridadError, validar_integridad  # noqa: E402

DESDE, HASTA = "2026-01-01", "2026-12-31"


def _bd() -> BaseDatos:
    carpeta = Path(tempfile.mkdtemp(prefix="coi_test_"))
    return BaseDatos(carpeta)


def test_integridad_demo():
    db = _bd()
    assert validar_integridad(db.tablas) == []
    assert len(db.tablas["polizas"]) == 1
    assert len(db.tablas["movimientosPoliza"]) == 22
    assert len(db.tablas["catalogoCuentas"]) == 22
    assert db.tablas["presupuestos"].empty


def test_estado_resultados():
    er = engine.estado_resultados(_bd().tablas, DESDE, HASTA)
    assert er["ventas_netas"] == 2260000.00
    assert er["costo_ventas"] == 1118750.00
    assert er["utilidad_bruta"] == 1141250.00
    assert er["gastos_operacion"] == 530000.00
    assert er["utilidad_operacion"] == 611250.00
    # RIF incluye otros gastos y productos: 200,000 + 120,000 - 119,000 - 328,000
    assert er["rif"] == -127000.00
    assert er["utilidad_antes_impuestos"] == 484250.00
    assert er["impuestos"] == 0.00
    assert er["utilidad_neta"] == 484250.00


def test_balance_cuadra():
    bg = engine.balance_general(_bd().tablas, HASTA)
    assert bg["activo_circulante"] == 7550400.00
    assert bg["activo_no_circulante"] == 4748200.00
    assert bg["total_activo"] == 12298600.00
    assert bg["total_pasivo"] == 3011000.00
    assert bg["total_capital"] == 9287600.00  # 8,803,350 capital social + 484,250 utilidad
    assert bg["cuadra"]


def test_balanza_sumas_iguales():
    _, tot, cuadre = engine.balanza(_bd().tablas, DESDE, HASTA)
    assert cuadre["general"]
    assert tot["cargos"] == tot["abonos"] == 14394350.00


def test_cambios_capital_coincide_con_balance():
    t = _bd().tablas
    eccc = engine.estado_cambios_capital(t, DESDE, HASTA)
    bg = engine.balance_general(t, HASTA)
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
    pid = db.guardar_poliza("2026-02-15", "Ingreso", "Venta de contado", [
        {"cuentaCodigo": "102-01", "cargo": 50000}, {"cuentaCodigo": "401-01", "abono": 50000},
    ])
    assert pid == "POL-002"
    assert validar_integridad(db.tablas) == []
    try:
        db.guardar_poliza("2026-02-15", "Diario", "Descuadrada", [
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
    db2 = BaseDatos(db.dir)  # recarga desde CSV para comprobar persistencia
    assert len(db2.tablas["polizas"]) == 1


def test_respaldos_ida_y_vuelta():
    db = _bd()
    for contenido, nombre in [(db.exportar_excel(), "r.xlsx"), (db.exportar_zip(), "r.zip"), (db.exportar_json(), "r.json")]:
        tablas = BaseDatos.leer_respaldo(contenido, nombre)
        assert validar_integridad(tablas) == []
        assert len(tablas["movimientosPoliza"]) == 22


def test_presupuesto_y_exportaciones():
    db = _bd()
    db.guardar_presupuesto("401-01", "2026-01", 2000000)
    t = db.tablas
    pvr = engine.presupuesto_vs_real(t, ["2026-01"])
    ventas = pvr[pvr["cuentaCodigo"] == "401-01"].iloc[0]
    assert ventas["real"] == 2260000.00 and ventas["semaforo"] == "🟢"
    er = engine.estado_resultados(t, DESDE, HASTA)
    bg = engine.balance_general(t, HASTA)
    df, tot, cua = engine.balanza(t, DESDE, HASTA)
    reportes = [
        exportar.reporte_estado_resultados(er),
        exportar.reporte_balance_general(bg),
        exportar.reporte_balanza(df, tot, cua, DESDE, HASTA),
        exportar.reporte_presupuesto(pvr),
        exportar.reporte_auxiliar(engine.auxiliar(t, "102-01", DESDE, HASTA), DESDE, HASTA),
        exportar.reporte_diario(engine.libro_diario(t, DESDE, HASTA), DESDE, HASTA),
    ]
    empresa = db.datos_empresa()
    assert exportar.generar_pdf(empresa, reportes)[:4] == b"%PDF"
    assert exportar.generar_excel(empresa, reportes)[:2] == b"PK"


def test_admin_presentacion_y_ajuste():
    db = _bd()
    db.actualizar_presentacion("115-01", "Inventarios (Almacén)", "Activo Circulante")
    bg = engine.balance_general(db.tablas, HASTA)
    assert "Inventarios (Almacén)" in set(bg["secciones"]["Activo Circulante"]["nombre"])
    rep = exportar.reporte_balance_general(bg)
    assert any("Inventarios (Almacén)" in str(f[0]) for f in rep["filas"])

    # Balance General: Bancos 1,600,000 -> 1,650,000 contra Capital Social
    aj = engine.ajuste_a_importe(db.tablas, "102-01", 1650000, "301-01", HASTA)
    assert aj["actual"] == 1600000.00 and aj["diferencia"] == 50000.00
    assert aj["movimientos"][0]["cargo"] == 50000.00 and aj["movimientos"][1]["abono"] == 50000.00
    db.guardar_poliza(HASTA, "Ajuste", "Ajuste admin", aj["movimientos"])
    assert engine.importe_en_estado(db.tablas, "102-01", HASTA)["importe"] == 1650000.00
    assert engine.balance_general(db.tablas, HASTA)["cuadra"]

    # Estado de Resultados: Ventas 2,260,000 -> 2,300,000 contra Deudores diversos
    aj = engine.ajuste_a_importe(db.tablas, "401-01", 2300000, "107-01", HASTA)
    assert aj["movimientos"][0]["abono"] == 40000.00
    db.guardar_poliza(HASTA, "Ajuste", "Ajuste admin ventas", aj["movimientos"])
    assert engine.estado_resultados(db.tablas, DESDE, HASTA)["ventas_netas"] == 2300000.00
    assert engine.balance_general(db.tablas, HASTA)["cuadra"]
    assert validar_integridad(db.tablas) == []


def test_csv_editado_en_excel_ansi():
    db = _bd()
    ruta = db.ruta("catalogoCuentas")
    contenido = ruta.read_bytes().decode("utf-8-sig").replace("Bancos", "Bancos Bajío")
    ruta.write_bytes(contenido.encode("cp1252"))  # como lo guarda Excel en Windows
    db2 = BaseDatos(db.dir)
    assert "Bancos Bajío" in set(db2.tablas["catalogoCuentas"]["nombre"])


if __name__ == "__main__":
    pruebas = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for prueba in pruebas:
        prueba()
        print(f"OK  {prueba.__name__}")
    print(f"\n{len(pruebas)} pruebas superadas.")
