from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Prefetch, Q, Sum, Value, When
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import ListView, TemplateView

from core.decorators import doctor_required
from core.forms import MedicalRecordForm, PrescriptionLineFormSet
from core.models import (
    Appointment,
    MedicalRecord,
    OperationLog,
    Prescription,
    PrescriptionLine,
    Schedule,
)
from core.utils import record_operation_log


def _patient_history_medical_records(appointment: Appointment):
    """当前挂号患者的历史病历（不含本次挂号），含处方与药品，按就诊时间倒序。"""
    return (
        MedicalRecord.objects.filter(patient=appointment.patient)
        .exclude(appointment=appointment)
        .select_related(
            "appointment",
            "appointment__schedule",
            "appointment__schedule__department",
            "doctor",
        )
        .prefetch_related(
            Prefetch(
                "prescriptions",
                queryset=Prescription.objects.prefetch_related("lines__drug").order_by(
                    "created_at"
                ),
            )
        )
        .order_by("-created_at")
    )


@method_decorator(doctor_required, name="dispatch")
class DoctorDashboardView(TemplateView):
    """医生个人看板：今日工作量与未来 7 天排班。"""

    template_name = "doctor/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        window_end = today + timedelta(days=6)

        schedules = (
            Schedule.objects.filter(
                doctor=user,
                work_date__gte=today,
                work_date__lte=window_end,
            )
            .select_related("department")
            .annotate(
                booked=Count(
                    "appointments",
                    filter=~Q(appointments__status=Appointment.Status.CANCELLED),
                )
            )
            .order_by("work_date", "shift")
        )

        today_completed = Appointment.objects.filter(
            schedule__doctor=user,
            schedule__work_date=today,
            status=Appointment.Status.COMPLETED,
        ).count()

        today_capacity_sum = (
            Schedule.objects.filter(doctor=user, work_date=today).aggregate(
                s=Sum("total_capacity")
            )["s"]
            or 0
        )

        today_awaiting = Appointment.objects.filter(
            schedule__doctor=user,
            schedule__work_date=today,
            status__in=(
                Appointment.Status.PENDING,
                Appointment.Status.CONFIRMED,
                Appointment.Status.IN_PROGRESS,
            ),
        ).count()

        today_booked_effective = Appointment.objects.filter(
            schedule__doctor=user,
            schedule__work_date=today,
        ).exclude(status=Appointment.Status.CANCELLED).count()

        today_queue = (
            Appointment.objects.filter(
                schedule__doctor=user,
                schedule__work_date=today,
            )
            .exclude(status=Appointment.Status.CANCELLED)
            .select_related("patient", "schedule", "schedule__department", "ai_report")
            .annotate(
                status_order=Case(
                    When(status=Appointment.Status.PENDING, then=Value(0)),
                    When(status=Appointment.Status.CONFIRMED, then=Value(1)),
                    When(status=Appointment.Status.IN_PROGRESS, then=Value(2)),
                    When(status=Appointment.Status.COMPLETED, then=Value(3)),
                    default=Value(9),
                    output_field=IntegerField(),
                )
            )
            .order_by("status_order", "created_at")
        )

        ctx["today"] = today
        ctx["schedule_window_end"] = window_end
        ctx["upcoming_schedules"] = schedules
        ctx["today_completed_count"] = today_completed
        ctx["today_capacity_sum"] = today_capacity_sum
        ctx["today_awaiting_count"] = today_awaiting
        ctx["today_booked_effective"] = today_booked_effective
        ctx["today_queue"] = today_queue
        return ctx


@method_decorator(doctor_required, name="dispatch")
class DoctorQueueListView(ListView):
    """当天、本科医生名下的患者预约队列。"""

    model = Appointment
    template_name = "doctor/queue_list.html"
    context_object_name = "appointments"

    def get_queryset(self):
        today = timezone.localdate()
        return (
            Appointment.objects.filter(
                schedule__doctor=self.request.user,
                schedule__work_date=today,
            )
            .exclude(
                status__in=(
                    Appointment.Status.CANCELLED,
                    Appointment.Status.COMPLETED,
                )
            )
            .select_related(
                "patient",
                "schedule",
                "schedule__department",
                "ai_report",
            )
            .order_by("status", "created_at")
        )


@method_decorator(doctor_required, name="dispatch")
class DoctorConsultView(TemplateView):
    """接诊：展示 AI 报告、录入病历、开具处方。"""

    template_name = "doctor/consult.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.appointment = get_object_or_404(
            Appointment.objects.select_related(
                "schedule",
                "schedule__department",
                "patient",
                "ai_report",
                "vital_sign",
            ),
            pk=kwargs["pk"],
            schedule__doctor=request.user,
        )
        self.medical_record = MedicalRecord.objects.filter(
            appointment=self.appointment
        ).first()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        appt = self.appointment
        ctx["appointment"] = appt
        ctx["ai_report"] = appt.ai_report
        ctx["can_edit"] = appt.status not in (
            Appointment.Status.COMPLETED,
            Appointment.Status.CANCELLED,
        )
        mr = self.medical_record
        ctx["medical_record"] = mr

        initial = {}
        if appt.ai_report and isinstance(appt.ai_report.structured_content, dict):
            sc = appt.ai_report.structured_content
            initial["chief_complaint"] = sc.get("chief_complaint", "") or ""
            initial["present_illness"] = sc.get("present_illness", "") or ""

        if mr:
            ctx["record_form"] = MedicalRecordForm(instance=mr)
        else:
            ctx["record_form"] = MedicalRecordForm(initial=initial)

        ctx["line_formset"] = PrescriptionLineFormSet(prefix="lines")
        ctx["prescriptions"] = []
        if mr:
            ctx["prescriptions"] = (
                Prescription.objects.filter(medical_record=mr)
                .prefetch_related("lines__drug")
                .order_by("-created_at")
            )
        ctx["patient_history_records"] = _patient_history_medical_records(appt)
        return ctx

    def post(self, request, *args, **kwargs):
        appt = self.appointment
        mr = self.medical_record

        if appt.status == Appointment.Status.CANCELLED:
            messages.error(request, "该预约已取消。")
            return redirect("core:doctor_queue")
        if appt.status == Appointment.Status.COMPLETED:
            messages.error(request, "该预约已结束，不可再提交。")
            return redirect("core:doctor_queue")

        if "submit_record" in request.POST:
            return self._post_record(request, appt, mr)
        if "submit_prescription" in request.POST:
            return self._post_prescription(request, appt, mr)
        if "submit_complete_visit" in request.POST:
            return self._post_complete_only(request, appt, mr)

        messages.error(request, "未知操作。")
        return redirect("core:doctor_appointment_consult", pk=appt.pk)

    def _post_record(self, request, appt, mr):
        form = MedicalRecordForm(
            request.POST,
            instance=mr,
        )
        if not form.is_valid():
            messages.error(request, "请检查病历表单。")
            ctx = self.get_context_data()
            ctx["record_form"] = form
            ctx["line_formset"] = PrescriptionLineFormSet(prefix="lines")
            return self.render_to_response(ctx)

        if mr:
            form.save()
        else:
            MedicalRecord.objects.create(
                appointment=appt,
                patient=appt.patient,
                doctor=request.user,
                **form.cleaned_data,
            )

        # 保存病历后进入「就诊中」，最终「已完成」在开具处方或点击「完成就诊」时写入
        appt.status = Appointment.Status.IN_PROGRESS
        appt.save(update_fields=["status", "updated_at"])
        messages.success(request, "病历已保存。")
        return redirect("core:doctor_appointment_consult", pk=appt.pk)

    def _post_prescription(self, request, appt, mr):
        if not mr:
            messages.error(request, "请先保存电子病历后再开具处方。")
            return redirect("core:doctor_appointment_consult", pk=appt.pk)

        formset = PrescriptionLineFormSet(request.POST, prefix="lines")
        if not formset.is_valid():
            messages.error(request, "处方明细有误，请检查。")
            ctx = self.get_context_data()
            ctx["line_formset"] = formset
            ctx["record_form"] = MedicalRecordForm(instance=mr)
            return self.render_to_response(ctx)

        rows = []
        for cd in formset.cleaned_data:
            if not cd:
                continue
            drug = cd.get("drug")
            qty = cd.get("quantity")
            usage = (cd.get("dosage_instruction") or "").strip()
            if drug and qty and usage:
                rows.append({"drug": drug, "quantity": qty, "dosage_instruction": usage})

        if not rows:
            messages.error(request, "请至少填写一行完整药品（药品、数量、用法用量）。")
            ctx = self.get_context_data()
            ctx["line_formset"] = formset
            ctx["record_form"] = MedicalRecordForm(instance=mr)
            return self.render_to_response(ctx)

        notes = (request.POST.get("prescription_notes") or "").strip()
        try:
            with transaction.atomic():
                presc = Prescription.objects.create(
                    medical_record=mr,
                    doctor=request.user,
                    status=Prescription.Status.SIGNED,
                    notes=notes,
                )
                for row in rows:
                    PrescriptionLine.objects.create(
                        prescription=presc,
                        drug=row["drug"],
                        quantity=row["quantity"],
                        dosage_instruction=row["dosage_instruction"],
                    )
        except Exception:
            messages.error(request, "保存处方失败，请重试。")
            return redirect("core:doctor_appointment_consult", pk=appt.pk)

        appt.status = Appointment.Status.COMPLETED
        appt.save(update_fields=["status", "updated_at"])
        patient_label = appt.patient.real_name or appt.patient.username
        record_operation_log(
            request,
            OperationLog.ActionType.CREATE,
            "诊疗业务",
            f"为患者 {patient_label} 完成了接诊并开具处方（挂号 #{appt.pk}）",
        )
        messages.success(request, "处方已签署，患者可至护士站取药执行。")
        return redirect("core:doctor_queue")

    def _post_complete_only(self, request, appt, mr):
        if not mr:
            messages.error(request, "请先保存病历。")
            return redirect("core:doctor_appointment_consult", pk=appt.pk)
        appt.status = Appointment.Status.COMPLETED
        appt.save(update_fields=["status", "updated_at"])
        patient_label = appt.patient.real_name or appt.patient.username
        record_operation_log(
            request,
            OperationLog.ActionType.CREATE,
            "诊疗业务",
            f"为患者 {patient_label} 完成就诊（未开具处方，挂号 #{appt.pk}）",
        )
        messages.success(request, "已标记就诊完成（未开处方）。")
        return redirect("core:doctor_queue")
