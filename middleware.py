
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve

ALLOWED_FOR_BLOCKED = {
    'home', 'catalogo',
    'login_unificado', 'logout_unificado', 'registro_cliente',
}

class BlockedUserRestrictionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/static/') or request.path.startswith('/media/') or request.path.startswith('/admin/'):
            return self.get_response(request)

        user = getattr(request, 'user', None)
        if user and user.is_authenticated and getattr(user, 'bloqueado', False):
            try:
                match = resolve(request.path)
                url_name = match.url_name
            except Exception:
                url_name = None

            if url_name not in ALLOWED_FOR_BLOCKED:
                messages.error(request, 'Tu cuenta está bloqueada. Solo puedes ver el catálogo.')
                return redirect('catalogo')

        return self.get_response(request)
