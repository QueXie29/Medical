import calendar
import datetime
import json
import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, ProtectedError, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from core.decorators import admin_or_headnurse_required, admin_required
from core.utils import record_operation_log
from core.forms import (
    AdminEmployeeCreateForm,
    AdminEmployeeUpdateForm,
    DepartmentForm,
    DrugForm,
    HospitalSettingForm,
    ScheduleAdminEditForm,
    SchedulePublishForm,
)
from core.models import (
    AIReport,
    Appointment,
    Department,
    Drug,
    HospitalSetting,
    MedicalRecord,
    OperationLog,
    Order,
    Prescription,
    PurchaseRequest,
    Schedule,
    User,
    UserRole,
)

STAFF_ROLES = (
    UserRole.DOCTOR,
    UserRole.NURSE,
    UserRole.HEAD_NURSE,
    UserRole.ADMIN,
)

ROLE_TO_PREFIX = {
    UserRole.DOCTOR: "doc",
    UserRole.NURSE: "nur",
    UserRole.HEAD_NURSE: "nur_head",
    UserRole.ADMIN: "admin",
}


def allocate_next_username(prefix: str) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    max_n = 0
    for username in User.objects.filter(username__startswith=prefix).values_list(
        "username", flat=True
    ):
        m = pattern.match(username)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{prefix}{max_n + 1}"


_admin = method_decorator(admin_required, name="dispatch")
_admin_or_headnurse = method_decorator(admin_or_headnurse_required, name="dispatch")


@admin_required
def api_doctors_by_department(request):
    """按科室返回归属该科室的主治医生（JSON），供发布排班页二级联动。"""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    raw = request.GET.get("department_id", "").strip()
    if not raw:
        return JsonResponse({"doctors": []})
    try:
        dept_id = int(raw)
    except ValueError:
        return JsonResponse({"doctors": []})
    if not Department.objects.filter(pk=dept_id, is_active=True).exists():
        return JsonResponse({"doctors": []})
    qs = (
        User.objects.filter(
            role=UserRole.DOCTOR,
            department_id=dept_id,
            is_active=True,
        )
        .order_by("username")
        .only("pk", "real_name", "username")
    )
    doctors = [
        {"id": u.pk, "real_name": (u.real_name or u.username or "").strip() or u.username}
        for u in qs
    ]
    return JsonResponse({"doctors": doctors})


@_admin
class AdminDashboardView(TemplateView):
    """管理端图形化看板：全院用户与挂号趋势。"""

    template_name = "admin/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        base = Appointment.objects.filter(schedule__work_date=today).exclude(
            status=Appointment.Status.CANCELLED
        )
        ctx["today"] = today
        ctx["total_patients"] = User.objects.filter(role=UserRole.PATIENT).count()
        ctx["total_staff"] = User.objects.filter(
            role__in=(
                UserRole.DOCTOR,
                UserRole.NURSE,
                UserRole.HEAD_NURSE,
            ),
            is_active=True,
        ).count()
        ctx["appt_today"] = base.count()
        # 本月挂号：排班出诊日落在本地日历当月，且非已取消（与列表展示口径一致）
        month_last_day = calendar.monthrange(today.year, today.month)[1]
        month_start = today.replace(day=1)
        month_end = today.replace(day=month_last_day)
        ctx["appt_month"] = (
            Appointment.objects.filter(
                schedule__work_date__gte=month_start,
                schedule__work_date__lte=month_end,
            )
            .exclude(status=Appointment.Status.CANCELLED)
            .count()
        )

        chart_labels = []
        chart_counts = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            chart_labels.append(d.strftime("%m-%d"))
            chart_counts.append(
                Appointment.objects.filter(schedule__work_date=d)
                .exclude(status=Appointment.Status.CANCELLED)
                .count()
            )
        ctx["chart_labels_json"] = json.dumps(chart_labels, ensure_ascii=False)
        ctx["chart_counts_json"] = json.dumps(chart_counts)

        by_status = list(
            base.values("status").annotate(n=Count("id")).order_by("status")
        )
        for row in by_status:
            row["label"] = Appointment.Status(row["status"]).label
        ctx["appt_by_status"] = by_status
        ctx["appt_by_dept"] = list(
            base.values("schedule__department__name")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        ctx["pending_count"] = base.filter(
            status=Appointment.Status.PENDING
        ).count()
        ctx["in_progress_count"] = base.filter(
            status=Appointment.Status.IN_PROGRESS
        ).count()
        ctx["completed_today_count"] = base.filter(
            status=Appointment.Status.COMPLETED
        ).count()
        return ctx


@_admin
class AdminFinancialStatsView(TemplateView):
    """财务统计：今日营收、科室占比、近 7 日趋势；支持 GET start_date/end_date 汇总区间总营收。"""

    template_name = "admin/financial_stats.html"

    @staticmethod
    def _paid_real_revenue_qs():
        """已支付且属于真实营收的订单（排除 RECHARGE 预收款）。"""
        return Order.objects.filter(
            status=Order.Status.PAID,
            order_type__in=(
                Order.OrderType.REGISTRATION,
                Order.OrderType.MEDICINE,
            ),
        )

    @staticmethod
    def _local_day_start_end(d):
        """按当前时区将本地日历日转为 [start, end] 的 aware datetime，避免 __date 与 UTC 错位。"""
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(
            datetime.datetime.combine(d, datetime.time.min),
            tz,
        )
        end = timezone.make_aware(
            datetime.datetime.combine(d, datetime.time.max),
            tz,
        )
        return start, end

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        ctx["today"] = today
        today_start, today_end = self._local_day_start_end(today)

        base_qs = self._paid_real_revenue_qs()
        start_date_str = (self.request.GET.get("start_date") or "").strip()
        end_date_str = (self.request.GET.get("end_date") or "").strip()
        parsed_start = parse_date(start_date_str) if start_date_str else None
        parsed_end = parse_date(end_date_str) if end_date_str else None

        range_qs = base_qs
        if parsed_start:
            range_start, _ = self._local_day_start_end(parsed_start)
            range_qs = range_qs.filter(created_at__gte=range_start)
        if parsed_end:
            _, range_end = self._local_day_start_end(parsed_end)
            range_qs = range_qs.filter(created_at__lte=range_end)

        has_range_filter = parsed_start is not None or parsed_end is not None
        if has_range_filter:
            interval_raw = range_qs.aggregate(Sum("amount"))["amount__sum"]
            ctx["total_revenue"] = float(interval_raw or 0)
        else:
            total_raw = base_qs.aggregate(Sum("amount"))["amount__sum"]
            ctx["total_revenue"] = float(total_raw or 0)

        today_raw = (
            base_qs.filter(
                created_at__gte=today_start,
                created_at__lte=today_end,
            ).aggregate(Sum("amount"))["amount__sum"]
        )

        ctx["today_revenue"] = float(today_raw or 0)
        ctx["revenue_today"] = ctx["today_revenue"]

        dates = []
        revenues = []
        for i in range(6, -1, -1):
            target_date = today - timedelta(days=i)
            d_start, d_end = self._local_day_start_end(target_date)
            daily_sum = (
                base_qs.filter(
                    created_at__gte=d_start,
                    created_at__lte=d_end,
                ).aggregate(Sum("amount"))["amount__sum"]
            )
            dates.append(target_date.strftime("%m-%d"))
            revenues.append(float(daily_sum or 0))

        ctx["chart_dates"] = json.dumps(dates)
        ctx["chart_revenues"] = json.dumps(revenues)

        dept_map = defaultdict(lambda: Decimal("0"))
        day_orders = (
            base_qs.filter(
                created_at__gte=today_start,
                created_at__lte=today_end,
            ).select_related(
                "appointment__schedule__department",
                "prescription__medical_record__appointment__schedule__department",
            )
        )
        for o in day_orders:
            label = None
            if o.order_type == Order.OrderType.REGISTRATION and o.appointment_id:
                label = o.appointment.schedule.department.name
            elif o.order_type == Order.OrderType.MEDICINE and o.prescription_id:
                label = (
                    o.prescription.medical_record.appointment.schedule.department.name
                )
            if label:
                dept_map[label] += o.amount

        dept_list = [
            {"name": k, "amount": float(v)}
            for k, v in sorted(dept_map.items(), key=lambda x: -x[1])
        ]
        ctx["dept_pie_json"] = json.dumps(dept_list, ensure_ascii=False)
        ctx["dept_legend"] = dept_list
        return ctx


@_admin
class AdminOrderListView(ListView):
    """订单流水列表，支持类型与日期筛选。"""

    model = Order
    template_name = "admin/order_list.html"
    context_object_name = "orders"
    paginate_by = 40

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-created_at").select_related(
            "patient"
        )

        order_type = self.request.GET.get("order_type")
        if order_type:
            queryset = queryset.filter(order_type=order_type)

        start_date_str = self.request.GET.get("start_date")
        end_date_str = self.request.GET.get("end_date")

        if start_date_str:
            parsed_start = parse_date(start_date_str.strip())
            if parsed_start:
                start_datetime = timezone.make_aware(
                    datetime.datetime.combine(parsed_start, datetime.time.min)
                )
                queryset = queryset.filter(created_at__gte=start_datetime)

        if end_date_str:
            parsed_end = parse_date(end_date_str.strip())
            if parsed_end:
                end_datetime = timezone.make_aware(
                    datetime.datetime.combine(parsed_end, datetime.time.max)
                )
                queryset = queryset.filter(created_at__lte=end_datetime)

        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["start_date"] = (self.request.GET.get("start_date") or "").strip()
        ctx["end_date"] = (self.request.GET.get("end_date") or "").strip()
        ctx["order_type"] = (self.request.GET.get("order_type") or "").strip()
        ctx["order_type_choices"] = Order.OrderType.choices
        return ctx


@_admin
class AdminHospitalSettingView(UpdateView):
    """医院门户单例：名称、大厅主视觉（仅管理员）。"""

    model = HospitalSetting
    form_class = HospitalSettingForm
    template_name = "manage/hospital_setting.html"
    success_url = reverse_lazy("core:admin_hospital_setting")

    def get_object(self, queryset=None):
        return HospitalSetting.load()

    def form_valid(self, form):
        response = super().form_valid(form)
        obj = self.object
        record_operation_log(
            self.request,
            OperationLog.ActionType.UPDATE,
            "门户配置",
            f"更新了医院门户配置：{obj.hospital_name}",
        )
        messages.success(self.request, "医院门户配置已保存。")
        return response


@_admin
class AdminPatientListView(ListView):
    model = User
    template_name = "manage/patient_list.html"
    context_object_name = "patients"
    paginate_by = 30

    def get_queryset(self):
        return (
            User.objects.filter(role=UserRole.PATIENT)
            .order_by("-date_joined")
            .only(
                "id",
                "username",
                "email",
                "real_name",
                "phone",
                "gender",
                "age",
                "date_joined",
            )
        )


@_admin
class AdminPatientDetailView(DetailView):
    model = User
    template_name = "manage/patient_detail.html"
    context_object_name = "profile_patient"

    def get_queryset(self):
        return User.objects.filter(role=UserRole.PATIENT)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        u = self.object
        ctx["medical_records"] = (
            MedicalRecord.objects.filter(patient=u)
            .select_related(
                "doctor",
                "appointment",
                "appointment__schedule",
                "appointment__schedule__department",
            )
            .order_by("-created_at")
        )
        ctx["prescriptions"] = (
            Prescription.objects.filter(medical_record__patient=u)
            .select_related("doctor", "medical_record")
            .prefetch_related("lines__drug")
            .order_by("-created_at")
        )
        return ctx


@_admin
class AdminPatientAccountListView(ListView):
    """患者账号管理：冻结/解封与密码重置（IT 运维，与患者全景档案区分）。"""

    model = User
    template_name = "admin/patient_account_list.html"
    context_object_name = "patient_accounts"
    paginate_by = 40

    def get_queryset(self):
        qs = (
            User.objects.filter(role=UserRole.PATIENT)
            .order_by("-date_joined")
            .only(
                "id",
                "username",
                "real_name",
                "is_active",
                "date_joined",
                "last_login",
            )
        )
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(real_name__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx


@_admin
class AdminPatientAccountToggleView(View):
    """切换患者账号启用状态（冻结 / 解封）。"""

    http_method_names = ["post"]

    def post(self, request, pk):
        patient = get_object_or_404(User, pk=pk, role=UserRole.PATIENT)
        patient.is_active = not patient.is_active
        patient.save(update_fields=["is_active"])
        verb = "解封" if patient.is_active else "冻结"
        record_operation_log(
            request,
            OperationLog.ActionType.UPDATE,
            "患者账号管理",
            f"{verb}了患者账号：{patient.username}（{patient.real_name or '—'}）",
        )
        messages.success(request, f"已{verb}患者账号「{patient.username}」。")
        return redirect(reverse("core:admin_patient_account_list"))


@_admin
class AdminPatientPasswordResetView(View):
    """将患者密码重置为默认密码并强制下次修改。"""

    http_method_names = ["post"]

    def post(self, request, pk):
        patient = get_object_or_404(User, pk=pk, role=UserRole.PATIENT)
        patient.set_password("123456")
        patient.must_change_password = True
        patient.save(update_fields=["password", "must_change_password"])
        record_operation_log(
            request,
            OperationLog.ActionType.UPDATE,
            "患者账号管理",
            f"重置了患者账号密码：{patient.username}（{patient.real_name or '—'}），已要求下次登录修改密码",
        )
        messages.success(
            request,
            f"已将患者「{patient.username}」的密码重置为初始密码，用户下次登录须修改密码。",
        )
        return redirect(reverse("core:admin_patient_account_list"))


@_admin
class AdminDepartmentListView(ListView):
    model = Department
    template_name = "manage/department_list.html"
    context_object_name = "departments"
    queryset = Department.objects.order_by("name")


@_admin
class AdminDepartmentCreateView(CreateView):
    model = Department
    form_class = DepartmentForm
    template_name = "manage/department_form.html"
    success_url = reverse_lazy("core:admin_department_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        record_operation_log(
            self.request,
            OperationLog.ActionType.CREATE,
            "科室管理",
            f"新增了科室：{self.object.name}",
        )
        messages.success(self.request, "科室已创建。")
        return response


@_admin
class AdminDepartmentUpdateView(UpdateView):
    model = Department
    form_class = DepartmentForm
    template_name = "manage/department_form.html"
    success_url = reverse_lazy("core:admin_department_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        record_operation_log(
            self.request,
            OperationLog.ActionType.UPDATE,
            "科室管理",
            f"修改了科室：{self.object.name}",
        )
        messages.success(self.request, "科室已更新。")
        return response


@_admin
class AdminDepartmentDeleteView(DeleteView):
    model = Department
    template_name = "manage/department_confirm_delete.html"
    success_url = reverse_lazy("core:admin_department_list")
    context_object_name = "department"

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            self.object.delete()
        except ProtectedError as e:
            raise PermissionDenied("存在关联数据，无法删除该科室。") from e
        messages.success(request, "科室已删除。")
        return redirect(self.get_success_url())

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        obj_info = str(obj)
        try:
            response = super().post(request, *args, **kwargs)
            record_operation_log(
                request,
                "DELETE",
                "科室管理",
                f"删除了: {obj_info}",
            )
            return response
        except Http404:
            raise
        except Exception as e:
            messages.error(request, f"删除失败: {e}")
            return redirect(self.get_success_url())


@_admin_or_headnurse
class AdminDrugListView(ListView):
    model = Drug
    template_name = "manage/drug_list.html"
    context_object_name = "drugs"
    queryset = Drug.objects.select_related("manufacturer").order_by(
        "name", "specification"
    )
    paginate_by = 50


@_admin_or_headnurse
class AdminDrugCreateView(CreateView):
    model = Drug
    form_class = DrugForm
    template_name = "manage/drug_form.html"
    success_url = reverse_lazy("core:admin_drug_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        record_operation_log(
            self.request,
            OperationLog.ActionType.CREATE,
            "药品管理",
            f"新增了药品：{self.object.name}",
        )
        messages.success(self.request, "药品已添加。")
        return response


@_admin_or_headnurse
class AdminDrugUpdateView(UpdateView):
    model = Drug
    form_class = DrugForm
    template_name = "manage/drug_form.html"
    success_url = reverse_lazy("core:admin_drug_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        d = self.object
        record_operation_log(
            self.request,
            OperationLog.ActionType.UPDATE,
            "药品管理",
            f"更新了药品：{d.name}（库存 {d.stock_quantity} {d.unit}）",
        )
        messages.success(self.request, "药品已更新。")
        return response


@_admin
class AdminDrugDeleteView(DeleteView):
    model = Drug
    template_name = "manage/drug_confirm_delete.html"
    success_url = reverse_lazy("core:admin_drug_list")
    context_object_name = "drug"

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            self.object.delete()
        except ProtectedError as e:
            raise PermissionDenied(
                "该药品存在处方或采购等关联记录，无法删除，可改为停用或清零库存后在后台处理。"
            ) from e
        messages.success(request, "药品已删除。")
        return redirect(self.get_success_url())

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        obj_info = str(obj)
        try:
            response = super().post(request, *args, **kwargs)
            record_operation_log(
                request,
                "DELETE",
                "药品管理",
                f"删除了: {obj_info}",
            )
            return response
        except Http404:
            raise
        except Exception as e:
            messages.error(request, f"删除失败: {e}")
            return redirect(self.get_success_url())


@_admin
class AdminScheduleListView(ListView):
    """近期排班一览（含今日及未来）。"""

    model = Schedule
    template_name = "admin/schedule_list.html"
    context_object_name = "schedules"

    def get_queryset(self):
        return (
            Schedule.objects.filter(work_date__gte=timezone.localdate())
            .select_related("department", "doctor", "doctor__department")
            .annotate(
                effective_booked=Count(
                    "appointments",
                    filter=~Q(appointments__status=Appointment.Status.CANCELLED),
                )
            )
            .order_by("work_date", "shift", "department__name")
        )


@_admin
class AdminSchedulePublishView(CreateView):
    model = Schedule
    form_class = SchedulePublishForm
    template_name = "manage/schedule_publish.html"
    success_url = reverse_lazy("core:admin_schedule_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        s = self.object
        record_operation_log(
            self.request,
            OperationLog.ActionType.CREATE,
            "排班管理",
            f"发布排班：{s.department.name}，医生 {s.doctor.username}，{s.work_date}，"
            f"{s.get_shift_display()}，挂号费 ￥{s.price}",
        )
        messages.success(self.request, "排班已发布。")
        return response


@_admin
class AdminScheduleUpdateView(UpdateView):
    """修改号源总数与是否开放预约（仅今日及未来排班）。"""

    model = Schedule
    form_class = ScheduleAdminEditForm
    template_name = "manage/schedule_edit.html"
    context_object_name = "schedule"

    def get_queryset(self):
        return (
            Schedule.objects.filter(work_date__gte=timezone.localdate())
            .select_related("department", "doctor", "doctor__department")
        )

    def get_success_url(self):
        return reverse_lazy("core:admin_schedule_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        s = self.object
        record_operation_log(
            self.request,
            OperationLog.ActionType.UPDATE,
            "排班管理",
            f"更新了排班 #{s.pk}：{s.department.name}，{s.doctor.username}，{s.work_date}，"
            f"总号源 {s.total_capacity}，挂号费 ￥{s.price}，开放预约={s.is_active}",
        )
        messages.success(self.request, "排班已更新。")
        return response


@_admin
class AdminScheduleDeleteView(DeleteView):
    """删除排班：须为今日及未来，且无有效患者预约。"""

    model = Schedule
    template_name = "manage/schedule_confirm_delete.html"
    success_url = reverse_lazy("core:admin_schedule_list")
    context_object_name = "schedule"

    def get_queryset(self):
        return Schedule.objects.filter(work_date__gte=timezone.localdate()).select_related(
            "department", "doctor", "doctor__department"
        )

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        today = timezone.localdate()
        if self.object.work_date < today:
            raise PermissionDenied("已过期排班不能删除。")
        if (
            Appointment.objects.filter(schedule=self.object)
            .exclude(status=Appointment.Status.CANCELLED)
            .exists()
        ):
            raise PermissionDenied(
                "该排班已有患者预约，无法删除。可先关闭开放预约或协调患者改约后再处理。"
            )
        self.object.delete()
        messages.success(request, "排班已删除。")
        return redirect(self.get_success_url())

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        obj_info = str(obj)
        try:
            response = super().post(request, *args, **kwargs)
            record_operation_log(
                request,
                "DELETE",
                "排班管理",
                f"删除了: {obj_info}",
            )
            return response
        except Http404:
            raise
        except Exception as e:
            messages.error(request, f"删除失败: {e}")
            return redirect(self.get_success_url())


@_admin
class AdminCreateEmployeeView(FormView):
    form_class = AdminEmployeeCreateForm
    template_name = "core/admin/create_employee.html"
    success_url = reverse_lazy("core:admin_create_employee")

    def form_valid(self, form):
        role = form.cleaned_data["role"]
        real_name = form.cleaned_data["real_name"].strip()
        prefix = ROLE_TO_PREFIX[role]
        username = allocate_next_username(prefix)

        dept = (
            form.cleaned_data["department"]
            if role == UserRole.DOCTOR
            else None
        )
        user = User(
            username=username,
            email=None,
            role=role,
            real_name=real_name,
            department=dept,
            is_staff=True,
            must_change_password=True,
        )
        user.set_password("123456")
        user.save()
        record_operation_log(
            self.request,
            OperationLog.ActionType.CREATE,
            "员工管理",
            f"新建员工账号：{username}，姓名 {real_name}，角色 {user.get_role_display()}",
        )
        messages.success(
            self.request,
            f"员工账号创建成功，分配的用户名为：{username}",
        )
        return super().form_valid(form)


@_admin
class AdminStaffListView(ListView):
    """在职员工列表（非患者），含医生所属科室。"""

    model = User
    template_name = "manage/staff_list.html"
    context_object_name = "staff_members"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            User.objects.filter(role__in=STAFF_ROLES)
            .select_related("department")
            .order_by("role", "username")
        )
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(real_name__icontains=q) | Q(username__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx


@_admin
class AdminStaffUpdateView(UpdateView):
    """修改员工姓名；主治医生可调整所属科室。"""

    model = User
    form_class = AdminEmployeeUpdateForm
    template_name = "manage/staff_edit.html"
    context_object_name = "employee"

    def get_queryset(self):
        return User.objects.filter(role__in=STAFF_ROLES, is_active=True)

    def get_success_url(self):
        return reverse_lazy("core:admin_staff_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        emp = self.object
        pwd = (form.cleaned_data.get("new_password") or "").strip()
        pwd_note = "（含登录密码重置，员工须再次修改密码）" if pwd else ""
        record_operation_log(
            self.request,
            OperationLog.ActionType.UPDATE,
            "员工管理",
            f"修改了员工 {emp.real_name or emp.username}（{emp.username}）的信息{pwd_note}",
        )
        messages.success(self.request, "员工信息/密码修改成功。")
        return response


@_admin
class AdminStaffDeleteView(DeleteView):
    """删除员工账号；若存在业务外键保护则改为停用账号（软删除）。"""

    model = User
    template_name = "manage/staff_confirm_delete.html"
    success_url = reverse_lazy("core:admin_staff_list")
    context_object_name = "employee"

    def get_queryset(self):
        return User.objects.filter(role__in=STAFF_ROLES, is_active=True)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.pk == request.user.pk:
            raise PermissionDenied("不能删除当前登录账号。")
        self.object.delete()
        messages.success(request, "员工账号已删除。")
        return redirect(self.get_success_url())

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        obj_info = str(obj)
        try:
            response = super().post(request, *args, **kwargs)
            record_operation_log(
                request,
                "DELETE",
                "员工管理",
                f"删除了: {obj_info}",
            )
            return response
        except Http404:
            raise
        except ProtectedError:
            user = self.get_object()
            user.is_active = False
            user.save(update_fields=["is_active"])
            label = user.real_name or user.username
            record_operation_log(
                request,
                "UPDATE",
                "员工管理",
                f"员工 {label} 存在历史诊疗记录，已自动转为停用(软删除)状态",
            )
            messages.warning(
                request,
                f"员工 {label} 存在历史诊疗/处方记录，系统拒绝物理删除，已自动将其账号【停用】！",
            )
            return redirect(self.get_success_url())
        except Exception as e:
            messages.error(request, f"删除失败: {e}")
            return redirect(self.get_success_url())


@_admin
class AdminOperationLogListView(ListView):
    """系统操作审计日志（仅管理员）。"""

    model = OperationLog
    template_name = "admin/operation_log_list.html"
    context_object_name = "logs"
    paginate_by = 20

    def get_queryset(self):
        return OperationLog.objects.select_related("user").order_by("-created_at")


# --- 业务数据查阅（替代原 Django Admin 中的列表/详情能力） ---


@_admin
class AdminAppointmentListView(ListView):
    model = Appointment
    template_name = "manage/appointment_list.html"
    context_object_name = "appointments"
    paginate_by = 30

    def get_queryset(self):
        return (
            Appointment.objects.select_related(
                "patient",
                "schedule",
                "schedule__department",
                "schedule__doctor",
                "ai_report",
            ).order_by("-created_at")
        )


@_admin
class AdminAppointmentDetailView(DetailView):
    model = Appointment
    template_name = "manage/appointment_detail.html"
    context_object_name = "appointment"

    def get_queryset(self):
        return Appointment.objects.select_related(
            "patient",
            "schedule",
            "schedule__department",
            "schedule__doctor",
            "ai_report",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["linked_medical_record"] = MedicalRecord.objects.filter(
            appointment_id=self.object.pk
        ).first()
        return ctx


@_admin
class AdminAIReportListView(ListView):
    model = AIReport
    template_name = "manage/ai_report_list.html"
    context_object_name = "reports"
    paginate_by = 30

    def get_queryset(self):
        return AIReport.objects.select_related("patient").order_by("-created_at")


@_admin
class AdminAIReportDetailView(DetailView):
    model = AIReport
    template_name = "manage/ai_report_detail.html"
    context_object_name = "report"

    def get_queryset(self):
        return AIReport.objects.select_related("patient", "recommended_department")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        raw = self.object.structured_content or {}
        symptom_keyword = ""
        if isinstance(raw, dict):
            symptom_keyword = str(raw.get("symptom_keyword", "") or "").strip()
        if not symptom_keyword:
            title = (self.object.title or "").strip()
            title_head = re.split(r"[-—]", title, maxsplit=1)[0].strip()
            symptom_keyword = title_head or "预问诊"
        ctx["symptom_keyword"] = symptom_keyword
        try:
            ctx["structured_json"] = json.dumps(raw, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            ctx["structured_json"] = str(raw)
        return ctx


@_admin
class AdminMedicalRecordListView(ListView):
    model = MedicalRecord
    template_name = "manage/medical_record_list.html"
    context_object_name = "records"
    paginate_by = 30

    def get_queryset(self):
        return (
            MedicalRecord.objects.select_related(
                "patient", "doctor", "appointment", "appointment__schedule"
            ).order_by("-created_at")
        )


@_admin
class AdminMedicalRecordDetailView(DetailView):
    model = MedicalRecord
    template_name = "manage/medical_record_detail.html"
    context_object_name = "record"

    def get_queryset(self):
        return MedicalRecord.objects.select_related(
            "patient", "doctor", "appointment", "appointment__schedule"
        )


@_admin
class AdminPrescriptionListView(ListView):
    model = Prescription
    template_name = "manage/prescription_list.html"
    context_object_name = "prescriptions"
    paginate_by = 30

    def get_queryset(self):
        qs = Prescription.objects.select_related(
            "doctor", "medical_record", "medical_record__patient"
        ).order_by("-created_at")
        mr = self.request.GET.get("mr")
        if mr:
            try:
                qs = qs.filter(medical_record_id=int(mr))
            except ValueError:
                pass
        return qs


@_admin
class AdminPrescriptionDetailView(DetailView):
    model = Prescription
    template_name = "manage/prescription_detail.html"
    context_object_name = "prescription"

    def get_queryset(self):
        return (
            Prescription.objects.select_related(
                "doctor", "medical_record", "medical_record__patient"
            ).prefetch_related("lines__drug")
        )


@_admin
class AdminPurchaseRequestListView(ListView):
    model = PurchaseRequest
    template_name = "manage/purchase_request_list.html"
    context_object_name = "purchase_requests"
    paginate_by = 30

    def get_queryset(self):
        return (
            PurchaseRequest.objects.select_related(
                "drug", "requester", "reviewer"
            ).order_by("-created_at")
        )


@_admin
class AdminPurchaseRequestDetailView(DetailView):
    model = PurchaseRequest
    template_name = "manage/purchase_request_detail.html"
    context_object_name = "purchase_request"

    def get_queryset(self):
        return PurchaseRequest.objects.select_related(
            "drug", "requester", "reviewer"
        )
