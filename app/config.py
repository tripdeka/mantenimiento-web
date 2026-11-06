"""Configuración global. Todas las rutas son relativas a la carpeta del proyecto."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "datos"
DB_PATH = DATA_DIR / "mantenimiento.db"
DOCS_DIR = DATA_DIR / "documentos"
BACKUP_DIR = DATA_DIR / "respaldos"
EXPORT_DIR = DATA_DIR / "reportes"

APP_NOMBRE = "Sistema de Mantenimiento y Refacciones"
MONEDA = "MXN"
ROLES = ("administrador", "supervisor", "tecnico", "almacen")


def mxn(valor) -> str:
    """Formato de moneda para México: $1,234.50 MXN"""
    try:
        return f"${float(valor):,.2f} {MONEDA}"
    except (TypeError, ValueError):
        return "$0.00 MXN"


def fecha_mx(iso: str) -> str:
    """'2026-10-28 14:30:00' -> '28/10/2026 14:30'"""
    if not iso:
        return ""
    iso = str(iso)
    try:
        f, _, h = iso.partition(" ")
        a, m, d = f.split("-")
        return f"{d}/{m}/{a}" + (f" {h[:5]}" if h else "")
    except ValueError:
        return iso
