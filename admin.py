from django.contrib import admin

from django.contrib.auth.admin import UserAdmin
from .models import Cliente, Categoria, Producto, Pedido, DetallePedido, SolicitudConfeccion

@admin.register(Cliente)
class ClienteAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Información adicional', {'fields': ('direccion', 'telefono')}),
    )
    list_display = ('username', 'email', 'direccion', 'telefono', 'is_staff')

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'precio', 'stock', 'categoria')

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre_cliente', 'estado', 'fecha', 'total')
    list_filter = ('estado', 'fecha')

@admin.register(DetallePedido)
class DetallePedidoAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'producto', 'cantidad', 'subtotal')

@admin.register(SolicitudConfeccion)
class SolicitudConfeccionAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'correo', 'tipo_prenda', 'estado', 'fecha_creacion')
    list_filter = ('tipo_prenda', 'estado', 'fecha_creacion')
    search_fields = ('nombre', 'correo', 'descripcion_diseno')