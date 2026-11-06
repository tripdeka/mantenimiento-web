"""Autenticación (PBKDF2) y permisos por rol."""
import hashlib
import hmac
import secrets
from datetime import datetime

from app import db

ITER = 200_000
TODOS = {"administrador", "supervisor", "tecnico", "almacen"}

# acción -> roles autorizados
PERMISOS = {
    "inventario.ver": TODOS,
    "inventario.editar": {"administrador", "supervisor", "almacen"},
    "inventario.entrada": {"administrador", "supervisor", "almacen"},
    "inventario.salida": TODOS,
    "inventario.excepcion": {"administrador", "supervisor"},
    "inventario.baja": {"administrador"},
    "equipos.ver": TODOS,
    "equipos.editar": {"administrador", "supervisor"},
    "equipos.baja": {"administrador"},
    "empleados.ver": TODOS,
    "empleados.editar": {"administrador", "supervisor"},
    "empleados.baja": {"administrador"},
    "ordenes.ver": TODOS,
    "ordenes.editar": {"administrador", "supervisor", "tecnico"},
    "ordenes.asignar": {"administrador", "supervisor"},
    "kpi.ver": {"administrador", "supervisor"},
    "kpi.editar": {"administrador"},
    "capacitacion.ver": TODOS,
    "capacitacion.editar": {"administrador", "supervisor"},
    "sistema.respaldo": {"administrador"},
    "sistema.demo": {"administrador"},
}


class ErrorAcceso(Exception):
    pass


class Sesion:
    usuario: dict | None = None

    @classmethod
    def puede(cls, accion: str) -> bool:
        return bool(cls.usuario) and cls.usuario["rol"] in PERMISOS.get(accion, set())

    @classmethod
    def exigir(cls, accion: str) -> None:
        if not cls.puede(accion):
            raise ErrorAcceso("No tiene permiso para realizar esta acción.")

    @classmethod
    def id(cls):
        return cls.usuario["id"] if cls.usuario else None


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITER).hex()


def crear_usuario(usuario, nombre, password, rol, debe_cambiar=False) -> int:
    if not usuario.strip() or not password:
        raise ValueError("Usuario y contraseña son obligatorios.")
    if len(password) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    salt = secrets.token_hex(16)
    try:
        with db.transaccion() as con:
            cur = con.execute(
                "INSERT INTO usuarios (usuario,nombre,salt,password_hash,rol,debe_cambiar) VALUES (?,?,?,?,?,?)",
                (usuario.strip().lower(), nombre.strip(), salt, _hash(password, salt), rol, int(debe_cambiar)),
            )
            return cur.lastrowid
    except Exception as e:
        if "UNIQUE" in str(e):
            raise ValueError(f"El usuario '{usuario}' ya existe.") from e
        raise


def crear_admin_inicial() -> None:
    if not db.consultar("SELECT 1 FROM usuarios LIMIT 1"):
        crear_usuario("admin", "Administrador", "admin123", "administrador", debe_cambiar=True)


def iniciar_sesion(usuario: str, password: str) -> dict:
    filas = db.consultar("SELECT * FROM usuarios WHERE usuario=? AND activo=1", (usuario.strip().lower(),))
    if not filas or not hmac.compare_digest(filas[0]["password_hash"], _hash(password, filas[0]["salt"])):
        raise ValueError("Usuario o contraseña incorrectos.")
    Sesion.usuario = filas[0]
    return filas[0]


def cambiar_password(usuario_id: int, nueva: str) -> None:
    if len(nueva) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    salt = secrets.token_hex(16)
    with db.transaccion() as con:
        con.execute("UPDATE usuarios SET salt=?, password_hash=?, debe_cambiar=0 WHERE id=?",
                    (salt, _hash(nueva, salt), usuario_id))
    if Sesion.usuario and Sesion.usuario["id"] == usuario_id:
        Sesion.usuario["debe_cambiar"] = 0


def ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
