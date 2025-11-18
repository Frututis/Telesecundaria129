from django.contrib import admin
from .models import Estudiante, ContactoEmergencia, Documento

class ContactoInline(admin.TabularInline):
    model = ContactoEmergencia
    extra = 0

class DocumentoInline(admin.TabularInline):
    model = Documento
    extra = 0

@admin.register(Estudiante)
class EstudianteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'apellido_paterno', 'grado_actual', 'grupo', 'estado')
    search_fields = ('nombre', 'curp')
    list_filter = ('grado_actual', 'estado')
    inlines = [ContactoInline, DocumentoInline]