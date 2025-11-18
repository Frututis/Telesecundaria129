from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, PerfilMaestro

# Esto personaliza la tabla de usuarios para ver el ROL en la lista
class CustomUsuarioAdmin(UserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'email', 'role', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Información Extra', {'fields': ('role', 'telefono', 'direccion')}),
    )

admin.site.register(Usuario, CustomUsuarioAdmin)
admin.site.register(PerfilMaestro)