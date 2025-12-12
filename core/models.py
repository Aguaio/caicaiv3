from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import make_password, check_password

class AdminUser(models.Model):
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=255)

    def __str__(self):
        return self.username

    # ↓ nuevos métodos seguros
    def set_password(self, raw_password: str) -> None:
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

class Producto(models.Model):
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class Cliente(AbstractUser):
    direccion = models.CharField(max_length=255, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    bloqueado = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        old_username = None
        if self.pk:
            try:
                old_username = Cliente.objects.get(pk=self.pk).username
            except Cliente.DoesNotExist:
                old_username = None

        super().save(*args, **kwargs)

        # Si cambió el username, propaga a pedidos e historial
        if old_username and old_username != self.username:
            Pedido.objects.filter(nombre_cliente=old_username).update(nombre_cliente=self.username)
            HistorialCliente.objects.filter(nombre=old_username).update(nombre=self.username)

class HistorialCliente(models.Model):
    nombre = models.CharField(max_length=150)
    correo = models.EmailField()
    fecha = models.DateTimeField(auto_now_add=True)
    accion = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.nombre} - {self.accion} ({self.fecha:%d/%m/%Y})"


class Pedido(models.Model):
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('en_proceso', 'En Proceso'),
        ('finalizado', 'Finalizado'),
        ('rechazado', 'Rechazado'),
    ]

    nombre_cliente = models.CharField(max_length=100)
    correo = models.EmailField()
    direccion = models.CharField(max_length=200)
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    motivo_rechazo = models.TextField(blank=True, null=True)

    def __str__(self):
        return f'Pedido #{self.id} - {self.nombre_cliente}'


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f'{self.producto.nombre} x {self.cantidad}'
    
    
class SolicitudConfeccion(models.Model):
    TIPO_PRENDA_CHOICES = [
        ('poleron', 'Polerón'),
        ('polera', 'Polera'),
        ('pantalon', 'Pantalón'),
        ('otro', 'Otro'),
    ]

    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('revisado', 'Revisado'),
        ('cotizado', 'Cotizado'),
        ('rechazado', 'Rechazado'),
        ('aceptado', 'Aceptado por cliente'),
        ('cancelado', 'Cancelado por cliente'),
    ]

    # Si el usuario está logeado, lo guardamos; si no, queda en blanco
    cliente = models.ForeignKey(
        'Cliente',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitudes_confeccion'
    )

    nombre = models.CharField(max_length=150)
    correo = models.EmailField()
    telefono = models.CharField(max_length=20)

    tipo_prenda = models.CharField(max_length=20, choices=TIPO_PRENDA_CHOICES)
    descripcion_diseno = models.TextField()

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente')
    respuesta = models.TextField(blank=True, null=True)
    observaciones_admin = models.TextField(blank=True, null=True, default='')
    cotizacion_monto = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cotizacion_aceptada = models.BooleanField(null=True, blank=True, default=None)

    def __str__(self):
        return f"Confección #{self.id} - {self.nombre} ({self.get_tipo_prenda_display()})"

    class Meta:
        ordering = ['-fecha_creacion']
