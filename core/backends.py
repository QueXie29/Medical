"""自定义认证：支持使用用户名或电子邮箱登录。"""

from __future__ import annotations

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class EmailOrUsernameModelBackend(ModelBackend):
    """
    登录时 `username` 字段可填用户名或邮箱：
    - 含 `@` 时按邮箱（不区分大小写）匹配；
    - 否则按用户名精确匹配。
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        username = str(username).strip()
        if not username:
            return None

        if "@" in username:
            user = User.objects.filter(email__iexact=username).first()
        else:
            user = User.objects.filter(username=username).first()

        if user is None:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
