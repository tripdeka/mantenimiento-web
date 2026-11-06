"""
Sistema de Mantenimiento de Planta — Versión Web (Streamlit)
Ejecutar:  streamlit run app_web.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Asegurar que el paquete app esté en el path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
from datetime import datetime, date

from app import db, config, seed, auth
from app.auth import Sesion, ErrorAcceso
from app.services import equipos as eq
from app.services import empleados as emp
from app.services import inventario as inv
from app.services import ordenes as ord
from app.services import kpi as kpi_svc
from app.services import capacitacion as cap

# ── Bootstrap ───────────────────────────────────────────────────────────────
db.inicializar()

st.set_page_config(
    page_title="Mantenimiento de Planta",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sesión Streamlit ↔ Sesion del backend ───────────────────────────────────
def _sync_sesion():
    u = st.session_state.get("usuario")
    Sesion.usuario = u

def login_page():
    st.title("🏭 Sistema de Mantenimiento de Planta")
    st.caption("Versión web · Administración de mantenimiento")
    with st.form("login"):
        usuario = st.text_input("Usuario", value="admin")
        password = st.text_input("Contraseña", type="password", value="")
        ok = st.form_submit_button("Entrar", type="primary")
        if ok:
            try:
                user = auth.iniciar_sesion(usuario, password)
                st.session_state["usuario"] = user
                Sesion.usuario = user
                if user.get("debe_cambiar"):
                    st.session_state["cambiar_pass"] = True
                st.rerun()
            except Exception as e:
                st.error(str(e))
    st.info("Usuario inicial: **admin** · Contraseña: **admin123** (cámbiala en el primer ingreso).")


def cambiar_password_page():
    st.title("Cambiar contraseña")
    with st.form("chg"):
        n1 = st.text_input("Nueva contraseña", type="password")
        n2 = st.text_input("Confirmar", type="password")
        if st.form_submit_button("Guardar"):
            if len(n1) < 6:
                st.error("Mínimo 6 caracteres.")
            elif n1 != n2:
                st.error("No coinciden.")
            else:
                auth.cambiar_password(Sesion.usuario["id"], n1)
                st.session_state["usuario"]["debe_cambiar"] = 0
                st.session_state.pop("cambiar_pass", None)
                st.success("Contraseña actualizada.")
                st.rerun()


# ── Helpers UI ──────────────────────────────────────────────────────────────
def df_safe(rows):
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def fmt_mxn(v):
    try:
        return f"${float(v):,.2f} MXN"
    except Exception:
        return "$0.00 MXN"


# ── Páginas ─────────────────────────────────────────────────────────────────
def page_inicio():
    st.header("Dashboard")
    c_eq = eq.contadores()
    c_em = emp.contadores()
    c_ot = ord.contadores_ordenes()
    bajos = inv.refacciones_stock_bajo()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equipos activos", c_eq["total"])
    c2.metric("En mantenimiento", c_eq["en_mto"])
    c3.metric("Empleados", c_em["total"])
    c4.metric("OT pendientes", c_ot["pendientes"])
    c5.metric("Stock bajo", len(bajos))

    st.subheader("Alertas de stock bajo")
    if bajos:
        st.dataframe(df_safe(bajos)[["codigo", "nombre", "existencia", "stock_minimo"]], use_container_width=True)
    else:
        st.success("Sin alertas de stock.")

    k = kpi_svc.resumen_kpis()
    st.subheader("KPI rápidos")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("MTTR (h)", f"{k['mttr']:.1f}" if k["mttr"] is not None else "—")
    k2.metric("MTBF (h)", f"{k['mtbf']:.1f}" if k["mtbf"] is not None else "—")
    k3.metric("OEE (%)", f"{k['oee']:.1f}" if k["oee"] is not None else "—")
    k4.metric("Cumplimiento OT (%)", f"{k['cumplimiento']:.1f}" if k["cumplimiento"] is not None else "—")


def page_equipos():
    st.header("Equipos y máquinas")
    c = eq.contadores()
    a, b, c_, d, e = st.columns(5)
    a.metric("Activos", c["total"])
    b.metric("Operativos", c["operativos"])
    c_.metric("En mto.", c["en_mto"])
    d.metric("Fuera de servicio", c["fuera"])
    e.metric("Criticidad alta", c["alta"])

    areas = eq.listar_areas()
    f1, f2, f3 = st.columns(3)
    fa = f1.selectbox("Área", ["Todas"] + [x["nombre"] for x in areas])
    fc = f2.selectbox("Criticidad", ["Todas", "alta", "media", "baja"])
    fe = f3.selectbox("Estado", ["Todos", "operativo", "en mantenimiento", "fuera de servicio"])
    area_id = next((x["id"] for x in areas if x["nombre"] == fa), None) if fa != "Todas" else None
    filas = eq.listar(
        area_id=area_id,
        criticidad=None if fc == "Todas" else fc,
        estado=None if fe == "Todos" else fe,
    )
    st.dataframe(
        df_safe(filas)[
            [c for c in ["codigo", "nombre", "area", "criticidad", "estado", "ubicacion", "responsable", "marca", "modelo"] if filas]
        ] if filas else df_safe(filas),
        use_container_width=True,
    )

    if Sesion.puede("equipos.editar"):
        with st.expander("➕ Nuevo equipo"):
            with st.form("nuevo_eq"):
                col1, col2 = st.columns(2)
                codigo = col1.text_input("Código *")
                nombre = col2.text_input("Nombre *")
                area_sel = st.selectbox("Área", ["(sin área)"] + [a["nombre"] for a in areas])
                ubicacion = st.text_input("Ubicación")
                marca = st.text_input("Marca")
                modelo = st.text_input("Modelo")
                criticidad = st.selectbox("Criticidad", ["alta", "media", "baja"], index=1)
                estado = st.selectbox("Estado", ["operativo", "en mantenimiento", "fuera de servicio"])
                freq = st.number_input("Frecuencia preventivo (días)", min_value=0, value=30)
                if st.form_submit_button("Guardar"):
                    try:
                        aid = next((a["id"] for a in areas if a["nombre"] == area_sel), None)
                        eq.crear({
                            "codigo": codigo, "nombre": nombre, "area_id": aid,
                            "ubicacion": ubicacion, "marca": marca, "modelo": modelo,
                            "criticidad": criticidad, "estado": estado,
                            "frecuencia_preventivo_dias": freq or None,
                        })
                        st.success("Equipo creado.")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))


def page_empleados():
    st.header("Empleados y organigrama")
    c = emp.contadores()
    st.metric("Empleados activos", c["total"])
    filas = emp.listar()
    st.subheader("Lista")
    st.dataframe(
        df_safe(filas)[[x for x in ["nombre", "puesto", "area", "jefe", "contacto"] if filas]],
        use_container_width=True,
    )
    st.subheader("Organigrama")
    arbol = emp.construir_arbol()

    def pintar(nodos, nivel=0):
        for n in sorted(nodos, key=lambda x: x["empleado"]["nombre"]):
            e = n["empleado"]
            st.markdown(("&nbsp;&nbsp;&nbsp;&nbsp;" * nivel) + f"**● {e['nombre']}** — {e['puesto']}" + (f" ({e.get('area') or ''})" if e.get("area") else ""))
            pintar(n["hijos"], nivel + 1)

    if arbol:
        pintar(arbol)
    else:
        st.info("Sin empleados. Carga datos demo desde el menú lateral.")

    if Sesion.puede("empleados.editar"):
        with st.expander("➕ Nuevo empleado"):
            areas = eq.listar_areas()
            jefes = emp.listar()
            with st.form("nuevo_emp"):
                nombre = st.text_input("Nombre *")
                puesto = st.text_input("Puesto *")
                area_sel = st.selectbox("Área", ["(sin área)"] + [a["nombre"] for a in areas])
                jefe_sel = st.selectbox("Jefe", ["(sin jefe)"] + [j["nombre"] for j in jefes])
                contacto = st.text_input("Contacto")
                if st.form_submit_button("Guardar"):
                    try:
                        aid = next((a["id"] for a in areas if a["nombre"] == area_sel), None)
                        jid = next((j["id"] for j in jefes if j["nombre"] == jefe_sel), None)
                        emp.crear({"nombre": nombre, "puesto": puesto, "area_id": aid, "jefe_id": jid, "contacto": contacto})
                        st.success("Empleado creado.")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))


def page_inventario():
    st.header("Inventario de refacciones")
    refs = inv.listar_refacciones()
    bajos = inv.refacciones_stock_bajo()
    c1, c2, c3 = st.columns(3)
    c1.metric("Refacciones activas", len(refs))
    c2.metric("Valor inventario", fmt_mxn(inv.valor_total_inventario()))
    c3.metric("Stock bajo", len(bajos))
    st.dataframe(
        df_safe(refs)[
            [c for c in ["codigo", "nombre", "categoria", "existencia", "stock_minimo", "unidad", "costo_unitario", "ubicacion_almacen"] if refs]
        ] if refs else df_safe(refs),
        use_container_width=True,
    )
    if Sesion.puede("inventario.editar"):
        with st.expander("➕ Nueva refacción"):
            with st.form("nueva_ref"):
                codigo = st.text_input("Código *")
                nombre = st.text_input("Nombre *")
                cat = st.text_input("Categoría")
                exist = st.number_input("Existencia inicial", min_value=0.0, value=0.0)
                smin = st.number_input("Stock mínimo", min_value=0.0, value=0.0)
                smax = st.number_input("Stock máximo", min_value=0.0, value=0.0)
                costo = st.number_input("Costo unitario", min_value=0.0, value=0.0)
                unidad = st.text_input("Unidad", value="pza")
                if st.form_submit_button("Guardar"):
                    try:
                        inv.crear_refaccion({
                            
                            "codigo": codigo, "nombre": nombre, "categoria": cat,
                            "stock_minimo": smin, "stock_maximo": smax,
                            "costo_unitario": costo, "unidad": unidad,
                        }, existencia_inicial=exist)
                        st.success("Refacción creada.")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))


def page_ordenes():
    st.header("Tareas y órdenes de trabajo")
    c = ord.contadores_ordenes()
    a, b, c_, d = st.columns(4)
    a.metric("Pendientes/asignadas", c["pendientes"])
    b.metric("En proceso", c["en_proceso"])
    c_.metric("Terminadas", c["terminadas"])
    d.metric("Vencidas", c["vencidas"])

    tareas = ord.listar_tareas(solo_activas=False)
    st.subheader("Tareas")
    st.dataframe(
        df_safe(tareas)[
            [x for x in ["folio", "nombre", "equipo_codigo", "tipo", "tecnico_nombre", "fecha_programada", "prioridad", "estado"] if tareas]
        ] if tareas else df_safe(tareas),
        use_container_width=True,
    )

    if Sesion.puede("ordenes.editar"):
        with st.expander("➕ Nueva tarea"):
            equipos = eq.listar()
            tecnicos = emp.listar()
            with st.form("nueva_tar"):
                nombre = st.text_input("Nombre *")
                desc = st.text_area("Descripción")
                eq_sel = st.selectbox("Equipo *", [f"{e['codigo']} – {e['nombre']}" for e in equipos] or ["(sin equipos)"])
                tipo = st.selectbox("Tipo", ["preventivo", "correctivo", "predictivo", "autonomo", "tpm"])
                tec_sel = st.selectbox("Técnico", ["(sin asignar)"] + [t["nombre"] for t in tecnicos])
                fprog = st.date_input("Fecha programada", value=date.today())
                prio = st.selectbox("Prioridad", ["alta", "media", "baja"], index=1)
                if st.form_submit_button("Crear tarea + OT"):
                    try:
                        eid = next(e["id"] for e in equipos if f"{e['codigo']} – {e['nombre']}" == eq_sel)
                        tid = next((t["id"] for t in tecnicos if t["nombre"] == tec_sel), None)
                        ord.crear_tarea({
                            "nombre": nombre, "descripcion": desc, "equipo_id": eid,
                            "tipo": tipo, "tecnico_id": tid,
                            "fecha_programada": fprog.isoformat(),
                            "prioridad": prio, "tiempo_estimado_h": 2,
                        })
                        st.success("Tarea y orden creadas.")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📅 Generar preventivos automáticos"):
                try:
                    n = ord.programar_preventivos()
                    st.success(f"Se generaron {n} preventivo(s).")
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))


def page_kpi():
    st.header("KPI, presupuesto y auditorías")
    k = kpi_svc.resumen_kpis()
    a, b, c, d = st.columns(4)
    a.metric("MTTR (h)", f"{k['mttr']:.1f}" if k["mttr"] is not None else "—")
    b.metric("MTBF (h)", f"{k['mtbf']:.1f}" if k["mtbf"] is not None else "—")
    c.metric("OEE (%)", f"{k['oee']:.1f}" if k["oee"] is not None else "—")
    d.metric("Cumplimiento OT (%)", f"{k['cumplimiento']:.1f}" if k["cumplimiento"] is not None else "—")

    hoy = datetime.now()
    pv = kpi_svc.presupuesto_vs_gasto(hoy.year, hoy.month)
    st.subheader(f"Presupuesto vs gasto — {hoy.month:02d}/{hoy.year}")
    p1, p2, p3 = st.columns(3)
    p1.metric("Presupuesto", fmt_mxn(pv["presupuesto"]))
    p2.metric("Gasto real", fmt_mxn(pv["gasto"]))
    p3.metric("Variación", fmt_mxn(pv["variacion"]))

    gastos_mes = kpi_svc.gasto_por_mes(hoy.year)
    if gastos_mes:
        st.bar_chart(df_safe(gastos_mes).set_index("mes")["total"])

    st.subheader("Auditorías")
    st.dataframe(df_safe(kpi_svc.listar_auditorias()), use_container_width=True)


def page_capacitacion():
    st.header("Capacitación, VOL/REP y reportes")
    c = cap.contadores_capacitacion()
    a, b, c_ = st.columns(3)
    a.metric("Cursos", c["cursos"])
    b.metric("Pendientes", c["pendientes"])
    c_.metric("Completadas", c["completadas"])

    st.subheader("Cursos")
    st.dataframe(df_safe(cap.listar_cursos()), use_container_width=True)
    st.subheader("Capacitaciones")
    st.dataframe(
        df_safe(cap.listar_capacitaciones())[
            [x for x in ["empleado_nombre", "curso_nombre", "fecha_programada", "estado", "fecha_completada"] if True]
        ],
        use_container_width=True,
    )
    st.subheader("VOL / REP")
    st.caption(cap.obtener_volrep_config())
    st.dataframe(df_safe(cap.listar_volrep()), use_container_width=True)

    st.subheader("Reportes PDF")
    tipo = st.selectbox("Tipo de reporte", ["inventario", "equipos", "ordenes", "kpi", "capacitacion"])
    if st.button("Generar PDF"):
        try:
            ruta = cap.generar_reporte_pdf(tipo)
            st.success(f"Generado: {ruta}")
            with open(ruta, "rb") as f:
                st.download_button("Descargar PDF", f, file_name=Path(ruta).name, mime="application/pdf")
        except Exception as ex:
            st.error(str(ex))


# ── Router ──────────────────────────────────────────────────────────────────
def main():
    _sync_sesion()

    if "usuario" not in st.session_state:
        login_page()
        return

    if st.session_state.get("cambiar_pass"):
        cambiar_password_page()
        return

    Sesion.usuario = st.session_state["usuario"]
    u = st.session_state["usuario"]

    with st.sidebar:
        st.markdown(f"**{u['nombre']}**")
        st.caption(u["rol"])
        pagina = st.radio(
            "Menú",
            [
                "🏠 Inicio",
                "⚙ Equipos",
                "👥 Empleados",
                "📦 Inventario",
                "🔧 Órdenes",
                "📊 KPI",
                "🎓 Capacitación",
            ],
        )
        st.divider()
        if Sesion.puede("sistema.demo"):
            if st.button("Cargar datos demo"):
                try:
                    seed.cargar_demo()
                    st.success("Demo cargado.")
                    st.rerun()
                except Exception as ex:
                    st.warning(str(ex))
            if st.button("Borrar datos demo"):
                try:
                    seed.borrar_demo()
                    st.success("Demo eliminado.")
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))
        if st.button("Cerrar sesión"):
            st.session_state.clear()
            Sesion.usuario = None
            st.rerun()

    if pagina.startswith("🏠"):
        page_inicio()
    elif pagina.startswith("⚙"):
        page_equipos()
    elif pagina.startswith("👥"):
        page_empleados()
    elif pagina.startswith("📦"):
        page_inventario()
    elif pagina.startswith("🔧"):
        page_ordenes()
    elif pagina.startswith("📊"):
        page_kpi()
    elif pagina.startswith("🎓"):
        page_capacitacion()


if __name__ == "__main__":
    main()
