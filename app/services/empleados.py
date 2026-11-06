"""Servicio de empleados y organigrama del departamento de mantenimiento."""
from app import db
from app.auth import ErrorAcceso, Sesion


def listar(solo_activos=True, area_id=None) -> list[dict]:
    sql = """
        SELECT e.*, a.nombre AS area, j.nombre AS jefe,
               u.usuario AS usuario_login, u.rol AS rol_usuario
        FROM empleados e
        LEFT JOIN areas a ON a.id = e.area_id
        LEFT JOIN empleados j ON j.id = e.jefe_id
        LEFT JOIN usuarios u ON u.id = e.usuario_id
        WHERE 1=1
    """
    params = []
    if solo_activos:
        sql += " AND e.activo=1"
    if area_id:
        sql += " AND e.area_id=?"
        params.append(area_id)
    sql += " ORDER BY e.nombre"
    return db.consultar(sql, params)


def obtener(empleado_id: int) -> dict | None:
    filas = db.consultar(
        """SELECT e.*, a.nombre AS area, j.nombre AS jefe
           FROM empleados e
           LEFT JOIN areas a ON a.id = e.area_id
           LEFT JOIN empleados j ON j.id = e.jefe_id
           WHERE e.id=?""",
        (empleado_id,),
    )
    return filas[0] if filas else None


def crear(datos: dict) -> int:
    Sesion.exigir("empleados.editar")
    nombre = (datos.get("nombre") or "").strip()
    puesto = (datos.get("puesto") or "").strip()
    if not nombre or not puesto:
        raise ValueError("Nombre y puesto son obligatorios.")
    with db.transaccion() as con:
        cur = con.execute(
            """INSERT INTO empleados
               (nombre, puesto, jefe_id, contacto, responsabilidades, area_id, usuario_id, activo)
               VALUES (?,?,?,?,?,?,?,1)""",
            (
                nombre,
                puesto,
                datos.get("jefe_id") or None,
                (datos.get("contacto") or "").strip() or None,
                (datos.get("responsabilidades") or "").strip() or None,
                datos.get("area_id") or None,
                datos.get("usuario_id") or None,
            ),
        )
        return cur.lastrowid


def actualizar(empleado_id: int, datos: dict) -> None:
    Sesion.exigir("empleados.editar")
    actual = obtener(empleado_id)
    if not actual or not actual["activo"]:
        raise ValueError("Empleado no encontrado o dado de baja.")
    nombre = (datos.get("nombre") or "").strip()
    puesto = (datos.get("puesto") or "").strip()
    if not nombre or not puesto:
        raise ValueError("Nombre y puesto son obligatorios.")
    jefe_id = datos.get("jefe_id") or None
    if jefe_id and int(jefe_id) == int(empleado_id):
        raise ValueError("Un empleado no puede ser su propio jefe.")
    with db.transaccion() as con:
        con.execute(
            """UPDATE empleados SET
               nombre=?, puesto=?, jefe_id=?, contacto=?, responsabilidades=?,
               area_id=?, usuario_id=?
               WHERE id=?""",
            (
                nombre,
                puesto,
                jefe_id,
                (datos.get("contacto") or "").strip() or None,
                (datos.get("responsabilidades") or "").strip() or None,
                datos.get("area_id") or None,
                datos.get("usuario_id") or None,
                empleado_id,
            ),
        )


def dar_de_baja(empleado_id: int) -> None:
    Sesion.exigir("empleados.baja")
    with db.transaccion() as con:
        con.execute("UPDATE empleados SET activo=0 WHERE id=?", (empleado_id,))
        # Quitar como jefe de subordinados para no dejar referencias huérfanas visuales
        con.execute("UPDATE empleados SET jefe_id=NULL WHERE jefe_id=?", (empleado_id,))


def organigrama() -> list[dict]:
    """Devuelve la lista de empleados activos con su jefe para construir el árbol."""
    return listar(solo_activos=True)


def construir_arbol(empleados: list[dict] | None = None) -> list[dict]:
    """Devuelve nodos raíz con hijos anidados {empleado, hijos: [...]}."""
    if empleados is None:
        empleados = organigrama()
    por_id = {e["id"]: {"empleado": e, "hijos": []} for e in empleados}
    raices = []
    for e in empleados:
        nodo = por_id[e["id"]]
        jefe = e.get("jefe_id")
        if jefe and jefe in por_id:
            por_id[jefe]["hijos"].append(nodo)
        else:
            raices.append(nodo)
    return raices


def contadores() -> dict:
    total = db.consultar("SELECT COUNT(*) AS n FROM empleados WHERE activo=1")[0]["n"]
    tecnicos = db.consultar(
        "SELECT COUNT(*) AS n FROM empleados WHERE activo=1 AND (LOWER(puesto) LIKE '%técnico%' OR LOWER(puesto) LIKE '%tecnico%')"
    )[0]["n"]
    return {"total": total, "tecnicos": tecnicos}
