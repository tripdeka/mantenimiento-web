"""Acceso a SQLite: conexión, transacciones y esquema completo del sistema."""
import sqlite3
from contextlib import contextmanager

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('administrador','supervisor','tecnico','almacen')),
    activo INTEGER NOT NULL DEFAULT 1,
    debe_cambiar INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS empleados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    puesto TEXT NOT NULL,
    jefe_id INTEGER REFERENCES empleados(id),
    contacto TEXT,
    responsabilidades TEXT,
    area_id INTEGER REFERENCES areas(id),
    usuario_id INTEGER REFERENCES usuarios(id),
    activo INTEGER NOT NULL DEFAULT 1,
    es_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS equipos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    area_id INTEGER REFERENCES areas(id),
    ubicacion TEXT,
    marca TEXT, modelo TEXT, numero_serie TEXT,
    descripcion TEXT,
    criticidad TEXT NOT NULL DEFAULT 'media' CHECK (criticidad IN ('alta','media','baja')),
    estado TEXT NOT NULL DEFAULT 'operativo' CHECK (estado IN ('operativo','en mantenimiento','fuera de servicio')),
    fecha_instalacion TEXT,
    frecuencia_preventivo_dias INTEGER,
    responsable_id INTEGER REFERENCES empleados(id),
    activo INTEGER NOT NULL DEFAULT 1,
    es_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    contacto TEXT, telefono TEXT, correo TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    es_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS refacciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    categoria TEXT,
    marca TEXT, modelo TEXT,
    ubicacion_almacen TEXT,
    existencia REAL NOT NULL DEFAULT 0,
    stock_minimo REAL NOT NULL DEFAULT 0 CHECK (stock_minimo >= 0),
    stock_maximo REAL NOT NULL DEFAULT 0 CHECK (stock_maximo >= 0),
    unidad TEXT NOT NULL DEFAULT 'pza',
    costo_unitario REAL NOT NULL DEFAULT 0 CHECK (costo_unitario >= 0),
    proveedor_id INTEGER REFERENCES proveedores(id),
    fecha_ultima_entrada TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    es_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS refaccion_equipo (
    refaccion_id INTEGER NOT NULL REFERENCES refacciones(id),
    equipo_id INTEGER NOT NULL REFERENCES equipos(id),
    PRIMARY KEY (refaccion_id, equipo_id)
);
CREATE TABLE IF NOT EXISTS tareas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    equipo_id INTEGER NOT NULL REFERENCES equipos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('preventivo','predictivo','correctivo','autonomo','tpm')),
    tecnico_id INTEGER REFERENCES empleados(id),
    fecha_programada TEXT NOT NULL,
    fecha_vencimiento TEXT,
    prioridad TEXT NOT NULL DEFAULT 'media',
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','asignada','en proceso','terminada','vencida')),
    tiempo_estimado_h REAL, tiempo_real_h REAL,
    costo_mano_obra REAL NOT NULL DEFAULT 0,
    costo_materiales REAL NOT NULL DEFAULT 0,
    fecha_terminada TEXT,
    observaciones TEXT
);
CREATE TABLE IF NOT EXISTS ordenes_trabajo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio TEXT NOT NULL UNIQUE,
    tarea_id INTEGER REFERENCES tareas(id),
    equipo_id INTEGER NOT NULL REFERENCES equipos(id),
    tecnico_id INTEGER REFERENCES empleados(id),
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','asignada','en proceso','terminada','vencida')),
    fecha_creacion TEXT NOT NULL,
    fecha_programada TEXT,
    fecha_inicio TEXT, fecha_fin TEXT,
    descripcion TEXT
);
CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refaccion_id INTEGER NOT NULL REFERENCES refacciones(id),
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('ENTRADA','SALIDA')),
    cantidad REAL NOT NULL CHECK (cantidad > 0),
    costo_unitario REAL NOT NULL DEFAULT 0,
    existencia_resultante REAL NOT NULL,
    motivo TEXT,
    orden_trabajo_id INTEGER REFERENCES ordenes_trabajo(id),
    equipo_id INTEGER REFERENCES equipos(id),
    usuario_id INTEGER REFERENCES usuarios(id),
    es_excepcion INTEGER NOT NULL DEFAULT 0,
    es_demo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_mov_ref ON movimientos_inventario(refaccion_id, fecha);
CREATE TABLE IF NOT EXISTS historial_mantenimiento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipo_id INTEGER NOT NULL REFERENCES equipos(id),
    fecha_hora TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('preventivo','correctivo','autonomo','predictivo','tpm')),
    tecnico_id INTEGER REFERENCES empleados(id),
    orden_trabajo_id INTEGER REFERENCES ordenes_trabajo(id),
    descripcion TEXT, falla TEXT, causa TEXT, solucion TEXT,
    horas_paro REAL NOT NULL DEFAULT 0,
    costo_refacciones REAL NOT NULL DEFAULT 0,
    costo_mano_obra REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL,
    ruta TEXT NOT NULL,
    equipo_id INTEGER REFERENCES equipos(id),
    orden_trabajo_id INTEGER REFERENCES ordenes_trabajo(id),
    fecha_carga TEXT NOT NULL,
    usuario_id INTEGER REFERENCES usuarios(id)
);
CREATE TABLE IF NOT EXISTS presupuestos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anio INTEGER NOT NULL, mes INTEGER NOT NULL,
    area_id INTEGER REFERENCES areas(id),
    monto REAL NOT NULL CHECK (monto >= 0)
);
CREATE TABLE IF NOT EXISTS gastos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    concepto TEXT NOT NULL CHECK (concepto IN ('refacciones','mano de obra','servicios externos','otros')),
    monto REAL NOT NULL CHECK (monto >= 0),
    equipo_id INTEGER REFERENCES equipos(id),
    area_id INTEGER REFERENCES areas(id),
    descripcion TEXT
);
CREATE TABLE IF NOT EXISTS kpi_metas (
    kpi TEXT PRIMARY KEY,
    meta REAL NOT NULL,
    mayor_es_mejor INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS auditorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL, nombre TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','realizada')),
    resultado_pct REAL
);
CREATE TABLE IF NOT EXISTS hallazgos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auditoria_id INTEGER NOT NULL REFERENCES auditorias(id),
    descripcion TEXT NOT NULL, incumplimiento TEXT,
    responsable_id INTEGER REFERENCES empleados(id),
    accion_correctiva TEXT, fecha_compromiso TEXT,
    estado TEXT NOT NULL DEFAULT 'abierto' CHECK (estado IN ('abierto','en seguimiento','cerrado'))
);
CREATE TABLE IF NOT EXISTS cursos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE, duracion_h REAL, instructor TEXT
);
CREATE TABLE IF NOT EXISTS capacitaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empleado_id INTEGER NOT NULL REFERENCES empleados(id),
    curso_id INTEGER NOT NULL REFERENCES cursos(id),
    fecha_programada TEXT, responsable TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','programada','completada')),
    fecha_completada TEXT, constancia_ruta TEXT
);
CREATE TABLE IF NOT EXISTS volrep_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    significado TEXT NOT NULL DEFAULT 'Por definir'
);
CREATE TABLE IF NOT EXISTS volrep_registros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL, titulo TEXT NOT NULL,
    detalle TEXT, observaciones TEXT, usuario_id INTEGER REFERENCES usuarios(id)
);
CREATE TABLE IF NOT EXISTS bitacora (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL, usuario_id INTEGER, accion TEXT NOT NULL, detalle TEXT
);
INSERT OR IGNORE INTO volrep_config (id, significado) VALUES (1, 'Por definir');
"""


def conectar() -> sqlite3.Connection:
    # Se lee config.DB_PATH en cada llamada (permite cambiarla en pruebas/restauración).
    con = sqlite3.connect(str(config.DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode=DELETE")
    return con


@contextmanager
def transaccion():
    """Confirma al salir sin error; revierte todo si hay una excepción."""
    con = conectar()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def consultar(sql: str, params=()) -> list[dict]:
    con = conectar()
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def inicializar() -> None:
    """Crea carpetas, tablas y el usuario administrador inicial si la BD es nueva."""
    for d in (config.DATA_DIR, config.DOCS_DIR, config.BACKUP_DIR, config.EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    con = conectar()
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        for stmt in SCHEMA.split(";"):
            s = stmt.strip()
            if s:
                con.execute(s)
        con.commit()
    finally:
        con.close()
    from app import auth
    auth.crear_admin_inicial()
