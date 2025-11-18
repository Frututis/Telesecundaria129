# estudiantes/models.py
from django.db import models
from django.conf import settings # <--- Importante para conectar con el usuario correcto
from django.utils import timezone

class Estudiante(models.Model):
    # Conexión con el sistema de login (Opcional, por si el alumno va a entrar al sistema)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='perfil_estudiante'
    )

    OPCIONES_ESTADO = [
        ('ACTIVO', 'Activo'),
        ('BAJA', 'Baja Temporal'),
        ('GRADUADO', 'Graduado'),
        ('RETIRADO', 'Retirado'),
    ]

    nombre = models.CharField(max_length=100)
    apellido_paterno = models.CharField(max_length=100)
    apellido_materno = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField()
    curp = models.CharField(max_length=18, unique=True, verbose_name="CURP")
    
    grado_actual = models.IntegerField(default=1, choices=[(1, '1°'), (2, '2°'), (3, '3°')])
    grupo = models.CharField(max_length=2, default='A')
    
    estado = models.CharField(max_length=20, choices=OPCIONES_ESTADO, default='ACTIVO')
    fecha_ingreso = models.DateField(default=timezone.now)
    fecha_egreso = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido_paterno} ({self.grado_actual}° {self.grupo})"

# Tabla: CONTACTOS DE EMERGENCIA
class ContactoEmergencia(models.Model):
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='contactos')
    nombre = models.CharField(max_length=150)
    relacion = models.CharField(max_length=50)
    telefono = models.CharField(max_length=15)
    email = models.EmailField(null=True, blank=True)

    def __str__(self):
        return f"{self.nombre} ({self.relacion})"

# Tabla: DOCUMENTOS
class Documento(models.Model):
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='documentos')
    nombre_archivo = models.CharField(max_length=100)
    archivo = models.FileField(upload_to='documentos_estudiantes/%Y/')
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre_archivo