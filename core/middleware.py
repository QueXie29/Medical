from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve


def _static_media_exempt(path: str) -> bool:
    su = settings.STATIC_URL or ""
    mu = settings.MEDIA_URL or ""
    prefixes = []
    for u in (su, mu):
        u = u.strip()
        if not u:
            continue
        if not u.startswith("/"):
            u = "/" + u
        prefixes.append(u)
    return any(path.startswith(p) for p in prefixes)


_EXEMPT_ROUTE_KEYS = frozenset(
    {
        "core:change_initial_password",
        "core:logout",
        "admin:logout",
    }
)


def _is_exempt_route(request) -> bool:
    """用 path_info 解析路由名，避免 reverse 与 request.path 不一致导致无法进入改密页。"""
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return False
    ns = (match.namespace or "").strip()
    name = match.url_name or ""
    key = f"{ns}:{name}" if ns else name
    return key in _EXEMPT_ROUTE_KEYS


class ForcePasswordChangeMiddleware:
    """
    已登录且 must_change_password=True 时，除改密与登出外一律重定向到改密页。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_redirect(request):
            return redirect("core:change_initial_password")
        return self.get_response(request)

    def _should_redirect(self, request) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if not getattr(user, "must_change_password", False):
            return False
        path = request.path
        if _static_media_exempt(path):
            return False
        if _is_exempt_route(request):
            return False
        return True
