"""KPI de mantenimiento, presupuestos, gastos y auditorías."""
from datetime import datetime, timedelta

from app import db
from app.auth import ErrorAcceso, Sesion


def _meses_atras(n=6) -> list[str]:
    hoy = datetime.now().replace(day=1)
    out = []
    for i in range(n - 1, -1, -1):
        m = hoy.month - i
        a = hoy.year
        while m <= 0:
            m += 12
            a -= 1
        out.append(f"{a:04d}-{m:02d}")
    return out


# ── KPIs ────────────────────────────────────────────────────────────────────

def calcular_mttr(dias=90) -> float | None:
    """Mean Time To Repair (horas): promedio de tiempo_real_h de correctivos terminados."""
    filas = db.consultar(
        """SELECT tiempo_real_h FROM tareas
           WHERE tipo='correctivo' AND estado='terminada'
             AND tiempo_real_h IS NOT NULL AND tiempo_real_h > 0
             AND fecha_terminada >= date('now', ?)""",
        (f"-{dias} days",),
    )
    if not filas:
        return None
    return sum(f["tiempo_real_h"] for f in filas) / len(filas)


def calcular_mtbf(dias=90) -> float | None:
    """Mean Time Between Failures (horas): tiempo total / número de fallas (correctivos)."""
    n_fallas = db.consultar(
        """SELECT COUNT(*) AS n FROM historial_mantenimiento
           WHERE tipo='correctivo' AND fecha_hora >= datetime('now', ?)""",
        (f"-{dias} days",),
    )[0]["n"]
    if n_fallas == 0:
        return None
    # Horas de operación aproximadas: días * 24 * equipos activos
    n_eq = db.consultar("SELECT COUNT(*) AS n FROM equipos WHERE activo=1")[0]["n"] or 1
    horas_totales = dias * 24 * n_eq
    return horas_totales / n_fallas


def calcular_oee(dias=30) -> float | None:
    """OEE simplificado: (1 - horas_paro / horas_disponibles) * 100."""
    paro = db.consultar(
        """SELECT COALESCE(SUM(horas_paro),0) AS h FROM historial_mantenimiento
           WHERE fecha_hora >= datetime('now', ?)""",
        (f"-{dias} days",),
    )[0]["h"]
    n_eq = db.consultar("SELECT COUNT(*) AS n FROM equipos WHERE activo=1")[0]["n"] or 1
    disponibles = dias * 24 * n_eq
    if disponibles <= 0:
        return None
    return max(0.0, min(100.0, (1 - paro / disponibles) * 100))


def cumplimiento_ordenes(dias=30) -> float | None:
    """% de tareas terminadas a tiempo (fecha_terminada <= fecha_vencimiento o sin vencimiento)."""
    filas = db.consultar(
        """SELECT fecha_terminada, fecha_vencimiento FROM tareas
           WHERE estado='terminada' AND fecha_terminada >= date('now', ?)""",
        (f"-{dias} days",),
    )
    if not filas:
        return None
    a_tiempo = 0
    for f in filas:
        if not f["fecha_vencimiento"] or (f["fecha_terminada"] or "")[:10] <= f["fecha_vencimiento"][:10]:
            a_tiempo += 1
    return 100.0 * a_tiempo / len(filas)


def resumen_kpis() -> dict:
    return {
        "mttr": calcular_mttr(),
        "mtbf": calcular_mtbf(),
        "oee": calcular_oee(),
        "cumplimiento": cumplimiento_ordenes(),
    }


def obtener_metas() -> dict:
    filas = db.consultar("SELECT * FROM kpi_metas")
    return {f["kpi"]: f for f in filas}


def guardar_meta(kpi: str, meta: float, mayor_es_mejor: bool = True) -> None:
    Sesion.exigir("kpi.editar")
    with db.transaccion() as con:
        con.execute(
            """INSERT INTO kpi_metas (kpi, meta, mayor_es_mejor) VALUES (?,?,?)
               ON CONFLICT(kpi) DO UPDATE SET meta=excluded.meta, mayor_es_mejor=excluded.mayor_es_mejor""",
            (kpi, meta, int(mayor_es_mejor)),
        )


# ── Presupuesto y gastos ────────────────────────────────────────────────────

def listar_presupuestos(anio=None) -> list[dict]:
    sql = """
        SELECT p.*, a.nombre AS area
        FROM presupuestos p
        LEFT JOIN areas a ON a.id = p.area_id
        WHERE 1=1
    """
    params = []
    if anio:
        sql += " AND p.anio=?"
        params.append(anio)
    sql += " ORDER BY p.anio DESC, p.mes, a.nombre"
    return db.consultar(sql, params)


def guardar_presupuesto(anio: int, mes: int, monto: float, area_id=None) -> None:
    Sesion.exigir("kpi.editar")
    if not (1 <= mes <= 12):
        raise ValueError("Mes inválido.")
    if monto < 0:
        raise ValueError("El monto no puede ser negativo.")
    with db.transaccion() as con:
        # Upsert simple
        existe = con.execute(
            "SELECT id FROM presupuestos WHERE anio=? AND mes=? AND IFNULL(area_id,0)=IFNULL(?,0)",
            (anio, mes, area_id),
        ).fetchone()
        if existe:
            con.execute("UPDATE presupuestos SET monto=? WHERE id=?", (monto, existe[0]))
        else:
            con.execute(
                "INSERT INTO presupuestos (anio, mes, area_id, monto) VALUES (?,?,?,?)",
                (anio, mes, area_id, monto),
            )


def listar_gastos(anio=None, mes=None) -> list[dict]:
    sql = """
        SELECT g.*, e.codigo AS equipo_codigo, a.nombre AS area
        FROM gastos g
        LEFT JOIN equipos e ON e.id = g.equipo_id
        LEFT JOIN areas a ON a.id = g.area_id
        WHERE 1=1
    """
    params = []
    if anio and mes:
        sql += " AND strftime('%Y', g.fecha)=? AND strftime('%m', g.fecha)=?"
        params.extend([str(anio), f"{mes:02d}"])
    elif anio:
        sql += " AND strftime('%Y', g.fecha)=?"
        params.append(str(anio))
    sql += " ORDER BY g.fecha DESC"
    return db.consultar(sql, params)


def registrar_gasto(datos: dict) -> int:
    Sesion.exigir("kpi.editar")
    concepto = datos.get("concepto") or "otros"
    if concepto not in ("refacciones", "mano de obra", "servicios externos", "otros"):
        raise ValueError("Concepto inválido.")
    monto = float(datos.get("monto") or 0)
    if monto < 0:
        raise ValueError("Monto inválido.")
    with db.transaccion() as con:
        cur = con.execute(
            """INSERT INTO gastos (fecha, concepto, monto, equipo_id, area_id, descripcion)
               VALUES (?,?,?,?,?,?)""",
            (
                datos.get("fecha") or datetime.now().strftime("%Y-%m-%d"),
                concepto, monto,
                datos.get("equipo_id") or None,
                datos.get("area_id") or None,
                (datos.get("descripcion") or "").strip() or None,
            ),
        )
        return cur.lastrowid


def presupuesto_vs_gasto(anio: int, mes: int) -> dict:
    pres = db.consultar(
        "SELECT COALESCE(SUM(monto),0) AS t FROM presupuestos WHERE anio=? AND mes=?",
        (anio, mes),
    )[0]["t"]
    gasto = db.consultar(
        """SELECT COALESCE(SUM(monto),0) AS t FROM gastos
           WHERE strftime('%Y', fecha)=? AND strftime('%m', fecha)=?""",
        (str(anio), f"{mes:02d}"),
    )[0]["t"]
    return {"presupuesto": pres, "gasto": gasto, "variacion": pres - gasto, "pct": (gasto / pres * 100) if pres else None}


def gasto_por_mes(anio: int) -> list[dict]:
    return db.consultar(
        """SELECT CAST(strftime('%m', fecha) AS INTEGER) AS mes, COALESCE(SUM(monto),0) AS total
           FROM gastos WHERE strftime('%Y', fecha)=?
           GROUP BY mes ORDER BY mes""",
        (str(anio),),
    )


# ── Auditorías ──────────────────────────────────────────────────────────────

def listar_auditorias() -> list[dict]:
    return db.consultar("SELECT * FROM auditorias ORDER BY fecha DESC")


def crear_auditoria(nombre: str, fecha: str) -> int:
    Sesion.exigir("kpi.editar")
    with db.transaccion() as con:
        cur = con.execute(
            "INSERT INTO auditorias (fecha, nombre, estado) VALUES (?,?, 'pendiente')",
            (fecha, nombre.strip()),
        )
        return cur.lastrowid


def cerrar_auditoria(auditoria_id: int, resultado_pct: float) -> None:
    Sesion.exigir("kpi.editar")
    with db.transaccion() as con:
        con.execute(
            "UPDATE auditorias SET estado='realizada', resultado_pct=? WHERE id=?",
            (resultado_pct, auditoria_id),
        )


def listar_hallazgos(auditoria_id: int) -> list[dict]:
    return db.consultar(
        """SELECT h.*, e.nombre AS responsable_nombre
           FROM hallazgos h
           LEFT JOIN empleados e ON e.id = h.responsable_id
           WHERE h.auditoria_id=?
           ORDER BY h.id""",
        (auditoria_id,),
    )


def agregar_hallazgo(datos: dict) -> int:
    Sesion.exigir("kpi.editar")
    with db.transaccion() as con:
        cur = con.execute(
            """INSERT INTO hallazgos
               (auditoria_id, descripcion, incumplimiento, responsable_id, accion_correctiva, fecha_compromiso, estado)
               VALUES (?,?,?,?,?,?, 'abierto')""",
            (
                datos["auditoria_id"],
                datos["descripcion"].strip(),
                (datos.get("incumplimiento") or "").strip() or None,
                datos.get("responsable_id") or None,
                (datos.get("accion_correctiva") or "").strip() or None,
                datos.get("fecha_compromiso") or None,
            ),
        )
        return cur.lastrowid


def actualizar_hallazgo(hallazgo_id: int, estado: str, accion_correctiva=None) -> None:
    Sesion.exigir("kpi.editar")
    if estado not in ("abierto", "en seguimiento", "cerrado"):
        raise ValueError("Estado inválido.")
    with db.transaccion() as con:
        if accion_correctiva is not None:
            con.execute(
                "UPDATE hallazgos SET estado=?, accion_correctiva=? WHERE id=?",
                (estado, accion_correctiva, hallazgo_id),
            )
        else:
            con.execute("UPDATE hallazgos SET estado=? WHERE id=?", (estado, hallazgo_id))
