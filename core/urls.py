from django.urls import path
from . import views

urlpatterns = [
    # Pagina principal
    path('', views.home, name='home'),

    # Catálogo y compras
    path('catalogo/', views.catalogo, name='catalogo'),
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('carrito/agregar/<int:id>/', views.agregar_al_carrito, name='agregar_al_carrito'),
    path('carrito/actualizar/<int:id>/', views.actualizar_cantidad_carrito, name='actualizar_cantidad_carrito'),
    path('carrito/eliminar/<int:id>/', views.eliminar_del_carrito, name='eliminar_del_carrito'),
    path('pedido/confirmar/', views.confirmar_pedido, name='confirmar_pedido'),
    path('mis-pedidos/', views.mis_pedidos, name='mis_pedidos'),
    path('mis-solicitudes-confeccion/', views.mis_solicitudes_confeccion, name='mis_solicitudes_confeccion'),
    path('mis-solicitudes-confeccion/<int:id>/respuesta/', views.respuesta_cotizacion, name='respuesta_cotizacion'),
    path('confeccion/', views.solicitud_confeccion, name='solicitud_confeccion'),

    # Registro y login unificados
    path('registro/', views.registro_cliente, name='registro_cliente'),
    path('login/', views.login_unificado, name='login_unificado'),
    path('logout/', views.logout_unificado, name='logout_unificado'),

    # Panel del administrador
    path('admin/login/', views.admin_login, name='admin_login'),
    path('panel/', views.admin_dashboard, name='admin_dashboard'),
    path('panel/dashboard/', views.admin_dashboard, name='admin_dashboard'),

    # Panel del administrador CATEGORIAS
    path('panel/categorias/', views.categorias_list, name='categorias_list'),
    path('panel/categorias/nueva/', views.categoria_create, name='categoria_create'),
    path('panel/categorias/editar/<int:id>/', views.categoria_edit, name='categoria_edit'),
    path('panel/categorias/eliminar/<int:id>/', views.categoria_delete, name='categoria_delete'),
    
    # Panel del administrador PRODUCTOS
    path('panel/productos/', views.productos_list, name='productos_list'),
    path('panel/productos/nuevo/', views.producto_create, name='producto_create'),
    path('panel/productos/editar/<int:id>/', views.producto_edit, name='producto_edit'),
    path('panel/productos/habilitar/<int:id>/', views.producto_habilitar, name='producto_habilitar'),
    path('panel/productos/eliminar/<int:id>/', views.producto_delete, name='producto_delete'),
    path('panel/ventas/', views.ventas_panel, name='ventas_panel'),

    # Panel del administrador PEDIDOS
    path('panel/pedidos/', views.pedidos_list, name='pedidos_list'),
    path('panel/pedidos/<int:id>/', views.pedido_detalle, name='pedido_detalle'),

    # CLIENTE
    path('perfil/', views.editar_perfil, name='editar_perfil'),
    
    # ADMIN CLIENTES
    path('panel/clientes/', views.clientes_list, name='clientes_list'),
    path('panel/clientes/bloquear/<int:id>/', views.cliente_bloquear, name='cliente_bloquear'),
    path('panel/clientes/desbloquear/<int:id>/', views.cliente_desbloquear, name='cliente_desbloquear'),
    path('panel/clientes/eliminar/<int:id>/', views.cliente_eliminar, name='cliente_eliminar'),
    path('panel/historial-clientes/', views.historial_clientes, name='historial_clientes'),

    path('password/solicitar/', views.solicitar_codigo_password, name='solicitar_codigo_password'),
    path('password/restablecer/', views.restablecer_password, name='restablecer_password'),
    path('perfil/cambiar-password/', views.cambiar_password_por_usuario_correo, name='cambiar_password_por_usuario_correo'),
    path('password/olvidada/', views.forgot_password_username, name='forgot_password_username'),
    path('password/olvidada/verificar/', views.forgot_password_verify, name='forgot_password_verify'),
    path('password/olvidada/nueva/', views.forgot_password_reset, name='forgot_password_reset'),

     # ADMIN SOLICITUDES DE CONFECCIÓN
    path('panel/solicitudes-confeccion/', views.solicitudes_confeccion_list, name='solicitudes_confeccion_list'),
    path('panel/solicitudes-confeccion/<int:id>/', views.solicitud_confeccion_detalle, name='solicitud_confeccion_detalle'),

    # Config alertas stock
    path('panel/alertas/stock/', views.set_low_stock_threshold, name='set_low_stock_threshold'),
]
