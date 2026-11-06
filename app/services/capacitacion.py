"""Capacitación, VOL/REP y generación de reportes PDF."""
from datetime import datetime
from pathlib import Path

from app import config, db
from app.auth import ErrorAcceso, Sesion


def _ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Cursos y capacitaciones ─────────────────────────────────────────────────

def listar_cursos() -> list[dict]:
    return db.consultar("SELECT * FROM cursos ORDER BY nombre")


def crear_curso(nombre: str, duracion_h=None, instructor=None) -> int:
    Sesion.exigir("capacitacion.editar")
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del curso es obligatorio.")
    with db.transaccion() as con:
        try:
            cur = con.execute(
                "INSERT INTO cursos (nombre, duracion_h, instructor) VALUES (?,?,?)",
                (nombre, float(duracion_h) if duracion_h not in (None, "") else None, (instructor or "").strip() or None),
            )
            return cur.lastrowid
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ValueError(f"Ya existe el curso «{nombre}».") from e
            raise


def listar_capacitaciones(estado=None, empleado_id=None) -> list[dict]:
    sql = """
        SELECT c.*, e.nombre AS empleado_nombre, e.puesto, cu.nombre AS curso_nombre,
               cu.duracion_h, cu.instructor
        FROM capacitaciones c
        JOIN empleados e ON e.id = c.empleado_id
        JOIN cursos cu ON cu.id = c.curso_id
        WHERE 1=1
    """
    params = []
    if estado:
        sql += " AND c.estado=?"
        params.append(estado)
    if empleado_id:
        sql += " AND c.empleado_id=?"
        params.append(empleado_id)
    sql += " ORDER BY c.fecha_programada DESC, c.id DESC"
    return db.consultar(sql, params)


def programar_capacitacion(datos: dict) -> int:
    Sesion.exigir("capacitacion.editar")
    if not datos.get("empleado_id") or not datos.get("curso_id"):
        raise ValueError("Empleado y curso son obligatorios.")
    with db.transaccion() as con:
        cur = con.execute(
            """INSERT INTO capacitaciones
               (empleado_id, curso_id, fecha_programada, responsable, estado)
               VALUES (?,?,?,?,'programada')""",
            (
                datos["empleado_id"], datos["curso_id"],
                datos.get("fecha_programada") or None,
                (datos.get("responsable") or "").strip() or None,
            ),
        )
        return cur.lastrowid


def completar_capacitacion(cap_id: int, constancia_ruta=None) -> None:
    Sesion.exigir("capacitacion.editar")
    with db.transaccion() as con:
        con.execute(
            """UPDATE capacitaciones SET estado='completada', fecha_completada=?, constancia_ruta=?
               WHERE id=?""",
            (_ahora()[:10], constancia_ruta, cap_id),
        )


def contadores_capacitacion() -> dict:
    pend = db.consultar("SELECT COUNT(*) AS n FROM capacitaciones WHERE estado IN ('pendiente','programada')")[0]["n"]
    comp = db.consultar("SELECT COUNT(*) AS n FROM capacitaciones WHERE estado='completada'")[0]["n"]
    cursos = db.consultar("SELECT COUNT(*) AS n FROM cursos")[0]["n"]
    return {"pendientes": pend, "completadas": comp, "cursos": cursos}


# ── VOL / REP ───────────────────────────────────────────────────────────────

def obtener_volrep_config() -> str:
    filas = db.consultar("SELECT significado FROM volrep_config WHERE id=1")
    return filas[0]["significado"] if filas else "Por definir"


def guardar_volrep_config(significado: str) -> None:
    Sesion.exigir("capacitacion.editar")
    with db.transaccion() as con:
        con.execute(
            "INSERT INTO volrep_config (id, significado) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET significado=excluded.significado",
            (significado.strip(),),
        )


def listar_volrep() -> list[dict]:
    return db.consultar(
        """SELECT v.*, u.nombre AS usuario_nombre
           FROM volrep_registros v
           LEFT JOIN usuarios u ON u.id = v.usuario_id
           ORDER BY v.fecha DESC, v.id DESC"""
    )


def registrar_volrep(titulo: str, detalle=None, observaciones=None) -> int:
    Sesion.exigir("capacitacion.editar")
    titulo = titulo.strip()
    if not titulo:
        raise ValueError("El título es obligatorio.")
    with db.transaccion() as con:
        cur = con.execute(
            """INSERT INTO volrep_registros (fecha, titulo, detalle, observaciones, usuario_id)
               VALUES (?,?,?,?,?)""",
            (_ahora()[:10], titulo, (detalle or "").strip() or None, (observaciones or "").strip() or None, Sesion.id()),
        )
        return cur.lastrowid


# ── Reportes PDF ────────────────────────────────────────────────────────────

def generar_reporte_pdf(tipo: str) -> str:
    """Genera un PDF según tipo: inventario | equipos | ordenes | kpi | capacitacion.
    Devuelve la ruta del archivo."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    except ImportError as e:
        raise ValueError("Falta reportlab. Ejecute: pip install reportlab") from e

    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now().strftime("%Y%m%d_%H%M")
    ruta = config.EXPORT_DIR / f"reporte_{tipo}_{fecha}.pdf"

    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle("TituloMX", parent=styles["Heading1"], fontSize=16, spaceAfter=8)
    sub_style = ParagraphStyle("SubMX", parent=styles["Normal"], fontSize=10, textColor=colors.grey)

    doc = SimpleDocTemplate(str(ruta), pagesize=letter, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story = []
    story.append(Paragraph("Sistema de Mantenimiento y Refacciones", titulo_style))
    story.append(Paragraph(f"Reporte: {tipo.upper()} — Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", sub_style))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1F4E79")))
    story.append(Spacer(1, 0.4 * cm))

    def tabla(headers, rows, col_widths=None):
        data = [headers] + rows
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    if tipo == "inventario":
        from app.services import inventario as inv
        refs = inv.listar_refacciones()
        story.append(Paragraph("Inventario de refacciones", styles["Heading2"]))
        rows = [[r["codigo"], r["nombre"][:40], f"{r['existencia']:g}", f"{r['stock_minimo']:g}",
                 f"${r['costo_unitario']:,.2f}"] for r in refs]
        story.append(tabla(["Código", "Nombre", "Exist.", "Mín.", "Costo"], rows))

    elif tipo == "equipos":
        from app.services import equipos as eq
        eqs = eq.listar()
        story.append(Paragraph("Equipos y máquinas", styles["Heading2"]))
        rows = [[e["codigo"], e["nombre"][:35], e.get("area") or "", e["criticidad"], e["estado"]] for e in eqs]
        story.append(tabla(["Código", "Nombre", "Área", "Criticidad", "Estado"], rows))

    elif tipo == "ordenes":
        from app.services import ordenes as ord
        tareas = ord.listar_tareas(solo_activas=False)
        story.append(Paragraph("Tareas y órdenes de trabajo", styles["Heading2"]))
        rows = [[t["folio"], t["nombre"][:30], t.get("equipo_codigo") or "", t["tipo"], t["estado"],
                 (t.get("fecha_programada") or "")[:10]] for t in tareas[:80]]
        story.append(tabla(["Folio", "Tarea", "Equipo", "Tipo", "Estado", "Programada"], rows))

    elif tipo == "kpi":
        k = resumen_kpis() if False else None
        from app.services import kpi as kpi_svc
        k = kpi_svc.resumen_kpis()
        story.append(Paragraph("Indicadores de mantenimiento", styles["Heading2"]))
        def fmt(v, suf=""):
            return f"{v:.1f}{suf}" if v is not None else "—"
        rows = [
            ["MTTR (horas)", fmt(k["mttr"]), "Promedio de reparación correctiva"],
            ["MTBF (horas)", fmt(k["mtbf"]), "Tiempo medio entre fallas"],
            ["OEE (%)", fmt(k["oee"]), "Efectividad global del equipo"],
            ["Cumplimiento OT (%)", fmt(k["cumplimiento"]), "Órdenes terminadas a tiempo"],
        ]
        story.append(tabla(["KPI", "Valor", "Descripción"], rows))
        hoy = datetime.now()
        pv = kpi_svc.presupuesto_vs_gasto(hoy.year, hoy.month)
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(f"Presupuesto vs gasto — {hoy.month:02d}/{hoy.year}", styles["Heading3"]))
        rows2 = [
            ["Presupuesto", f"${pv['presupuesto']:,.2f}"],
            ["Gasto real", f"${pv['gasto']:,.2f}"],
            ["Variación", f"${pv['variacion']:,.2f}"],
        ]
        story.append(tabla(["Concepto", "Monto"], rows2))

    elif tipo == "capacitacion":
        caps = listar_capacitaciones()
        story.append(Paragraph("Capacitaciones", styles["Heading2"]))
        rows = [[c.get("empleado_nombre") or "", c.get("curso_nombre") or "", c["estado"],
                 (c.get("fecha_programada") or "")[:10], (c.get("fecha_completada") or "")[:10]] for c in caps[:80]]
        story.append(tabla(["Empleado", "Curso", "Estado", "Programada", "Completada"], rows))

    else:
        raise ValueError(f"Tipo de reporte desconocido: {tipo}")

    doc.build(story)
    return str(ruta)


# Import local to avoid circular issues at module level for kpi summary in PDF
def resumen_kpis():
    from app.services import kpi as kpi_svc
    return kpi_svc.resumen_kpis()
