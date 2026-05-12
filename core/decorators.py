from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from core.models import UserRole


def _reject_role():
    raise PermissionDenied("无权访问该功能。")


def role_required(*roles, allow_superuser=True):
    """
    仅允许指定 role 的用户访问；未登录跳转登录页。
    allow_superuser=True 时 Django 超级用户可通行（便于运维）。
    """

    roles = tuple(roles)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if allow_superuser and request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if getattr(request.user, "role", None) not in roles:
                _reject_role()
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def admin_required(view_func):
    """
    系统管理员角色或 Django 超级用户；未登录跳转登录页，否则 403。
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        if getattr(request.user, "role", None) != UserRole.ADMIN:
            _reject_role()
        return view_func(request, *args, **kwargs)

    return _wrapped


doctor_required = role_required(UserRole.DOCTOR)
nurse_required = role_required(UserRole.NURSE)
headnurse_required = role_required(UserRole.HEAD_NURSE)
patient_required = role_required(UserRole.PATIENT)

# 医疗供应链：管理员与护士长共用（生产厂家、药品入库等）
admin_or_headnurse_required = role_required(UserRole.ADMIN, UserRole.HEAD_NURSE)
