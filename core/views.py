from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.views.decorators.cache import never_cache
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout, get_user_model
from .models import AdminUser, Categoria, Producto, Pedido, DetallePedido, Cliente, HistorialCliente, SolicitudConfeccion, AdminUser
from .decorators import admin_required
from django.urls import reverse
from .forms import SolicitudConfeccionForm, RegistroClienteForm


from django.db import transaction
from django.views.decorators.csrf import csrf_protect
from decimal import Decimal, InvalidOperation

from django.views.decorators.http import require_POST

from django.http import JsonResponse  

from collections import defaultdict

from django.utils.functional import cached_property

import random, string, time
from django.contrib.auth.hashers import make_password


User = get_user_model()

# ------------------- PÁGINAS PÚBLICAS -------------------

def home(request):
    cart = request.session.get('cart', {})
    cart_count = 0
    try:
        cart_count = sum(item.get('cantidad', 0) for item in cart.values())
    except Exception:
        cart_count = 0

    context = {
        'cart_count': cart_count,
    }
    return render(request, 'core/home.html', context)


def _cart_count(request):
    carrito = request.session.get('carrito', {})
    return sum(int(q) for q in carrito.values())


def catalogo(request):
    query = request.GET.get('q')
    categoria_id = request.GET.get('categoria')

    productos = Producto.objects.all()
    categorias = Categoria.objects.all()

    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
    if query:
        productos = productos.filter(Q(nombre__icontains=query) | Q(descripcion__icontains=query))

    # Selecciona imágenes para el banner (prioridad: media/productos, luego media/fotos, luego fotos de productos)
    import os
    from django.conf import settings
    banner_images = []
    target_imgs = 8

    def add_from_dir(folder):
        base = os.path.join(settings.MEDIA_ROOT, folder)
        if os.path.isdir(base):
            for fname in sorted(os.listdir(base)):
                if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    rel = f'/{folder}/{fname}'
                    banner_images.append(settings.MEDIA_URL.rstrip('/') + rel)
                    if len(banner_images) >= target_imgs:
                        return

    add_from_dir('productos')
    if len(banner_images) < target_imgs:
        add_from_dir('fotos')

    if len(banner_images) < target_imgs:
        for p in productos.exclude(imagen='').exclude(imagen__isnull=True):
            try:
                banner_images.append(p.imagen.url)
            except Exception:
                continue
            if len(banner_images) >= target_imgs:
                break

    while len(banner_images) < 4:
        banner_images.append('')

    return render(request, 'core/catalogo.html', {
        'productos': productos,
        'categorias': categorias,
        'categoria_id': categoria_id,
        'query': query,
        'cart_count': _cart_count(request),
        'banner_images': banner_images,
    })

@never_cache
def admin_login(request):
    return redirect('login_unificado')


# ------------------- LOGIN UNIFICADO -------------------

@never_cache
@csrf_protect
def login_unificado(request):
    """
    Login unificado:
    - Si coincide con AdminUser -> panel de administración.
    - Si coincide con usuario Django:
        - si es staff/superuser -> también panel de administración.
        - si no, va al catálogo como cliente normal.
    """
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = (request.POST.get('password') or '').strip()

        # 1) Intentar login como AdminUser (modelo propio del panel)
        admin = AdminUser.objects.filter(username=username).first()
        if admin and admin.check_password(password):
            # limpiamos sesión anterior por seguridad
            request.session.flush()
            request.session['admin_id'] = admin.id
            messages.success(request, 'Has iniciado sesión como administrador.')
            return redirect('admin_dashboard')

        # 2) Intentar login como usuario normal de Django (auth_user)
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)

            # Si es staff o superuser, lo tratamos como administrador del panel
            if user.is_staff or user.is_superuser:
                request.session['admin_id'] = user.id
                messages.success(request, 'Has iniciado sesión como administrador.')
                return redirect('admin_dashboard')

            # Si no es staff/superuser, es cliente normal
            messages.success(request, 'Has iniciado sesión correctamente.')
            return redirect('home')

        # 3) Si llega aquí, credenciales inválidas
        messages.error(request, 'Usuario o contraseña incorrectos.')

    # GET o POST con error -> mostrar formulario
    return render(request, 'core/login_unificado.html', {})

def logout_unificado(request):
    """
    Cierra sesión tanto de usuario normal como de admin del panel.
    """
    # logout de Django (usuario normal)
    logout(request)
    # limpiar marca de admin del panel
    request.session.pop('admin_id', None)
    messages.success(request, 'Has cerrado sesión correctamente.')
    return redirect('catalogo')

# ------------------- REGISTRO CLIENTE -------------------

@csrf_protect
def registro_cliente(request):
    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Iniciar sesión automáticamente después de registrarse
            login(request, user)
            messages.success(
                request,
                "Cuenta creada exitosamente. ¡Bienvenido(a) a Caicai!"
            )
            return redirect("home")
        else:
            messages.error(
                request,
                "Por favor corrige los errores marcados en el formulario."
            )
    else:
        form = RegistroClienteForm()

    return render(request, "core/registro_cliente.html", {"form": form})


# ------------------- PERFIL CLIENTE -------------------

@login_required
def editar_perfil(request):
    user = request.user

    if request.method == 'POST':
        email = request.POST.get('correo', '').strip()
        direccion = request.POST.get('direccion', '').strip()
        telefono = request.POST.get('telefono', '').strip()

        if not email:
            messages.error(request, 'El correo no puede estar vacío.')
        elif User.objects.exclude(id=user.id).filter(email=email).exists():
            messages.error(request, 'Ese correo ya está en uso.')
        else:
            user.email = email
            user.direccion = direccion
            user.telefono = telefono
            user.save()
            messages.success(request, 'Perfil actualizado correctamente.')
            return redirect('editar_perfil')

    return render(request, 'core/editar_perfil.html', {'user': user})


# ------------------- PANEL ADMIN -------------------

@admin_required
@never_cache
def admin_dashboard(request):
    return render(request, 'core/admin_dashboard.html')


# ----- CRUD Categorías -----

@admin_required
def categorias_list(request):
    categorias = Categoria.objects.all()
    return render(request, 'core/categorias_list.html', {'categorias': categorias})


@admin_required
def categoria_create(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre').strip()
        if not nombre:
            messages.error(request, 'El nombre no puede estar vacío.')
        elif Categoria.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, 'Ya existe una categoría con ese nombre.')
        else:
            Categoria.objects.create(nombre=nombre)
            messages.success(request, 'Categoría creada correctamente.')
            return redirect('categorias_list')
    return render(request, 'core/categoria_form.html', {
        'categoria': None,
        'values': {
            'nombre': request.POST.get('nombre', '') if request.method == 'POST' else '',
        }
    })


@admin_required
def categoria_edit(request, id):
    categoria = get_object_or_404(Categoria, id=id)
    if request.method == 'POST':
        nombre = request.POST.get('nombre').strip()
        if not nombre:
            messages.error(request, 'El nombre no puede estar vacío.')
        elif Categoria.objects.exclude(id=id).filter(nombre__iexact=nombre).exists():
            messages.error(request, 'Ya existe una categoría con ese nombre.')
        else:
            categoria.nombre = nombre
            categoria.save()
            messages.success(request, 'Categoría actualizada correctamente.')
            return redirect('categorias_list')
    return render(request, 'core/categoria_form.html', {
        'categoria': categoria,
        'values': {
            'nombre': request.POST.get('nombre', categoria.nombre),
        }
    })


@admin_required
@csrf_protect
def categoria_delete(request, id):
    if request.method != 'POST':
        messages.error(request, 'Operación no permitida.')
        return redirect('categorias_list')
    Categoria.objects.filter(id=id).delete()
    messages.success(request, 'Categoría eliminada correctamente.')
    return redirect('categorias_list')


# ----- CLIENTES ADMIN -----

@admin_required
def clientes_list(request):
    clientes = Cliente.objects.all().order_by('username')
    nombres = list(clientes.values_list('username', flat=True))
    historial_qs = HistorialCliente.objects.filter(nombre__in=nombres).order_by('-fecha')
    historial_por_cliente = defaultdict(list)
    for h in historial_qs:
        historial_por_cliente[h.nombre].append(h)
    resumen = []
    for c in clientes:
        lst = historial_por_cliente.get(c.username, [])
        last = lst[0] if lst else None
        resumen.append({
            'username': c.username,
            'correo': c.email,
            'accion': last.accion if last else '—',
            'fecha': last.fecha if last else None,
            'tiene_historial': bool(lst),
        })

    return render(request, 'core/clientes_list.html', {
        'clientes': clientes,
        'resumen': resumen,
        'historial_por_cliente': historial_por_cliente,
    })


@admin_required
@require_POST
@csrf_protect
def cliente_bloquear(request, id):
    cliente = get_object_or_404(Cliente, id=id)
    cliente.bloqueado = True
    cliente.save()
    HistorialCliente.objects.create(nombre=cliente.username, correo=cliente.email, accion='bloqueado')
    messages.error(request, f'Cliente {cliente.username} bloqueado.')
    return redirect('clientes_list')


@admin_required
@require_POST
@csrf_protect
def cliente_desbloquear(request, id):
    cliente = get_object_or_404(Cliente, id=id)
    cliente.bloqueado = False
    cliente.save()
    HistorialCliente.objects.create(nombre=cliente.username, correo=cliente.email, accion='desbloqueado')
    messages.success(request, f'Cliente {cliente.username} desbloqueado.')
    return redirect('clientes_list')



# ------------------- PRODUCTOS -------------------

@admin_required
def productos_list(request):
    productos = Producto.objects.all()
    return render(request, 'core/productos_list.html', {'productos': productos})


@admin_required
@csrf_protect
def producto_create(request):
    categorias = Categoria.objects.all()
    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        descripcion = (request.POST.get('descripcion') or '').strip()
        precio_raw = request.POST.get('precio')
        stock_raw = request.POST.get('stock')
        categoria_id = request.POST.get('categoria')
        imagen = request.FILES.get('imagen')

        if not nombre or precio_raw is None or stock_raw is None or not categoria_id:
            messages.error(request, 'Todos los campos obligatorios deben completarse.')
        else:
            try:
                precio = Decimal(precio_raw)
                stock = int(stock_raw)
                if precio < 0 or stock < 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                messages.error(request, 'Precio o stock inválidos.')
                return render(request, 'core/producto_form.html', {'categorias': categorias})

            categoria = get_object_or_404(Categoria, id=categoria_id)
            Producto.objects.create(
                nombre=nombre,
                descripcion=descripcion,
                precio=precio,
                stock=stock,
                categoria=categoria,
                imagen=imagen
            )
            messages.success(request, 'Producto creado correctamente.')
            return redirect('productos_list')
    return render(request, 'core/producto_form.html', {
        'categorias': categorias,
        'producto': None,  # para reutilizar el template sin variable ausente
        'values': {
            'nombre': request.POST.get('nombre', '') if request.method == 'POST' else '',
            'categoria': request.POST.get('categoria', '') if request.method == 'POST' else '',
            'precio': request.POST.get('precio', '') if request.method == 'POST' else '',
            'stock': request.POST.get('stock', '') if request.method == 'POST' else '',
            'descripcion': request.POST.get('descripcion', '') if request.method == 'POST' else '',
        }
    })


@admin_required
@csrf_protect
def producto_edit(request, id):
    producto = get_object_or_404(Producto, id=id)
    categorias = Categoria.objects.all()
    if request.method == 'POST':
        producto.nombre = (request.POST.get('nombre') or '').strip()
        producto.descripcion = (request.POST.get('descripcion') or '').strip()
        try:
            producto.precio = Decimal(request.POST.get('precio'))
            producto.stock = int(request.POST.get('stock'))
            if producto.precio < 0 or producto.stock < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, 'Precio o stock inválidos.')
            return render(request, 'core/producto_form.html', {'producto': producto, 'categorias': categorias})

        producto.categoria_id = request.POST.get('categoria')
        if request.FILES.get('imagen'):
            producto.imagen = request.FILES.get('imagen')
        producto.save()
        messages.success(request, 'Producto actualizado correctamente.')
        return redirect('productos_list')
    return render(request, 'core/producto_form.html', {
        'producto': producto,
        'categorias': categorias,
        'values': {
            'nombre': request.POST.get('nombre', producto.nombre),
            'categoria': request.POST.get('categoria', producto.categoria_id),
            'precio': request.POST.get('precio', producto.precio),
            'stock': request.POST.get('stock', producto.stock),
            'descripcion': request.POST.get('descripcion', producto.descripcion),
        }
    })


@admin_required
@csrf_protect
def producto_delete(request, id):
    if request.method != 'POST':
        messages.error(request, 'Operación no permitida.')
        return redirect('productos_list')
    Producto.objects.filter(id=id).delete()
    messages.success(request, 'Producto eliminado correctamente.')
    return redirect('productos_list')


# ------------------- PEDIDOS -------------------

@admin_required
def pedidos_list(request):
    pedido_id = (request.GET.get('pedido_id') or '').strip()

    pedidos_qs = Pedido.objects.all()
    if pedido_id:
        try:
            pid = int(pedido_id)
            pedidos_qs = pedidos_qs.filter(id=pid)
        except ValueError:
            pedidos_qs = pedidos_qs.none()

    pedidos = list(pedidos_qs.order_by('-fecha'))

    # Colecta identificadores presentes en la tabla de pedidos
    usernames = {p.nombre_cliente for p in pedidos if p.nombre_cliente}
    correos = {p.correo for p in pedidos if p.correo}

    # Trae clientes que coincidan por username o email
    clientes = Cliente.objects.filter(Q(username__in=usernames) | Q(email__in=correos)) \
                              .values('username', 'email', 'bloqueado')

    # Índices para lookup rápido
    block_by_user = {c['username']: c['bloqueado'] for c in clientes}
    block_by_mail = {c['email']: c['bloqueado'] for c in clientes}

    # Anexa flag al objeto pedido
    for p in pedidos:
        p.bloqueado = bool(block_by_user.get(p.nombre_cliente) or block_by_mail.get(p.correo))

    return render(request, 'core/pedidos_list.html', {
        'pedidos': pedidos,
        'pedido_id': pedido_id,
    })

@admin_required
def pedido_detalle(request, id):
    pedido = get_object_or_404(Pedido, id=id)
    detalles = pedido.detalles.all()

    bloqueado = Cliente.objects.filter(
        username=pedido.nombre_cliente
    ).values_list('bloqueado', flat=True).first() or False

    if request.method == 'POST':
        nuevo_estado = request.POST.get('estado')
        motivo = (request.POST.get('motivo') or '').strip()
        estado_anterior = pedido.estado

        pedido.estado = nuevo_estado
        if nuevo_estado == 'rechazado':
            pedido.motivo_rechazo = motivo or 'Sin motivo especificado'
        else:
            pedido.motivo_rechazo = ''
        pedido.save()

        if estado_anterior == nuevo_estado == 'rechazado':
            accion = f'Pedido {pedido.id} -> rechazado (motivo actualizado)'
        else:
            accion = f'Pedido {pedido.id} -> {nuevo_estado}'

        HistorialCliente.objects.create(
            nombre=pedido.nombre_cliente,
            correo=pedido.correo,
            accion=accion
        )

        messages.success(request, f'Estado del pedido {pedido.id} actualizado a {nuevo_estado}.')
        return redirect('pedido_detalle', id=pedido.id)

    return render(request, 'core/pedido_detalle.html', {
        'pedido': pedido,
        'detalles': detalles,
        'bloqueado': bloqueado
    })


# ------------------- SOLICITUDES DE CONFECCIÓN (ADMIN) -------------------

@admin_required
def solicitudes_confeccion_list(request):
    """
    Lista todas las solicitudes de confección para el panel de administración.
    """
    solicitudes = SolicitudConfeccion.objects.all().order_by('-fecha_creacion')
    return render(request, 'core/solicitudes_confeccion_list.html', {
        'solicitudes': solicitudes,
    })


@admin_required
def historial_clientes(request):
    search = (request.GET.get('q') or '').strip()
    selected = (request.GET.get('cliente') or '').strip()

    clientes_qs = Cliente.objects.all().order_by('username')
    if search:
        clientes_qs = clientes_qs.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search)
        )

    if selected:
        historial = HistorialCliente.objects.filter(nombre=selected).order_by('-fecha')
    else:
        historial = HistorialCliente.objects.none()

    return render(request, 'core/historial_clientes.html', {
        'clientes': clientes_qs,
        'historial': historial,
        'selected_cliente': selected,
        'search': search,
    })


@admin_required
@csrf_protect
def solicitud_confeccion_detalle(request, id):
    solicitud = get_object_or_404(SolicitudConfeccion, id=id)

    if request.method == 'POST':
        nuevo_estado = (request.POST.get('estado') or solicitud.estado).strip()
        observaciones = (request.POST.get('observaciones_admin') or '').strip()

        # lista clara de valores válidos: 'pendiente', 'revisado', 'cotizado', 'rechazado'
        estados_validos = [value for value, _ in SolicitudConfeccion.ESTADO_CHOICES]

        if nuevo_estado not in estados_validos:
            messages.error(request, 'Estado inválido.')
        else:
            solicitud.estado = nuevo_estado
            solicitud.observaciones_admin = observaciones
            solicitud.save()
            messages.success(request, 'Solicitud actualizada correctamente.')
            return redirect('solicitud_confeccion_detalle', id=solicitud.id)

    return render(request, 'core/solicitud_confeccion_detalle.html', {
        'solicitud': solicitud,
        'estados': SolicitudConfeccion.ESTADO_CHOICES,
    })


# ------------------- CARRITO -------------------

@require_POST
@csrf_protect
def agregar_al_carrito(request, id):
    if request.user.is_authenticated and getattr(request.user, 'bloqueado', False):
        return JsonResponse({'ok': False, 'error': 'bloqueado'}, status=403)
    
    carrito = request.session.get('carrito', {})
    try:
        cantidad = int(request.POST.get('cantidad', 1))
        if cantidad < 1:
            cantidad = 1
    except ValueError:
        cantidad = 1

    key = str(id)
    carrito[key] = carrito.get(key, 0) + cantidad
    request.session['carrito'] = carrito
    count = _cart_count(request)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('accept', '').find('application/json') != -1:
        return JsonResponse({'ok': True, 'count': count})

    return redirect('ver_carrito')


@require_POST
@csrf_protect
def eliminar_del_carrito(request, id):
    carrito = request.session.get('carrito', {})
    if str(id) in carrito:
        del carrito[str(id)]
        request.session['carrito'] = carrito
    return redirect('ver_carrito')


def ver_carrito(request):
    carrito = request.session.get('carrito', {})
    productos = []
    total = Decimal(0)
    faltantes = []
    allow_checkout = True

    for id, cantidad in carrito.items():
        producto = Producto.objects.get(id=id)
        subtotal = producto.precio * cantidad
        total += subtotal
        stock_ok = producto.stock >= cantidad
        if not stock_ok:
            allow_checkout = False
            faltantes.append({
                'nombre': producto.nombre,
                'disponible': producto.stock,
                'cantidad': cantidad,
            })
        productos.append({
            'id': producto.id,
            'nombre': producto.nombre,
            'precio': producto.precio,
            'cantidad': cantidad,
            'subtotal': subtotal,
            'imagen': producto.imagen.url if getattr(producto, 'imagen', None) else '',
            'stock_ok': stock_ok,
            'stock': producto.stock,
        })

    return render(request, 'core/carrito.html', {
        'productos': productos,
        'total': total,
        'cart_count': _cart_count(request),
        'allow_checkout': allow_checkout,
        'faltantes': faltantes,
    })


@login_required
@csrf_protect
def confirmar_pedido(request):
    if request.user.bloqueado:
        messages.error(request, 'Tu cuenta está bloqueada. No puedes realizar pedidos.')
        return redirect('catalogo')

    carrito = request.session.get('carrito', {})
    if not carrito:
        messages.error(request, 'Tu carrito está vacío.')
        return redirect('catalogo')

    # Prepara vista previa de productos en el carrito
    productos_ctx = []
    total_ctx = Decimal('0')
    for pid, cantidad in carrito.items():
        prod = Producto.objects.get(id=pid)
        subtotal = prod.precio * cantidad
        total_ctx += subtotal
        productos_ctx.append({
            'id': prod.id,
            'nombre': prod.nombre,
            'precio': prod.precio,
            'cantidad': cantidad,
            'subtotal': subtotal,
            'imagen': prod.imagen.url if getattr(prod, 'imagen', None) else '',
        })

    if request.method == 'POST':
        with transaction.atomic():
            # Verificación previa de stock con bloqueo de fila
            faltantes = []
            productos_seleccionados = {}
            for pid, cantidad in carrito.items():
                prod = Producto.objects.select_for_update().get(id=pid)
                if prod.stock < cantidad:
                    faltantes.append((prod.nombre, prod.stock, cantidad))
                productos_seleccionados[pid] = prod

            if faltantes:
                readable = '; '.join([f'{n} (disponible: {d}, solicitado: {c})' for n, d, c in faltantes])
                msg = 'No hay stock suficiente para: ' + readable
                messages.error(request, msg)
                return redirect('ver_carrito')

            cliente = request.user
            pedido = Pedido.objects.create(
                nombre_cliente=cliente.username,
                correo=cliente.email,
                direccion=cliente.direccion or 'Sin dirección',
                total=Decimal('0')
            )

            total = Decimal('0')
            for pid, cantidad in carrito.items():
                prod = productos_seleccionados[pid]
                subtotal = prod.precio * cantidad
                total += subtotal
                DetallePedido.objects.create(pedido=pedido, producto=prod, cantidad=cantidad, subtotal=subtotal)
                prod.stock -= cantidad
                prod.save()

            pedido.total = total
            pedido.save()

        request.session['carrito'] = {}
        messages.success(request, 'Pedido confirmado correctamente.')
        return render(request, 'core/pedido_confirmado.html', {'pedido': pedido})

    return render(request, 'core/confirmar_pedido.html', {
        'productos': productos_ctx,
        'total': total_ctx,
        'cart_count': _cart_count(request),
    })


@login_required
def mis_pedidos(request):
    pedidos = Pedido.objects.filter(nombre_cliente=request.user.username).order_by('-fecha')
    return render(request, 'core/mis_pedidos.html', {'pedidos': pedidos, 'cart_count': _cart_count(request)})

# ------------------- Solicitud de confeccion -------------------

@csrf_protect
def solicitud_confeccion(request):
    """
    Vista para que el cliente envíe una solicitud de confección a medida.
    Si el usuario está autenticado, se pre-rellena nombre, correo y teléfono.
    """
    initial_data = {}

    if request.user.is_authenticated:
        initial_data = {
            'nombre': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
            'correo': request.user.email,
            # si el usuario no tiene telefono, queda vacío
            'telefono': getattr(request.user, 'telefono', '') or '',
        }

    if request.method == 'POST':
        form = SolicitudConfeccionForm(request.POST)
        if form.is_valid():
            solicitud = form.save(commit=False)
            if request.user.is_authenticated:
                solicitud.cliente = request.user
            solicitud.save()
            messages.success(
                request,
                'Tu solicitud de confección a medida ha sido enviada. Te contactaremos pronto.'
            )
            return redirect('solicitud_confeccion')
        else:
            # SOLO entra aquí si el form tiene errores
            messages.error(request, 'Todos los campos marcados con * son obligatorios.')
    else:
        form = SolicitudConfeccionForm(initial=initial_data)

    return render(request, 'core/solicitud_confeccion.html', {
        'form': form,
        'cart_count': _cart_count(request),
    })





##############################################################################################################################
##############################################################################################################################
##############################################################################################################################
##############################################################################################################################


# util: guardar un “código” temporal en sesión (válido 10 min)
def _issue_pwd_code(request, username, email):
    code = ''.join(random.choices(string.digits, k=6))
    request.session['pwd_reset'] = {
        'username': username,
        'email': email,
        'code': code,
        'ts': int(time.time())
    }
    request.session.modified = True
    return code

def _validate_pwd_code(request, username, email, code):
    data = request.session.get('pwd_reset')
    if not data:
        return False, 'No hay código generado.'
    if data.get('username') != username or data.get('email') != email:
        return False, 'Usuario o correo no coinciden.'
    if data.get('code') != code:
        return False, 'Código incorrecto.'
    if int(time.time()) - int(data.get('ts', 0)) > 600:
        return False, 'Código expirado.'
    return True, ''

@csrf_protect
def solicitar_codigo_password(request):
    # Form: username, correo
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        correo = (request.POST.get('correo') or '').strip()

        try:
            user = User.objects.get(username=username, email=correo)
        except User.DoesNotExist:
            messages.error(request, 'Usuario/correo no encontrados.')
            return render(request, 'core/solicitar_codigo_password.html')

        code = _issue_pwd_code(request, username, correo)

        # En desarrollo: mostramos el código por mensaje para que puedas probar
        # En producción, envíalo por correo usando EmailMessage o backend de email.
        messages.success(request, f'Se envió un código a tu correo. (DEV: código {code})')
        return redirect(f'{reverse("restablecer_password")}?u={username}&e={correo}')

    return render(request, 'core/solicitar_codigo_password.html')



@csrf_protect
def restablecer_password(request):
    # Form: username, correo, codigo, nueva_password
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        correo = (request.POST.get('correo') or '').strip()
        codigo = (request.POST.get('codigo') or '').strip()
        nueva = (request.POST.get('password') or '').strip()

        ok, err = _validate_pwd_code(request, username, correo, codigo)
        if not ok:
            messages.error(request, err)
            return render(request, 'core/restablecer_password.html', {
                'username': username,
                'correo': correo
            })

        try:
            user = User.objects.get(username=username, email=correo)
        except User.DoesNotExist:
            messages.error(request, 'Usuario/correo no encontrados.')
            return render(request, 'core/restablecer_password.html', {
                'username': username,
                'correo': correo
            })

        if len(nueva) < 3:
            messages.error(request, 'La contraseña debe tener al menos 3 caracteres.')
            return render(request, 'core/restablecer_password.html', {
                'username': username,
                'correo': correo
            })

        user.set_password(nueva)
        user.save()
        # limpiar código
        request.session.pop('pwd_reset', None)
        messages.success(request, 'Contraseña actualizada. Inicia sesión.')
        return redirect('login_unificado')

    # Si se accede por GET, prellenar usuario y correo desde la URL
    username = request.GET.get('u', '')
    correo = request.GET.get('e', '')
    return render(request, 'core/restablecer_password.html', {
        'username': username,
        'correo': correo
    })



@login_required
@csrf_protect
def cambiar_password_por_usuario_correo(request):
    # Form: username, correo, nueva_password
    # Requiere estar logueado, y que username+correo correspondan a su cuenta.
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        correo = (request.POST.get('correo') or '').strip()
        nueva = (request.POST.get('password') or '').strip()

        if request.user.username != username or request.user.email != correo:
            messages.error(request, 'Usuario o correo no coinciden con tu cuenta.')
            return render(request, 'core/cambiar_password.html')

        if len(nueva) < 3:
            messages.error(request, 'La contraseña debe tener al menos 3 caracteres.')
            return render(request, 'core/cambiar_password.html')

        request.user.set_password(nueva)
        request.user.save()
        messages.success(request, 'Contraseña actualizada. Vuelve a iniciar sesión.')
        return redirect('login_unificado')

    return render(request, 'core/cambiar_password.html')


# ------------------- OLVIDÉ MI CONTRASEÑA (flujo por pasos) -------------------

def forgot_password_username(request):
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        if not username:
            messages.error(request, 'Debes ingresar un nombre de usuario.')
        else:
            request.session['fp_username'] = username
            return redirect('forgot_password_verify')
    return render(request, 'core/forgot_password_username.html')


def forgot_password_verify(request):
    username = request.session.get('fp_username', '')
    if not username:
        return redirect('forgot_password_username')

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('telefono') or '').strip()
        try:
            user = User.objects.get(username=username, email=email, telefono=phone)
        except User.DoesNotExist:
            messages.error(request, 'Los datos no coinciden con nuestra base de usuarios.')
            return render(request, 'core/forgot_password_verify.html', {'username': username})

        request.session['fp_user_id'] = user.id
        return redirect('forgot_password_reset')

    return render(request, 'core/forgot_password_verify.html', {'username': username})


def forgot_password_reset(request):
    user_id = request.session.get('fp_user_id')
    username = request.session.get('fp_username', '')
    if not user_id:
        return redirect('forgot_password_username')

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        request.session.pop('fp_user_id', None)
        return redirect('forgot_password_username')

    if request.method == 'POST':
        p1 = (request.POST.get('password1') or '').strip()
        p2 = (request.POST.get('password2') or '').strip()
        if len(p1) < 3:
            messages.error(request, 'La contraseña debe tener al menos 3 caracteres.')
        elif p1 != p2:
            messages.error(request, 'Las contraseñas no coinciden.')
        else:
            user.set_password(p1)
            user.save()
            HistorialCliente.objects.create(
                nombre=user.username,
                correo=user.email,
                accion='password restablecida'
            )
            request.session.pop('fp_user_id', None)
            request.session.pop('fp_username', None)
            messages.success(request, 'Contraseña actualizada. Ahora puedes iniciar sesión.')
            return redirect('login_unificado')

    return render(request, 'core/forgot_password_reset.html', {'username': username})

##############################################################################################################################
##############################################################################################################################
##############################################################################################################################
##############################################################################################################################
