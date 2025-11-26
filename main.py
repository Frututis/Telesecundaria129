import shutil
import os
from datetime import datetime
from typing import Optional

# Librerías de FastAPI y Web
from fastapi import FastAPI, Request, Form, Response, UploadFile, File, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Librería de Base de Datos
import mysql.connector

# --- CONFIGURACIÓN INICIAL ---

app = FastAPI()

# 1. Configuración de carpetas
# Creamos la carpeta 'uploads' si no existe (para guardar los PDFs)
os.makedirs("uploads", exist_ok=True)

# 2. Montar archivos estáticos
# Esto permite que el navegador pueda acceder a los archivos subidos mediante la URL /archivos/...
app.mount("/archivos", StaticFiles(directory="uploads"), name="archivos")

# 3. Configuración de Plantillas HTML
templates = Jinja2Templates(directory="templates")

# --- CONEXIÓN A BASE DE DATOS (XAMPP) ---
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",      # Usuario por defecto de XAMPP
        password="",      # Contraseña por defecto de XAMPP (vacía)
        database="TelesecundariaDB"
    )

# --- RUTAS DEL SISTEMA ---

# 1. PÁGINA DE LOGIN (GET)
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    # Si el usuario ya tiene la cookie de sesión, lo mandamos directo al dashboard
    token = request.cookies.get("usuario_logueado")
    if token:
        return RedirectResponse(url="/dashboard")
    
    return templates.TemplateResponse("login.html", {"request": request})


# 2. PROCESAR LOGIN (POST)
@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request, 
    response: Response, 
    username: str = Form(...), 
    password: str = Form(...)
):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Validar usuario y contraseña
        # NOTA: En un sistema real, aquí usaríamos hash para la contraseña
        query = "SELECT * FROM users WHERE usuario = %s AND password_hash = %s"
        cursor.execute(query, (username, password))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()

        if user:
            # Login Exitoso: Creamos cookies y redirigimos
            redirect = RedirectResponse(url="/dashboard", status_code=303)
            redirect.set_cookie(key="usuario_logueado", value=user['usuario'])
            redirect.set_cookie(key="rol_usuario", value=user['rol'])
            return redirect
        else:
            # Login Fallido
            return templates.TemplateResponse("login.html", {
                "request": request, 
                "error": "Usuario o contraseña incorrectos"
            })
            
    except Exception as e:
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": f"Error de conexión: {str(e)}"
        })


# 3. DASHBOARD PRINCIPAL (GET)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    # Seguridad: Verificar cookies
    usuario = request.cookies.get("usuario_logueado")
    rol = request.cookies.get("rol_usuario")
    
    if not usuario:
        return RedirectResponse(url="/")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # VARIABLE: Nombre del archivo HTML a usar
        archivo_html = "" 
        lista_planeaciones = []

        # LÓGICA DE NEGOCIO SEGÚN EL ROL
        if rol == 'DIRECTOR':
            # Definimos que usaremos la vista de director
            archivo_html = "dashboard_director.html"
            
            # Query del Director (Todos los archivos + Nombre del maestro)
            query = """
            SELECT p.*, u.nombre_completo 
            FROM planeaciones p 
            JOIN users u ON p.id_maestro = u.id_usuario 
            ORDER BY p.fecha_subida DESC
            """
            cursor.execute(query)
            lista_planeaciones = cursor.fetchall()
            
        elif rol == 'MAESTRO':
            # Definimos que usaremos la vista de maestro
            archivo_html = "dashboard_maestro.html"

            # Query del Maestro (Solo sus archivos)
            cursor.execute("SELECT id_usuario FROM users WHERE usuario = %s", (usuario,))
            user_data = cursor.fetchone()
            
            if user_data:
                id_maestro = user_data['id_usuario']
                query = "SELECT * FROM planeaciones WHERE id_maestro = %s ORDER BY fecha_subida DESC"
                cursor.execute(query, (id_maestro,))
                lista_planeaciones = cursor.fetchall()

        cursor.close()
        conn.close()

        # AQUÍ ES EL CAMBIO CLAVE: Usamos la variable 'archivo_html' en lugar de un nombre fijo
        return templates.TemplateResponse(archivo_html, {
            "request": request,
            "usuario": usuario,
            "rol": rol,
            "planeaciones": lista_planeaciones
        })
        
    except Exception as e:
        print(f"Error en dashboard: {e}")
        return HTMLResponse(content=f"Error interno del servidor: {e}", status_code=500)

# 4. SUBIR PLANEACIÓN (POST)
@app.post("/subir-planeacion")
async def subir_archivo(
    request: Request, 
    archivo: UploadFile = File(...), 
    comentarios: str = Form(...)
):
    usuario = request.cookies.get("usuario_logueado")
    if not usuario:
        return RedirectResponse(url="/")
    
    try:
        # A. Guardar el archivo físico en la carpeta 'uploads'
        # Usamos timestamp para evitar nombres duplicados
        nombre_seguro = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{archivo.filename}"
        ubicacion_archivo = f"uploads/{nombre_seguro}"
        
        with open(ubicacion_archivo, "wb") as buffer:
            shutil.copyfileobj(archivo.file, buffer)
            
        # B. Guardar el registro en MySQL
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Obtener ID del maestro que está subiendo
        cursor.execute("SELECT id_usuario FROM users WHERE usuario = %s", (usuario,))
        userData = cursor.fetchone()
        
        if userData:
            id_maestro = userData['id_usuario']
            
            # Insertar registro
            query = """
            INSERT INTO planeaciones (id_maestro, nombre_archivo, ruta_archivo, comentarios) 
            VALUES (%s, %s, %s, %s)
            """
            cursor.execute(query, (id_maestro, archivo.filename, nombre_seguro, comentarios))
            conn.commit()
        
        cursor.close()
        conn.close()
        
        # Recargar el dashboard para ver el nuevo archivo
        return RedirectResponse(url="/dashboard", status_code=303)

    except Exception as e:
        print(f"Error al subir archivo: {e}")
        return HTMLResponse(content="Error al subir el archivo", status_code=500)


# 5. CERRAR SESIÓN (GET)
@app.get("/logout")
async def logout(response: Response):
    redirect = RedirectResponse(url="/")
    # Borramos las cookies para sacar al usuario
    redirect.delete_cookie("usuario_logueado")
    redirect.delete_cookie("rol_usuario")
    return redirect