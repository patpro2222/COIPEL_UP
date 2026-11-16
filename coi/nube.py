"""Persistencia opcional de los CSV en un repositorio de GitHub.

Streamlit Community Cloud no garantiza que los archivos escritos por la app
sobrevivan a un reinicio. Si en los *secrets* de la app se configura la sección
``[github]``, COI-UP:

1. Al arrancar, descarga los CSV de la rama de datos (por defecto ``datos``).
2. Cada vez que se guarda una tabla, sube (commit) solo los CSV que cambiaron.

Así GitHub funciona como respaldo permanente y con historial de versiones.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from pathlib import Path

import requests

API = "https://api.github.com"


def _sha_git(contenido: bytes) -> str:
    """SHA que GitHub asigna a un archivo (blob); sirve para detectar si cambió."""
    return hashlib.sha1(b"blob " + str(len(contenido)).encode() + b"\0" + contenido).hexdigest()


class SincronizadorGitHub:
    def __init__(self, token: str, repo: str, rama: str = "datos", carpeta: str = "datos/db",
                 automatico: bool = True, timeout: int = 20):
        self.token = token
        self.repo = repo.strip().strip("/")
        self.rama = rama
        self.carpeta = carpeta.strip("/")
        self.automatico = automatico
        self.timeout = timeout
        self._rama_lista = False
        self._shas: dict[str, str] = {}
        self.ultimo_error: str | None = None
        self.ultima_sincronizacion: datetime | None = None

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "coi-up-contabilidad",
        }

    def _url(self, archivo: str) -> str:
        return f"{API}/repos/{self.repo}/contents/{self.carpeta}/{archivo}"

    def asegurar_rama(self) -> None:
        if self._rama_lista:
            return
        r = requests.get(f"{API}/repos/{self.repo}/branches/{self.rama}", headers=self._headers, timeout=self.timeout)
        if r.status_code == 404:
            info = requests.get(f"{API}/repos/{self.repo}", headers=self._headers, timeout=self.timeout)
            info.raise_for_status()
            principal = info.json()["default_branch"]
            ref = requests.get(
                f"{API}/repos/{self.repo}/git/ref/heads/{principal}", headers=self._headers, timeout=self.timeout
            )
            ref.raise_for_status()
            crear = requests.post(
                f"{API}/repos/{self.repo}/git/refs",
                headers=self._headers,
                json={"ref": f"refs/heads/{self.rama}", "sha": ref.json()["object"]["sha"]},
                timeout=self.timeout,
            )
            crear.raise_for_status()
        else:
            r.raise_for_status()
        self._rama_lista = True

    def descargar(self, archivos: list[str], destino: Path) -> list[str]:
        """Descarga los CSV existentes en GitHub hacia ``destino``. Devuelve los que se descargaron."""
        destino.mkdir(parents=True, exist_ok=True)
        descargados = []
        for archivo in archivos:
            r = requests.get(self._url(archivo), params={"ref": self.rama}, headers=self._headers, timeout=self.timeout)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            datos = r.json()
            contenido = base64.b64decode(datos.get("content", "")) if datos.get("content") else b""
            if not contenido and datos.get("download_url"):
                crudo = requests.get(datos["download_url"], headers=self._headers, timeout=self.timeout)
                crudo.raise_for_status()
                contenido = crudo.content
            (destino / archivo).write_bytes(contenido)
            self._shas[archivo] = datos["sha"]
            descargados.append(archivo)
        self.ultima_sincronizacion = datetime.now()
        return descargados

    def subir(self, rutas: list[Path], mensaje: str | None = None) -> int:
        """Hace commit de los archivos que cambiaron. Devuelve cuántos se subieron."""
        self.asegurar_rama()
        subidos = 0
        for ruta in rutas:
            contenido = ruta.read_bytes()
            nombre = ruta.name
            sha_remoto = self._shas.get(nombre)
            if sha_remoto is None:
                r = requests.get(self._url(nombre), params={"ref": self.rama}, headers=self._headers, timeout=self.timeout)
                if r.status_code == 200:
                    sha_remoto = r.json()["sha"]
                elif r.status_code != 404:
                    r.raise_for_status()
            if sha_remoto == _sha_git(contenido):
                continue
            cuerpo = {
                "message": mensaje or f"COI-UP: actualiza {nombre} ({datetime.now():%Y-%m-%d %H:%M})",
                "content": base64.b64encode(contenido).decode("ascii"),
                "branch": self.rama,
            }
            if sha_remoto:
                cuerpo["sha"] = sha_remoto
            r = requests.put(self._url(nombre), headers=self._headers, json=cuerpo, timeout=self.timeout)
            r.raise_for_status()
            self._shas[nombre] = r.json()["content"]["sha"]
            subidos += 1
        self.ultima_sincronizacion = datetime.now()
        self.ultimo_error = None
        return subidos
