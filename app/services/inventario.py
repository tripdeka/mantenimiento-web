"""Lógica de negocio del inventario de refacciones (sin dependencias de interfaz)."""
import sqlite3

from app import auth, config, db
from app.auth import Sesion


class ErrorNegocio(ValueError):
    """Error de validación o regla de negocio, con mensaje apto para el usuario."""


def _num(valor, campo, minimo=0.0, obligatorio=True) -> float:
    if valor in (None, ""):
        if obligatorio:
            raise ErrorNegocio(f"El campo «{campo}» es obligatorio.")
        return 0.0
    try:
        n = float(str(valor).replace(",", ""))
    except ValueError:
        raise ErrorNegocio(f"«{campo}» debe ser un número.") from None
    if n < minimo:
        raise ErrorNegocio(f"«{campo}» no puede ser menor que {minimo:g}.")
    return n


def _validar_refaccion(d: dict) -> dict:
    v = {
        "codigo": (d.get("codigo") or "").strip().upper(),
        "nombre": (d.get("nombre") or "").strip(),
        "descripcion": (d.get("descripcion") or "").strip(),
        "categoria": (d.get("categoria") or "").strip(),
        "marca": (d.get("marca") or "").strip(),
        "modelo": (d.get("modelo") or "").strip(),
        "ubicacion_almacen": (d.get("ubicacion_almacen") or "").strip(),
        "unidad": (d.get("unidad") or "pza").strip(),
        "stock_minimo": _num(d.get("stock_minimo"), "Stock mínimo", obligatorio=False),
        "stock_maximo": _num(d.get("stock_maximo"), "Stock máximo", obligatorio=False),
        "costo_unitario": _num(d.get("costo_unitario"), "Costo unitario", obligatorio=False),
        "proveedor_id": d.get("proveedor_id") or None,
    }
    if not v["codigo"]:
        raise ErrorNegocio("El código es obligatorio.")
    if not v["nombre"]:
        raise ErrorNegocio("El nombre es obligatorio.")
    if v["stock_maximo"] and v["stock_maximo"] < v["stock_minimo"]:
        raise ErrorNegocio("El stock máximo no puede ser menor que el stock mínimo.")
    return v


def _bitacora(con, accion, detalle):
    con.execute("INSERT INTO bitacora (fecha,usuario_id,accion,detalle) VALUES (?,?,?,?)",
                (auth.ahora(), Sesion.id(), accion, detalle))


# ---------- Catálogo ----------
def crear_refaccion(datos: dict, existencia_inicial=0) -> int:
    Sesion.exigir("inventario.editar")
    v = _validar_refaccion(datos)
    inicial = _num(existencia_inicial, "Existencia inicial", obligatorio=False)
    try:
        with db.transaccion() as con:
            cur = con.execute(
                """INSERT INTO refacciones (codigo,nombre,descripcion,categoria,marca,modelo,ubicacion_almacen,
                   stock_minimo,stock_maximo,unidad,costo_unitario,proveedor_id)
                   VALUES (:codigo,:nombre,:descripcion,:categoria,:marca,:modelo,:ubicacion_almacen,
                   :stock_minimo,:stock_maximo,:unidad,:costo_unitario,:proveedor_id)""", v)
            rid = cur.lastrowid
            _bitacora(con, "refaccion.crear", v["codigo"])
            if inicial > 0:
                _mover(con, rid, "ENTRADA", inicial, v["costo_unitario"], "Existencia inicial")
            return rid
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise ErrorNegocio(f"Ya existe una refacción con el código {v['codigo']}.") from e
        raise


def actualizar_refaccion(rid: int, datos: dict) -> None:
    Sesion.exigir("inventario.editar")
    v = _validar_refaccion(datos)
    v["id"] = rid
    try:
        with db.transaccion() as con:
            n = con.execute(
                """UPDATE refacciones SET codigo=:codigo,nombre=:nombre,descripcion=:descripcion,categoria=:categoria,
                   marca=:marca,modelo=:modelo,ubicacion_almacen=:ubicacion_almacen,stock_minimo=:stock_minimo,
                   stock_maximo=:stock_maximo,unidad=:unidad,costo_unitario=:costo_unitario,proveedor_id=:proveedor_id
                   WHERE id=:id""", v).rowcount
            if not n:
                raise ErrorNegocio("La refacción ya no existe.")
            _bitacora(con, "refaccion.editar", v["codigo"])
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise ErrorNegocio(f"Ya existe otra refacción con el código {v['codigo']}.") from e
        raise


def dar_de_baja(rid: int, activo: bool = False) -> None:
    """Baja lógica: conserva el historial de movimientos (no se borra información)."""
    Sesion.exigir("inventario.baja")
    with db.transaccion() as con:
        con.execute("UPDATE refacciones SET activo=? WHERE id=?", (int(activo), rid))
        _bitacora(con, "refaccion.alta" if activo else "refaccion.baja", str(rid))


def listar_refacciones(texto="", solo_stock_bajo=False, incluir_inactivas=False) -> list[dict]:
    sql = """SELECT r.*, p.nombre AS proveedor,
                    ROUND(r.existencia*r.costo_unitario,2) AS valor,
                    CASE WHEN r.existencia < r.stock_minimo THEN 1 ELSE 0 END AS stock_bajo
             FROM refacciones r LEFT JOIN proveedores p ON p.id=r.proveedor_id WHERE 1=1"""
    params: list = []
    if not incluir_inactivas:
        sql += " AND r.activo=1"
    if texto:
        sql += " AND (r.codigo LIKE ? OR r.nombre LIKE ? OR r.categoria LIKE ? OR r.marca LIKE ?)"
        params += [f"%{texto}%"] * 4
    if solo_stock_bajo:
        sql += " AND r.existencia < r.stock_minimo"
    return db.consultar(sql + " ORDER BY r.codigo", params)


def listar_proveedores() -> list[dict]:
    return db.consultar("SELECT * FROM proveedores WHERE activo=1 ORDER BY nombre")


def crear_proveedor(nombre, contacto="", telefono="", correo="") -> int:
    Sesion.exigir("inventario.editar")
    if not nombre.strip():
        raise ErrorNegocio("El nombre del proveedor es obligatorio.")
    try:
        with db.transaccion() as con:
            return con.execute("INSERT INTO proveedores (nombre,contacto,telefono,correo) VALUES (?,?,?,?)",
                               (nombre.strip(), contacto, telefono, correo)).lastrowid
    except sqlite3.IntegrityError as e:
        raise ErrorNegocio(f"El proveedor «{nombre}» ya existe.") from e


# ---------- Movimientos ----------
def _mover(con, rid, tipo, cantidad, costo, motivo, ot_id=None, equipo_id=None, excepcion=False, demo=0):
    fila = con.execute("SELECT existencia, costo_unitario FROM refacciones WHERE id=? AND activo=1", (rid,)).fetchone()
    if not fila:
        raise ErrorNegocio("La refacción no existe o está dada de baja.")
    nueva = fila["existencia"] + cantidad if tipo == "ENTRADA" else fila["existencia"] - cantidad
    ahora = auth.ahora()
    if tipo == "ENTRADA":
        costo = costo if costo else fila["costo_unitario"]
        con.execute("UPDATE refacciones SET existencia=?, costo_unitario=?, fecha_ultima_entrada=? WHERE id=?",
                    (nueva, costo, ahora, rid))
    else:
        costo = fila["costo_unitario"]
        con.execute("UPDATE refacciones SET existencia=? WHERE id=?", (nueva, rid))
    con.execute(
        """INSERT INTO movimientos_inventario (refaccion_id,fecha,tipo,cantidad,costo_unitario,existencia_resultante,
           motivo,orden_trabajo_id,equipo_id,usuario_id,es_excepcion,es_demo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rid, ahora, tipo, cantidad, costo, nueva, motivo, ot_id, equipo_id, Sesion.id(), int(excepcion), demo))
    return nueva


def registrar_entrada(rid: int, cantidad, costo_unitario=None, motivo="Compra") -> float:
    Sesion.exigir("inventario.entrada")
    c = _num(cantidad, "Cantidad")
    if c <= 0:
        raise ErrorNegocio("La cantidad debe ser mayor que cero.")
    costo = _num(costo_unitario, "Costo unitario", obligatorio=False)
    with db.transaccion() as con:
        return _mover(con, rid, "ENTRADA", c, costo, motivo or "Entrada")


def registrar_salida(rid: int, cantidad, motivo="", ot_id=None, equipo_id=None, excepcion=False) -> float:
    """Salida de material. Si excede la existencia solo procede con excepción de un usuario autorizado."""
    Sesion.exigir("inventario.salida")
    c = _num(cantidad, "Cantidad")
    if c <= 0:
        raise ErrorNegocio("La cantidad debe ser mayor que cero.")
    with db.transaccion() as con:
        fila = con.execute("SELECT existencia, nombre FROM refacciones WHERE id=?", (rid,)).fetchone()
        if not fila:
            raise ErrorNegocio("La refacción no existe.")
        if c > fila["existencia"]:
            if not excepcion:
                raise ErrorNegocio(f"Existencia insuficiente de «{fila['nombre']}»: hay {fila['existencia']:g} y se piden {c:g}.")
            Sesion.exigir("inventario.excepcion")
            if not (motivo or "").strip():
                raise ErrorNegocio("Una salida de excepción requiere indicar el motivo.")
        return _mover(con, rid, "SALIDA", c, 0, motivo or "Salida", ot_id, equipo_id,
                      excepcion=c > fila["existencia"])


def descontar_para_orden(ot_id: int, equipo_id: int, piezas: list[tuple[int, float]]) -> None:
    """Descuenta varias refacciones de una OT en UNA transacción: o se descuentan todas o ninguna."""
    Sesion.exigir("inventario.salida")
    with db.transaccion() as con:
        for rid, cant in piezas:
            c = _num(cant, "Cantidad")
            fila = con.execute("SELECT existencia, nombre FROM refacciones WHERE id=?", (rid,)).fetchone()
            if not fila or c > fila["existencia"]:
                raise ErrorNegocio(f"Existencia insuficiente de «{fila['nombre'] if fila else rid}» para la OT.")
            _mover(con, rid, "SALIDA", c, 0, f"Consumo en OT {ot_id}", ot_id, equipo_id)


def historial_movimientos(rid: int | None = None) -> list[dict]:
    sql = """SELECT m.*, r.codigo, r.nombre AS refaccion, u.nombre AS usuario, e.codigo AS equipo
             FROM movimientos_inventario m JOIN refacciones r ON r.id=m.refaccion_id
             LEFT JOIN usuarios u ON u.id=m.usuario_id LEFT JOIN equipos e ON e.id=m.equipo_id"""
    if rid:
        return db.consultar(sql + " WHERE m.refaccion_id=? ORDER BY m.id DESC", (rid,))
    return db.consultar(sql + " ORDER BY m.id DESC LIMIT 1000")


# ---------- Indicadores ----------
def valor_total_inventario() -> float:
    r = db.consultar("SELECT COALESCE(SUM(existencia*costo_unitario),0) AS v FROM refacciones WHERE activo=1")
    return round(r[0]["v"], 2)


def refacciones_stock_bajo() -> list[dict]:
    return db.consultar("SELECT * FROM refacciones WHERE activo=1 AND existencia < stock_minimo ORDER BY codigo")


def consumo_mensual() -> list[dict]:
    """Piezas que salieron por mes."""
    return db.consultar("""SELECT strftime('%Y-%m', fecha) AS mes, ROUND(SUM(cantidad),2) AS piezas
                           FROM movimientos_inventario WHERE tipo='SALIDA' GROUP BY mes ORDER BY mes""")


def gasto_mensual() -> list[dict]:
    """Valor (MXN) de lo consumido por mes = cantidad × costo unitario al momento de la salida."""
    return db.consultar("""SELECT strftime('%Y-%m', fecha) AS mes, ROUND(SUM(cantidad*costo_unitario),2) AS gasto
                           FROM movimientos_inventario WHERE tipo='SALIDA' GROUP BY mes ORDER BY mes""")


def exportar_excel(ruta=None):
    import pandas as pd
    ruta = ruta or config.EXPORT_DIR / f"inventario_{auth.ahora().replace(':','').replace(' ','_').replace('-','')}.xlsx"
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    ref = pd.DataFrame(listar_refacciones())
    cols = {"codigo": "Código", "nombre": "Nombre", "categoria": "Categoría", "marca": "Marca", "modelo": "Modelo",
            "ubicacion_almacen": "Ubicación", "existencia": "Existencia", "stock_minimo": "Mínimo",
            "stock_maximo": "Máximo", "unidad": "Unidad", "costo_unitario": "Costo unitario (MXN)",
            "valor": "Valor (MXN)", "proveedor": "Proveedor"}
    ref = ref[list(cols)].rename(columns=cols) if not ref.empty else pd.DataFrame(columns=list(cols.values()))
    mov = pd.DataFrame(historial_movimientos())
    with pd.ExcelWriter(ruta, engine="openpyxl") as xl:
        ref.to_excel(xl, sheet_name="Existencias", index=False)
        mov.to_excel(xl, sheet_name="Movimientos", index=False)
    return ruta
