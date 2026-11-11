"""
Django settings for Medical project.

MySQL、静态文件与模板路径见下方配置；敏感项建议通过环境变量注入。
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_local_env():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_local_env()

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-change-me-in-development-only",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() in ("1", "true", "yes")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "Medical.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.hospital_portal",
            ],
        },
    },
]

WSGI_APPLICATION = "Medical.wsgi.application"

# MySQL 8.x utf8mb4（可通过环境变量覆盖）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE", "medical"),
        "USER": os.environ.get("MYSQL_USER", "root"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", "123456"),
        "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "zh-hans"

TIME_ZONE = "Asia/Shanghai"

USE_I18N = True

USE_TZ = True

# ---------------------------------------------------------------------------
# 邮件（QQ 邮箱 SMTP，用于注册验证码等）
# 1. 登录 QQ 邮箱网页版 → 设置 → 账户 → 开启 POP3/SMTP 服务
# 2. 按提示生成「授权码」（不是 QQ 登录密码），填入环境变量 QQ_EMAIL_AUTH_CODE
# 3. Windows PowerShell 示例（当前会话）：
#    $env:QQ_EMAIL = "你的QQ号@qq.com"
#    $env:QQ_EMAIL_AUTH_CODE = "xxxxxxxxxxxxxxxx"
# ---------------------------------------------------------------------------
QQ_EMAIL = os.environ.get("QQ_EMAIL", "").strip()
QQ_EMAIL_AUTH_CODE = os.environ.get("QQ_EMAIL_AUTH_CODE", "").strip()

if QQ_EMAIL and QQ_EMAIL_AUTH_CODE:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.qq.com"
    EMAIL_PORT = 465
    EMAIL_USE_SSL = True
    EMAIL_USE_TLS = False
    EMAIL_HOST_USER = QQ_EMAIL
    EMAIL_HOST_PASSWORD = QQ_EMAIL_AUTH_CODE
    DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", QQ_EMAIL)
    SERVER_EMAIL = DEFAULT_FROM_EMAIL
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "webmaster@localhost")
    SERVER_EMAIL = DEFAULT_FROM_EMAIL

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.User"

AUTHENTICATION_BACKENDS = [
    "core.backends.EmailOrUsernameModelBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "/accounts/login/"
# 与 core.urls 中 path("", …, name="home") 一致；登录后默认进入 RoleBasedHomeView 再做角色分发
LOGIN_REDIRECT_URL = "/"

# DeepSeek Chat API（OpenAI 兼容，见 https://api.deepseek.com ）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_API_BASE = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_TIMEOUT = int(os.environ.get("DEEPSEEK_TIMEOUT", "120"))
