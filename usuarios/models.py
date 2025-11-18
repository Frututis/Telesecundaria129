# usuarios/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class Usuario(AbstractUser):
    ROLES = (
        ('DIRECTOR', 'Director'),
        ('MAESTRO', 'Maestro'),
        ('ADMINISTRATIVO', 'Administrativo'),
        ('ALUMNO', 'Alumno'),
    )
    
    role = models.CharField(max_length=20, choices=ROLES, default='ALUMNO')
    telefono = models.CharField(max_length=15, blank=True, null=True)
    direccion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.username} - {self.get_role_display()}"

class PerfilMaestro(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='perfil_maestro')
    cedula_profesional = models.CharField(max_length=50)
    especialidad = models.CharField(max_length=100) 

    def __str__(self):
        return f"Profe. {self.usuario.first_name}"