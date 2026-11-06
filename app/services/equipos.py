"""Servicio de equipos / máquinas: listado, alta, edición, baja y consulta por área."""
from datetime import datetime

from app import db
from app.auth import ErrorAcceso, Sesion


def listar(area_id=None, solo_activos=True, criticidad=None, estado=None) -> list[dict]:
    sql = """
        SELECT e.*, a.nombre AS area, emp.nombre AS responsable
        FROM equipos e
        LEFT JOIN areas a ON a.id = e.area_id
        LEFT JOIN empleados emp ON emp.id = e.responsable_id
        WHERE 1=1
    """
    params = []
    if solo_activos:
        sql += " AND e.activo=1"
    if area_id:
        sql += " AND e.area_id=?"
        params.append(area_id)
    if criticidad:
        sql += " AND e.criticidad=?"
        params.append(criticidad)
    if estado:
        sql += " AND e.estado=?"
        params.append(estado)
    sql += " ORDER BY e.codigo"
    return db.consultar(sql, params)


def obtener(equipo_id: int) -> dict | None:
    filas = db.consultar(
        """SELECT e.*, a.nombre AS area, emp.nombre AS responsable
           FROM equipos e
           LEFT JOIN areas a ON a.id = e.area_id
           LEFT JOIN empleados emp ON emp.id = e.responsable_id
           WHERE e.id=?""",
        (equipo_id,),
    )
    return filas[0] if filas else None


def crear(datos: dict) -> int:
    Sesion.exigir("equipos.editar")
    codigo = (datos.get("codigo") or "").strip().upper()
    nombre = (datos.get("nombre") or "").strip()
    if not codigo or not nombre:
        raise ValueError("Código y nombre son obligatorios.")
    criticidad = datos.get("criticidad") or "media"
    estado = datos.get("estado") or "operativo"
    if criticidad not in ("alta", "media", "baja"):
        raise ValueError("Criticidad inválida.")
    if estado not in ("operativo", "en mantenimiento", "fuera de servicio"):
        raise ValueError("Estado inválido.")
    with db.transaccion() as con:
        try:
            cur = con.execute(
                """INSERT INTO equipos
                   (codigo, nombre, area_id, ubicacion, marca, modelo, numero_serie,
                    descripcion, criticidad, estado, fecha_instalacion,
                    frecuencia_preventivo_dias, responsable_id, activo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                (
                    codigo,
                    nombre,
                    datos.get("area_id") or None,
                    (datos.get("ubicacion") or "").strip() or None,
                    (datos.get("marca") or "").strip() or None,
                    (datos.get("modelo") or "").strip() or None,
                    (datos.get("numero_serie") or "").strip() or None,
                    (datos.get("descripcion") or "").strip() or None,
                    criticidad,
                    estado,
                    datos.get("fecha_instalacion") or None,
                    int(datos["frecuencia_preventivo_dias"]) if datos.get("frecuencia_preventivo_dias") else None,
                    datos.get("responsable_id") or None,
                ),
            )
            return cur.lastrowid
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ValueError(f"Ya existe un equipo con el código '{codigo}'.") from e
            raise


def actualizar(equipo_id: int, datos: dict) -> None:
    Sesion.exigir("equipos.editar")
    actual = obtener(equipo_id)
    if not actual or not actual["activo"]:
        raise ValueError("Equipo no encontrado o dado de baja.")
    codigo = (datos.get("codigo") or "").strip().upper()
    nombre = (datos.get("nombre") or "").strip()
    if not codigo or not nombre:
        raise ValueError("Código y nombre son obligatorios.")
    criticidad = datos.get("criticidad") or "media"
    estado = datos.get("estado") or "operativo"
    if criticidad not in ("alta", "media", "baja"):
        raise ValueError("Criticidad inválida.")
    if estado not in ("operativo", "en mantenimiento", "fuera de servicio"):
        raise ValueError("Estado inválido.")
    with db.transaccion() as con:
        try:
            con.execute(
                """UPDATE equipos SET
                   codigo=?, nombre=?, area_id=?, ubicacion=?, marca=?, modelo=?, numero_serie=?,
                   descripcion=?, criticidad=?, estado=?, fecha_instalacion=?,
                   frecuencia_preventivo_dias=?, responsable_id=?
                   WHERE id=?""",
                (
                    codigo,
                    nombre,
                    datos.get("area_id") or None,
                    (datos.get("ubicacion") or "").strip() or None,
                    (datos.get("marca") or "").strip() or None,
                    (datos.get("modelo") or "").strip() or None,
                    (datos.get("numero_serie") or "").strip() or None,
                    (datos.get("descripcion") or "").strip() or None,
                    criticidad,
                    estado,
                    datos.get("fecha_instalacion") or None,
                    int(datos["frecuencia_preventivo_dias"]) if datos.get("frecuencia_preventivo_dias") else None,
                    datos.get("responsable_id") or None,
                    equipo_id,
                ),
            )
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ValueError(f"Ya existe un equipo con el código '{codigo}'.") from e
            raise


def dar_de_baja(equipo_id: int) -> None:
    Sesion.exigir("equipos.baja")
    with db.transaccion() as con:
        con.execute("UPDATE equipos SET activo=0 WHERE id=?", (equipo_id,))


def contadores() -> dict:
    filas = db.consultar(
        """SELECT
             COUNT(*) FILTER (WHERE activo=1) AS total,
             COUNT(*) FILTER (WHERE activo=1 AND estado='operativo') AS operativos,
             COUNT(*) FILTER (WHERE activo=1 AND estado='en mantenimiento') AS en_mto,
             COUNT(*) FILTER (WHERE activo=1 AND estado='fuera de servicio') AS fuera,
             COUNT(*) FILTER (WHERE activo=1 AND criticidad='alta') AS alta
           FROM equipos"""
    )
    # SQLite no tiene FILTER en versiones antiguas; usamos consultas separadas por compatibilidad
    total = db.consultar("SELECT COUNT(*) AS n FROM equipos WHERE activo=1")[0]["n"]
    operativos = db.consultar("SELECT COUNT(*) AS n FROM equipos WHERE activo=1 AND estado='operativo'")[0]["n"]
    en_mto = db.consultar("SELECT COUNT(*) AS n FROM equipos WHERE activo=1 AND estado='en mantenimiento'")[0]["n"]
    fuera = db.consultar("SELECT COUNT(*) AS n FROM equipos WHERE activo=1 AND estado='fuera de servicio'")[0]["n"]
    alta = db.consultar("SELECT COUNT(*) AS n FROM equipos WHERE activo=1 AND criticidad='alta'")[0]["n"]
    return {
        "total": total,
        "operativos": operativos,
        "en_mto": en_mto,
        "fuera": fuera,
        "alta": alta,
    }


def listar_areas() -> list[dict]:
    return db.consultar("SELECT id, nombre FROM areas ORDER BY nombre")


def asegurar_area(nombre: str) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("Nombre de área vacío.")
    filas = db.consultar("SELECT id FROM areas WHERE nombre=?", (nombre,))
    if filas:
        return filas[0]["id"]
    with db.transaccion() as con:
        cur = con.execute("INSERT INTO areas (nombre) VALUES (?)", (nombre,))
        return cur.lastrowid
