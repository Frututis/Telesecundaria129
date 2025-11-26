import shutil
import os
from datetime import datetime
from typing import Optional

# Librerías de FastAPI y Web
from fastapi import FastAPI, Request, Form, Response, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Librería de Base de Datos
import mysql.connector

# ==========================================
# 1. CONFIGURACIÓN GLOBAL DEL SISTEMA
# ==========================================
app = FastAPI()

# ¡IMPORTANTE! Cambia esto cada año (ej. "2025-2026") para limpiar las vistas
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

# ==========================================
# 3. AUTENTICACIÓN (LOGIN / LOGOUT)
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    # Si ya está logueado, ir directo al dashboard
    token = request.cookies.get("usuario_logueado")
    if token:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, response: Response, username: str = Form(...), password: str = Form(...)):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Validar usuario
        query = "SELECT * FROM users WHERE usuario = %s AND password_hash = %s"
        cursor.execute(query, (username, password))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()

        if user:
            # Login Exitoso
            redirect = RedirectResponse(url="/dashboard", status_code=303)
            
            # 1. Checamos si requiere cambio de contraseña
            if user['requiere_cambio'] == 1:
                # LO DESVIAMOS a la pantalla de cambio
                redirect = RedirectResponse(url="/primer-ingreso", status_code=303)
            
            # Guardamos cookies (esto se hace igual en ambos casos para saber quién es)
            redirect.set_cookie(key="usuario_logueado", value=user['usuario'])
            redirect.set_cookie(key="rol_usuario", value=user['rol'])
            return redirect
        
    except Exception as e:
        return templates.TemplateResponse("login.html", {"request": request, "error": f"Error de conexión: {str(e)}"})

@app.get("/logout")
async def logout(response: Response):
    redirect = RedirectResponse(url="/")
    redirect.delete_cookie("usuario_logueado")
    redirect.delete_cookie("rol_usuario")
    return redirect

# --- MÓDULO DE CAMBIO DE CONTRASEÑA OBLIGATORIO ---

@app.get("/primer-ingreso", response_class=HTMLResponse)
async def vista_primer_ingreso(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")
    return templates.TemplateResponse("cambiar_password.html", {"request": request})

@app.post("/guardar-nuevo-password")
async def guardar_nuevo_password(
    request: Request, 
    pass1: str = Form(...), 
    pass2: str = Form(...)
):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    # 1. Validar que coincidan
    if pass1 != pass2:
        return templates.TemplateResponse("cambiar_password.html", {
            "request": request, "error": "Las contraseñas no coinciden."
        })

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 2. Actualizar contraseña y quitar la bandera (requiere_cambio = 0)
        query = "UPDATE users SET password_hash = %s, requiere_cambio = 0 WHERE usuario = %s"
        cursor.execute(query, (pass1, usuario))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()

    # 3. Mandar al Dashboard ahora sí
    return RedirectResponse(url="/dashboard", status_code=303)
# ==========================================
# 4. DASHBOARD PRINCIPAL (ROUTER)
# ==========================================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    rol = request.cookies.get("rol_usuario")
    
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    archivo_html = "" 
    lista_planeaciones = []

    try:
        if rol == 'DIRECTOR':
            archivo_html = "dashboard_director.html"
            # Director ve planeaciones de TODOS, filtradas por CICLO ACTUAL
            query = """
            SELECT p.*, u.nombre_completo 
            FROM planeaciones p 
            JOIN users u ON p.id_maestro = u.id_usuario 
            WHERE p.ciclo_escolar = %s
            ORDER BY p.fecha_subida DESC
            LIMIT 10
            """
            cursor.execute(query, (CICLO_ACTUAL,))
            lista_planeaciones = cursor.fetchall()
            
        elif rol == 'MAESTRO':
            archivo_html = "dashboard_maestro.html"
            # Maestro ve SOLO SUS archivos del CICLO ACTUAL
            cursor.execute("SELECT id_usuario FROM users WHERE usuario = %s", (usuario,))
            user_data = cursor.fetchone()
            if user_data:
                id_maestro = user_data['id_usuario']
                query = "SELECT * FROM planeaciones WHERE id_maestro = %s AND ciclo_escolar = %s ORDER BY fecha_subida DESC"
                cursor.execute(query, (id_maestro, CICLO_ACTUAL))
                lista_planeaciones = cursor.fetchall()

    except Exception as e:
        print(f"Error en dashboard: {e}")
    finally:
        cursor.close()
        conn.close()

    return templates.TemplateResponse(archivo_html, {
        "request": request,
        "usuario": usuario,
        "rol": rol,
        "planeaciones": lista_planeaciones
    })

# ==========================================
# 5. MÓDULO DE PLANEACIONES (SUBIDA Y GESTIÓN)
# ==========================================

@app.post("/subir-planeacion")
async def subir_archivo(request: Request, archivo: UploadFile = File(...), comentarios: str = Form(...)):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")
    
    try:
        # A. Guardar archivo físico
        nombre_seguro = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{archivo.filename}"
        ubicacion_archivo = f"uploads/{nombre_seguro}"
        with open(ubicacion_archivo, "wb") as buffer:
            shutil.copyfileobj(archivo.file, buffer)
            
        # B. Guardar en BD con CICLO ESCOLAR
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT id_usuario FROM users WHERE usuario = %s", (usuario,))
        user_data = cursor.fetchone()
        
        if user_data:
            id_maestro = user_data['id_usuario']
            query = """
            INSERT INTO planeaciones (id_maestro, nombre_archivo, ruta_archivo, comentarios, ciclo_escolar) 
            VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(query, (id_maestro, archivo.filename, nombre_seguro, comentarios, CICLO_ACTUAL))
            conn.commit()
        
        cursor.close()
        conn.close()
        return RedirectResponse(url="/dashboard", status_code=303)

    except Exception as e:
        print(f"Error subiendo: {e}")
        return HTMLResponse("Error interno", status_code=500)

# VISTA DIRECTOR: LISTA DE CARPETAS (MAESTROS)
@app.get("/director/maestros", response_class=HTMLResponse)
async def lista_maestros(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Contamos archivos solo del ciclo actual
    query = """
    SELECT u.id_usuario, u.nombre_completo, 
           (SELECT COUNT(*) FROM planeaciones p WHERE p.id_maestro = u.id_usuario AND p.ciclo_escolar = %s) as total_archivos
    FROM users u 
    WHERE u.rol = 'MAESTRO'
    """
    cursor.execute(query, (CICLO_ACTUAL,))
    maestros = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("director_lista_maestros.html", {"request": request, "lista_maestros": maestros})

# VISTA DIRECTOR: ARCHIVOS DE UN MAESTRO
@app.get("/director/ver-planeaciones/{id_maestro}", response_class=HTMLResponse)
async def detalle_planeaciones_maestro(request: Request, id_maestro: int):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT nombre_completo FROM users WHERE id_usuario = %s", (id_maestro,))
    dato = cursor.fetchone()
    nombre = dato['nombre_completo'] if dato else "Maestro"

    # Filtramos por ciclo actual
    query = "SELECT * FROM planeaciones WHERE id_maestro = %s AND ciclo_escolar = %s ORDER BY fecha_subida DESC"
    cursor.execute(query, (id_maestro, CICLO_ACTUAL))
    archivos = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("director_detalle_planeaciones.html", {
        "request": request, "nombre_maestro": nombre, "planeaciones": archivos
    })

# ==========================================
# 6. MÓDULO DE ASISTENCIA (ESTADÍSTICAS Y REPORTE)
# ==========================================

# VISTA: REPORTE DIARIO (TABLA)
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

# VISTA: ESTADÍSTICAS AVANZADAS (GRÁFICAS)
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
    FROM asistencia a
    JOIN alumnos al ON a.id_alumno = al.id_alumno
    JOIN grupos g ON al.id_grupo = g.id_grupo
    WHERE a.estado = 'FALTA'
    GROUP BY g.id_grupo
    ORDER BY total_faltas DESC
    """
    cursor.execute(query_grupos)
    datos_grupos = cursor.fetchall()
    labels_grupo = [d['nombre_grupo'] for d in datos_grupos]
    data_grupo = [d['total_faltas'] for d in datos_grupos]

    # 3. TOP FALTAS
    cursor.execute("""
        SELECT al.nombre_completo, CONCAT(g.grado, '° ', g.grupo) as grupo, COUNT(*) as cantidad
        FROM asistencia a JOIN alumnos al ON a.id_alumno = al.id_alumno JOIN grupos g ON al.id_grupo = g.id_grupo
        WHERE a.estado = 'FALTA' GROUP BY al.id_alumno ORDER BY cantidad DESC LIMIT 5
    """)
    top_faltas = cursor.fetchall()

    # 4. TOP RETARDOS
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
# 7. MÓDULO DE ASIGNACIÓN (CAMBIO DE MAESTROS)
# ==========================================

@app.get("/director/asignacion", response_class=HTMLResponse)
async def ver_asignacion(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Lista de grupos
    cursor.execute("""
        SELECT g.id_grupo, g.grado, g.grupo, g.id_maestro_encargado, u.nombre_completo as nombre_actual
        FROM grupos g LEFT JOIN users u ON g.id_maestro_encargado = u.id_usuario
        ORDER BY g.grado, g.grupo
    """)
    lista_grupos = cursor.fetchall()

    # Lista de maestros
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
                id_nuevo_maestro = value 
                cursor.execute("UPDATE grupos SET id_maestro_encargado = %s WHERE id_grupo = %s", (id_nuevo_maestro, id_grupo))
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()
    return RedirectResponse(url="/director/asignacion", status_code=303)

# ==========================================
# 8. MÓDULO DE ALTA DE DOCENTES (NUEVO)
# ==========================================

# 1. VISTA: FORMULARIO DE REGISTRO
@app.get("/director/nuevo-maestro", response_class=HTMLResponse)
async def form_nuevo_maestro(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    rol = request.cookies.get("rol_usuario")
    
    # Seguridad: Solo Director
    if not usuario or rol != 'DIRECTOR': 
        return RedirectResponse(url="/dashboard")

    return templates.TemplateResponse("director_nuevo_maestro.html", {
        "request": request
    })

# 2. ACCIÓN: GUARDAR EN BASE DE DATOS
# Asegúrate de importar esto arriba
from mysql.connector import IntegrityError 

@app.post("/director/crear-maestro")
async def crear_maestro(
    request: Request,
    nombre: str = Form(...),
    usuario: str = Form(...),
    password: str = Form(...)
):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Intentamos guardar
        query = """
        INSERT INTO users (nombre_completo, usuario, password_hash, rol, requiere_cambio) 
        VALUES (%s, %s, %s, 'MAESTRO', 1)
        """
        cursor.execute(query, (nombre, usuario, password))
        conn.commit()
        
        # Si llegamos aquí, fue el primer clic y todo salió bien
        mensaje = f"¡Maestro {nombre} registrado correctamente!"
        tipo_mensaje = "exito" # Verde

    except IntegrityError as e:
        # SI OCURRE EL ERROR DE DUPLICADO (Doble Clic)
        if e.errno == 1062:
            # En lugar de error, decimos: "Ya está listo"
            mensaje = f"El maestro {nombre} ya está registrado (Detectamos doble clic, no te preocupes)."
            tipo_mensaje = "warning" # Amarillo/Naranja para avisar suavemente
        else:
            # Si es otro error real, sí fallamos
            mensaje = f"Error de base de datos: {e}"
            tipo_mensaje = "error"

    except Exception as e:
        mensaje = f"Error del sistema: {e}"
        tipo_mensaje = "error"
        
    finally:
        cursor.close()
        conn.close()

    # Devolvemos la vista con el mensaje procesado
    return templates.TemplateResponse("director_nuevo_maestro.html", {
        "request": request, 
        "mensaje": mensaje if tipo_mensaje != "error" else None,
        "error": mensaje if tipo_mensaje == "error" else None,
        "tipo_alerta": tipo_mensaje # Pasamos el tipo para cambiar el color en HTML
    })