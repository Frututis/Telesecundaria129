import shutil
import os
from datetime import datetime
from typing import Optional

# Librerías de FastAPI y Web
from fastapi import FastAPI, Request, Form, Response, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Librería de Base de Datos y Errores
import mysql.connector
from mysql.connector import IntegrityError

# ==========================================
# 1. CONFIGURACIÓN GLOBAL DEL SISTEMA
# ==========================================
app = FastAPI()

# ¡IMPORTANTE! Cambia esto cada año (ej. "2025-2026") para limpiar las vistas por defecto
CICLO_ACTUAL = "2024-2025"

# Configuración de carpetas
os.makedirs("uploads", exist_ok=True) # Crea carpeta para PDFs
app.mount("/archivos", StaticFiles(directory="uploads"), name="archivos") # Hace públicos los PDFs
templates = Jinja2Templates(directory="templates") # Carpeta de HTMLs

# ==========================================
# 2. CONEXIÓN A BASE DE DATOS (XAMPP)
# ==========================================
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",      # Usuario default XAMPP
        password="",      # Password default XAMPP (vacío)
        database="TelesecundariaDB"
    )

# Helper: Saber qué ciclo quiere ver el Director (Cookie vs Default)
def obtener_ciclo_activo(request: Request):
    return request.cookies.get("ciclo_seleccionado", CICLO_ACTUAL)

# ==========================================
# 3. AUTENTICACIÓN (LOGIN, LOGOUT, PASSWORD)
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    token = request.cookies.get("usuario_logueado")
    if token: return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, response: Response, username: str = Form(...), password: str = Form(...)):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        query = "SELECT * FROM users WHERE usuario = %s AND password_hash = %s"
        cursor.execute(query, (username, password))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()

        if user:
            redirect = RedirectResponse(url="/dashboard", status_code=303)
            
            # Validar si es primer ingreso (Cambio obligatorio)
            if user['requiere_cambio'] == 1:
                redirect = RedirectResponse(url="/primer-ingreso", status_code=303)

            redirect.set_cookie(key="usuario_logueado", value=user['usuario'])
            redirect.set_cookie(key="rol_usuario", value=user['rol'])
            return redirect
        else:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Datos incorrectos"})
    except Exception as e:
        return templates.TemplateResponse("login.html", {"request": request, "error": f"Error: {str(e)}"})

@app.get("/logout")
async def logout(response: Response):
    redirect = RedirectResponse(url="/")
    redirect.delete_cookie("usuario_logueado")
    redirect.delete_cookie("rol_usuario")
    return redirect

# --- CAMBIO DE CONTRASEÑA OBLIGATORIO ---
@app.get("/primer-ingreso", response_class=HTMLResponse)
async def vista_primer_ingreso(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")
    return templates.TemplateResponse("cambiar_password.html", {"request": request})

@app.post("/guardar-nuevo-password")
async def guardar_nuevo_password(request: Request, pass1: str = Form(...), pass2: str = Form(...)):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    if pass1 != pass2:
        return templates.TemplateResponse("cambiar_password.html", {"request": request, "error": "Las contraseñas no coinciden."})

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET password_hash = %s, requiere_cambio = 0 WHERE usuario = %s", (pass1, usuario))
    conn.commit()
    cursor.close()
    conn.close()
    return RedirectResponse(url="/dashboard", status_code=303)

# ==========================================
# 4. DASHBOARD PRINCIPAL (ROUTER)
# ==========================================

@app.post("/director/cambiar-ciclo")
async def cambiar_ciclo_escolar(request: Request, nuevo_ciclo: str = Form(...)):
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="ciclo_seleccionado", value=nuevo_ciclo)
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    rol = request.cookies.get("rol_usuario")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    archivo_html = "" 
    lista_planeaciones = []
    
    # Lógica del Ciclo Escolar
    ciclo_visualizar = obtener_ciclo_activo(request)
    cursor.execute("SELECT DISTINCT ciclo_escolar FROM planeaciones ORDER BY ciclo_escolar DESC")
    ciclos_disponibles = [fila['ciclo_escolar'] for fila in cursor.fetchall()]
    if CICLO_ACTUAL not in ciclos_disponibles: ciclos_disponibles.insert(0, CICLO_ACTUAL)

    try:
        if rol == 'DIRECTOR':
            archivo_html = "dashboard_director.html"
            query = """
            SELECT p.*, u.nombre_completo 
            FROM planeaciones p 
            JOIN users u ON p.id_maestro = u.id_usuario 
            WHERE p.ciclo_escolar = %s
            ORDER BY p.fecha_subida DESC LIMIT 10
            """
            cursor.execute(query, (ciclo_visualizar,))
            lista_planeaciones = cursor.fetchall()
            
        elif rol == 'MAESTRO':
            archivo_html = "dashboard_maestro.html"
            cursor.execute("SELECT id_usuario FROM users WHERE usuario = %s", (usuario,))
            user_data = cursor.fetchone()
            if user_data:
                id_maestro = user_data['id_usuario']
                query = "SELECT * FROM planeaciones WHERE id_maestro = %s AND ciclo_escolar = %s ORDER BY fecha_subida DESC"
                cursor.execute(query, (id_maestro, CICLO_ACTUAL))
                lista_planeaciones = cursor.fetchall()

    except Exception as e:
        print(f"Error dashboard: {e}")
    finally:
        cursor.close()
        conn.close()

    return templates.TemplateResponse(archivo_html, {
        "request": request, "usuario": usuario, "rol": rol,
        "planeaciones": lista_planeaciones,
        "ciclo_actual": ciclo_visualizar, "lista_ciclos": ciclos_disponibles
    })

# ==========================================
# 5. MÓDULO DE PLANEACIONES (KANBAN Y SUBIDA)
# ==========================================

@app.post("/subir-planeacion")
async def subir_archivo(
    request: Request, 
    archivo: UploadFile = File(...), 
    comentarios: str = Form(...),
    periodo: str = Form(...) 
):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")
    
    try:
        # A. Guardar archivo físico
        nombre_seguro = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{archivo.filename}"
        ubicacion_archivo = f"uploads/{nombre_seguro}"
        with open(ubicacion_archivo, "wb") as buffer:
            shutil.copyfileobj(archivo.file, buffer)
            
        # B. Guardar en BD con CICLO y PERIODO
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT id_usuario FROM users WHERE usuario = %s", (usuario,))
        user_data = cursor.fetchone()
        
        if user_data:
            id_maestro = user_data['id_usuario']
            query = """
            INSERT INTO planeaciones (id_maestro, nombre_archivo, ruta_archivo, comentarios, ciclo_escolar, periodo, estado) 
            VALUES (%s, %s, %s, %s, %s, %s, 'EN_REVISION')
            """
            cursor.execute(query, (id_maestro, archivo.filename, nombre_seguro, comentarios, CICLO_ACTUAL, periodo))
            conn.commit()
        
        cursor.close()
        conn.close()
        return RedirectResponse(url="/dashboard", status_code=303)

    except Exception as e:
        print(f"Error subiendo: {e}")
        return HTMLResponse("Error interno", status_code=500)

# VISTA DIRECTOR: KANBAN (TABLERO VISTOSO)
@app.get("/director/kanban", response_class=HTMLResponse)
async def ver_kanban(request: Request, periodo: str = "SEP-Q1"): 
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    ciclo_visualizar = obtener_ciclo_activo(request)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id_usuario, nombre_completo FROM users WHERE rol='MAESTRO'")
    todos_maestros = cursor.fetchall()

    query = """
    SELECT p.*, u.nombre_completo, u.id_usuario 
    FROM planeaciones p
    JOIN users u ON p.id_maestro = u.id_usuario
    WHERE p.ciclo_escolar = %s AND p.periodo = %s
    """
    cursor.execute(query, (ciclo_visualizar, periodo))
    entregas = cursor.fetchall()

    columna_pendientes = []
    columna_revision = []
    columna_aprobados = []

    ids_entregaron = [e['id_usuario'] for e in entregas]

    for m in todos_maestros:
        if m['id_usuario'] not in ids_entregaron:
            columna_pendientes.append(m)

    for e in entregas:
        if e['estado'] == 'APROBADO':
            columna_aprobados.append(e)
        else:
            columna_revision.append(e)

    conn.close()

    return templates.TemplateResponse("director_kanban.html", {
        "request": request, "periodo_actual": periodo,
        "pendientes": columna_pendientes, "revision": columna_revision, "aprobados": columna_aprobados,
        "periodos_lista": ["SEP-Q1", "SEP-Q2", "OCT-Q1", "OCT-Q2", "NOV-Q1", "NOV-Q2"] 
    })

# ACCIÓN: APROBAR CON COMENTARIOS (POST)
@app.post("/director/aprobar-feedback")
async def aprobar_con_feedback(
    request: Request,
    id_planeacion_modal: int = Form(...), # El ID viene oculto en el modal
    feedback: str = Form(...)             # El texto que escribe el director
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Actualizamos el estado APROBADO y guardamos la RETROALIMENTACIÓN
    query = """
    UPDATE planeaciones 
    SET estado = 'APROBADO', retroalimentacion = %s 
    WHERE id_planeacion = %s
    """
    cursor.execute(query, (feedback, id_planeacion_modal))
    conn.commit()
    conn.close()

    # Recargamos el tablero
    return RedirectResponse(url="/director/kanban", status_code=303)

# VISTA DIRECTOR: LISTA CLÁSICA (POR SI ACASO)
@app.get("/director/maestros", response_class=HTMLResponse)
async def lista_maestros(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")
    
    ciclo_visualizar = obtener_ciclo_activo(request)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
    SELECT u.id_usuario, u.nombre_completo, 
           (SELECT COUNT(*) FROM planeaciones p WHERE p.id_maestro = u.id_usuario AND p.ciclo_escolar = %s) as total_archivos
    FROM users u WHERE u.rol = 'MAESTRO'
    """
    cursor.execute(query, (ciclo_visualizar,))
    maestros = cursor.fetchall()
    conn.close()
    return templates.TemplateResponse("director_lista_maestros.html", {"request": request, "lista_maestros": maestros})

# VISTA DIRECTOR: DETALLE ARCHIVOS MAESTRO
@app.get("/director/ver-planeaciones/{id_maestro}", response_class=HTMLResponse)
async def detalle_planeaciones_maestro(request: Request, id_maestro: int):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    ciclo_visualizar = obtener_ciclo_activo(request)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT nombre_completo FROM users WHERE id_usuario = %s", (id_maestro,))
    dato = cursor.fetchone()
    nombre = dato['nombre_completo'] if dato else "Maestro"

    query = "SELECT * FROM planeaciones WHERE id_maestro = %s AND ciclo_escolar = %s ORDER BY fecha_subida DESC"
    cursor.execute(query, (id_maestro, ciclo_visualizar))
    archivos = cursor.fetchall()
    conn.close()
    return templates.TemplateResponse("director_detalle_planeaciones.html", {
        "request": request, "nombre_maestro": nombre, "planeaciones": archivos
    })

# ==========================================
# 6. MÓDULO DE ASISTENCIA (ESTADÍSTICAS)
# ==========================================

@app.get("/ver-asistencias", response_class=HTMLResponse)
async def ver_asistencias(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
    SELECT a.hora_entrada, a.estado, al.nombre_completo, g.grado, g.grupo
    FROM asistencia a
    JOIN alumnos al ON a.id_alumno = al.id_alumno
    JOIN grupos g ON al.id_grupo = g.id_grupo
    WHERE a.fecha = CURDATE()
    ORDER BY a.hora_entrada DESC
    """
    cursor.execute(query)
    resultados = cursor.fetchall()
    conn.close()
    return templates.TemplateResponse("asistencia_director.html", {
        "request": request, "lista_asistencia": resultados, "fecha_hoy": datetime.now().strftime('%d/%m/%Y')
    })

@app.get("/director/estadisticas", response_class=HTMLResponse)
async def estadisticas_asistencia(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. GLOBAL (Pastel)
    cursor.execute("SELECT estado, COUNT(*) as total FROM asistencia GROUP BY estado")
    datos_globales = cursor.fetchall()
    labels_global = [d['estado'] for d in datos_globales]
    data_global = [d['total'] for d in datos_globales]

    # 2. GRUPOS (Barras)
    query_grupos = """
    SELECT CONCAT(g.grado, '° ', g.grupo) as nombre_grupo, COUNT(*) as total_faltas
    FROM asistencia a JOIN alumnos al ON a.id_alumno = al.id_alumno JOIN grupos g ON al.id_grupo = g.id_grupo
    WHERE a.estado = 'FALTA' GROUP BY g.id_grupo ORDER BY total_faltas DESC
    """
    cursor.execute(query_grupos)
    datos_grupos = cursor.fetchall()
    labels_grupo = [d['nombre_grupo'] for d in datos_grupos]
    data_grupo = [d['total_faltas'] for d in datos_grupos]

    # 3. TOPS
    cursor.execute("""
        SELECT al.nombre_completo, CONCAT(g.grado, '° ', g.grupo) as grupo, COUNT(*) as cantidad
        FROM asistencia a JOIN alumnos al ON a.id_alumno = al.id_alumno JOIN grupos g ON al.id_grupo = g.id_grupo
        WHERE a.estado = 'FALTA' GROUP BY al.id_alumno ORDER BY cantidad DESC LIMIT 5
    """)
    top_faltas = cursor.fetchall()

    cursor.execute("""
        SELECT al.nombre_completo, CONCAT(g.grado, '° ', g.grupo) as grupo, COUNT(*) as cantidad
        FROM asistencia a JOIN alumnos al ON a.id_alumno = al.id_alumno JOIN grupos g ON al.id_grupo = g.id_grupo
        WHERE a.estado = 'RETARDO' GROUP BY al.id_alumno ORDER BY cantidad DESC LIMIT 5
    """)
    top_retardos = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("estadisticas_director.html", {
        "request": request,
        "labels_global": labels_global, "data_global": data_global,
        "labels_grupo": labels_grupo, "data_grupo": data_grupo,
        "top_faltas": top_faltas, "top_retardos": top_retardos
    })

# ==========================================
# 7. MÓDULO DE GESTIÓN DE PERSONAL
# ==========================================

@app.get("/director/asignacion", response_class=HTMLResponse)
async def ver_asignacion(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT g.id_grupo, g.grado, g.grupo, g.id_maestro_encargado, u.nombre_completo as nombre_actual
        FROM grupos g LEFT JOIN users u ON g.id_maestro_encargado = u.id_usuario ORDER BY g.grado, g.grupo
    """)
    lista_grupos = cursor.fetchall()
    cursor.execute("SELECT id_usuario, nombre_completo FROM users WHERE rol = 'MAESTRO'")
    lista_maestros = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("director_asignacion.html", {
        "request": request, "grupos": lista_grupos, "maestros": lista_maestros
    })

@app.post("/director/guardar-asignacion")
async def guardar_asignacion(request: Request):
    form_data = await request.form()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for key, value in form_data.items():
            if key.startswith("grupo_"):
                id_grupo = key.split("_")[1]
                cursor.execute("UPDATE grupos SET id_maestro_encargado = %s WHERE id_grupo = %s", (value, id_grupo))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return RedirectResponse(url="/director/asignacion", status_code=303)

@app.get("/director/nuevo-maestro", response_class=HTMLResponse)
async def form_nuevo_maestro(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")
    return templates.TemplateResponse("director_nuevo_maestro.html", {"request": request})

@app.post("/director/crear-maestro")
async def crear_maestro(request: Request, nombre: str = Form(...), usuario: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = "INSERT INTO users (nombre_completo, usuario, password_hash, rol, requiere_cambio) VALUES (%s, %s, %s, 'MAESTRO', 1)"
        cursor.execute(query, (nombre, usuario, password))
        conn.commit()
        mensaje = f"¡Maestro {nombre} registrado correctamente!"
        tipo = "exito"
    except IntegrityError as e:
        if e.errno == 1062:
            mensaje = f"El usuario {usuario} ya existe (posible doble clic). Todo en orden."
            tipo = "warning"
        else:
            mensaje = f"Error DB: {e}"
            tipo = "error"
    except Exception as e:
        mensaje = f"Error: {e}"
        tipo = "error"
    finally:
        cursor.close()
        conn.close()

    return templates.TemplateResponse("director_nuevo_maestro.html", {
        "request": request,
        "mensaje": mensaje if tipo != "error" else None,
        "error": mensaje if tipo == "error" else None,
        "tipo_alerta": tipo
    })