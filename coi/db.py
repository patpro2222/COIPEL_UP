"""Capa de datos relacional de COI-UP.

La "base de datos" son 5 archivos CSV (uno por tabla) dentro de ``datos/db``.
Esta clase los carga en memoria como DataFrames de pandas y se encarga de:

* Llaves primarias (PK) únicas y no vacías.
* Llaves foráneas (FK) válidas:
    movimientosPoliza.polizaId     -> polizas.id            (ON DELETE CASCADE)
    movimientosPoliza.cuentaCodigo -> catalogoCuentas.codigo (ON DELETE RESTRICT)
    presupuestos.cuentaCodigo      -> catalogoCuentas.codigo (ON DELETE RESTRICT)
* Escritura atómica (archivo temporal + reemplazo) para no corromper los CSV.
* Respaldos en Excel (.xlsx), ZIP de CSV y JSON, e importación validada.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import threading
import zipfile
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = BASE_DIR / "datos" / "demo"
DB_DIR = BASE_DIR / "datos" / "db"

TOL = 0.005  # medio centavo: tolerancia para comparar importes

NATURALEZAS = ["Deudora", "Acreedora"]
TIPOS_POLIZA = ["Ingreso", "Egreso", "Diario", "Ajuste"]
ESTADOS_FINANCIEROS = ["Balance General", "Estado de Resultados"]
RUBROS_BALANCE = [
    "Activo Circulante",
    "Activo No Circulante",
    "Pasivo Corto Plazo",
    "Pasivo Largo Plazo",
    "Capital Contable",
]
RUBROS_RESULTADOS = ["Ventas Netas", "Costo de Ventas", "Gastos de Operacion", "RIF", "Impuestos"]
RUBROS = RUBROS_BALANCE + RUBROS_RESULTADOS

# Naturaleza "normal" sugerida para cada rubro (se puede cambiar, p. ej. cuentas complementarias).
NATURALEZA_SUGERIDA = {
    "Activo Circulante": "Deudora",
    "Activo No Circulante": "Deudora",
    "Pasivo Corto Plazo": "Acreedora",
    "Pasivo Largo Plazo": "Acreedora",
    "Capital Contable": "Acreedora",
    "Ventas Netas": "Acreedora",
    "Costo de Ventas": "Deudora",
    "Gastos de Operacion": "Deudora",
    "RIF": "Deudora",
    "Impuestos": "Deudora",
}

ESQUEMA: dict[str, dict] = {
    "catalogoCuentas": {
        "archivo": "catalogo_cuentas.csv",
        "pk": "codigo",
        "columnas": ["codigo", "codigoSAT", "nombre", "naturaleza", "estadoFinanciero", "rubro", "nombreReporte"],
        "numericas": [],
        # Columnas que pueden faltar en respaldos antiguos; se crean vacías.
        "opcionales": ["nombreReporte"],
    },
    "polizas": {
        "archivo": "polizas.csv",
        "pk": "id",
        "columnas": ["id", "fecha", "tipo", "concepto"],
        "numericas": [],
    },
    "movimientosPoliza": {
        "archivo": "movimientos_poliza.csv",
        "pk": "id",
        "columnas": ["id", "polizaId", "cuentaCodigo", "referencia", "cargo", "abono"],
        "numericas": ["cargo", "abono"],
    },
    "presupuestos": {
        "archivo": "presupuestos.csv",
        "pk": "id",
        "columnas": ["id", "cuentaCodigo", "periodo", "montoPresupuestado"],
        "numericas": ["montoPresupuestado"],
    },
    "empresa": {
        "archivo": "empresa.csv",
        "pk": "clave",
        "columnas": ["clave", "valor"],
        "numericas": [],
    },
}

TABLAS_OBLIGATORIAS = ["catalogoCuentas", "polizas", "movimientosPoliza", "presupuestos"]

# (tabla hija, columna FK, tabla padre, columna PK)
RELACIONES = [
    ("movimientosPoliza", "polizaId", "polizas", "id"),
    ("movimientosPoliza", "cuentaCodigo", "catalogoCuentas", "codigo"),
    ("presupuestos", "cuentaCodigo", "catalogoCuentas", "codigo"),
]

PATRON_CODIGO = re.compile(r"^\d{3}-\d{2}(-\d{2,3})?$")
PATRON_PERIODO = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

EMPRESA_DEFAULT = {
    "razon_social": "Mi Empresa, S.A. de C.V.",
    "rfc": "XAXX010101000",
    "domicilio": "",
    "regimen_fiscal": "601 - General de Ley Personas Morales",
    "moneda": "MXN",
}


class IntegridadError(ValueError):
    """Se lanza cuando una operación violaría una regla de negocio o de integridad."""


def estado_de_rubro(rubro: str) -> str:
    return "Balance General" if rubro in RUBROS_BALANCE else "Estado de Resultados"


def tabla_vacia(nombre: str) -> pd.DataFrame:
    cfg = ESQUEMA[nombre]
    df = pd.DataFrame({c: pd.Series(dtype="float64" if c in cfg["numericas"] else "object") for c in cfg["columnas"]})
    return df


def _anexar(df: pd.DataFrame, filas: list[dict]) -> pd.DataFrame:
    """Agrega filas sin advertencias de pandas cuando la tabla está vacía."""
    nuevas = pd.DataFrame(filas, columns=df.columns)
    if df.empty:
        return nuevas.reset_index(drop=True)
    return pd.concat([df, nuevas], ignore_index=True)


def _normalizar_periodo(valor: str) -> str:
    valor = str(valor).strip()
    if PATRON_PERIODO.match(valor):
        return valor
    fecha = pd.to_datetime(valor, errors="coerce")
    return "" if pd.isna(fecha) else fecha.strftime("%Y-%m")


def normalizar(nombre: str, df: pd.DataFrame) -> pd.DataFrame:
    """Asegura columnas, tipos y formatos de una tabla."""
    cfg = ESQUEMA[nombre]
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for opcional in cfg.get("opcionales", []):
        if opcional not in df.columns:
            df[opcional] = ""
    faltan = [c for c in cfg["columnas"] if c not in df.columns]
    if faltan:
        raise IntegridadError(f"La tabla '{nombre}' no tiene las columnas: {', '.join(faltan)}")
    df = df[cfg["columnas"]]
    for col in cfg["columnas"]:
        if col in cfg["numericas"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float).round(2)
        else:
            df[col] = df[col].fillna("").astype(str).str.strip()
    if nombre == "polizas" and len(df):
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    if nombre == "presupuestos" and len(df):
        df["periodo"] = df["periodo"].map(_normalizar_periodo)
    return df.reset_index(drop=True)


def validar_integridad(tablas: dict[str, pd.DataFrame]) -> list[str]:
    """Revisa PK, FK y reglas contables. Devuelve una lista de problemas (vacía = todo correcto)."""
    errores: list[str] = []
    for nombre, cfg in ESQUEMA.items():
        df = tablas[nombre]
        pk = cfg["pk"]
        vacios = int(df[pk].eq("").sum())
        if vacios:
            errores.append(f"{nombre}: {vacios} registro(s) sin llave primaria '{pk}'.")
        dup = df.loc[df[pk].duplicated() & df[pk].ne(""), pk].unique()
        if len(dup):
            errores.append(f"{nombre}: llave primaria '{pk}' duplicada ({', '.join(map(str, dup[:5]))}).")
    for hija, fk, padre, pk in RELACIONES:
        validos = set(tablas[padre][pk])
        huerfanos = tablas[hija][~tablas[hija][fk].isin(validos)]
        if len(huerfanos):
            ejemplos = ", ".join(map(str, huerfanos[fk].unique()[:5]))
            errores.append(
                f"{hija}.{fk}: {len(huerfanos)} registro(s) apuntan a un '{padre}' inexistente ({ejemplos})."
            )
    cat = tablas["catalogoCuentas"]
    if (~cat["naturaleza"].isin(NATURALEZAS)).any():
        errores.append("catalogoCuentas: hay cuentas con naturaleza distinta de Deudora/Acreedora.")
    if (~cat["rubro"].isin(RUBROS)).any():
        errores.append("catalogoCuentas: hay cuentas con un rubro no reconocido.")
    incongruentes = cat[cat["rubro"].map(estado_de_rubro) != cat["estadoFinanciero"]]
    if len(incongruentes):
        errores.append(
            "catalogoCuentas: el estado financiero no corresponde al rubro en "
            + ", ".join(incongruentes["codigo"].head(5))
            + "."
        )
    pol = tablas["polizas"]
    if pol["fecha"].eq("").any():
        errores.append("polizas: hay pólizas sin fecha válida.")
    if (~pol["tipo"].isin(TIPOS_POLIZA)).any():
        errores.append("polizas: hay pólizas con tipo no válido.")
    movs = tablas["movimientosPoliza"]
    if ((movs["cargo"] < 0) | (movs["abono"] < 0)).any():
        errores.append("movimientosPoliza: hay importes negativos.")
    if ((movs["cargo"] > 0) & (movs["abono"] > 0)).any():
        errores.append("movimientosPoliza: hay renglones con cargo y abono simultáneos.")
    sumas = movs.groupby("polizaId")[["cargo", "abono"]].sum()
    descuadradas = sumas[(sumas["cargo"] - sumas["abono"]).abs() > TOL]
    if len(descuadradas):
        errores.append(
            "Partida doble: pólizas descuadradas (" + ", ".join(descuadradas.index[:5]) + ")."
        )
    sin_movs = set(pol["id"]) - set(movs["polizaId"])
    if sin_movs:
        errores.append("polizas: pólizas sin movimientos (" + ", ".join(sorted(sin_movs)[:5]) + ").")
    pres = tablas["presupuestos"]
    if pres["periodo"].eq("").any():
        errores.append("presupuestos: hay presupuestos sin periodo válido (AAAA-MM).")
    if pres.duplicated(subset=["cuentaCodigo", "periodo"]).any():
        errores.append("presupuestos: hay más de un presupuesto para la misma cuenta y periodo.")
    return errores


def _siguiente_folio(serie: pd.Series, prefijo: str, digitos: int, cuantos: int = 1) -> list[str]:
    numeros = serie.astype(str).str.extract(r"(\d+)$")[0].dropna().astype(int)
    inicio = int(numeros.max()) + 1 if len(numeros) else 1
    return [f"{prefijo}-{n:0{digitos}d}" for n in range(inicio, inicio + cuantos)]


class BaseDatos:
    """Repositorio relacional sobre CSV."""

    def __init__(
        self,
        directorio: Path | str = DB_DIR,
        demo: Path | str = DEMO_DIR,
        al_guardar: Callable[[list[Path]], None] | None = None,
    ):
        self.dir = Path(directorio)
        self.demo_dir = Path(demo)
        self.al_guardar = al_guardar
        self._lock = threading.RLock()
        self.version = 0
        self.dir.mkdir(parents=True, exist_ok=True)
        if not all((self.dir / cfg["archivo"]).exists() for cfg in ESQUEMA.values()):
            self._copiar_demo(solo_faltantes=True)
        self.tablas: dict[str, pd.DataFrame] = self._cargar_de(self.dir)

    # ------------------------------------------------------------------ E/S
    def ruta(self, nombre: str) -> Path:
        return self.dir / ESQUEMA[nombre]["archivo"]

    @property
    def rutas(self) -> list[Path]:
        return [self.ruta(n) for n in ESQUEMA]

    @staticmethod
    def _leer_csv(ruta: Path, nombre: str) -> pd.DataFrame:
        if not ruta.exists():
            return tabla_vacia(nombre)
        df = pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        return normalizar(nombre, df)

    def _cargar_de(self, carpeta: Path) -> dict[str, pd.DataFrame]:
        return {n: self._leer_csv(carpeta / cfg["archivo"], n) for n, cfg in ESQUEMA.items()}

    def _copiar_demo(self, solo_faltantes: bool = False) -> None:
        for cfg in ESQUEMA.values():
            destino = self.dir / cfg["archivo"]
            if solo_faltantes and destino.exists():
                continue
            shutil.copyfile(self.demo_dir / cfg["archivo"], destino)

    def recargar(self) -> None:
        with self._lock:
            self.tablas = self._cargar_de(self.dir)
            self.version += 1

    def guardar(self, *nombres: str) -> None:
        nombres = nombres or tuple(ESQUEMA)
        rutas: list[Path] = []
        with self._lock:
            for nombre in nombres:
                ruta = self.ruta(nombre)
                temporal = ruta.with_suffix(".tmp")
                self.tablas[nombre].to_csv(temporal, index=False, encoding="utf-8-sig", float_format="%.2f")
                temporal.replace(ruta)
                rutas.append(ruta)
            self.version += 1
        if self.al_guardar:
            self.al_guardar(rutas)

    def restaurar_demo(self) -> None:
        with self._lock:
            self._copiar_demo()
            self.tablas = self._cargar_de(self.dir)
        self.guardar()

    # ---------------------------------------------------------- utilidades
    def __getitem__(self, nombre: str) -> pd.DataFrame:
        return self.tablas[nombre]

    def conteos(self) -> dict[str, int]:
        return {n: len(df) for n, df in self.tablas.items()}

    def integridad(self) -> list[str]:
        return validar_integridad(self.tablas)

    # ------------------------------------------------------------- empresa
    def datos_empresa(self) -> dict[str, str]:
        datos = dict(EMPRESA_DEFAULT)
        emp = self.tablas["empresa"]
        datos.update({k: v for k, v in zip(emp["clave"], emp["valor"]) if k})
        return datos

    def actualizar_empresa(self, datos: dict[str, str]) -> None:
        actuales = self.datos_empresa()
        actuales.update({k: str(v).strip() for k, v in datos.items()})
        if not actuales.get("razon_social"):
            raise IntegridadError("La razón social es obligatoria.")
        with self._lock:
            self.tablas["empresa"] = pd.DataFrame({"clave": list(actuales), "valor": list(actuales.values())})
        self.guardar("empresa")

    # --------------------------------------------------- catálogo de cuentas
    def _validar_cuenta(self, codigo: str, nombre: str, naturaleza: str, rubro: str) -> list[str]:
        errores = []
        if not PATRON_CODIGO.match(codigo):
            errores.append("El código debe tener el formato 000-00 o 000-00-000 (ej. 101-01).")
        if not nombre:
            errores.append("El nombre de la cuenta es obligatorio.")
        if naturaleza not in NATURALEZAS:
            errores.append("La naturaleza debe ser Deudora o Acreedora.")
        if rubro not in RUBROS:
            errores.append("Selecciona un rubro válido.")
        return errores

    def agregar_cuenta(self, codigo: str, codigoSAT: str, nombre: str, naturaleza: str, rubro: str) -> None:
        codigo, codigoSAT, nombre = codigo.strip(), codigoSAT.strip(), nombre.strip()
        errores = self._validar_cuenta(codigo, nombre, naturaleza, rubro)
        if codigo in set(self.tablas["catalogoCuentas"]["codigo"]):
            errores.append(f"El código {codigo} ya existe en el catálogo (llave primaria duplicada).")
        if errores:
            raise IntegridadError("\n".join(errores))
        fila = {
            "codigo": codigo,
            "codigoSAT": codigoSAT,
            "nombre": nombre,
            "naturaleza": naturaleza,
            "estadoFinanciero": estado_de_rubro(rubro),
            "rubro": rubro,
            "nombreReporte": "",
        }
        with self._lock:
            cat = _anexar(self.tablas["catalogoCuentas"], [fila])
            self.tablas["catalogoCuentas"] = cat.sort_values("codigo").reset_index(drop=True)
        self.guardar("catalogoCuentas")

    def actualizar_cuenta(self, codigo: str, codigoSAT: str, nombre: str, naturaleza: str, rubro: str) -> None:
        cat = self.tablas["catalogoCuentas"]
        if codigo not in set(cat["codigo"]):
            raise IntegridadError(f"La cuenta {codigo} no existe.")
        errores = self._validar_cuenta(codigo, nombre.strip(), naturaleza, rubro)
        if errores:
            raise IntegridadError("\n".join(errores))
        with self._lock:
            cat = cat.copy()
            mascara = cat["codigo"] == codigo
            cat.loc[mascara, ["codigoSAT", "nombre", "naturaleza", "estadoFinanciero", "rubro"]] = [
                codigoSAT.strip(),
                nombre.strip(),
                naturaleza,
                estado_de_rubro(rubro),
                rubro,
            ]
            self.tablas["catalogoCuentas"] = cat
        self.guardar("catalogoCuentas")

    def actualizar_presentacion(self, codigo: str, nombre_reporte: str, rubro: str) -> None:
        """Panel de administrador: nombre con el que la cuenta sale en los estados y el bloque donde se presenta."""
        cat = self.tablas["catalogoCuentas"]
        if codigo not in set(cat["codigo"]):
            raise IntegridadError(f"La cuenta {codigo} no existe.")
        if rubro not in RUBROS:
            raise IntegridadError("Selecciona un rubro válido.")
        with self._lock:
            cat = cat.copy()
            mascara = cat["codigo"] == codigo
            cat.loc[mascara, ["nombreReporte", "rubro", "estadoFinanciero"]] = [
                nombre_reporte.strip(),
                rubro,
                estado_de_rubro(rubro),
            ]
            self.tablas["catalogoCuentas"] = cat
        self.guardar("catalogoCuentas")

    def eliminar_cuenta(self, codigo: str) -> None:
        en_movs = int((self.tablas["movimientosPoliza"]["cuentaCodigo"] == codigo).sum())
        en_pres = int((self.tablas["presupuestos"]["cuentaCodigo"] == codigo).sum())
        if en_movs or en_pres:
            raise IntegridadError(
                f"No se puede eliminar la cuenta {codigo}: tiene {en_movs} movimiento(s) y "
                f"{en_pres} presupuesto(s) relacionados (integridad referencial)."
            )
        with self._lock:
            cat = self.tablas["catalogoCuentas"]
            self.tablas["catalogoCuentas"] = cat[cat["codigo"] != codigo].reset_index(drop=True)
        self.guardar("catalogoCuentas")

    def sugerir_codigo(self, rubro: str) -> str:
        """Sugiere el siguiente código libre dentro del grupo del rubro."""
        prefijos = {
            "Activo Circulante": "1",
            "Activo No Circulante": "1",
            "Pasivo Corto Plazo": "2",
            "Pasivo Largo Plazo": "2",
            "Capital Contable": "3",
            "Ventas Netas": "4",
            "Costo de Ventas": "5",
            "Gastos de Operacion": "6",
            "RIF": "7",
            "Impuestos": "8",
        }
        cat = self.tablas["catalogoCuentas"]
        existentes = set(cat["codigo"])
        del_rubro = sorted(cat.loc[cat["rubro"] == rubro, "codigo"])
        if del_rubro:
            base = del_rubro[-1][:3]
        else:
            base = prefijos.get(rubro, "9") + "99"
        for sub in range(1, 100):
            propuesta = f"{base}-{sub:02d}"
            if propuesta not in existentes:
                return propuesta
        return f"{base}-01-001"

    # ---------------------------------------------------------------- pólizas
    def siguiente_id_poliza(self) -> str:
        return _siguiente_folio(self.tablas["polizas"]["id"], "POL", 3)[0]

    def guardar_poliza(
        self,
        fecha: date | str,
        tipo: str,
        concepto: str,
        movimientos: Iterable[dict] | pd.DataFrame,
        poliza_id: str | None = None,
    ) -> str:
        """Alta o modificación de una póliza (encabezado + detalle) con validación de partida doble."""
        from .engine import validar_poliza  # import local para evitar ciclos

        cuentas = set(self.tablas["catalogoCuentas"]["codigo"])
        val = validar_poliza(movimientos, cuentas)
        errores = list(val["errores"])
        try:
            fecha_txt = date.fromisoformat(str(fecha)[:10]).isoformat()
        except ValueError:
            errores.append("La fecha de la póliza no es válida.")
            fecha_txt = ""
        if tipo not in TIPOS_POLIZA:
            errores.append("El tipo de póliza no es válido.")
        concepto = (concepto or "").strip()
        if not concepto:
            errores.append("El concepto de la póliza es obligatorio.")
        if poliza_id and poliza_id not in set(self.tablas["polizas"]["id"]):
            errores.append(f"La póliza {poliza_id} no existe.")
        if errores:
            raise IntegridadError("\n".join(errores))

        with self._lock:
            pol = self.tablas["polizas"]
            movs = self.tablas["movimientosPoliza"]
            pid = poliza_id or self.siguiente_id_poliza()
            ids = _siguiente_folio(movs["id"], "MOV", 4, len(val["filas"]))
            if poliza_id:
                pol = pol[pol["id"] != pid]
                movs = movs[movs["polizaId"] != pid]
            filas_mov = [
                {
                    "id": ids[i],
                    "polizaId": pid,
                    "cuentaCodigo": f["cuentaCodigo"],
                    "referencia": f["referencia"],
                    "cargo": f["cargo"],
                    "abono": f["abono"],
                }
                for i, f in enumerate(val["filas"])
            ]
            pol = _anexar(pol, [{"id": pid, "fecha": fecha_txt, "tipo": tipo, "concepto": concepto}])
            self.tablas["polizas"] = pol.sort_values(["fecha", "id"]).reset_index(drop=True)
            self.tablas["movimientosPoliza"] = _anexar(movs, filas_mov).reset_index(drop=True)
        self.guardar("polizas", "movimientosPoliza")
        return pid

    def eliminar_poliza(self, poliza_id: str) -> None:
        """Elimina la póliza y en cascada sus movimientos."""
        with self._lock:
            pol = self.tablas["polizas"]
            if poliza_id not in set(pol["id"]):
                raise IntegridadError(f"La póliza {poliza_id} no existe.")
            movs = self.tablas["movimientosPoliza"]
            self.tablas["polizas"] = pol[pol["id"] != poliza_id].reset_index(drop=True)
            self.tablas["movimientosPoliza"] = movs[movs["polizaId"] != poliza_id].reset_index(drop=True)
        self.guardar("polizas", "movimientosPoliza")

    def movimientos_de(self, poliza_id: str) -> pd.DataFrame:
        movs = self.tablas["movimientosPoliza"]
        return movs[movs["polizaId"] == poliza_id].reset_index(drop=True)

    # ------------------------------------------------------------ presupuestos
    def guardar_presupuesto(self, cuentaCodigo: str, periodo: str, monto: float) -> str:
        if cuentaCodigo not in set(self.tablas["catalogoCuentas"]["codigo"]):
            raise IntegridadError(f"La cuenta {cuentaCodigo} no existe en el catálogo.")
        if not PATRON_PERIODO.match(periodo):
            raise IntegridadError("El periodo debe tener formato AAAA-MM (ej. 2026-11).")
        monto = round(float(monto), 2)
        if monto < 0:
            raise IntegridadError("El monto presupuestado no puede ser negativo.")
        with self._lock:
            pres = self.tablas["presupuestos"].copy()
            mascara = (pres["cuentaCodigo"] == cuentaCodigo) & (pres["periodo"] == periodo)
            if mascara.any():
                pres.loc[mascara, "montoPresupuestado"] = monto
                pid = pres.loc[mascara, "id"].iloc[0]
            else:
                pid = _siguiente_folio(pres["id"], "PRE", 3)[0]
                pres = _anexar(
                    pres, [{"id": pid, "cuentaCodigo": cuentaCodigo, "periodo": periodo, "montoPresupuestado": monto}]
                )
            self.tablas["presupuestos"] = pres.sort_values(["periodo", "cuentaCodigo"]).reset_index(drop=True)
        self.guardar("presupuestos")
        return pid

    def eliminar_presupuesto(self, presupuesto_id: str) -> None:
        with self._lock:
            pres = self.tablas["presupuestos"]
            self.tablas["presupuestos"] = pres[pres["id"] != presupuesto_id].reset_index(drop=True)
        self.guardar("presupuestos")

    def copiar_presupuesto(self, origen: str, destino: str, factor: float = 1.0) -> int:
        """Copia el presupuesto de un periodo a otro (opcionalmente con un factor de ajuste)."""
        if not PATRON_PERIODO.match(destino):
            raise IntegridadError("El periodo destino debe tener formato AAAA-MM.")
        pres = self.tablas["presupuestos"]
        base = pres[pres["periodo"] == origen]
        if base.empty:
            raise IntegridadError(f"El periodo {origen} no tiene presupuesto que copiar.")
        with self._lock:
            pres = pres.copy()
            nuevos = []
            for _, fila in base.iterrows():
                monto = round(float(fila["montoPresupuestado"]) * factor, 2)
                mascara = (pres["cuentaCodigo"] == fila["cuentaCodigo"]) & (pres["periodo"] == destino)
                if mascara.any():
                    pres.loc[mascara, "montoPresupuestado"] = monto
                else:
                    nuevos.append({"cuentaCodigo": fila["cuentaCodigo"], "periodo": destino, "montoPresupuestado": monto})
            if nuevos:
                ids = _siguiente_folio(pres["id"], "PRE", 3, len(nuevos))
                for i, n in enumerate(nuevos):
                    n["id"] = ids[i]
                pres = _anexar(pres, nuevos)
            self.tablas["presupuestos"] = pres.sort_values(["periodo", "cuentaCodigo"]).reset_index(drop=True)
        self.guardar("presupuestos")
        return len(base)

    # --------------------------------------------------------------- respaldo
    def exportar_excel(self) -> bytes:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            for nombre, df in self.tablas.items():
                df.to_excel(writer, sheet_name=nombre[:31], index=False)
                hoja = writer.sheets[nombre[:31]]
                for i, col in enumerate(df.columns, start=1):
                    ancho = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
                    hoja.column_dimensions[hoja.cell(row=1, column=i).column_letter].width = min(ancho, 60)
        return buffer.getvalue()

    def exportar_zip(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for nombre, cfg in ESQUEMA.items():
                csv = self.tablas[nombre].to_csv(index=False, float_format="%.2f")
                zf.writestr(cfg["archivo"], ("﻿" + csv).encode("utf-8"))
        return buffer.getvalue()

    def exportar_json(self) -> bytes:
        contenido = {n: df.to_dict(orient="records") for n, df in self.tablas.items()}
        return json.dumps(contenido, ensure_ascii=False, indent=2).encode("utf-8")

    @staticmethod
    def leer_respaldo(contenido: bytes, nombre_archivo: str) -> dict[str, pd.DataFrame]:
        extension = Path(nombre_archivo).suffix.lower()
        crudas: dict[str, pd.DataFrame] = {}
        if extension == ".xlsx":
            hojas = pd.read_excel(io.BytesIO(contenido), sheet_name=None, dtype=str, keep_default_na=False)
            for nombre in ESQUEMA:
                if nombre[:31] in hojas:
                    crudas[nombre] = hojas[nombre[:31]]
        elif extension == ".zip":
            with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
                por_nombre = {Path(n).name: n for n in zf.namelist()}
                for nombre, cfg in ESQUEMA.items():
                    if cfg["archivo"] in por_nombre:
                        datos = zf.read(por_nombre[cfg["archivo"]])
                        crudas[nombre] = pd.read_csv(
                            io.BytesIO(datos), dtype=str, keep_default_na=False, encoding="utf-8-sig"
                        )
        elif extension == ".json":
            datos = json.loads(contenido.decode("utf-8-sig"))
            for nombre in ESQUEMA:
                if nombre in datos:
                    crudas[nombre] = pd.DataFrame(datos[nombre], columns=ESQUEMA[nombre]["columnas"])
        else:
            raise IntegridadError("Formato no soportado. Usa un respaldo .xlsx, .zip o .json generado por COI-UP.")

        faltantes = [n for n in TABLAS_OBLIGATORIAS if n not in crudas]
        if faltantes:
            raise IntegridadError("El respaldo no contiene las tablas: " + ", ".join(faltantes))
        tablas = {}
        for nombre in ESQUEMA:
            tablas[nombre] = normalizar(nombre, crudas[nombre]) if nombre in crudas else tabla_vacia(nombre)
        return tablas

    def importar(self, contenido: bytes, nombre_archivo: str) -> None:
        tablas = self.leer_respaldo(contenido, nombre_archivo)
        errores = validar_integridad(tablas)
        if errores:
            raise IntegridadError("El respaldo no pasó la validación relacional:\n- " + "\n- ".join(errores))
        with self._lock:
            self.tablas = tablas
        self.guardar()
