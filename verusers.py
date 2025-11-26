import mysql.connector

print("🕵️ INICIANDO INVESTIGACIÓN...")

try:
    # Usamos la misma configuración exacta de tu main.py
    conn = mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="TelesecundariaDB"
    )
    cursor = conn.cursor()

    # 1. ¿A qué base de datos estoy conectado realmente?
    cursor.execute("SELECT DATABASE(), USER(), @@port;")
    info = cursor.fetchone()
    print(f"📍 Python conectado a BD: '{info[0]}'")
    print(f"👤 Usuario: '{info[1]}'")
    print(f"🔌 Puerto: {info[2]}")

    # 2. ¿Existe Ari aquí?
    print("\n🔍 Buscando al usuario 'Ari' (Búsqueda exacta)...")
    cursor.execute("SELECT id_usuario, usuario, nombre_completo FROM users WHERE usuario = 'Ari'")
    usuario_fantasma = cursor.fetchone()

    if usuario_fantasma:
        print("⚠️ ¡CULPABLE ENCONTRADO!")
        print(f"   ID: {usuario_fantasma[0]}")
        print(f"   Usuario: {usuario_fantasma[1]}")
        print(f"   Nombre: {usuario_fantasma[2]}")
        print("   -> Python lo encontró, por eso no te deja crearlo de nuevo.")
        
        # Opcional: Borrarlo automáticamente
        # cursor.execute("DELETE FROM users WHERE usuario = 'Ari'")
        # conn.commit()
        # print("   🗑️ ¡Usuario fantasma eliminado! Intenta registrarlo de nuevo.")
    else:
        print("✅ No se encontró a 'Ari' en esta base de datos.")
        print("   Si te sigue dando error, es un problema de caché del navegador.")

    conn.close()

except Exception as e:
    print(f"❌ Error conectando: {e}")
    