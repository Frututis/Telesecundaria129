from django.db import models
from django.conf import settings
from estudiantes.models import Estudiante

class Materia(models.Model):
    nombre = models.CharField(max_length=100)
    grado = models.IntegerField(choices=[(1, '1°'), (2, '2°'), (3, '3°')])
    maestro = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        limit_choices_to={'role': 'MAESTRO'}
    )
    def __str__(self): return self.nombre

class Calificacion(models.Model):
    BIMESTRES = [(i, f'Bimestre {i}') for i in range(1, 6)]
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE)
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE)
    periodo = models.IntegerField(choices=BIMESTRES)
    calificacion = models.DecimalField(max_digits=4, decimal_places=1)
    class Meta: unique_together = ('estudiante', 'materia', 'periodo') 

class Planeacion(models.Model):
    maestro = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    titulo = models.CharField(max_length=200)
    archivo = models.FileField(upload_to='planeaciones/')
    aprobado = models.BooleanField(default=False)
    fecha_subida = models.DateTimeField(auto_now_add=True)

class Asistencia(models.Model):
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE)
    fecha = models.DateField()
    estado = models.CharField(max_length=1, choices=[('A', 'Asistencia'), ('F', 'Falta')], default='A')