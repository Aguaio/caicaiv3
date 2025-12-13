from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q, Sum
from django.views.decorators.cache import never_cache
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.db.models import F
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout, get_user_model
from .models import AdminUser, Categoria, Producto, Pedido, DetallePedido, Cliente, HistorialCliente, SolicitudConfeccion, AdminUser
from .decorators import admin_required
from django.urls import reverse
from .forms import SolicitudConfeccionForm, RegistroClienteForm
from .validators import validar_telefono_formato


from django.db import transaction
from django.views.decorators.csrf import csrf_protect
from decimal import Decimal, InvalidOperation

from django.views.decorators.http import require_POST

from django.http import JsonResponse  

from collections import defaultdict

from django.utils.functional import cached_property
from django.utils import timezone
from datetime import datetime, time as dt_time

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


def _low_stock_threshold(request):
    try:
        value = int(request.session.get('low_stock_threshold', getattr(settings, 'LOW_STOCK_THRESHOLD', 5)))
        return max(1, min(20, value))
    except (TypeError, ValueError):
        return 5

def _low_stock_products(threshold: int):
    qs = Producto.objects.filter(activo=True, stock__lte=threshold).annotate(nombre_display=F('nombre'))
    return list(qs)

def _low_stock_context(request):
    threshold = _low_stock_threshold(request)
    productos = _low_stock_products(threshold)
    return {
        'low_stock_products': productos,
        'low_stock_count': len(productos),
        'low_stock_threshold': threshold,
    }


@admin_required
@require_POST
@csrf_protect
def set_low_stock_threshold(request):
    """
    Actualiza el umbral de stock bajo para la sesión del admin (3 a 20).
    """
    try:
        value = int(request.POST.get('threshold', 5))
    except (TypeError, ValueError):
        value = 5
    value = max(3, min(20, value))
    request.session['low_stock_threshold'] = value

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('admin_dashboard')
    return redirect(next_url)


def _boleta_path(tipo: str, obj_id: int) -> Path:
    base = Path(settings.MEDIA_ROOT) / "boletas"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{tipo}_{obj_id}.pdf"


def _boleta_url(tipo: str, obj_id: int) -> str:
    return f"{settings.MEDIA_URL.rstrip('/')}/boletas/{tipo}_{obj_id}.pdf"


def _render_boleta_pdf(title: str, lines: list[str], path: Path) -> None:
    """
    Genera un PDF mínimo con texto plano para la boleta sin dependencias externas.
    """
    content_lines = []
    y_offset = 0
    for line in lines:
        content_lines.append(f"0 -14 Td ({line}) Tj")
        y_offset -= 14

    stream_parts = [
        "BT",
        "/F1 12 Tf",
        "50 780 Td",
        f"({title}) Tj",
        "/F1 10 Tf",
        *content_lines,
        "ET",
    ]
    stream = "\n".join(stream_parts)
    stream_bytes = stream.encode("latin-1", "replace")

    pdf_chunks = [
        "%PDF-1.4",
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        "2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj",
        f"4 0 obj << /Length {len(stream_bytes)} >> stream\n",
    ]
    pdf_bytes = "\n".join(pdf_chunks).encode() + stream_bytes + b"\nendstream\nendobj\n"
    pdf_bytes += b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"

    # tabla xref simple
    objects = pdf_bytes.split(b"endobj")
    offsets = []
    cursor = 0
    for part in objects[:-1]:
        offsets.append(cursor)
        cursor += len(part) + len(b"endobj\n")
    offsets.append(cursor)

    xref_lines = ["xref", f"0 {len(offsets)}", "0000000000 65535 f "]
    for off in offsets[1:]:
        xref_lines.append(f"{off:010d} 00000 n ")

    xref = "\n".join(xref_lines).encode() + b"\n"
    trailer = f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{len(pdf_bytes)}\n%%EOF"
    final_pdf = pdf_bytes + xref + trailer.encode()
    path.write_bytes(final_pdf)


def _boleta_pedido(pedido):
    if pedido.estado != "finalizado":
        return None
    pdf_path = _boleta_path("pedido", pedido.id)
    if not pdf_path.exists():
        lines = [
            f"Cliente: {pedido.nombre_cliente}",
            f"Correo: {pedido.correo}",
            f"Dirección: {pedido.direccion}",
            f"Fecha: {pedido.fecha:%d/%m/%Y %H:%M}",
            f"Estado: {pedido.estado}",
            f"Total: {pedido.total}",
        ]
        _render_boleta_pdf(f"Boleta Pedido #{pedido.id}", lines, pdf_path)
    return _boleta_url("pedido", pedido.id)


def _boleta_confeccion(solicitud):
    if solicitud.cotizacion_aceptada is not True:
        return None
    pdf_path = _boleta_path("confeccion", solicitud.id)
    if not pdf_path.exists():
        lines = [
            f"Cliente: {solicitud.nombre}",
            f"Correo: {solicitud.correo}",
            f"Teléfono: {solicitud.telefono}",
            f"Fecha: {solicitud.fecha_creacion:%d/%m/%Y %H:%M}",
            f"Prenda: {solicitud.get_tipo_prenda_display()}",
            f"Estado: {solicitud.get_estado_display()}",
        ]
        if solicitud.cotizacion_monto:
            lines.append(f"Cotización: {solicitud.cotizacion_monto}")
        _render_boleta_pdf(f"Boleta Confección #{solicitud.id}", lines, pdf_path)
    return _boleta_url("confeccion", solicitud.id)

def catalogo(request):
    query = request.GET.get('q')
    categoria_id = request.GET.get('categoria')

    productos = Producto.objects.filter(activo=True)
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
        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('correo') or '').strip()
        direccion = (request.POST.get('direccion') or '').strip()
        telefono = (request.POST.get('telefono') or '').strip()

        if not username:
            messages.error(request, 'El nombre de usuario no puede estar vacio.')
        elif User.objects.exclude(id=user.id).filter(username=username).exists():
            messages.error(request, 'Ese nombre de usuario ya esta en uso.')
        elif not email:
            messages.error(request, 'El correo no puede estar vacio.')
        elif User.objects.exclude(id=user.id).filter(email=email).exists():
            messages.error(request, 'Ese correo ya esta en uso.')
        else:
            try:
                telefono_normalizado = validar_telefono_formato(telefono)
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                old_username = user.username
                user.username = username
                user.email = email
                user.direccion = direccion
                user.telefono = telefono_normalizado
                user.save()

                if old_username != username:
                    Pedido.objects.filter(nombre_cliente=old_username).update(nombre_cliente=username)
                    HistorialCliente.objects.filter(nombre=old_username).update(nombre=username)

                messages.success(request, 'Perfil actualizado correctamente.')
                return redirect('editar_perfil')

    return render(request, 'core/editar_perfil.html', {'user': user})

# ------------------- PANEL ADMIN -------------------

@admin_required
@never_cache
def admin_dashboard(request):
    return render(request, 'core/admin_dashboard.html', _low_stock_context(request))


# ----- CRUD Categorías -----

@admin_required
def categorias_list(request):
    categorias = Categoria.objects.all()
    ctx = {'categorias': categorias}
    ctx.update(_low_stock_context(request))
    return render(request, 'core/categorias_list.html', ctx)


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
        },
        **_low_stock_context(request),
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
        },
        **_low_stock_context(request),
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
    search = (request.GET.get('q') or '').strip()
    clientes = Cliente.objects.all().order_by('username')
    if search:
        clientes = clientes.filter(Q(username__icontains=search) | Q(email__icontains=search))
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

    ctx = {
        'clientes': clientes,
        'resumen': resumen,
        'historial_por_cliente': historial_por_cliente,
        'search': search,
    }
    ctx.update(_low_stock_context(request))
    return render(request, 'core/clientes_list.html', ctx)


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

@admin_required
@require_POST
@csrf_protect
def cliente_eliminar(request, id):
    cliente = get_object_or_404(Cliente, id=id)

    if cliente.is_staff or cliente.is_superuser:
        messages.error(request, 'No puedes eliminar cuentas de administradores.')
        return redirect('clientes_list')

    nombre = cliente.username
    correo = cliente.email
    cliente.delete()
    HistorialCliente.objects.create(nombre=nombre, correo=correo, accion='eliminado')
    messages.success(request, f'Cliente {nombre} eliminado.')
    return redirect('clientes_list')



# ------------------- PRODUCTOS -------------------

@admin_required
def productos_list(request):
    sort = (request.GET.get('sort') or '').strip()
    show = (request.GET.get('show') or 'activos').strip()
    order_map = {
        'categoria': 'categoria__nombre',
        'stock_asc': 'stock',
        'stock_desc': '-stock',
        'precio_asc': 'precio',
        'precio_desc': '-precio',
        'nombre': 'nombre',
    }
    productos = Producto.objects.all()
    if show == 'activos':
        productos = productos.filter(activo=True)
    elif show == 'inactivos':
        productos = productos.filter(activo=False)
    else:
        show = 'todos'
    if sort in order_map:
        productos = productos.order_by(order_map[sort])
    else:
        productos = productos.order_by('id')

    ctx = {'productos': productos, 'sort': sort, 'show': show}
    ctx.update(_low_stock_context(request))
    return render(request, 'core/productos_list.html', ctx)


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

        if not nombre or precio_raw is None or stock_raw is None:
            messages.error(request, 'Nombre, precio y stock son obligatorios.')
        else:
            try:
                precio = Decimal(precio_raw).quantize(Decimal('0.01'))
                stock = int(stock_raw)
                max_precio = Decimal('9999999.99')  # max 7 digitos (parte entera)
                max_stock = 9999999  # max 7 digitos
                if precio < 0 or stock < 0 or precio > max_precio or stock > max_stock:
                    raise ValueError
            except (InvalidOperation, ValueError):
                messages.error(request, 'Precio o stock invalidos o demasiado altos.')
                return render(request, 'core/producto_form.html', {'categorias': categorias, **_low_stock_context(request)})

            categoria_obj = None
            if categoria_id:
                categoria_obj = get_object_or_404(Categoria, id=categoria_id)

            Producto.objects.create(
                nombre=nombre,
                descripcion=descripcion,
                precio=precio,
                stock=stock,
                categoria=categoria_obj,
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
        },
        **_low_stock_context(request),
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
            precio_raw = request.POST.get('precio')
            stock_raw = request.POST.get('stock')
            max_precio = Decimal('9999999.99')
            max_stock = 9999999

            producto.precio = Decimal(precio_raw).quantize(Decimal('0.01'))
            producto.stock = int(stock_raw)
            if producto.precio < 0 or producto.stock < 0 or producto.precio > max_precio or producto.stock > max_stock:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, 'Precio o stock invalidos o demasiado altos.')
            return render(request, 'core/producto_form.html', {'producto': producto, 'categorias': categorias, **_low_stock_context(request)})

        categoria_id = request.POST.get('categoria') or None
        producto.categoria_id = categoria_id if categoria_id else None
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
            'categoria': request.POST.get('categoria', producto.categoria_id if producto.categoria_id else ''),
            'precio': request.POST.get('precio', producto.precio),
            'stock': request.POST.get('stock', producto.stock),
            'descripcion': request.POST.get('descripcion', producto.descripcion),
        },
        **_low_stock_context(request),
    })


@admin_required
@csrf_protect
def producto_delete(request, id):
    if request.method != 'POST':
        messages.error(request, 'Operacion no permitida.')
        return redirect('productos_list')
    producto = get_object_or_404(Producto, id=id)
    producto.activo = False
    producto.save(update_fields=['activo'])

    # Rechaza pedidos abiertos que incluyan este producto descontinuado
    motivo_rechazo = 'Producto descontinuado.'
    pedidos_afectados = (
        Pedido.objects
        .filter(detalles__producto=producto)
        .exclude(estado__in=['rechazado', 'finalizado'])
        .distinct()
    )
    rechazados = 0
    with transaction.atomic():
        for pedido in pedidos_afectados:
            pedido.estado = 'rechazado'
            pedido.motivo_rechazo = motivo_rechazo
            pedido.save(update_fields=['estado', 'motivo_rechazo'])
            HistorialCliente.objects.create(
                nombre=pedido.nombre_cliente,
                correo=pedido.correo,
                accion=f'Pedido {pedido.id} -> rechazado por producto descontinuado'
            )
            rechazados += 1

    if rechazados:
        messages.warning(request, f'Se rechazaron {rechazados} pedidos abiertos asociados a este producto (motivo: {motivo_rechazo}).')
    messages.success(request, 'Producto deshabilitado. Ya no aparecera en el catalogo.')
    return redirect('productos_list')


@admin_required
@csrf_protect
def producto_habilitar(request, id):
    if request.method != 'POST':
        messages.error(request, 'Operacion no permitida.')
        return redirect('productos_list')
    producto = get_object_or_404(Producto, id=id)
    producto.activo = True
    producto.save(update_fields=['activo'])
    messages.success(request, 'Producto habilitado nuevamente.')
    return redirect('productos_list')


# ------------------- PEDIDOS -------------------

@admin_required
def pedidos_list(request):
    pedido_id = (request.GET.get('pedido_id') or '').strip()
    estado = (request.GET.get('estado') or 'todos').strip()
    fecha_desde_raw = (request.GET.get('desde') or '').strip()
    fecha_hasta_raw = (request.GET.get('hasta') or '').strip()

    pedidos_qs = Pedido.objects.all()
    if pedido_id:
        try:
            pid = int(pedido_id)
            pedidos_qs = pedidos_qs.filter(id=pid)
        except ValueError:
            pedidos_qs = pedidos_qs.none()

    # Filtro por estado
    estados_validos = {'pendiente', 'en_proceso', 'finalizado', 'rechazado', 'todos'}
    if estado not in estados_validos:
        estado = 'todos'
    if estado != 'todos':
        pedidos_qs = pedidos_qs.filter(estado=estado)

    # Filtro por rango de fechas (inclusive)
    fecha_desde = fecha_hasta = None
    if fecha_desde_raw:
        try:
            fecha_desde = datetime.strptime(fecha_desde_raw, '%Y-%m-%d').date()
            pedidos_qs = pedidos_qs.filter(fecha__gte=timezone.make_aware(datetime.combine(fecha_desde, dt_time.min)))
        except ValueError:
            messages.error(request, 'Fecha desde inválida.')
            fecha_desde = None

    if fecha_hasta_raw:
        try:
            fecha_hasta = datetime.strptime(fecha_hasta_raw, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Fecha hasta inválida.')
            fecha_hasta = None

    if fecha_desde and fecha_hasta:
        if fecha_hasta < fecha_desde:
            messages.error(request, 'La fecha hasta no puede ser anterior a la fecha desde.')
            fecha_hasta = None
        else:
            pedidos_qs = pedidos_qs.filter(fecha__lte=timezone.make_aware(datetime.combine(fecha_hasta, dt_time.max)))
    elif fecha_hasta:
        pedidos_qs = pedidos_qs.filter(fecha__lte=timezone.make_aware(datetime.combine(fecha_hasta, dt_time.max)))

    pedidos = list(pedidos_qs.order_by('-fecha'))
    total_pedidos = pedidos_qs.aggregate(total=Sum('total'))['total'] or Decimal('0')

    # Colecta identificadores presentes en la tabla de pedidos
    usernames = {p.nombre_cliente for p in pedidos if p.nombre_cliente}
    correos = {p.correo for p in pedidos if p.correo}

    # Índices para lookup rápido
    clientes = Cliente.objects.filter(Q(username__in=usernames) | Q(email__in=correos)) \
                              .values('username', 'email', 'bloqueado')
    block_by_user = {c['username']: c['bloqueado'] for c in clientes}
    block_by_mail = {c['email']: c['bloqueado'] for c in clientes}

    for p in pedidos:
        p.bloqueado = bool(block_by_user.get(p.nombre_cliente) or block_by_mail.get(p.correo))

    low_stock = _low_stock_context(request)

    return render(request, 'core/pedidos_list.html', {
        'pedidos': pedidos,
        'pedido_id': pedido_id,
        'estado': estado,
        'fecha_desde': fecha_desde_raw,
        'fecha_hasta': fecha_hasta_raw,
        'total_pedidos': total_pedidos,
        **low_stock,
    })


@admin_required
def ventas_panel(request):
    estado_pedido = (request.GET.get('estado_pedido') or 'todos').strip()
    estado_confeccion = (request.GET.get('estado_confeccion') or 'todos').strip()
    fecha_desde_raw = (request.GET.get('desde') or '').strip()
    fecha_hasta_raw = (request.GET.get('hasta') or '').strip()

    pedidos_qs = Pedido.objects.all()
    solicitudes_qs = SolicitudConfeccion.objects.all()

    estados_pedido_validos = {'pendiente', 'en_proceso', 'finalizado', 'rechazado', 'todos'}
    if estado_pedido not in estados_pedido_validos:
        estado_pedido = 'todos'
    if estado_pedido != 'todos':
        pedidos_qs = pedidos_qs.filter(estado=estado_pedido)

    estados_conf_validos = {value for value, _ in SolicitudConfeccion.ESTADO_CHOICES} | {'todos'}
    if estado_confeccion not in estados_conf_validos:
        estado_confeccion = 'todos'
    if estado_confeccion != 'todos':
        solicitudes_qs = solicitudes_qs.filter(estado=estado_confeccion)

    fecha_desde = fecha_hasta = None
    if fecha_desde_raw:
        try:
            fecha_desde = datetime.strptime(fecha_desde_raw, '%Y-%m-%d').date()
        except ValueError:
            fecha_desde = None
    if fecha_hasta_raw:
        try:
            fecha_hasta = datetime.strptime(fecha_hasta_raw, '%Y-%m-%d').date()
        except ValueError:
            fecha_hasta = None

    if fecha_desde and fecha_hasta:
        if fecha_hasta < fecha_desde:
            messages.error(request, 'La fecha hasta no puede ser anterior a la fecha desde.')
            fecha_hasta = None
        else:
            pedidos_qs = pedidos_qs.filter(fecha__range=(timezone.make_aware(datetime.combine(fecha_desde, dt_time.min)), timezone.make_aware(datetime.combine(fecha_hasta, dt_time.max))))
            solicitudes_qs = solicitudes_qs.filter(fecha_creacion__range=(timezone.make_aware(datetime.combine(fecha_desde, dt_time.min)), timezone.make_aware(datetime.combine(fecha_hasta, dt_time.max))))
    elif fecha_desde:
        pedidos_qs = pedidos_qs.filter(fecha__gte=timezone.make_aware(datetime.combine(fecha_desde, dt_time.min)))
        solicitudes_qs = solicitudes_qs.filter(fecha_creacion__gte=timezone.make_aware(datetime.combine(fecha_desde, dt_time.min)))
    elif fecha_hasta:
        pedidos_qs = pedidos_qs.filter(fecha__lte=timezone.make_aware(datetime.combine(fecha_hasta, dt_time.max)))
        solicitudes_qs = solicitudes_qs.filter(fecha_creacion__lte=timezone.make_aware(datetime.combine(fecha_hasta, dt_time.max)))

    pedidos = list(pedidos_qs.order_by('-fecha')[:50])
    solicitudes = list(solicitudes_qs.order_by('-fecha_creacion')[:50])

    total_pedidos = pedidos_qs.aggregate(total=Sum('total'))['total'] or Decimal('0')
    total_cotizaciones = solicitudes_qs.aggregate(total=Sum('cotizacion_monto'))['total'] or Decimal('0')
    ventas_totales = (total_pedidos or Decimal('0')) + (total_cotizaciones or Decimal('0'))

    ctx = {
        'pedidos': pedidos,
        'solicitudes': solicitudes,
        'total_pedidos': total_pedidos,
        'total_cotizaciones': total_cotizaciones,
        'ventas_totales': ventas_totales,
        'estado_pedido': estado_pedido,
        'estado_confeccion': estado_confeccion,
        'fecha_desde': fecha_desde_raw,
        'fecha_hasta': fecha_hasta_raw,
    }
    ctx.update(_low_stock_context(request))
    return render(request, 'core/ventas.html', ctx)

@admin_required
def pedido_detalle(request, id):
    pedido = get_object_or_404(Pedido, id=id)
    detalles = pedido.detalles.all()
    pedido.boleta_url = _boleta_pedido(pedido)

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

    low_stock = _low_stock_context(request)

    return render(request, 'core/pedido_detalle.html', {
        'pedido': pedido,
        'detalles': detalles,
        'bloqueado': bloqueado,
        **low_stock,
    })


# ------------------- SOLICITUDES DE CONFECCIÓN (ADMIN) -------------------

@admin_required
def solicitudes_confeccion_list(request):
    """
    Lista todas las solicitudes de confección para el panel de administración.
    """
    estado = (request.GET.get('estado') or 'todos').strip()
    fecha_desde_raw = (request.GET.get('desde') or '').strip()
    fecha_hasta_raw = (request.GET.get('hasta') or '').strip()
    solicitud_id = (request.GET.get('solicitud_id') or '').strip()

    solicitudes_qs = SolicitudConfeccion.objects.all()

    if solicitud_id:
        try:
            sid = int(solicitud_id)
            solicitudes_qs = solicitudes_qs.filter(id=sid)
        except ValueError:
            solicitudes_qs = solicitudes_qs.none()

    estados_validos = {value for value, _ in SolicitudConfeccion.ESTADO_CHOICES} | {'todos'}
    if estado not in estados_validos:
        estado = 'todos'
    if estado != 'todos':
        solicitudes_qs = solicitudes_qs.filter(estado=estado)

    fecha_desde = fecha_hasta = None
    if fecha_desde_raw:
        try:
            fecha_desde = datetime.strptime(fecha_desde_raw, '%Y-%m-%d').date()
            solicitudes_qs = solicitudes_qs.filter(fecha_creacion__gte=timezone.make_aware(datetime.combine(fecha_desde, dt_time.min)))
        except ValueError:
            messages.error(request, 'Fecha desde inválida.')
            fecha_desde = None

    if fecha_hasta_raw:
        try:
            fecha_hasta = datetime.strptime(fecha_hasta_raw, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Fecha hasta inválida.')
            fecha_hasta = None

    if fecha_desde and fecha_hasta:
        if fecha_hasta < fecha_desde:
            messages.error(request, 'La fecha hasta no puede ser anterior a la fecha desde.')
            fecha_hasta = None
        else:
            solicitudes_qs = solicitudes_qs.filter(fecha_creacion__lte=timezone.make_aware(datetime.combine(fecha_hasta, dt_time.max)))
    elif fecha_hasta:
        solicitudes_qs = solicitudes_qs.filter(fecha_creacion__lte=timezone.make_aware(datetime.combine(fecha_hasta, dt_time.max)))

    solicitudes = list(solicitudes_qs.order_by('-fecha_creacion'))
    total_cotizaciones = solicitudes_qs.aggregate(total=Sum('cotizacion_monto'))['total'] or Decimal('0')

    low_stock = _low_stock_context(request)

    return render(request, 'core/solicitudes_confeccion_list.html', {
        'solicitudes': solicitudes,
        'estado': estado,
        'fecha_desde': fecha_desde_raw,
        'fecha_hasta': fecha_hasta_raw,
        'solicitud_id': solicitud_id,
        'total_cotizaciones': total_cotizaciones,
        **low_stock,
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

    ctx = {
        'clientes': clientes_qs,
        'historial': historial,
        'selected_cliente': selected,
        'search': search,
    }
    ctx.update(_low_stock_context(request))
    return render(request, 'core/historial_clientes.html', ctx)


@admin_required
@csrf_protect
def solicitud_confeccion_detalle(request, id):
    solicitud = get_object_or_404(SolicitudConfeccion, id=id)
    solicitud.boleta_url = _boleta_confeccion(solicitud)
    edicion_bloqueada = solicitud.estado in ('aceptado', 'cancelado')

    if request.method == 'POST':
        if edicion_bloqueada:
            messages.error(request, 'La solicitud ya fue finalizada por el cliente y no se puede editar.')
            return redirect('solicitud_confeccion_detalle', id=solicitud.id)

        nuevo_estado = (request.POST.get('estado') or solicitud.estado).strip()
        observaciones = (request.POST.get('observaciones_admin') or '').strip()
        cotizacion_raw = request.POST.get('cotizacion_monto')

        # lista clara de valores válidos
        estados_validos = [value for value, _ in SolicitudConfeccion.ESTADO_CHOICES]

        if nuevo_estado not in estados_validos:
            messages.error(request, 'Estado inválido.')
        elif nuevo_estado in ('aceptado', 'cancelado'):
            messages.error(request, 'Este estado lo define el cliente al aceptar o rechazar la cotización.')
        else:
            if nuevo_estado == 'cotizado':
                try:
                    precio = Decimal(cotizacion_raw).quantize(Decimal('0.01'))
                    if precio <= 0:
                        raise ValueError
                except Exception:
                    messages.error(request, 'Debes ingresar un monto válido para la cotización.')
                    return render(request, 'core/solicitud_confeccion_detalle.html', {
                        'solicitud': solicitud,
                        'estados': SolicitudConfeccion.ESTADO_CHOICES,
                        'edicion_bloqueada': edicion_bloqueada,
                    })
                solicitud.cotizacion_monto = precio
                solicitud.cotizacion_aceptada = None

            solicitud.estado = nuevo_estado
            solicitud.observaciones_admin = observaciones
            solicitud.save()
            messages.success(request, 'Solicitud actualizada correctamente.')
            return redirect('solicitud_confeccion_detalle', id=solicitud.id)

    low_stock = _low_stock_context(request)

    return render(request, 'core/solicitud_confeccion_detalle.html', {
        'solicitud': solicitud,
        'estados': SolicitudConfeccion.ESTADO_CHOICES,
        'edicion_bloqueada': edicion_bloqueada,
        **low_stock,
    })


@login_required
@require_POST
@csrf_protect
def respuesta_cotizacion(request, id):
    solicitud = get_object_or_404(SolicitudConfeccion, id=id)

    # Sólo el dueño de la solicitud (por FK o por correo) puede responder
    if solicitud.cliente_id and solicitud.cliente_id != request.user.id:
        messages.error(request, 'No puedes responder esta cotización.')
        return redirect('mis_solicitudes_confeccion')
    if not solicitud.cliente_id and solicitud.correo != request.user.email:
        messages.error(request, 'No puedes responder esta cotización.')
        return redirect('mis_solicitudes_confeccion')

    if solicitud.estado != 'cotizado' or not solicitud.cotizacion_monto:
        messages.error(request, 'Esta solicitud no está en estado cotizado.')
        return redirect('mis_solicitudes_confeccion')

    decision = request.POST.get('decision')
    if decision not in ['aceptar', 'rechazar']:
        messages.error(request, 'Acción inválida.')
        return redirect('mis_solicitudes_confeccion')

    if decision == 'aceptar':
        solicitud.estado = 'aceptado'
        solicitud.cotizacion_aceptada = True
        messages.success(request, 'Has aceptado la cotización.')
    else:
        solicitud.estado = 'cancelado'
        solicitud.cotizacion_aceptada = False
        messages.success(request, 'Has rechazado la cotización. La solicitud fue cancelada.')

    solicitud.save()
    return redirect('mis_solicitudes_confeccion')


# ------------------- CARRITO -------------------

@require_POST
@csrf_protect
def agregar_al_carrito(request, id):
    if request.user.is_authenticated and getattr(request.user, 'bloqueado', False):
        return JsonResponse({'ok': False, 'error': 'bloqueado'}, status=403)
    
    try:
        Producto.objects.get(id=id, activo=True)
    except Producto.DoesNotExist:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('accept', '').find('application/json') != -1:
            return JsonResponse({'ok': False, 'error': 'no_disponible'}, status=404)
        messages.error(request, 'El producto no esta disponible.')
        return redirect('catalogo')

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
def actualizar_cantidad_carrito(request, id):
    """
    Permite modificar la cantidad de un producto ya presente en el carrito.
    """
    carrito = request.session.get('carrito', {})
    key = str(id)

    if key not in carrito:
        messages.error(request, 'El producto no esta en tu carrito.')
        return redirect('ver_carrito')

    try:
        cantidad = int(request.POST.get('cantidad', carrito[key]))
    except (TypeError, ValueError):
        messages.error(request, 'Cantidad invalida.')
        return redirect('ver_carrito')

    if cantidad < 1:
        messages.error(request, 'La cantidad debe ser al menos 1.')
        return redirect('ver_carrito')

    carrito[key] = cantidad
    request.session['carrito'] = carrito
    messages.success(request, 'Cantidad actualizada.')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('accept', '').find('application/json') != -1:
        return JsonResponse({'ok': True, 'count': _cart_count(request)})

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
        try:
            producto = Producto.objects.get(id=id)
        except Producto.DoesNotExist:
            allow_checkout = False
            faltantes.append({
                'nombre': f'Producto #{id} no disponible',
                'disponible': 0,
                'cantidad': cantidad,
            })
            productos.append({
                'id': id,
                'nombre': 'Producto no disponible',
                'precio': Decimal('0'),
                'cantidad': cantidad,
                'subtotal': Decimal('0'),
                'imagen': '',
                'stock_ok': False,
                'stock': 0,
                'activo': False,
            })
            continue

        subtotal = producto.precio * cantidad
        total += subtotal
        stock_ok = producto.stock >= cantidad
        activo_ok = producto.activo
        if not stock_ok or not activo_ok:
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
            'activo': activo_ok,
            'comprable': stock_ok and activo_ok,
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
        try:
            prod = Producto.objects.get(id=pid)
        except Producto.DoesNotExist:
            messages.error(request, 'Hay productos no disponibles en tu carrito.')
            return redirect('ver_carrito')

        if not prod.activo:
            messages.error(request, f'El producto "{prod.nombre}" esta deshabilitado y no puede comprarse.')
            return redirect('ver_carrito')
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
                try:
                    prod = Producto.objects.select_for_update().get(id=pid)
                except Producto.DoesNotExist:
                    faltantes.append((f'Producto #{pid} no disponible', 0, cantidad))
                    continue

                if not prod.activo:
                    faltantes.append((f'{prod.nombre} (deshabilitado)', prod.stock, cantidad))
                    continue

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
    for p in pedidos:
        p.boleta_url = _boleta_pedido(p)

    return render(request, 'core/mis_pedidos.html', {
        'pedidos': pedidos,
        'cart_count': _cart_count(request)
    })


@login_required
def mis_solicitudes_confeccion(request):
    solicitudes = SolicitudConfeccion.objects.filter(
        Q(cliente=request.user) |
        Q(cliente__isnull=True, correo=request.user.email)
    ).order_by('-fecha_creacion')
    for s in solicitudes:
        s.boleta_url = _boleta_confeccion(s)

    return render(request, 'core/mis_solicitudes_confeccion.html', {
        'solicitudes': solicitudes,
        'cart_count': _cart_count(request),
    })

# ------------------- Solicitud de confeccion -------------------

@csrf_protect
def solicitud_confeccion(request):
    """
    Vista para que el cliente envíe una solicitud de confección a medida.
    Si el usuario está autenticado, se pre-rellena nombre, correo y teléfono.
    """
    if request.session.get('admin_id'):
        messages.info(request, 'Los administradores solo pueden revisar solicitudes desde el panel.')
        return redirect('solicitudes_confeccion_list')

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
        elif nueva.lower() == username.lower():
            messages.error(request, 'La contrasena no puede ser igual al nombre de usuario.')
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
    if request.method == 'POST':
        actual = (request.POST.get('password_actual') or '').strip()
        nueva = (request.POST.get('password1') or '').strip()
        confirm = (request.POST.get('password2') or '').strip()

        if not request.user.check_password(actual):
            messages.error(request, 'La contrasena actual es incorrecta.')
            return render(request, 'core/cambiar_password.html')

        if len(nueva) < 3:
            messages.error(request, 'La contrasena debe tener al menos 3 caracteres.')
            return render(request, 'core/cambiar_password.html')
        elif nueva.lower() == request.user.username.lower():
            messages.error(request, 'La contrasena no puede ser igual al nombre de usuario.')
            return render(request, 'core/cambiar_password.html')
        elif nueva != confirm:
            messages.error(request, 'Las contrasenas no coinciden.')
            return render(request, 'core/cambiar_password.html')

        request.user.set_password(nueva)
        request.user.save()
        messages.success(request, 'Contrasena actualizada. Vuelve a iniciar sesion.')
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
            phone = validar_telefono_formato(phone)
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, 'core/forgot_password_verify.html', {'username': username})
        if not phone:
            messages.error(request, 'Ingresa tu número con formato +569XXXXXXXX.')
            return render(request, 'core/forgot_password_verify.html', {'username': username})
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
            messages.error(request, 'La contrasena debe tener al menos 3 caracteres.')
        elif p1.lower() == username.lower():
            messages.error(request, 'La contrasena no puede ser igual al nombre de usuario.')
        elif p1 != p2:
            messages.error(request, 'Las contrasenas no coinciden.')
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
