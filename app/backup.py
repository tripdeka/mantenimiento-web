"""Respaldo y restauración de la base de datos SQLite."""
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from app import config


def respaldar(destino: Path | None = None) -> Path:
    """Copia consistente (API de respaldo de SQLite, segura aunque la app esté abierta)."""
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destino = Path(destino) if destino else config.BACKUP_DIR / f"respaldo_{datetime.now():%Y%m%d_%H%M%S}.db"
    origen = sqlite3.connect(config.DB_PATH)
    dest = sqlite3.connect(destino)
    try:
        origen.backup(dest)
    finally:
        dest.close()
        origen.close()
    return destino


def restaurar(archivo: Path) -> Path:
    """Valida el archivo, guarda un respaldo de seguridad del estado actual y lo reemplaza."""
    archivo = Path(archivo)
    if not archivo.exists():
        raise ValueError("El archivo de respaldo no existe.")
    try:
        con = sqlite3.connect(archivo)
        ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tablas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
    except sqlite3.DatabaseError as e:
        raise ValueError("El archivo no es una base de datos SQLite válida.") from e
    if not ok or not {"usuarios", "refacciones", "equipos"} <= tablas:
        raise ValueError("El archivo no corresponde a una base de datos de este sistema.")
    seguridad = respaldar(config.BACKUP_DIR / f"antes_de_restaurar_{datetime.now():%Y%m%d_%H%M%S}.db")
    shutil.copyfile(archivo, config.DB_PATH)
    return seguridad
