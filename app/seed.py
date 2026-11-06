"""Datos de demostración (ficticios, marcados es_demo=1)."""
import random
from datetime import datetime, timedelta

from app import db

PROVEEDORES = [
    "Refacciones Industriales del Norte (demo)",
    "Hidráulica y Sellos SA (demo)",
    "Rodamientos Express (demo)",
    "Lubricantes Premium MX (demo)",
]

REFACCIONES = [
    # codigo, nombre, categoria, ubicacion, min, max, unidad, costo, idx_proveedor, existencia
    ("DEMO-ROD-001", "Rodamiento 6205-2RS (demo)", "Rodamientos", "A-01-1", 4, 20, "pza", 85.50, 2, 8),
    ("DEMO-ROD-002", "Rodamiento 6308 (demo)", "Rodamientos", "A-01-2", 2, 12, "pza", 145.00, 2, 3),
    ("DEMO-SEL-003", "Sello mecánico 45 mm (demo)", "Sellos", "A-02-1", 2, 10, "pza", 420.00, 1, 4),
    ("DEMO-BAN-004", "Banda V A-48 (demo)", "Transmisión", "B-01-3", 3, 15, "pza", 78.90, 0, 6),
    ("DEMO-FIL-005", "Filtro hidráulico 10µ (demo)", "Hidráulica", "C-01-4", 5, 15, "pza", 398.00, 2, 11),
    ("DEMO-LUB-006", "Grasa EP-2 cartucho (demo)", "Lubricantes", "B-04-1", 12, 48, "pza", 62.30, 1, 30),
]

AREAS = ["Producción", "Empaque", "Servicios", "Almacén"]

EMPLEADOS = [
    # nombre, puesto, jefe_idx (None=raíz), area_idx, contacto
    ("Carlos Mendoza", "Jefe de Mantenimiento", None, 0, "carlos.mendoza@demo.local"),
    ("Ana Ruiz", "Supervisora de Mantenimiento", 0, 0, "ana.ruiz@demo.local"),
    ("Luis Hernández", "Técnico mecánico", 1, 0, "luis.h@demo.local"),
    ("María López", "Técnico eléctrico", 1, 0, "maria.l@demo.local"),
    ("Pedro Sánchez", "Técnico de instrumentación", 1, 2, "pedro.s@demo.local"),
    ("Sofía Vargas", "Almacenista de refacciones", 0, 3, "sofia.v@demo.local"),
]

EQUIPOS = [
    # codigo, nombre, area_idx, ubicacion, marca, modelo, criticidad, estado, responsable_idx, freq_dias
    ("EQ-BOM-01", "Bomba centrífuga principal", 0, "Línea 1", "Grundfos", "CR 32-4", "alta", "operativo", 2, 30),
    ("EQ-MOT-02", "Motor de banda transportadora", 0, "Línea 2", "Siemens", "1LE0001", "alta", "operativo", 2, 45),
    ("EQ-COM-03", "Compresor de aire", 2, "Cuarto de máquinas", "Atlas Copco", "GA 22", "alta", "en mantenimiento", 4, 60),
    ("EQ-CHL-04", "Chiller de proceso", 0, "Área fría", "Carrier", "30RB", "media", "operativo", 3, 90),
    ("EQ-EMP-05", "Selladora de empaque", 1, "Línea empaque", "Ulma", "FR 200", "media", "operativo", 2, 30),
    ("EQ-TRA-06", "Transformador 480 V", 2, "Subestación", "ABB", "Dry 500kVA", "alta", "operativo", 3, 180),
    ("EQ-BOM-07", "Bomba de recirculación", 0, "Tanque 3", "KSB", "Etanorm", "baja", "fuera de servicio", 2, 60),
    ("EQ-VEN-08", "Ventilador de extracción", 2, "Techo nave 2", "Systemair", "DV 450", "baja", "operativo", 4, 120),
]


def hay_demo() -> bool:
    return bool(db.consultar("SELECT 1 FROM refacciones WHERE es_demo=1 LIMIT 1")) or bool(
        db.consultar("SELECT 1 FROM equipos WHERE es_demo=1 LIMIT 1")
    ) or bool(db.consultar("SELECT 1 FROM empleados WHERE es_demo=1 LIMIT 1"))


def cargar_demo() -> None:
    if hay_demo():
        raise ValueError("Los datos de demostración ya están cargados.")
    random.seed(7)
    with db.transaccion() as con:
        # Áreas
        area_ids = []
        for nom in AREAS:
            cur = con.execute("INSERT OR IGNORE INTO areas (nombre) VALUES (?)", (nom,))
            if cur.lastrowid:
                area_ids.append(cur.lastrowid)
            else:
                row = con.execute("SELECT id FROM areas WHERE nombre=?", (nom,)).fetchone()
                area_ids.append(row[0])

        # Empleados
        emp_ids = []
        for nom, puesto, jefe_idx, area_idx, contacto in EMPLEADOS:
            jefe_id = emp_ids[jefe_idx] if jefe_idx is not None else None
            cur = con.execute(
                """INSERT INTO empleados (nombre, puesto, jefe_id, contacto, area_id, activo, es_demo)
                   VALUES (?,?,?,?,?,1,1)""",
                (nom, puesto, jefe_id, contacto, area_ids[area_idx]),
            )
            emp_ids.append(cur.lastrowid)

        # Equipos
        for cod, nom, area_idx, ubi, marca, modelo, crit, est, resp_idx, freq in EQUIPOS:
            con.execute(
                """INSERT INTO equipos
                   (codigo, nombre, area_id, ubicacion, marca, modelo, criticidad, estado,
                    frecuencia_preventivo_dias, responsable_id, activo, es_demo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1,1)""",
                (cod, nom, area_ids[area_idx], ubi, marca, modelo, crit, est, freq, emp_ids[resp_idx]),
            )

        # Proveedores + refacciones
        pids = [con.execute("INSERT INTO proveedores (nombre,es_demo) VALUES (?,1)", (n,)).lastrowid for n in PROVEEDORES]
        hoy = datetime.now()
        for cod, nom, cat, ubi, mn, mx, uni, costo, p, exist in REFACCIONES:
            rid = con.execute(
                """INSERT INTO refacciones (codigo,nombre,categoria,ubicacion_almacen,stock_minimo,stock_maximo,
                   unidad,costo_unitario,proveedor_id,existencia,fecha_ultima_entrada,es_demo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
                (cod, nom, cat, ubi, mn, mx, uni, costo, pids[p], exist, (hoy - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")),
            ).lastrowid
            salidas = [(m, random.randint(1, 4)) for m in range(5, 0, -1)]
            total_sal = sum(c for _, c in salidas)
            entrada0 = exist + total_sal
            f0 = (hoy - timedelta(days=185)).strftime("%Y-%m-%d 09:00:00")
            con.execute(
                """INSERT INTO movimientos_inventario (refaccion_id,fecha,tipo,cantidad,costo_unitario,
                   existencia_resultante,motivo,es_demo) VALUES (?,?,'ENTRADA',?,?,?,?,1)""",
                (rid, f0, entrada0, costo, entrada0, "Existencia inicial (demo)"),
            )
            saldo = entrada0
            for m, c in salidas:
                saldo -= c
                f = (hoy - timedelta(days=30 * m)).strftime("%Y-%m-%d 10:00:00")
                con.execute(
                    """INSERT INTO movimientos_inventario (refaccion_id,fecha,tipo,cantidad,costo_unitario,
                       existencia_resultante,motivo,es_demo) VALUES (?,?,'SALIDA',?,?,?,?,1)""",
                    (rid, f, c, costo, saldo, "Consumo de ejemplo (demo)"),
                )



        # --- Cursos y capacitaciones ---
        cids = []
        for nom, dur, inst in (
            ("Seguridad industrial básica (demo)", 8, "Instructor demo"),
            ("Lubricación de equipos rotativos (demo)", 4, "Instructor demo"),
            ("Lectura de planos eléctricos (demo)", 6, "Instructor demo"),
        ):
            cids.append(con.execute(
                "INSERT INTO cursos (nombre, duracion_h, instructor) VALUES (?,?,?)", (nom, dur, inst)
            ).lastrowid)
        con.execute(
            """INSERT INTO capacitaciones (empleado_id, curso_id, fecha_programada, responsable, estado)
               VALUES (?,?, date('now', '+7 days'), 'Ana Ruiz', 'programada')""",
            (emp_ids[2], cids[0]),
        )
        con.execute(
            """INSERT INTO capacitaciones (empleado_id, curso_id, fecha_programada, responsable, estado, fecha_completada)
               VALUES (?,?, date('now', '-30 days'), 'Ana Ruiz', 'completada', date('now', '-25 days'))""",
            (emp_ids[3], cids[1]),
        )

        # --- Presupuesto y metas KPI ---
        from datetime import datetime as _dt
        _hoy = _dt.now()
        con.execute("INSERT INTO presupuestos (anio, mes, area_id, monto) VALUES (?,?,?,?)",
                    (_hoy.year, _hoy.month, area_ids[0], 50000))
        con.execute("INSERT INTO presupuestos (anio, mes, area_id, monto) VALUES (?,?,?,?)",
                    (_hoy.year, _hoy.month, None, 120000))
        for kpi, meta, mayor in (("mttr", 4, 0), ("mtbf", 500, 1), ("oee", 85, 1), ("cumplimiento", 90, 1)):
            con.execute("INSERT OR REPLACE INTO kpi_metas (kpi, meta, mayor_es_mejor) VALUES (?,?,?)",
                        (kpi, meta, mayor))

        # --- Tarea / OT demo ---
        import uuid as _uuid
        ft = "TAR-DEMO-" + _uuid.uuid4().hex[:6].upper()
        fo = "OT-DEMO-" + _uuid.uuid4().hex[:6].upper()
        eq_row = con.execute("SELECT id FROM equipos WHERE es_demo=1 ORDER BY id LIMIT 1").fetchone()
        eq_id = eq_row[0] if eq_row else None
        if eq_id:
            tid = con.execute(
                """INSERT INTO tareas (folio, nombre, descripcion, equipo_id, tipo, tecnico_id,
                   fecha_programada, prioridad, estado, tiempo_estimado_h)
                   VALUES (?,?,?,?, 'correctivo', ?, date('now'), 'alta', 'asignada', 3)""",
                (ft, "Fuga en sello de bomba (demo)", "Correctivo de ejemplo para pruebas", eq_id, emp_ids[2]),
            ).lastrowid
            con.execute(
                """INSERT INTO ordenes_trabajo (folio, tarea_id, equipo_id, tecnico_id, estado, fecha_creacion, fecha_programada, descripcion)
                   VALUES (?,?,?,?, 'asignada', datetime('now'), date('now'), ?)""",
                (fo, tid, eq_id, emp_ids[2], "Fuga en sello de bomba (demo)"),
            )

        # VOL/REP
        con.execute("UPDATE volrep_config SET significado=? WHERE id=1",
                    ("VOL = Vales de salida de almacén / REP = Reportes de paro de equipo (demo)",))
        con.execute(
            """INSERT INTO volrep_registros (fecha, titulo, detalle, observaciones, usuario_id)
               VALUES (date('now'), 'Paro de línea 1 (demo)', 'Paro de 45 min por falla de banda', 'Registro demo', NULL)"""
        )



def borrar_demo() -> None:
    with db.transaccion() as con:
        con.execute("DELETE FROM movimientos_inventario WHERE es_demo=1")
        con.execute("DELETE FROM refacciones WHERE es_demo=1")
        con.execute("DELETE FROM proveedores WHERE es_demo=1")
        # Órdenes y tareas ligadas a equipos demo
        con.execute("""DELETE FROM historial_mantenimiento WHERE equipo_id IN (SELECT id FROM equipos WHERE es_demo=1)""")
        con.execute("""DELETE FROM ordenes_trabajo WHERE equipo_id IN (SELECT id FROM equipos WHERE es_demo=1)""")
        con.execute("""DELETE FROM tareas WHERE equipo_id IN (SELECT id FROM equipos WHERE es_demo=1)""")
        con.execute("""DELETE FROM documentos WHERE equipo_id IN (SELECT id FROM equipos WHERE es_demo=1)""")
        con.execute("DELETE FROM equipos WHERE es_demo=1")
        con.execute("""DELETE FROM capacitaciones WHERE empleado_id IN (SELECT id FROM empleados WHERE es_demo=1)""")
        con.execute("DELETE FROM empleados WHERE es_demo=1")
        con.execute("DELETE FROM cursos WHERE nombre LIKE '%(demo)%'")
        con.execute("DELETE FROM volrep_registros WHERE titulo LIKE '%(demo)%'")
        con.execute("DELETE FROM presupuestos WHERE anio >= 2020")  # demo budgets of current year are fine to clear on full demo wipe
