# 📒 COI-UP Contabilidad

Sistema contable y presupuestal **hecho en Python**, inspirado en la lógica de Aspel COI, que corre
**en computadora, tableta y celular** desde el navegador. Genera automáticamente:

- **Balanza de Comprobación** (saldos iniciales, movimientos, saldos finales y "sumas iguales").
- **Estado de Resultados** con estructura formal (Ventas → Utilidad Bruta → EBIT → RIF → UAI → ISR → Utilidad Neta).
- **Balance General** clasificado (Activo circulante/no circulante, Pasivo CP/LP, Capital) con verificación
  **Activo = Pasivo + Capital**.
- **Panel de administrador** (con contraseña) para modificar, cuenta por cuenta, el nombre, el rubro y el importe
  con que aparece en el Estado de Resultados y el Balance General; los cambios llegan también al PDF y al Excel.
- Auxiliares (mayor por cuenta), Libro Diario y **Control Presupuestal** con semáforo.
- Exportación a **PDF** (formato ejecutivo con firmas) y **Excel (.xlsx)**.

---

## 1. ¿Cómo está hecho? (explicación sencilla)

| Pieza | Tecnología | Para qué sirve |
|---|---|---|
| Lenguaje | **Python 3.12** | Todo el sistema: lógica contable, reportes e interfaz. |
| Interfaz web | **Streamlit** | Convierte código Python en una página web *responsiva* (se adapta al celular). |
| Base de datos | **5 archivos CSV** relacionados | Se abren en Excel, se versionan en GitHub y no requieren servidor de BD. |
| Cálculos | **pandas** | JOINs entre tablas, sumas de cargos/abonos y saldos. |
| Gráficas | **Plotly** | Gráficas interactivas (tocar/hacer zoom en el celular). |
| PDF / Excel | **fpdf2 / openpyxl** | Reportes listos para imprimir o seguir trabajando en Excel. |
| Hosting | **Streamlit Community Cloud** (gratis) | Publica la app con un enlace `https://...streamlit.app`. |
| Código y respaldo | **GitHub** (gratis) | Guarda el código y, opcionalmente, los datos con historial. |

```
 Celular / Tableta / PC  ──navegador──▶  Streamlit Community Cloud  ──lee código──▶  GitHub (rama main)
                                              │   app.py + coi/ + vistas/
                                              ▼
                                   datos/db/*.csv  ◀──respaldo opcional──▶  GitHub (rama "datos")
```

**¿Por qué Streamlit Community Cloud?** Es gratuito, está hecho para apps de Python, se conecta
directamente con GitHub (cada vez que subes un cambio, la app se actualiza sola), no requiere configurar
servidores y da un enlace que funciona igual en el celular y en la computadora.

---

## 2. Base de datos relacional (CSV)

```
catalogoCuentas (PK codigo) ──1:N──▶ movimientosPoliza (FK cuentaCodigo)   [RESTRICT: no se borra una cuenta con movimientos]
polizas         (PK id)     ──1:N──▶ movimientosPoliza (FK polizaId)       [CASCADE: al borrar la póliza se borra su detalle]
catalogoCuentas (PK codigo) ──1:N──▶ presupuestos      (FK cuentaCodigo)   [RESTRICT]
empresa (clave/valor)  → razón social, RFC, domicilio para los encabezados de los reportes
```

| Archivo | Columnas |
|---|---|
| `catalogo_cuentas.csv` | codigo, codigoSAT, nombre, naturaleza (Deudora/Acreedora), estadoFinanciero, rubro, nombreReporte (nombre en los estados, lo define el admin) |
| `polizas.csv` | id, fecha (AAAA-MM-DD), tipo (Ingreso/Egreso/Diario/Ajuste), concepto |
| `movimientos_poliza.csv` | id, polizaId, cuentaCodigo, referencia, cargo, abono |
| `presupuestos.csv` | id, cuentaCodigo, periodo (AAAA-MM), montoPresupuestado |
| `empresa.csv` | clave, valor |

- `datos/demo/` contiene los datos de demostración (no se modifican).
- `datos/db/` es la base de trabajo; se crea sola copiando la demo la primera vez.
- El módulo `coi/db.py` hace cumplir las llaves primarias/foráneas y valida todo respaldo antes de importarlo.
- Desde la app puedes **descargar respaldo** en Excel (una hoja por tabla), ZIP de CSV o JSON, **importarlo** de vuelta
  y **restaurar los datos de demostración**.

### Reglas contables implementadas
- **Partida doble:** la póliza solo se guarda si `Total Cargos = Total Abonos` y ambos son mayores a 0. El botón
  *Guardar póliza* se bloquea y aparece una alerta roja de descuadre en tiempo real.
- **Saldo por naturaleza:** Deudora = Cargos − Abonos; Acreedora = Abonos − Cargos.
- **Balance General:** la Utilidad Neta del ejercicio (1 de enero a la fecha de corte) se integra automáticamente
  al Capital Contable.
- **Semáforo presupuestal:** ingresos 🟢 ≥100 % · 🟡 90–99 % · 🔴 <90 %; gastos 🟢 <90 % · 🟡 90–100 % · 🔴 >100 %.

### Datos de demostración (prototipo de sistema contable, ejercicio 2026)
Una póliza de saldos iniciales al **1 de enero de 2026** con las 22 cuentas del prototipo visto en clase.
Sin presupuestos capturados (se agregan desde *Control presupuestal*).

- El Capital Social se registra en **$8,803,350.00** para que la apertura cuadre; en el Excel original era
  $7,467,035.00 y los saldos tenían una diferencia de $1,336,315.00.
- *Otros gastos* y *Otros productos* se presentan dentro del Resultado Integral de Financiamiento (RIF).

| Estado de Resultados | Importe |
|---|---:|
| Ventas | $2,260,000.00 |
| (−) Costo de Ventas | $1,118,750.00 |
| (=) Utilidad Bruta | $1,141,250.00 |
| (−) Gastos de Operación (ventas + administración) | $530,000.00 |
| (=) Utilidad de Operación | $611,250.00 |
| (+/−) RIF (productos 200,000 + otros productos 120,000 − gastos 119,000 − otros gastos 328,000) | −$127,000.00 |
| (=) Utilidad Neta | **$484,250.00** |

Balance General: Activo circulante $7,550,400.00 + Activo no circulante $4,748,200.00 = **$12,298,600.00** =
Pasivo $3,011,000.00 + Capital contable $9,287,600.00 (Capital Social + Utilidad Neta).

---

## 3. Estructura del proyecto

```
coi-up-contabilidad/
├── app.py                     ← punto de entrada y menú de navegación
├── requirements.txt           ← librerías que instala Streamlit Cloud
├── .streamlit/
│   ├── config.toml            ← tema azul marino/pizarra
│   └── secrets.toml.example   ← plantilla para el respaldo en GitHub (opcional)
├── coi/
│   ├── db.py                  ← base de datos relacional sobre CSV (PK, FK, respaldos)
│   ├── engine.py              ← motor contable (partida doble, saldos, estados financieros)
│   ├── exportar.py            ← PDF y Excel
│   ├── formato.py             ← moneda, porcentajes, fechas en español
│   ├── nube.py                ← sincronización opcional con GitHub
│   └── ui.py                  ← estilos, tarjetas, selector de periodo
├── vistas/                    ← una pantalla por módulo
│   ├── dashboard.py  catalogo.py  polizas.py  balanza.py
│   └── estados.py    presupuestos.py  admin.py  datos.py
├── datos/demo/*.csv           ← datos de demostración
└── tests/test_motor.py        ← pruebas automáticas del motor contable
```

---

## 4. Correrlo en tu computadora (opcional, ~5 minutos)

1. Instala **Python 3.12** desde <https://www.python.org/downloads/> (en Windows marca *"Add python.exe to PATH"*).
2. Abre una terminal en la carpeta del proyecto y crea un entorno virtual:
   ```bash
   python -m venv .venv
   ```
   Actívalo: en Windows `.venv\Scripts\activate`; en Mac/Linux `source .venv/bin/activate`.
3. Instala las librerías:
   ```bash
   pip install -r requirements.txt
   ```
4. Arranca la app:
   ```bash
   streamlit run app.py
   ```
   Se abre en `http://localhost:8501`. Para verla **desde tu celular en la misma red Wi-Fi**, usa la dirección
   *Network URL* que muestra la terminal (por ejemplo `http://192.168.1.20:8501`).
5. (Opcional) Ejecuta las pruebas: `python -m pytest -q` (requiere `pip install pytest`).

---

## 5. Publicarlo gratis en internet (GitHub + Streamlit Community Cloud)

### Paso 1 · Crear tu cuenta de GitHub y el repositorio
1. Entra a <https://github.com> y crea una cuenta gratuita.
2. Clic en **New repository** → nombre `coi-up-contabilidad` → **Public** o **Private** → *Create repository*.

### Paso 2 · Subir el código
**Opción fácil (sin comandos):** en tu repositorio vacío, clic en *uploading an existing file*, arrastra **todo el
contenido** de la carpeta del proyecto (incluida la carpeta `.streamlit`) y presiona **Commit changes**.

> En Windows las carpetas que empiezan con punto pueden estar ocultas. Si `.streamlit` no se sube, créala
> en GitHub con *Add file → Create new file* escribiendo `.streamlit/config.toml` como nombre y pegando su contenido.

**Opción con Git:**
```bash
git init
```
```bash
git add .
```
```bash
git commit -m "COI-UP Contabilidad"
```
```bash
git branch -M main
```
```bash
git remote add origin https://github.com/TU-USUARIO/coi-up-contabilidad.git
```
```bash
git push -u origin main
```

### Paso 3 · Crear la app en Streamlit Community Cloud
1. Entra a <https://share.streamlit.io> y elige **Continue with GitHub** (autoriza el acceso).
2. Clic en **Create app** → *Deploy a public app from GitHub*.
3. Llena: **Repository** `TU-USUARIO/coi-up-contabilidad` · **Branch** `main` · **Main file path** `app.py`.
4. (Opcional) Elige tu subdominio, por ejemplo `coi-up-contabilidad.streamlit.app`.
5. En **Advanced settings** selecciona **Python 3.12**.
6. Clic en **Deploy**. La primera vez tarda unos minutos instalando las librerías; después verás el Dashboard.

### Paso 4 · Abrirla en el celular o tableta como si fuera una app
- **Android (Chrome):** abre el enlace → menú ⋮ → **Agregar a pantalla principal**.
- **iPhone/iPad (Safari):** abre el enlace → botón Compartir → **Agregar a inicio**.

Aparecerá un ícono en tu pantalla. En el celular el menú lateral se abre con el botón **›** de la esquina superior
izquierda; las tablas se desplazan horizontalmente con el dedo y los botones son grandes para uso táctil.

### Paso 5 · Actualizar la app
Cada vez que modifiques un archivo en GitHub (o hagas `git push`), Streamlit Cloud detecta el cambio y
actualiza la app en segundos. No hay que volver a desplegar.

### Paso 6 · ⚠️ Que los datos no se pierdan (recomendado)
Streamlit Community Cloud **no garantiza** que los archivos que la app escribe sobrevivan cuando la app se
reinicia o "se duerme" por falta de visitas. Tienes dos opciones:

**A. Respaldo automático en GitHub (recomendado, gratis):**
1. En GitHub: foto de perfil → **Settings → Developer settings → Personal access tokens → Fine-grained tokens →
   Generate new token**.
2. *Repository access:* **Only select repositories** → elige `coi-up-contabilidad`.
3. *Permissions → Repository permissions → Contents:* **Read and write**. Genera el token y cópialo.
4. En Streamlit Cloud: tu app → **⋮ → Settings → Secrets** y pega (con tus datos):
   ```toml
   [github]
   token = "github_pat_..."
   repo = "TU-USUARIO/coi-up-contabilidad"
   rama = "datos"
   carpeta = "datos/db"
   automatico = true
   ```
   En ese mismo cuadro agrega la contraseña del Panel de administrador:
   ```toml
   [admin]
   password = "tu-contraseña-segura"
   ```
5. Guarda. La app se reinicia y desde entonces cada póliza, cuenta o presupuesto que guardes se sube como
   *commit* a la rama `datos` (se crea sola). Al reiniciarse, la app vuelve a descargar los CSV desde ahí.
   Puedes ver el historial de cambios de tu contabilidad en GitHub → rama `datos` → carpeta `datos/db`.

> Se usa una rama separada (`datos`) para que guardar información no reinicie la app ni mezcle datos con el código.
> El token es secreto: **nunca** lo pongas en un archivo del repositorio.

**B. Respaldo manual:** en *Base de datos y respaldo* descarga el Excel o ZIP al terminar de trabajar e
impórtalo cuando lo necesites.

---

## 6. Uso rápido

1. **Base de datos y respaldo → Datos de la empresa:** captura razón social y RFC (aparecen en todos los reportes).
2. **Catálogo de cuentas:** consulta saldos, filtra por rubro/naturaleza y da de alta cuentas (el código no se puede repetir).
3. **Pólizas → Captura:** llena encabezado y renglones; observa en vivo Total Cargos, Total Abonos y Diferencia.
4. **Balanza y auxiliares:** verifica sumas iguales y revisa el mayor de cada cuenta.
5. **Estados financieros:** elige el periodo y exporta Estado de Resultados y Balance General a PDF o Excel.
6. **Control presupuestal:** captura presupuestos mensuales y compara contra lo real con el semáforo.
7. **Panel de administrador:** ajusta cómo se presentan las cuentas (ver sección 6.1).

### 6.1 Panel de administrador

Entra a *Administración → Panel de administrador* con la contraseña. Si no configuraste una en los Secrets
(`[admin] password = "..."`), la contraseña de demostración es **`admin123`**: cámbiala antes de publicar.

1. Elige la **cuenta** (`[ER]` = Estado de Resultados, `[BG]` = Balance General) y la **fecha de corte**.
   Verás el importe con el que aparece hoy en su estado.
2. **Nombre y rubro:** escribe el nombre con el que debe salir en los estados (vacío = nombre del catálogo) y el
   bloque donde se presenta (por ejemplo, mover una cuenta de Gastos de Operación a RIF).
3. **Ajustar importe:** escribe el importe deseado y la **cuenta de contrapartida**. El sistema muestra la póliza de
   ajuste propuesta y cómo quedarían la utilidad neta, el activo y el pasivo + capital. Al confirmar se guarda como
   póliza tipo **Ajuste**, así la balanza y la ecuación contable siguen cuadradas.
4. **Ajustes realizados:** consulta los ajustes generados desde el panel y revierte cualquiera.
5. **Modificar / eliminar pólizas** (selector en la parte superior del panel): busca cualquier póliza por tipo,
   folio o concepto y elige la acción:
   - **Modificar:** cambia fecha, tipo, concepto y renglones (cuenta, referencia, cargo, abono; agrega o quita
     renglones). El botón *Guardar* se bloquea si la póliza no cuadra.
   - **Eliminar:** muestra el detalle y cómo quedarían la utilidad neta, el activo y el pasivo + capital sin ella;
     se elimina tras marcar la confirmación (borra también sus movimientos).

Todo lo que cambies se refleja al instante en *Estados financieros* y en las exportaciones a PDF y Excel.
Para el Estado de Resultados, el importe ajustado es el acumulado del 1 de enero a la fecha de corte.

> La sesión de administrador dura mientras no recargues la página; muévete con el menú lateral para conservarla.

---

## 7. Preguntas frecuentes

**¿Cuánto cuesta?** Nada: GitHub y Streamlit Community Cloud tienen planes gratuitos suficientes para este proyecto.

**¿La app es pública?** Si el repositorio es público, cualquiera con el enlace puede abrir la app. En Streamlit
Cloud (⋮ → Settings → Sharing) puedes restringirla a correos específicos. No captures información sensible real
en una app pública.

**La app tarda en abrir.** Si nadie la usa por un tiempo, Streamlit la "duerme"; al entrar aparece un botón para
despertarla y tarda unos segundos. Con el respaldo en GitHub (Paso 6A) los datos se recuperan solos.

**¿Puedo editar la base de datos en Excel?** Sí: descarga el respaldo .xlsx, edítalo y vuelve a importarlo.
La app valida llaves primarias, llaves foráneas y que cada póliza cuadre antes de aceptarlo.

**¿Alternativas de hosting gratuito?** Hugging Face Spaces (también corre Streamlit) o Render; Streamlit Community
Cloud es el más sencillo porque se configura en tres clics desde GitHub.
