import shutil
import os
from datetime import datetime
from typing import Optional

# Librerías de FastAPI y Web
from fastapi import FastAPI, Request, Form, Response, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Librería de Base de Datos y Errores
import mysql.connector
from mysql.connector import IntegrityError

# ==========================================
# 1. CONFIGURACIÓN GLOBAL DEL SISTEMA
# ==========================================
app = FastAPI()


# Configuración de carpetas
os.makedirs("uploads", exist_ok=True) # Carpeta principal
os.makedirs("uploads/alumnos", exist_ok=True) # Carpeta para expedientes
app.mount("/archivos", StaticFiles(directory="uploads"), name="archivos") # Archivos públicos
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")   # Acceso directo a uploads
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

# Helper: Saber qué ciclo quiere ver el Director
def obtener_ciclo_activo(request: Request):
    return request.cookies.get("ciclo_seleccionado", get_ciclo_sistema())

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
            
            # Validar si es primer ingreso
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
    redirect.delete_cookie("ciclo_seleccionado")
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
# 4. DASHBOARD PRINCIPAL (ROUTER MAESTRO/DIRECTOR)
# ==========================================

@app.post("/director/cambiar-ciclo")
async def cambiar_ciclo_escolar(request: Request, nuevo_ciclo: str = Form(...)):
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="ciclo_seleccionado", value=nuevo_ciclo)
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    fecha: str = None,          # Filtro Asistencia
    periodo_filtro: str = None  # Filtro Planeaciones
):
    usuario = request.cookies.get("usuario_logueado")
    rol = request.cookies.get("rol_usuario")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fecha por defecto para asistencia: HOY
    fecha_seleccionada = fecha if fecha else datetime.now().strftime('%Y-%m-%d')
    
    archivo_html = "" 
    # Contexto base
    contexto = {
        "request": request, "usuario": usuario, "rol": rol,
        "ciclo_actual":get_ciclo_sistema(),
        "fecha_seleccionada": fecha_seleccionada
    }

    try:
        # --- LÓGICA DIRECTOR ---
        if rol == 'DIRECTOR':
            archivo_html = "dashboard_director.html"
            ciclo_visualizar = obtener_ciclo_activo(request)
            
            # Planeaciones Recientes del Ciclo
            query = """
            SELECT p.*, u.nombre_completo 
            FROM planeaciones p 
            JOIN users u ON p.id_maestro = u.id_usuario 
            WHERE p.ciclo_escolar = %s
            ORDER BY p.fecha_subida DESC LIMIT 10
            """
            cursor.execute(query, (ciclo_visualizar,))
            contexto["planeaciones"] = cursor.fetchall()
            
            # Lista de Ciclos para el Selector
            cursor.execute("SELECT nombre FROM ciclos ORDER BY nombre DESC")
            ciclos = [fila['nombre'] for fila in cursor.fetchall()]
            
            ciclo_sistema = get_ciclo_sistema()
            if ciclo_sistema not in ciclos:
                ciclos.insert(0, ciclo_sistema)
            
            contexto["lista_ciclos"] = ciclos
            contexto["ciclo_actual"] = ciclo_visualizar

        # --- LÓGICA MAESTRO ---
        elif rol == 'MAESTRO':
            archivo_html = "dashboard_maestro.html"
            cursor.execute("SELECT id_usuario FROM users WHERE usuario = %s", (usuario,))
            user_data = cursor.fetchone()
            id_maestro = user_data['id_usuario']

            # 1. Asistencia del Día Seleccionado
            query_alumnos = """
            SELECT al.id_alumno, al.nombre_completo, al.curp, 
                   ast.hora_entrada, ast.estado as estado_asistencia, ast.id_asistencia
            FROM grupos g
            JOIN alumnos al ON g.id_grupo = al.id_grupo
            LEFT JOIN asistencia ast ON al.id_alumno = ast.id_alumno AND ast.fecha = %s 
            WHERE g.id_maestro_encargado = %s
            ORDER BY al.nombre_completo
            """
            cursor.execute(query_alumnos, (fecha_seleccionada, id_maestro))
            contexto["alumnos"] = cursor.fetchall()

            # 2. Filtro de Periodos (Dropdown)
            cursor.execute("""
                SELECT DISTINCT periodo FROM planeaciones 
                WHERE id_maestro = %s AND ciclo_escolar = %s 
                ORDER BY periodo DESC
            """, (id_maestro, CICLO_ACTUAL))
            lista_periodos_usados = [row['periodo'] for row in cursor.fetchall()]

            # 3. Planeaciones Filtradas
            if periodo_filtro and periodo_filtro != "TODOS":
                query_planes = """
                SELECT * FROM planeaciones 
                WHERE id_maestro = %s AND ciclo_escolar = %s AND periodo = %s 
                ORDER BY fecha_subida DESC
                """
                cursor.execute(query_planes, (id_maestro, CICLO_ACTUAL, periodo_filtro))
            else:
                query_planes = """
                SELECT * FROM planeaciones 
                WHERE id_maestro = %s AND ciclo_escolar = %s 
                ORDER BY fecha_subida DESC LIMIT 10
                """
                cursor.execute(query_planes, (id_maestro, CICLO_ACTUAL))
            
            contexto["planeaciones"] = cursor.fetchall()
            contexto["mis_periodos"] = lista_periodos_usados
            contexto["periodo_seleccionado"] = periodo_filtro or ""

    except Exception as e:
        print(f"Error dashboard: {e}")
    finally:
        cursor.close()
        conn.close()

    return templates.TemplateResponse(archivo_html, contexto)

# ==========================================
# 5. MÓDULO MAESTRO: OPERACIONES (SUBIR / JUSTIFICAR)
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
        nombre_seguro = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{archivo.filename}"
        ubicacion_archivo = f"uploads/{nombre_seguro}"
        with open(ubicacion_archivo, "wb") as buffer:
            shutil.copyfileobj(archivo.file, buffer)
            
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

@app.get("/maestro/justificar/{id_alumno}")
async def justificar_alumno(id_alumno: int, fecha: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Busca si existe registro ese día
    cursor.execute("SELECT id_asistencia FROM asistencia WHERE id_alumno = %s AND fecha = %s", (id_alumno, fecha))
    existe = cursor.fetchone()
    
    if existe:
        cursor.execute("UPDATE asistencia SET estado = 'JUSTIFICADO' WHERE id_asistencia = %s", (existe[0],))
    else:
        # Crea registro justificado
        cursor.execute("""
            INSERT INTO asistencia (id_alumno, fecha, hora_entrada, estado) 
            VALUES (%s, %s, '00:00:00', 'JUSTIFICADO')
        """, (id_alumno, fecha))
        
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/dashboard?fecha={fecha}", status_code=303)

# ==========================================
# 6. MÓDULO DIRECTOR: KANBAN DE REVISIÓN
# ==========================================

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

    # Clasificación Kanban
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

@app.post("/director/aprobar-feedback")
async def aprobar_con_feedback(request: Request, id_planeacion_modal: int = Form(...), feedback: str = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE planeaciones SET estado = 'APROBADO', retroalimentacion = %s WHERE id_planeacion = %s", (feedback, id_planeacion_modal))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/director/kanban", status_code=303)

# ==========================================
# 7. MÓDULO DIRECTOR: ESTADÍSTICAS Y ASISTENCIA
# ==========================================

@app.get("/ver-asistencias", response_class=HTMLResponse)
async def ver_asistencias(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
    SELECT a.hora_entrada, a.estado, al.nombre_completo, g.grado, g.grupo
    FROM asistencia a JOIN alumnos al ON a.id_alumno = al.id_alumno JOIN grupos g ON al.id_grupo = g.id_grupo
    WHERE a.fecha = CURDATE() ORDER BY a.hora_entrada DESC
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

    # Datos para gráficas
    cursor.execute("SELECT estado, COUNT(*) as total FROM asistencia GROUP BY estado")
    datos_globales = cursor.fetchall()
    labels_global = [d['estado'] for d in datos_globales]
    data_global = [d['total'] for d in datos_globales]

    query_grupos = """
    SELECT CONCAT(g.grado, '° ', g.grupo) as nombre_grupo, COUNT(*) as total_faltas
    FROM asistencia a JOIN alumnos al ON a.id_alumno = al.id_alumno JOIN grupos g ON al.id_grupo = g.id_grupo
    WHERE a.estado = 'FALTA' GROUP BY g.id_grupo ORDER BY total_faltas DESC
    """
    cursor.execute(query_grupos)
    datos_grupos = cursor.fetchall()
    labels_grupo = [d['nombre_grupo'] for d in datos_grupos]
    data_grupo = [d['total_faltas'] for d in datos_grupos]

    # Tops alumnos
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
        "request": request, "labels_global": labels_global, "data_global": data_global,
        "labels_grupo": labels_grupo, "data_grupo": data_grupo, "top_faltas": top_faltas, "top_retardos": top_retardos
    })

# ==========================================
# 8. MÓDULO DIRECTOR: GESTIÓN DE PERSONAL
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
        "request": request, "mensaje": mensaje if tipo != "error" else None, "error": mensaje if tipo == "error" else None, "tipo_alerta": tipo
    })

# ==========================================
# 9. MÓDULO EXPEDIENTES (ALUMNOS Y DOCUMENTOS)
# ==========================================

# MENÚ PRINCIPAL EXPEDIENTES
@app.get("/director/expedientes", response_class=HTMLResponse)
async def menu_expedientes(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
    SELECT a.id_alumno, a.nombre_completo, a.curp, g.grado, g.grupo
    FROM alumnos a JOIN grupos g ON a.id_grupo = g.id_grupo
    ORDER BY g.grado, g.grupo, a.nombre_completo
    """
    cursor.execute(query)
    alumnos = cursor.fetchall()
    conn.close()
    return templates.TemplateResponse("director_expedientes_menu.html", {"request": request, "alumnos": alumnos})

# VISTA AGREGAR ALUMNO
@app.get("/director/agregar-alumno", response_class=HTMLResponse)
async def vista_agregar_alumno(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id_grupo, grado, grupo FROM grupos ORDER BY grado, grupo")
    grupos = cursor.fetchall()
    conn.close()
    return templates.TemplateResponse("director_agregar_alumno.html", {"request": request, "grupos": grupos})

# ACCIÓN: GUARDAR ALUMNO (CON 4 TELÉFONOS Y REDIRECCIÓN INTELIGENTE)
@app.post("/director/guardar-alumno")
async def guardar_alumno(
    request: Request, 
    nombre: str = Form(...), 
    curp: str = Form(...), 
    id_grupo: int = Form(...),
    contacto: str = Form(...), # Nombre del Tutor Principal
    tel_tutor: str = Form(""), # Usamos default "" por si lo dejan vacío
    tel_madre: str = Form(""),
    tel_padre: str = Form(""),
    tel_emergencia: str = Form("")
):
    conn = get_db_connection()
    cursor = conn.cursor()
    id_nuevo_alumno = None

    try:
        # Insertamos los datos
        query = """
        INSERT INTO alumnos 
        (nombre_completo, curp, id_grupo, nombre_contacto, telefono_tutor, telefono_madre, telefono_padre, telefono_emergencia) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (nombre, curp, id_grupo, contacto, tel_tutor, tel_madre, tel_padre, tel_emergencia))
        conn.commit()
        
        # OBTENEMOS EL ID DEL ALUMNO RECIÉN CREADO
        id_nuevo_alumno = cursor.lastrowid 
        
    except Exception as e:
        print(f"Error: {e}")
        # Si falla, volvemos al formulario con error
        return RedirectResponse(url="/director/agregar-alumno?error=Error al guardar", status_code=303)
    finally:
        conn.close()
    
    # --- CAMBIO CLAVE DE FLUJO ---
    # En lugar de volver al formulario vacío, lo mandamos directo a SU PERFIL
    # y activamos la pestaña de documentos automáticamente via URL (?tab=docs)
    return RedirectResponse(
        url=f"/director/perfil-alumno/{id_nuevo_alumno}?msg=Alumno registrado. Sube sus documentos ahora.&tab=documentos", 
        status_code=303
    )
# API BUSCADOR (JSON)
@app.get("/api/buscar-alumno")
async def buscar_alumno_api(q: str = ""):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
    SELECT a.id_alumno, a.nombre_completo, a.curp, g.grado, g.grupo
    FROM alumnos a JOIN grupos g ON a.id_grupo = g.id_grupo
    WHERE a.nombre_completo LIKE %s LIMIT 5
    """
    cursor.execute(query, (f"%{q}%",))
    resultados = cursor.fetchall()
    conn.close()
    return resultados

# PERFIL INTEGRAL DEL ALUMNO (TABS)
@app.get("/director/perfil-alumno/{id_alumno}", response_class=HTMLResponse)
async def perfil_alumno(request: Request, id_alumno: int):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario: return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT a.*, g.grado, g.grupo FROM alumnos a JOIN grupos g ON a.id_grupo = g.id_grupo WHERE a.id_alumno = %s", (id_alumno,))
    alumno = cursor.fetchone()
    
    cursor.execute("SELECT * FROM documentos_alumnos WHERE id_alumno = %s ORDER BY categoria", (id_alumno,))
    documentos = cursor.fetchall()
    
    cursor.execute("SELECT * FROM historial_tramites WHERE id_alumno = %s ORDER BY fecha DESC", (id_alumno,))
    historial = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("director_perfil_alumno.html", {
        "request": request, "alumno": alumno, "documentos": documentos, "historial": historial, "usuario_logueado": usuario
    })

# ACCIÓN: ACTUALIZAR DATOS COMPLETOS (CON 4 TELÉFONOS)
@app.post("/director/actualizar-datos-alumno")
async def actualizar_datos_alumno(
    request: Request,
    id_alumno: int = Form(...),
    nombre: str = Form(...),
    curp: str = Form(...),
    contacto: str = Form(...), # Tutor
    tel_tutor: str = Form(""),
    tel_madre: str = Form(""),
    tel_padre: str = Form(""),
    tel_emergencia: str = Form("")
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        query = """
        UPDATE alumnos 
        SET nombre_completo = %s, 
            curp = %s, 
            nombre_contacto = %s, 
            telefono_tutor = %s,
            telefono_madre = %s,
            telefono_padre = %s,
            telefono_emergencia = %s
        WHERE id_alumno = %s
        """
        cursor.execute(query, (nombre, curp, contacto, tel_tutor, tel_madre, tel_padre, tel_emergencia, id_alumno))
        conn.commit()
    except Exception as e:
        print(f"Error actualizando: {e}")
    finally:
        conn.close()
    
    return RedirectResponse(url=f"/director/perfil-alumno/{id_alumno}?msg=Datos actualizados correctamente", status_code=303)

# SUBIR DOCUMENTO A LA BÓVEDA
@app.post("/director/subir-documento-alumno")
async def subir_documento_alumno(request: Request, id_alumno: int = Form(...), categoria: str = Form(...), archivo: UploadFile = File(...)):
    try:
        carpeta_alumno = f"uploads/alumnos/{id_alumno}"
        os.makedirs(carpeta_alumno, exist_ok=True)
        nombre_limpio = f"{categoria}_{archivo.filename.replace(' ', '_')}"
        ruta_guardado = f"{carpeta_alumno}/{nombre_limpio}"
        
        with open(ruta_guardado, "wb") as buffer:
            shutil.copyfileobj(archivo.file, buffer)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO documentos_alumnos (id_alumno, categoria, nombre_archivo, ruta_archivo, estado) VALUES (%s, %s, %s, %s, 'PENDIENTE')", (id_alumno, categoria, archivo.filename, ruta_guardado))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error subiendo: {e}")
    return RedirectResponse(url=f"/director/perfil-alumno/{id_alumno}", status_code=303)

# GENERADOR DE DOCUMENTOS (PDF)
@app.post("/director/imprimir-documento-avanzado")
async def imprimir_avanzado(
    request: Request,
    id_alumno: int = Form(...),
    tipo_documento: str = Form(...), 
    nota1: str = Form(None), nota2: str = Form(None), nota3: str = Form(None), promedio_final: str = Form(None)
):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Datos alumno
    cursor.execute("SELECT a.nombre_completo, a.curp, g.grado, g.grupo FROM alumnos a JOIN grupos g ON a.id_grupo = g.id_grupo WHERE a.id_alumno = %s", (id_alumno,))
    alumno = cursor.fetchone()
    
    # Registrar en historial
    usuario = request.cookies.get("usuario_logueado")
    cursor.execute("INSERT INTO historial_tramites (id_alumno, tramite, usuario_responsable) VALUES (%s, %s, %s)", (id_alumno, f"Generación de {tipo_documento}", usuario))
    conn.commit()
    conn.close()

    # Fecha bonita
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    hoy = datetime.now()
    fecha_texto = f"{hoy.day} de {meses[hoy.month-1]} de {hoy.year}"

    plantilla = "plantilla_constancia.html" if tipo_documento == 'CONSTANCIA' else "plantilla_kardex.html"
    
    return templates.TemplateResponse(plantilla, {
        "request": request, "alumno": alumno, "fecha": fecha_texto,
        "n1": nota1, "n2": nota2, "n3": nota3, "pf": promedio_final
    })
# ==========================================
# 11. MÓDULO DE GESTIÓN DE CICLOS (SISTEMA)
# ==========================================

# HELPER: Obtener cuál es el ciclo activo REAL desde la BD
def get_ciclo_sistema():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT nombre FROM ciclos WHERE activo = 1")
    ciclo = cursor.fetchone()
    conn.close()
    # Si por error no hay ninguno, regresamos uno default
    return ciclo['nombre'] if ciclo else "2024-2025"

# VISTA: PANEL DE CONFIGURACIÓN DE CICLOS
# VISTA: PANEL DE CONFIGURACIÓN DE CICLOS
@app.get("/director/configuracion-ciclos", response_class=HTMLResponse)
async def configurar_ciclos(request: Request):
    usuario = request.cookies.get("usuario_logueado")
    rol = request.cookies.get("rol_usuario")
    
    # Seguridad: Solo el Director entra aquí
    if not usuario or rol != 'DIRECTOR': 
        return RedirectResponse(url="/dashboard")
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Traemos todos los ciclos para la lista
    # Ordenamos por nombre descendente para ver los años más nuevos arriba
    cursor.execute("SELECT * FROM ciclos ORDER BY nombre DESC")
    lista_ciclos = cursor.fetchall()
    
    conn.close()
    
    return templates.TemplateResponse("director_ciclos.html", {
        "request": request, 
        "ciclos": lista_ciclos
    })
# ACCIÓN: CREAR UN NUEVO CICLO (POST)
@app.post("/director/crear-ciclo")
async def crear_ciclo(request: Request, nombre_ciclo: str = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Insertamos el nuevo ciclo (por defecto nace inactivo/cerrado)
        # La columna 'activo' se pone en 0 automáticamente según definimos la tabla
        query = "INSERT INTO ciclos (nombre, activo) VALUES (%s, 0)"
        cursor.execute(query, (nombre_ciclo,))
        conn.commit()
    except Exception as e:
        print(f"Error creando ciclo: {e}")
        # Aquí podrías manejar el error si intentan crear un duplicado
    finally:
        conn.close()
        
    return RedirectResponse(url="/director/configuracion-ciclos", status_code=303)

# ACCIÓN: ACTIVAR UN CICLO (CAMBIO DE AÑO)
@app.get("/director/activar-ciclo/{id_ciclo}")
async def activar_ciclo(id_ciclo: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. "Apagamos" todos los ciclos primero (activo = 0)
        cursor.execute("UPDATE ciclos SET activo = 0")
        
        # 2. "Prendemos" solo el que el director seleccionó (activo = 1)
        cursor.execute("UPDATE ciclos SET activo = 1 WHERE id_ciclo = %s", (id_ciclo,))
        
        conn.commit()
    except Exception as e:
        print(f"Error activando ciclo: {e}")
    finally:
        conn.close()
        
    return RedirectResponse(url="/director/configuracion-ciclos", status_code=303)
