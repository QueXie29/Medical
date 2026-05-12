import logging
import random
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.contrib.auth.views import LogoutView as DjangoLogoutView
from django.contrib.auth.views import PasswordChangeView
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django.views.generic import CreateView, TemplateView
from django.contrib.auth.password_validation import validate_password as validate_user_password

from core.forms import (
    EmailOrUsernameAuthenticationForm,
    PatientPortalPasswordChangeForm,
    PatientRegistrationForm,
)
from core.models import EmailVerifyRecord, OperationLog, User, UserRole
from core.utils import record_operation_log

logger = logging.getLogger(__name__)

EMAIL_VERIFY_SEND_COOLDOWN_SECONDS = 60
EMAIL_VERIFY_HOURLY_MAX_PER_EMAIL = 10


class RoleBasedHomeView(View):
    """
    根路径 / 智能分发：未登录去登录页；已登录按 role 进入对应工作台。
    患者门户大厅在 /portal/（IndexView），供患者导航与未登录浏览。
    """

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                next=request.get_full_path(),
                login_url=settings.LOGIN_URL,
            )
        user = request.user
        role = getattr(user, "role", None)
        if user.is_superuser or role == UserRole.ADMIN:
            return redirect("core:admin_dashboard")
        if role == UserRole.DOCTOR:
            return redirect("core:doctor_dashboard")
        if role == UserRole.NURSE:
            return redirect("core:nurse_triage_list")
        if role == UserRole.HEAD_NURSE:
            return redirect("core:headnurse_dashboard")
        return redirect("core:index")


class IndexView(TemplateView):
    """患者门户大厅（/portal/），可与患者端导航「大厅」对应。"""

    template_name = "patient/lobby.html"


@method_decorator(csrf_protect, name="dispatch")
class SendEmailVerifyCodeView(View):
    """向邮箱发送 6 位数字验证码（POST，带防刷）。POST 参数 `action`：register（注册）或 reset（找回密码）。"""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("email") or "").strip()
        action = (request.POST.get("action") or "register").strip() or "register"
        if not email:
            return JsonResponse({"status": "error", "msg": "请填写邮箱"}, status=400)
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({"status": "error", "msg": "邮箱格式不正确"}, status=400)

        norm = email.lower()
        if action == "register" and User.objects.filter(email__iexact=norm).exists():
            return JsonResponse(
                {"status": "error", "msg": "该邮箱已被注册"},
                status=400,
            )
        if action == "reset" and not User.objects.filter(email__iexact=norm).exists():
            return JsonResponse(
                {
                    "status": "error",
                    "msg": "未找到该邮箱绑定的账号，请检查输入",
                },
                status=400,
            )

        now = timezone.now()
        latest = (
            EmailVerifyRecord.objects.filter(email=norm).order_by("-created_at").first()
        )
        if latest and (now - latest.created_at).total_seconds() < EMAIL_VERIFY_SEND_COOLDOWN_SECONDS:
            return JsonResponse(
                {"status": "error", "msg": "发送过于频繁，请稍后再试"},
                status=429,
            )

        hour_ago = now - timedelta(hours=1)
        recent_count = EmailVerifyRecord.objects.filter(
            email=norm, created_at__gte=hour_ago
        ).count()
        if recent_count >= EMAIL_VERIFY_HOURLY_MAX_PER_EMAIL:
            return JsonResponse(
                {"status": "error", "msg": "该邮箱请求次数过多，请一小时后再试"},
                status=429,
            )

        code = str(random.randint(100000, 999999))
        EmailVerifyRecord.objects.create(email=norm, code=code)

        mail_subject = (
            "智慧医疗系统 - 密码重置验证码"
            if action == "reset"
            else "智慧医疗系统 - 注册验证码"
        )
        mail_body = (
            f"您正在重置登录密码。验证码：{code}，5分钟内有效。如非本人操作请忽略。"
            if action == "reset"
            else f"您的验证码是：{code}，5分钟内有效。"
        )
        try:
            send_mail(
                subject=mail_subject,
                message=mail_body,
                from_email=None,
                recipient_list=[norm],
                fail_silently=False,
            )
        except Exception:
            logger.exception("send_mail failed for registration verify code")
            return JsonResponse(
                {"status": "error", "msg": "邮件发送失败，请稍后再试"},
                status=503,
            )

        return JsonResponse({"status": "success", "msg": "发送成功"})


@method_decorator(csrf_protect, name="dispatch")
class ForgotPasswordView(View):
    """通过邮箱验证码重置登录密码（无需登录）。"""

    http_method_names = ["get", "post"]

    def get(self, request, *args, **kwargs):
        return render(request, "core/auth/forgot_password.html")

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("email") or "").strip().lower()
        verify_code = (request.POST.get("verify_code") or "").strip()
        new_password = request.POST.get("new_password") or ""

        if not email or not verify_code or not new_password:
            return JsonResponse(
                {"status": "error", "msg": "请完整填写邮箱、验证码与新密码。"},
                status=400,
            )

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return JsonResponse(
                {"status": "error", "msg": "未找到该邮箱绑定的账号。"},
                status=400,
            )

        latest = (
            EmailVerifyRecord.objects.filter(email=email)
            .order_by("-created_at")
            .first()
        )
        if not latest or latest.code != verify_code:
            return JsonResponse(
                {"status": "error", "msg": "验证码不正确。"},
                status=400,
            )
        if timezone.now() - latest.created_at > timedelta(minutes=5):
            return JsonResponse(
                {"status": "error", "msg": "验证码已过期"},
                status=400,
            )

        try:
            validate_user_password(new_password, user=user)
        except ValidationError as exc:
            msgs = getattr(exc, "messages", None) or [str(exc)]
            return JsonResponse(
                {"status": "error", "msg": " ".join(msgs)},
                status=400,
            )

        user.set_password(new_password)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        record_operation_log(
            request,
            "UPDATE",
            "账号安全",
            f"患者 {user.real_name or user.username} 通过邮箱验证码重置了登录密码",
            actor=user,
        )
        latest.delete()
        return JsonResponse({"status": "success", "msg": "密码重置成功！"})


class RegisterView(CreateView):
    form_class = PatientRegistrationForm
    template_name = "core/auth/register.html"
    success_url = reverse_lazy("core:login")

    def form_valid(self, form):
        email = (form.cleaned_data.get("email") or "").strip().lower()
        response = super().form_valid(form)
        if email:
            EmailVerifyRecord.objects.filter(email=email).delete()
        user = self.object
        label = (getattr(user, "real_name", None) or "").strip() or user.username
        record_operation_log(
            self.request,
            OperationLog.ActionType.CREATE,
            "患者注册",
            f"新患者 {label} 注册了账号",
            actor=user,
        )
        messages.success(self.request, "注册成功，请登录。")
        return response


class LoginView(DjangoLoginView):
    template_name = "core/auth/login.html"
    authentication_form = EmailOrUsernameAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        label = (getattr(user, "real_name", None) or "").strip() or user.username
        record_operation_log(
            self.request,
            OperationLog.ActionType.LOGIN,
            "系统认证",
            f"{label} 登录了系统",
        )
        return response

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        if redirect_to:
            return redirect_to
        return reverse("core:home")


class LogoutView(DjangoLogoutView):
    next_page = reverse_lazy("core:login")


class ChangeInitialPasswordView(PasswordChangeView):
    form_class = PatientPortalPasswordChangeForm
    template_name = "core/auth/change_initial_password.html"
    success_url = reverse_lazy("core:home")

    def get_template_names(self):
        user = self.request.user
        if getattr(user, "role", None) == UserRole.PATIENT:
            return ["patient/force_password.html"]
        return [self.template_name]

    def get_success_url(self):
        return reverse("core:home")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        messages.success(self.request, "密码已更新。")
        return response
