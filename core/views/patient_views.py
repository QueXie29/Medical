import json
import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.views import PasswordChangeView
from django.db import transaction
from django.db.models import Count, Min, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import (
    DeleteView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from core.decorators import patient_required
from core.forms import (
    AppointmentBookForm,
    PatientPortalPasswordChangeForm,
    PatientProfileForm,
)
from core.models import (
    AIReport,
    Appointment,
    Department,
    MedicalRecord,
    OperationLog,
    Order,
    Schedule,
    User,
    UserRole,
)
from core.utils import record_operation_log
from core.services.deepseek_service import DeepSeekService, DeepSeekServiceError

SESSION_KEY_AI_CHAT = "patient_ai_chat_messages"
MAX_CHAT_MESSAGES = 60


def _build_ai_report_title(structured: dict) -> str:
    """优先使用模型给出的 title；否则退回关键词逻辑 + 当前本地时间。"""
    t = (structured.get("title") or "").strip()
    if t:
        base = t[:80]
        now = timezone.localtime()
        return f"{base}-{now.strftime('%m月%d日 %H:%M')}"
    kw = (structured.get("symptom_keyword") or "").strip()
    if not (2 <= len(kw) <= 4):
        cc = (structured.get("chief_complaint") or "").replace("待补充", "").strip()
        kw = re.sub(r"[^\u4e00-\u9fff]", "", cc)[:4]
        if len(kw) < 2:
            kw = "预问诊"
        elif len(kw) > 4:
            kw = kw[:4]
    now = timezone.localtime()
    return f"{kw}-{now.strftime('%m月%d日 %H:%M')}"


def _build_patient_summary(structured: dict, chief_complaint: str, present_illness: str) -> str:
    """为旧模型响应或解析失败场景提供患者端兜底总结。"""
    patient_summary = (structured.get("patient_summary") or "").strip()
    if patient_summary:
        return patient_summary
    details = []
    if chief_complaint and chief_complaint != "待补充":
        details.append(chief_complaint)
    if present_illness and present_illness != "待补充":
        details.append(present_illness)
    if details:
        return (
            "根据您的描述，我们已将您提到的不适情况整理成就诊前小结："
            f"{'；'.join(details)}。建议您带着这份记录前往相应科室就诊，"
            "具体诊断和处理请以医生面诊及检查结果为准。"
        )
    return "根据您的描述，目前可整理的信息还不够完整。建议您继续补充不适部位、持续时间、加重或缓解因素等情况，并以线下医生面诊判断为准。"


def _schedule_effective_booked_count(schedule_id: int) -> int:
    """某条排班下、非已取消的预约数（号源按 Schedule 扣减）。"""
    return (
        Appointment.objects.filter(schedule_id=schedule_id)
        .exclude(status=Appointment.Status.CANCELLED)
        .count()
    )


@method_decorator(patient_required, name="dispatch")
class PatientDoctorListView(ListView):
    """找医生：可按科室筛选，展示主治医生卡片。"""

    template_name = "patient/doctor_list.html"
    context_object_name = "doctors"

    def get_queryset(self):
        today = timezone.localdate()
        qs = (
            User.objects.filter(role=UserRole.DOCTOR, is_active=True)
            .select_related("department")
            .annotate(
                min_booking_price=Min(
                    "doctor_schedules__price",
                    filter=Q(
                        doctor_schedules__work_date__gte=today,
                        doctor_schedules__is_active=True,
                    ),
                )
            )
            .order_by("department__name", "real_name", "username")
        )
        raw = self.request.GET.get("department", "").strip()
        if raw:
            try:
                qs = qs.filter(department_id=int(raw))
            except (TypeError, ValueError):
                pass
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["all_departments"] = Department.objects.filter(is_active=True).order_by(
            "name"
        )
        raw = self.request.GET.get("department", "").strip()
        ctx["selected_department_id"] = None
        if raw:
            try:
                ctx["selected_department_id"] = int(raw)
            except ValueError:
                pass
        return ctx


# 患者端挂号日历：时段键与表头（与 Schedule.shift 取值 morning / afternoon 一致）
PATIENT_BOOKING_SLOT_ROWS = (
    ("morning", "上午 (08-12时)"),
    ("afternoon", "下午 (14-18时)"),
)


def _patient_doctor_booking_grid_context(doctor: User) -> dict:
    """
    今日起 7 天的日期头 + 将排班按 (日期 ISO, 时段键) 填入矩阵。
    时段键：morning / afternoon，与 Schedule.Shift 一致。
    """
    today = timezone.localdate()
    end = today + timedelta(days=6)
    weekday_cn = "一二三四五六日"

    calendar_days = []
    for i in range(7):
        d = today + timedelta(days=i)
        calendar_days.append(
            {
                "date": d.isoformat(),
                "day_name": "周" + weekday_cn[d.weekday()],
                "date_short": d.strftime("%m/%d"),
            }
        )

    schedules = list(
        Schedule.objects.filter(
            doctor=doctor,
            is_active=True,
            work_date__gte=today,
            work_date__lte=end,
        )
        .select_related("department", "doctor", "doctor__department")
        .annotate(
            booked=Count(
                "appointments",
                filter=~Q(appointments__status=Appointment.Status.CANCELLED),
            )
        )
        .order_by("work_date", "shift", "department__name")
    )
    for s in schedules:
        s.remaining_slots = max(0, int(s.total_capacity) - int(s.booked))

    matrix = defaultdict(list)
    for s in schedules:
        d_iso = s.work_date.isoformat()
        if s.shift == Schedule.Shift.MORNING:
            matrix[(d_iso, "morning")].append(s)
        elif s.shift == Schedule.Shift.AFTERNOON:
            matrix[(d_iso, "afternoon")].append(s)

    schedule_matrix = {
        f"{d_iso}|{slot}": list(lst) for (d_iso, slot), lst in matrix.items()
    }

    grid_rows = []
    for slot_key, slot_label in PATIENT_BOOKING_SLOT_ROWS:
        cells = []
        for day in calendar_days:
            cells.append(
                {"schedules": list(matrix.get((day["date"], slot_key), []))}
            )
        grid_rows.append({"slot_key": slot_key, "label": slot_label, "cells": cells})

    return {
        "calendar_days": calendar_days,
        "schedule_matrix": schedule_matrix,
        "grid_rows": grid_rows,
    }


@method_decorator(patient_required, name="dispatch")
class PatientDoctorScheduleListView(TemplateView):
    """某医生未来 7 日内可预约排班（日历时间网格）。"""

    template_name = "patient/doctor_schedule_booking.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.doctor = get_object_or_404(
            User.objects.filter(role=UserRole.DOCTOR, is_active=True).select_related(
                "department"
            ),
            pk=self.kwargs["doctor_id"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["doctor"] = self.doctor
        ctx.update(_patient_doctor_booking_grid_context(self.doctor))
        return ctx


def _patient_has_booking_same_doctor_work_date(patient, doctor_id: int, work_date) -> bool:
    """同一患者在同一出诊日是否已向该医生挂过有效号（不限班次/科室）。"""
    return (
        Appointment.objects.filter(
            patient=patient,
            schedule__doctor_id=doctor_id,
            schedule__work_date=work_date,
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .exists()
    )


@method_decorator(patient_required, name="dispatch")
class DepartmentListView(ListView):
    """患者：科室列表（入口）。"""

    model = Department
    template_name = "patient/department_list.html"
    context_object_name = "departments"
    queryset = Department.objects.filter(is_active=True).order_by("name")


@method_decorator(patient_required, name="dispatch")
class ScheduleListView(ListView):
    """患者：某科室下可预约的医生排班。"""

    model = Schedule
    template_name = "patient/schedule_list.html"
    context_object_name = "schedules"

    def get_queryset(self):
        self.department = get_object_or_404(
            Department,
            pk=self.kwargs["department_id"],
            is_active=True,
        )
        today = timezone.localdate()
        return (
            Schedule.objects.filter(
                department=self.department,
                is_active=True,
                work_date__gte=today,
            )
            .select_related("doctor", "doctor__department", "department")
            .annotate(
                booked=Count(
                    "appointments",
                    filter=~Q(appointments__status=Appointment.Status.CANCELLED),
                )
            )
            .order_by("work_date", "shift")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["department"] = self.department
        for s in ctx["schedules"]:
            s.remaining_slots = max(0, s.total_capacity - s.booked)
        return ctx


@method_decorator(patient_required, name="dispatch")
class AppointmentBookView(FormView):
    """患者：提交挂号（可选关联 AIReport），事务内锁排班并校验号源。"""

    form_class = AppointmentBookForm
    template_name = "patient/appointment_book.html"

    def dispatch(self, request, *args, schedule_id, **kwargs):
        self.schedule = get_object_or_404(
            Schedule.objects.select_related(
                "department", "doctor", "doctor__department"
            ),
            pk=schedule_id,
        )
        return super().dispatch(request, *args, **kwargs)

    def _booking_state(self):
        today = timezone.localdate()
        booked = _schedule_effective_booked_count(self.schedule.pk)
        remaining = max(0, self.schedule.total_capacity - booked)
        duplicate_doctor_same_day = _patient_has_booking_same_doctor_work_date(
            self.request.user,
            self.schedule.doctor_id,
            self.schedule.work_date,
        )
        price = self.schedule.price or Decimal("0")
        price = price.quantize(Decimal("0.01"))
        balance = (self.request.user.balance or Decimal("0")).quantize(
            Decimal("0.01")
        )
        balance_sufficient = balance >= price
        can = (
            self.schedule.is_active
            and self.schedule.work_date >= today
            and remaining > 0
            and not duplicate_doctor_same_day
            and balance_sufficient
        )
        return {
            "booked": booked,
            "remaining_slots": remaining,
            "duplicate_doctor_same_day": duplicate_doctor_same_day,
            "schedule_price": price,
            "balance_sufficient": balance_sufficient,
            "can_book": can,
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["schedule"] = self.schedule
        ctx.update(self._booking_state())
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["patient"] = self.request.user
        return kwargs

    def post(self, request, *args, **kwargs):
        st = self._booking_state()
        if not st["can_book"]:
            today = timezone.localdate()
            if (
                not self.schedule.is_active
                or self.schedule.work_date < today
            ):
                messages.error(request, "该班次已不可预约。")
            elif st["remaining_slots"] <= 0:
                messages.error(request, "该排班号源已满。")
            elif st["duplicate_doctor_same_day"]:
                messages.error(
                    request,
                    "您在该出诊日已预约过该医生，请勿重复挂号。",
                )
            elif not st["balance_sufficient"]:
                messages.error(request, "余额不足，请先充值")
            else:
                messages.error(request, "当前无法预约该班次。")
            return redirect(
                "core:patient_doctor_schedules",
                doctor_id=self.schedule.doctor_id,
            )
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        ai_report = form.cleaned_data.get("ai_report")
        if ai_report is not None and ai_report.patient_id != self.request.user.id:
            messages.error(self.request, "只能选择本人名下的预问诊报告。")
            return self.form_invalid(form)

        remark = (form.cleaned_data.get("remark") or "").strip()

        try:
            with transaction.atomic():
                # 锁定该医生当日出诊涉及的所有排班，避免并发下同日重复挂同一医生
                list(
                    Schedule.objects.select_for_update()
                    .filter(
                        doctor_id=self.schedule.doctor_id,
                        work_date=self.schedule.work_date,
                    )
                    .order_by("pk")
                )
                schedule = Schedule.objects.select_for_update().get(pk=self.schedule.pk)
                today = timezone.localdate()
                if not schedule.is_active or schedule.work_date < today:
                    raise ValueError("该班次已不可预约。")
                used = _schedule_effective_booked_count(schedule.pk)
                if used >= schedule.total_capacity:
                    raise ValueError("该排班号源已满。")
                if _patient_has_booking_same_doctor_work_date(
                    self.request.user,
                    schedule.doctor_id,
                    schedule.work_date,
                ):
                    raise ValueError(
                        "您在该出诊日已预约过该医生，请勿重复挂号。"
                    )

                price = (schedule.price or Decimal("0")).quantize(Decimal("0.01"))
                patient_user = User.objects.select_for_update().get(
                    pk=self.request.user.pk
                )
                pat_bal = (patient_user.balance or Decimal("0")).quantize(
                    Decimal("0.01")
                )
                if pat_bal < price:
                    raise ValueError("余额不足，请先充值")

                patient_user.balance = pat_bal - price
                patient_user.save(update_fields=["balance"])

                appt = Appointment.objects.create(
                    patient_id=patient_user.pk,
                    schedule=schedule,
                    ai_report=ai_report,
                    remark=remark,
                    status=Appointment.Status.PENDING,
                    amount_paid=price,
                )
                doc_label = schedule.doctor.real_name or schedule.doctor.username
                Order.objects.create(
                    patient_id=patient_user.pk,
                    order_type=Order.OrderType.REGISTRATION,
                    amount=price,
                    status=Order.Status.PAID,
                    description=(
                        f"挂号：{schedule.department.name} · {doc_label} · "
                        f"{schedule.work_date} {schedule.get_shift_display()}"
                    )[:500],
                    appointment=appt,
                )
        except ValueError as e:
            messages.error(self.request, str(e))
            return self.form_invalid(form)

        messages.success(self.request, "挂号提交成功，请在「我的挂号」查看记录。")
        return redirect("core:patient_appointment_list")


@method_decorator(patient_required, name="dispatch")
class PatientOrderListView(ListView):
    """我的账单：当前患者全部订单流水，按创建时间倒序。"""

    model = Order
    template_name = "patient/center_orders.html"
    context_object_name = "orders"
    paginate_by = 25

    def get_queryset(self):
        return Order.objects.filter(patient=self.request.user).order_by("-created_at")


@method_decorator(patient_required, name="dispatch")
class PatientAppointmentListView(ListView):
    """我的挂号：按排班日期、创建时间倒序。"""

    model = Appointment
    template_name = "patient/center_appointments.html"
    context_object_name = "appointments"
    paginate_by = 20

    def get_queryset(self):
        return (
            Appointment.objects.filter(patient=self.request.user)
            .select_related(
                "schedule",
                "schedule__department",
                "schedule__doctor",
                "schedule__doctor__department",
                "ai_report",
                "medical_record",
            )
            .order_by("-schedule__work_date", "-created_at")
        )


@method_decorator(patient_required, name="dispatch")
class PatientMedicalRecordDetailView(DetailView):
    """患者查看本人电子病历详情（诊断全文等）。"""

    model = MedicalRecord
    template_name = "patient/medical_record_detail.html"
    context_object_name = "medical_record"

    def get_queryset(self):
        return MedicalRecord.objects.filter(patient=self.request.user).select_related(
            "appointment",
            "appointment__schedule",
            "appointment__schedule__department",
            "appointment__schedule__doctor",
            "doctor",
        )


@method_decorator(patient_required, name="dispatch")
class PatientProfileUpdateView(UpdateView):
    model = User
    form_class = PatientProfileForm
    template_name = "patient/center_profile.html"

    def get_object(self, queryset=None):
        return self.request.user

    def get_success_url(self):
        return reverse_lazy("core:patient_profile_edit")

    def form_valid(self, form):
        messages.success(self.request, "个人信息已保存。")
        return super().form_valid(form)


@method_decorator(patient_required, name="dispatch")
class PatientPasswordChangeView(PasswordChangeView):
    form_class = PatientPortalPasswordChangeForm
    template_name = "patient/center_password.html"
    success_url = reverse_lazy("core:index")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        if user.must_change_password:
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
        record_operation_log(
            self.request,
            "UPDATE",
            "账号安全",
            "患者主动修改了登录密码",
        )
        messages.success(self.request, "密码已更新。")
        return response


@method_decorator(patient_required, name="dispatch")
class PatientRechargeView(View):
    """患者账户余额充值（POST amount，单位元）。"""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        raw = (request.POST.get("amount") or "").strip()
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            messages.error(request, "请输入有效的充值金额。")
            return redirect("core:patient_profile_edit")
        amount = amount.quantize(Decimal("0.01"))
        if amount < Decimal("0.01") or amount > Decimal("10000"):
            messages.error(request, "单次充值需在 0.01～10000 元之间。")
            return redirect("core:patient_profile_edit")

        new_bal = Decimal("0")
        with transaction.atomic():
            u = User.objects.select_for_update().get(pk=request.user.pk)
            new_bal = (
                (u.balance or Decimal("0")).quantize(Decimal("0.01")) + amount
            )
            u.balance = new_bal
            u.save(update_fields=["balance"])
            Order.objects.create(
                patient=u,
                order_type=Order.OrderType.RECHARGE,
                amount=amount,
                status=Order.Status.PAID,
                description=f"账户充值 ￥{amount}"[:500],
            )

        record_operation_log(
            request,
            OperationLog.ActionType.UPDATE,
            "财务中心",
            "患者充值",
        )
        messages.success(request, f"充值成功，当前余额 ￥{new_bal}。")
        return redirect("core:patient_profile_edit")


@method_decorator(patient_required, name="dispatch")
class PatientAppointmentCancelView(View):
    """
    取消挂号：仅待就诊(pending)；软取消释放号源（有效预约统计排除 cancelled）。
    不删除记录，不解除 ai_report 关联。待就诊取消时按 amount_paid 原子退款至余额。
    """

    http_method_names = ["post"]

    def post(self, request, pk, *args, **kwargs):
        refund = Decimal("0")
        try:
            with transaction.atomic():
                appt = (
                    Appointment.objects.select_for_update()
                    .select_related("schedule")
                    .get(pk=pk, patient=request.user)
                )
                if appt.status != Appointment.Status.PENDING:
                    messages.error(
                        request,
                        "仅「待就诊」状态的挂号可由患者取消；已开始就诊或已结束的记录无法在此取消。",
                    )
                    return redirect("core:patient_appointment_list")

                refund = (appt.amount_paid or Decimal("0")).quantize(Decimal("0.01"))
                patient_user = User.objects.select_for_update().get(pk=request.user.pk)
                patient_user.balance = (
                    (patient_user.balance or Decimal("0")).quantize(Decimal("0.01"))
                    + refund
                )
                patient_user.save(update_fields=["balance"])
                appt.status = Appointment.Status.CANCELLED
                appt.save(update_fields=["status", "updated_at"])
                Order.objects.filter(
                    appointment=appt,
                    order_type=Order.OrderType.REGISTRATION,
                    status=Order.Status.PAID,
                ).update(status=Order.Status.REFUNDED)
        except Appointment.DoesNotExist:
            messages.error(request, "未找到该挂号记录。")
            return redirect("core:patient_appointment_list")

        record_operation_log(
            request,
            OperationLog.ActionType.UPDATE,
            "财务中心",
            f"取消挂号并退还金额 ￥{refund}",
        )
        messages.success(request, "挂号已取消，号源已释放给其他患者。")
        return redirect("core:patient_appointment_list")


@method_decorator(patient_required, name="dispatch")
class AIReportListView(ListView):
    """当前患者的预问诊报告列表。"""

    model = AIReport
    template_name = "patient/center_reports.html"
    context_object_name = "reports"
    paginate_by = 20

    def get_queryset(self):
        return (
            AIReport.objects.filter(patient=self.request.user)
            .annotate(appt_count=Count("appointments"))
            .order_by("-created_at")
        )


@method_decorator(patient_required, name="dispatch")
class AIReportDetailView(DetailView):
    """报告详情（仅本人）。"""

    model = AIReport
    template_name = "patient/report_detail.html"
    context_object_name = "report"

    def get_queryset(self):
        return AIReport.objects.filter(patient=self.request.user).prefetch_related(
            "appointments"
        )


@method_decorator(patient_required, name="dispatch")
class AIReportDeleteView(DeleteView):
    """删除未关联挂号的预问诊报告。"""

    model = AIReport
    template_name = "patient/report_confirm_delete.html"
    context_object_name = "report"
    success_url = reverse_lazy("core:patient_ai_report_list")

    def get_queryset(self):
        return AIReport.objects.filter(patient=self.request.user)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        if Appointment.objects.filter(ai_report=self.object).exists():
            messages.error(
                request,
                "该报告已关联挂号记录，作为正式就诊资料保留，无法删除。",
            )
            return redirect("core:patient_ai_report_list")
        messages.success(request, "预问诊报告已删除。")
        return super().delete(request, *args, **kwargs)


@method_decorator(ensure_csrf_cookie, name="dispatch")
@method_decorator(patient_required, name="dispatch")
class PatientAIChatView(TemplateView):
    """患者端 AI 预问诊聊天页（HTML）。"""

    template_name = "patient/ai_chat.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        raw = self.request.session.get(SESSION_KEY_AI_CHAT, [])
        if not isinstance(raw, list):
            raw = []
        ctx["initial_chat_messages"] = raw
        return ctx


@require_POST
@patient_required
def ai_chat_send(request):
    """接收患者一条消息，返回助手回复 JSON。"""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "无效的 JSON"}, status=400)

    text = (data.get("message") or "").strip()
    if not text:
        return JsonResponse({"ok": False, "error": "消息不能为空"}, status=400)
    if len(text) > 8000:
        return JsonResponse({"ok": False, "error": "消息过长"}, status=400)

    messages_list = request.session.get(SESSION_KEY_AI_CHAT, [])
    if not isinstance(messages_list, list):
        messages_list = []

    messages_list.append({"role": "user", "content": text})
    if len(messages_list) > MAX_CHAT_MESSAGES:
        messages_list = messages_list[-MAX_CHAT_MESSAGES:]

    dept_names = list(
        Department.objects.filter(is_active=True)
        .order_by("name")
        .values_list("name", flat=True)
    )
    service = DeepSeekService()
    try:
        reply = service.chat_turn(messages_list, department_names=dept_names)
    except DeepSeekServiceError as e:
        messages_list.pop()
        request.session[SESSION_KEY_AI_CHAT] = messages_list
        request.session.modified = True
        return JsonResponse({"ok": False, "error": str(e)}, status=503)

    messages_list.append({"role": "assistant", "content": reply})
    request.session[SESSION_KEY_AI_CHAT] = messages_list
    request.session.modified = True

    return JsonResponse({"ok": True, "reply": reply})


@require_POST
@patient_required
def ai_chat_finish(request):
    """结束问诊：抽取结构化主诉/现病史并写入 AIReport，清空会话。"""
    messages_list = request.session.get(SESSION_KEY_AI_CHAT, [])
    if not isinstance(messages_list, list) or not messages_list:
        return JsonResponse(
            {"ok": False, "error": "暂无对话内容，请先与助手交流后再生成报告。"},
            status=400,
        )

    dept_names = list(
        Department.objects.filter(is_active=True)
        .order_by("name")
        .values_list("name", flat=True)
    )
    service = DeepSeekService()
    try:
        structured, raw_text, rec_dept = service.extract_structured_summary(
            messages_list, department_names=dept_names
        )
    except DeepSeekServiceError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=503)

    cc = structured.get("chief_complaint", "待补充")
    pi = structured.get("present_illness", "待补充")
    patient_summary = _build_patient_summary(structured, cc, pi)
    structured["patient_summary"] = patient_summary
    summary = f"主诉：{cc}\n现病史：{pi}"
    report_title = _build_ai_report_title(structured)

    report = AIReport.objects.create(
        patient=request.user,
        title=report_title[:100],
        summary=summary,
        patient_summary=patient_summary,
        structured_content=structured,
        raw_llm_response=raw_text,
        recommended_department=rec_dept,
    )

    request.session[SESSION_KEY_AI_CHAT] = []
    request.session.modified = True

    payload = {
        "ok": True,
        "report_id": report.id,
        "title": report.title,
        "symptom_keyword": structured.get("symptom_keyword", ""),
        "patient_summary": report.patient_summary,
    }
    if rec_dept is not None:
        payload["recommended_department_id"] = rec_dept.pk
        payload["recommended_department_name"] = rec_dept.name
    return JsonResponse(payload)
