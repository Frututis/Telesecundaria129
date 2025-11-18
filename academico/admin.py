from django.contrib import admin
from .models import Materia, Calificacion, Planeacion, Asistencia

@admin.register(Materia)
class MateriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'grado', 'maestro')

@admin.register(Calificacion)
class CalificacionAdmin(admin.ModelAdmin):
    list_display = ('estudiante', 'materia', 'calificacion')

admin.site.register(Planeacion)
admin.site.register(Asistencia)