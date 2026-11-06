"""Órdenes de trabajo, tareas de mantenimiento, historial y documentos."""
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import uuid

from app import config, db
from app.auth import ErrorAcceso, Sesion
from app.services import inventario as inv


def _ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _folio(prefijo: str) -> str:
    return f"{prefijo}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


# ── Tareas ──────────────────────────────────────────────────────────────────

def listar_tareas(estado=None, equipo_id=None, tecnico_id=None, solo_activas=True) -> list[dict]:
    sql = """
        SELECT t.*, e.codigo AS equipo_codigo, e.nombre AS equipo_nombre,
               emp.nombre AS tecnico_nombre, a.nombre AS area
        FROM tareas t
        JOIN equipos e ON e.id = t.equipo_id
        LEFT JOIN empleados emp ON emp.id = t.tecnico_id
        LEFT JOIN areas a ON a.id = e.area_id
        WHERE 1=1
    """
    params = []
    if solo_activas:
        sql += " AND t.estado NOT IN ('terminada')"
    if estado:
        sql += " AND t.estado=?"
        params.append(estado)
    if equipo_id:
        sql += " AND t.equipo_id=?"
        params.append(equipo_id)
    if tecnico_id:
        sql += " AND t.tecnico_id=?"
        params.append(tecnico_id)
    sql += " ORDER BY t.fecha_programada, t.prioridad DESC"
    return db.consultar(sql, params)


def crear_tarea(datos: dict) -> int:
    Sesion.exigir("ordenes.editar")
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("El nombre de la tarea es obligatorio.")
    if not datos.get("equipo_id"):
        raise ValueError("Seleccione un equipo.")
    if not datos.get("fecha_programada"):
        raise ValueError("Indique la fecha programada.")
    tipo = datos.get("tipo") or "preventivo"
    if tipo not in ("preventivo", "predictivo", "correctivo", "autonomo", "tpm"):
        raise ValueError("Tipo de mantenimiento inválido.")
    prioridad = datos.get("prioridad") or "media"
    folio = _folio("TAR")
    estado = "asignada" if datos.get("tecnico_id") else "pendiente"
    with db.transaccion() as con:
        cur = con.execute(
            """INSERT INTO tareas
               (folio, nombre, descripcion, equipo_id, tipo, tecnico_id,
                fecha_programada, fecha_vencimiento, prioridad, estado,
                tiempo_estimado_h, observaciones)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                folio, nombre, (datos.get("descripcion") or "").strip() or None,
                datos["equipo_id"], tipo, datos.get("tecnico_id") or None,
                datos["fecha_programada"], datos.get("fecha_vencimiento") or None,
                prioridad, estado,
                float(datos["tiempo_estimado_h"]) if datos.get("tiempo_estimado_h") not in (None, "") else None,
                (datos.get("observaciones") or "").strip() or None,
            ),
        )
        tid = cur.lastrowid
        # Crear orden de trabajo asociada
        ofolio = _folio("OT")
        con.execute(
            """INSERT INTO ordenes_trabajo
               (folio, tarea_id, equipo_id, tecnico_id, estado, fecha_creacion, fecha_programada, descripcion)
               VALUES (?,?,?,?,?,?,?,?)""",
            (ofolio, tid, datos["equipo_id"], datos.get("tecnico_id") or None, estado, _ahora(),
             datos["fecha_programada"], nombre),
        )
        return tid


def asignar_tecnico(tarea_id: int, tecnico_id: int) -> None:
    Sesion.exigir("ordenes.asignar")
    with db.transaccion() as con:
        con.execute("UPDATE tareas SET tecnico_id=?, estado='asignada' WHERE id=?", (tecnico_id, tarea_id))
        con.execute(
            "UPDATE ordenes_trabajo SET tecnico_id=?, estado='asignada' WHERE tarea_id=?",
            (tecnico_id, tarea_id),
        )


def iniciar_tarea(tarea_id: int) -> None:
    Sesion.exigir("ordenes.editar")
    with db.transaccion() as con:
        con.execute("UPDATE tareas SET estado='en proceso' WHERE id=?", (tarea_id,))
        con.execute(
            "UPDATE ordenes_trabajo SET estado='en proceso', fecha_inicio=? WHERE tarea_id=? AND fecha_inicio IS NULL",
            (_ahora(), tarea_id),
        )
        # Marcar equipo en mantenimiento
        row = con.execute("SELECT equipo_id FROM tareas WHERE id=?", (tarea_id,)).fetchone()
        if row:
            con.execute("UPDATE equipos SET estado='en mantenimiento' WHERE id=?", (row[0],))


def terminar_tarea(tarea_id: int, datos: dict) -> None:
    """Cierra la tarea: registra historial, descuenta refacciones, actualiza costos y estado del equipo."""
    Sesion.exigir("ordenes.editar")
    filas = db.consultar("SELECT * FROM tareas WHERE id=?", (tarea_id,))
    if not filas:
        raise ValueError("Tarea no encontrada.")
    t = filas[0]
    if t["estado"] == "terminada":
        raise ValueError("La tarea ya está terminada.")

    tiempo_real = float(datos.get("tiempo_real_h") or 0)
    costo_mo = float(datos.get("costo_mano_obra") or 0)
    falla = (datos.get("falla") or "").strip() or None
    causa = (datos.get("causa") or "").strip() or None
    solucion = (datos.get("solucion") or "").strip() or None
    horas_paro = float(datos.get("horas_paro") or 0)
    observaciones = (datos.get("observaciones") or "").strip() or None
    refacciones_usadas = datos.get("refacciones") or []  # list of {refaccion_id, cantidad}

    costo_mat = 0.0
    ot_rows = db.consultar("SELECT id FROM ordenes_trabajo WHERE tarea_id=? ORDER BY id DESC LIMIT 1", (tarea_id,))
    ot_id = ot_rows[0]["id"] if ot_rows else None

    with db.transaccion() as con:
        # Descontar refacciones
        for r in refacciones_usadas:
            rid = r.get("refaccion_id")
            cant = float(r.get("cantidad") or 0)
            if not rid or cant <= 0:
                continue
            ref = con.execute("SELECT * FROM refacciones WHERE id=? AND activo=1", (rid,)).fetchone()
            if not ref:
                raise ValueError(f"Refacción id={rid} no encontrada.")
            if ref["existencia"] < cant and not r.get("excepcion"):
                raise ValueError(
                    f"Existencia insuficiente de {ref['codigo']} (hay {ref['existencia']:g}, se piden {cant:g})."
                )
            nueva = ref["existencia"] - cant
            con.execute(
                "UPDATE refacciones SET existencia=? WHERE id=?",
                (nueva, rid),
            )
            con.execute(
                """INSERT INTO movimientos_inventario
                   (refaccion_id, fecha, tipo, cantidad, costo_unitario, existencia_resultante,
                    motivo, orden_trabajo_id, equipo_id, usuario_id, es_excepcion)
                   VALUES (?,?,'SALIDA',?,?,?,?,?,?,?,?)""",
                (
                    rid, _ahora(), cant, ref["costo_unitario"], nueva,
                    f"OT {t['folio']}: {t['nombre']}", ot_id, t["equipo_id"],
                    Sesion.id(), int(bool(r.get("excepcion"))),
                ),
            )
            costo_mat += cant * float(ref["costo_unitario"] or 0)

        con.execute(
            """UPDATE tareas SET estado='terminada', tiempo_real_h=?, costo_mano_obra=?,
               costo_materiales=?, fecha_terminada=?, observaciones=? WHERE id=?""",
            (tiempo_real, costo_mo, costo_mat, _ahora(), observaciones, tarea_id),
        )
        con.execute(
            "UPDATE ordenes_trabajo SET estado='terminada', fecha_fin=? WHERE tarea_id=?",
            (_ahora(), tarea_id),
        )
        con.execute(
            """INSERT INTO historial_mantenimiento
               (equipo_id, fecha_hora, tipo, tecnico_id, orden_trabajo_id, descripcion,
                falla, causa, solucion, horas_paro, costo_refacciones, costo_mano_obra)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                t["equipo_id"], _ahora(), t["tipo"], t["tecnico_id"], ot_id,
                t["nombre"], falla, causa, solucion, horas_paro, costo_mat, costo_mo,
            ),
        )
        # Registrar gasto de materiales y mano de obra
        if costo_mat > 0:
            area = con.execute("SELECT area_id FROM equipos WHERE id=?", (t["equipo_id"],)).fetchone()
            con.execute(
                """INSERT INTO gastos (fecha, concepto, monto, equipo_id, area_id, descripcion)
                   VALUES (?, 'refacciones', ?, ?, ?, ?)""",
                (_ahora()[:10], costo_mat, t["equipo_id"], area[0] if area else None, f"OT {t['folio']}"),
            )
        if costo_mo > 0:
            area = con.execute("SELECT area_id FROM equipos WHERE id=?", (t["equipo_id"],)).fetchone()
            con.execute(
                """INSERT INTO gastos (fecha, concepto, monto, equipo_id, area_id, descripcion)
                   VALUES (?, 'mano de obra', ?, ?, ?, ?)""",
                (_ahora()[:10], costo_mo, t["equipo_id"], area[0] if area else None, f"OT {t['folio']}"),
            )
        # Devolver equipo a operativo si no hay otras OT abiertas
        abiertas = con.execute(
            """SELECT COUNT(*) FROM tareas
               WHERE equipo_id=? AND estado IN ('pendiente','asignada','en proceso') AND id!=?""",
            (t["equipo_id"], tarea_id),
        ).fetchone()[0]
        if abiertas == 0:
            con.execute("UPDATE equipos SET estado='operativo' WHERE id=?", (t["equipo_id"],))


def listar_ordenes(estado=None) -> list[dict]:
    sql = """
        SELECT o.*, e.codigo AS equipo_codigo, e.nombre AS equipo_nombre,
               emp.nombre AS tecnico_nombre, t.nombre AS tarea_nombre, t.tipo AS tipo_mto
        FROM ordenes_trabajo o
        JOIN equipos e ON e.id = o.equipo_id
        LEFT JOIN empleados emp ON emp.id = o.tecnico_id
        LEFT JOIN tareas t ON t.id = o.tarea_id
        WHERE 1=1
    """
    params = []
    if estado:
        sql += " AND o.estado=?"
        params.append(estado)
    sql += " ORDER BY o.fecha_creacion DESC"
    return db.consultar(sql, params)


def historial_equipo(equipo_id: int) -> list[dict]:
    return db.consultar(
        """SELECT h.*, emp.nombre AS tecnico_nombre, o.folio AS ot_folio
           FROM historial_mantenimiento h
           LEFT JOIN empleados emp ON emp.id = h.tecnico_id
           LEFT JOIN ordenes_trabajo o ON o.id = h.orden_trabajo_id
           WHERE h.equipo_id=?
           ORDER BY h.fecha_hora DESC""",
        (equipo_id,),
    )


# ── Documentos ──────────────────────────────────────────────────────────────

def guardar_documento(ruta_origen: str, nombre: str, tipo: str, equipo_id=None, ot_id=None) -> int:
    Sesion.exigir("ordenes.editar")
    origen = Path(ruta_origen)
    if not origen.is_file():
        raise ValueError("Archivo no encontrado.")
    dest_dir = config.DOCS_DIR / (f"equipo_{equipo_id}" if equipo_id else f"ot_{ot_id}" if ot_id else "general")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex[:8]}_{origen.name}"
    shutil.copy2(origen, dest)
    with db.transaccion() as con:
        cur = con.execute(
            """INSERT INTO documentos (nombre, tipo, ruta, equipo_id, orden_trabajo_id, fecha_carga, usuario_id)
               VALUES (?,?,?,?,?,?,?)""",
            (nombre or origen.name, tipo or "otro", str(dest), equipo_id, ot_id, _ahora(), Sesion.id()),
        )
        return cur.lastrowid


def listar_documentos(equipo_id=None, ot_id=None) -> list[dict]:
    sql = "SELECT * FROM documentos WHERE 1=1"
    params = []
    if equipo_id:
        sql += " AND equipo_id=?"
        params.append(equipo_id)
    if ot_id:
        sql += " AND orden_trabajo_id=?"
        params.append(ot_id)
    sql += " ORDER BY fecha_carga DESC"
    return db.consultar(sql, params)


def contadores_ordenes() -> dict:
    pend = db.consultar("SELECT COUNT(*) AS n FROM tareas WHERE estado IN ('pendiente','asignada')")[0]["n"]
    proceso = db.consultar("SELECT COUNT(*) AS n FROM tareas WHERE estado='en proceso'")[0]["n"]
    term = db.consultar("SELECT COUNT(*) AS n FROM tareas WHERE estado='terminada'")[0]["n"]
    venc = db.consultar(
        "SELECT COUNT(*) AS n FROM tareas WHERE estado NOT IN ('terminada') AND fecha_vencimiento IS NOT NULL AND fecha_vencimiento < date('now')"
    )[0]["n"]
    return {"pendientes": pend, "en_proceso": proceso, "terminadas": term, "vencidas": venc}


def programar_preventivos() -> int:
    """Genera tareas preventivas para equipos cuya frecuencia ya venció. Devuelve cuántas se crearon."""
    Sesion.exigir("ordenes.editar")
    equipos = db.consultar(
        """SELECT e.* FROM equipos e
           WHERE e.activo=1 AND e.frecuencia_preventivo_dias IS NOT NULL AND e.frecuencia_preventivo_dias > 0"""
    )
    creadas = 0
    for e in equipos:
        # Último preventivo terminado
        ult = db.consultar(
            """SELECT fecha_hora FROM historial_mantenimiento
               WHERE equipo_id=? AND tipo='preventivo' ORDER BY fecha_hora DESC LIMIT 1""",
            (e["id"],),
        )
        # ¿Hay tarea preventiva abierta?
        abierta = db.consultar(
            """SELECT 1 FROM tareas WHERE equipo_id=? AND tipo='preventivo'
               AND estado IN ('pendiente','asignada','en proceso') LIMIT 1""",
            (e["id"],),
        )
        if abierta:
            continue
        if ult:
            try:
                ultima = datetime.strptime(ult[0]["fecha_hora"][:10], "%Y-%m-%d")
            except ValueError:
                ultima = datetime.now() - timedelta(days=e["frecuencia_preventivo_dias"] + 1)
        else:
            ultima = datetime.now() - timedelta(days=e["frecuencia_preventivo_dias"] + 1)
        dias = (datetime.now() - ultima).days
        if dias >= e["frecuencia_preventivo_dias"]:
            crear_tarea({
                "nombre": f"Preventivo programado – {e['codigo']}",
                "descripcion": f"Mantenimiento preventivo según frecuencia de {e['frecuencia_preventivo_dias']} días.",
                "equipo_id": e["id"],
                "tipo": "preventivo",
                "tecnico_id": e.get("responsable_id"),
                "fecha_programada": datetime.now().strftime("%Y-%m-%d"),
                "fecha_vencimiento": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
                "prioridad": "alta" if e["criticidad"] == "alta" else "media",
                "tiempo_estimado_h": 2,
            })
            creadas += 1
    return creadas
