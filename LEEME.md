# Sistema de Mantenimiento de Planta — Versión Web

Aplicación web con Streamlit + SQLite.

## Ejecutar en tu PC

```bash
cd mantenimiento_web
python -m venv .venv

# Windows:
.venv\Scripts\activate

# Mac/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
streamlit run app_web.py
```

Se abrirá el navegador en http://localhost:8501

**Usuario:** admin  
**Contraseña:** admin123

## Módulos
- Dashboard con KPIs y alertas
- Equipos y máquinas
- Empleados y organigrama
- Inventario de refacciones
- Tareas y órdenes de trabajo
- KPI, presupuesto y auditorías
- Capacitación, VOL/REP y reportes PDF

## Datos demo
En el menú lateral (usuario admin) usa el botón **Cargar datos demo**.

## Publicar link para el maestro (opciones)

### Opción A — Google Drive (código)
1. Comprime la carpeta `mantenimiento_web` en zip
2. Súbelo a Drive y comparte el link

### Opción B — Streamlit Community Cloud (link real que se abre en el navegador)
1. Sube esta carpeta a un repositorio de GitHub
2. Entra a https://share.streamlit.io
3. Conecta el repo y despliega `app_web.py`
4. Comparte el link tipo `https://xxxxx.streamlit.app`

### Opción C — Túnel temporal (ngrok)
```bash
streamlit run app_web.py
# en otra terminal:
ngrok http 8501
```
Copia el link https que te da ngrok.
