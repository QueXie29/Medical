from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import FormView, ListView, TemplateView, View
from decimal import Decimal

from core.decorators import nurse_required
from core.forms import NursePurchaseRequestForm, VitalSignForm
from core.models import (
    Appointment,
    Drug,
    OperationLog,
    Order,
    Prescription,
    PurchaseRequest,
    User,
    VitalSign,
)
from core.utils import record_operation_log


@method_decorator(nurse_required, name="dispatch")
class NurseTriageListView(ListView):
    """门诊分诊台：今日待就诊患者，支持录入基础体征。"""

    model = Appointment
    template_name = "nurse/triage_list.html"
    context_object_name = "appointments"

    def get_queryset(self):
        today = timezone.localdate()
        return (
            Appointment.objects.filter(
                schedule__work_date=today,
                status=Appointment.Status.PENDING,
            )
            .select_related(
                "patient",
                "schedule",
                "schedule__department",
                "schedule__doctor",
                "vital_sign",
            )
            .order_by("schedule__department__name", "schedule__shift", "created_at")
        )


@method_decorator(nurse_required, name="dispatch")
class VitalSignCreateView(FormView):
    """为指定今日待就诊挂号录入或修改体征。"""

    form_class = VitalSignForm
    template_name = "nurse/vital_sign_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.appointment = get_object_or_404(
            Appointment.objects.select_related(
                "patient",
                "schedule",
                "schedule__department",
                "schedule__doctor",
            ),
            pk=kwargs["pk"],
            status=Appointment.Status.PENDING,
            schedule__work_date=timezone.localdate(),
        )
        self._existing_vital = VitalSign.objects.filter(
            appointment=self.appointment
        ).first()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["appointment"] = self.appointment
        ctx["is_update"] = self._existing_vital is not None
        return ctx

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        if self._existing_vital is not None:
            kw["instance"] = self._existing_vital
        return kw

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.appointment = self.appointment
        obj.save()
        record_operation_log(
            self.request,
            OperationLog.ActionType.CREATE,
            "门诊分诊",
            "录入了患者体征数据",
        )
        messages.success(self.request, "体征已保存。")
        return redirect("core:nurse_triage_list")

    def form_invalid(self, form):
        messages.error(self.request, "请检查体征填写是否正确。")
        return super().form_invalid(form)


@method_decorator(nurse_required, name="dispatch")
class NursePrescriptionListView(TemplateView):
    """处方执行工作台：待执行（已签署）与已执行（已发药）分区展示。"""

    template_name = "nurse/prescription_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base = (
            Prescription.objects.select_related(
                "medical_record",
                "medical_record__patient",
                "medical_record__appointment",
                "doctor",
            )
            .prefetch_related("lines__drug")
        )
        ctx["pending_prescriptions"] = base.filter(
            status=Prescription.Status.SIGNED
        ).order_by("-created_at")
        ctx["completed_prescriptions"] = base.filter(
            status=Prescription.Status.DISPENSED
        ).order_by("-executed_at", "-updated_at")
        return ctx


@method_decorator(nurse_required, name="dispatch")
class NurseDispenseView(View):
    """发药：校验库存与患者余额，扣费、写订单流水，扣减库存并将处方标为已发药。"""

    http_method_names = ["post"]

    def post(self, request, *args, pk, **kwargs):
        presc = get_object_or_404(
            Prescription.objects.select_related(
                "medical_record",
                "medical_record__patient",
                "medical_record__appointment",
                "medical_record__appointment__schedule",
                "medical_record__appointment__schedule__department",
            ).prefetch_related("lines__drug"),
            pk=pk,
            status=Prescription.Status.SIGNED,
        )

        total_charged = Decimal("0")
        desc_parts = []

        try:
            with transaction.atomic():
                presc_locked = (
                    Prescription.objects.select_for_update()
                    .select_related(
                        "medical_record",
                        "medical_record__patient",
                        "medical_record__appointment",
                    )
                    .prefetch_related("lines__drug")
                    .get(pk=presc.pk, status=Prescription.Status.SIGNED)
                )

                scanned_appointment_id = (
                    request.POST.get("scanned_appointment_id") or ""
                ).strip()
                real_appt = presc_locked.medical_record.appointment
                real_id = real_appt.pk
                if not scanned_appointment_id:
                    raise ValueError(
                        "请先扫描或输入患者挂号单号以核对身份，禁止发药。"
                    )
                if str(scanned_appointment_id) != str(real_id):
                    raise ValueError(
                        "患者身份核对失败：腕带 ID 不匹配，禁止发药！"
                    )

                lines = list(presc_locked.lines.select_related("drug"))
                for line in lines:
                    drug = Drug.objects.select_for_update().get(pk=line.drug_id)
                    if drug.stock_quantity < line.quantity:
                        raise ValueError(
                            f"{drug.name} 库存不足（当前 {drug.stock_quantity}，需要 {line.quantity}）。请发起采购申请。"
                        )

                total = Decimal("0")
                parts = []
                for line in lines:
                    unit = (line.drug.price or Decimal("0")).quantize(Decimal("0.01"))
                    line_amt = (unit * line.quantity).quantize(Decimal("0.01"))
                    total += line_amt
                    parts.append(f"{line.drug.name} ×{line.quantity}")
                total = total.quantize(Decimal("0.01"))

                patient = User.objects.select_for_update().get(
                    pk=presc_locked.medical_record.patient_id
                )
                pat_bal = (patient.balance or Decimal("0")).quantize(Decimal("0.01"))
                if pat_bal < total:
                    raise ValueError(
                        f"患者账户余额不足（当前 ￥{pat_bal}，药费合计 ￥{total}），无法发药。请通知患者充值。"
                    )

                patient.balance = pat_bal - total
                patient.save(update_fields=["balance"])

                order_desc = "购买：" + "；".join(parts) if parts else "处方发药"
                if len(order_desc) > 500:
                    order_desc = order_desc[:497] + "..."

                Order.objects.create(
                    patient=patient,
                    order_type=Order.OrderType.MEDICINE,
                    amount=total,
                    status=Order.Status.PAID,
                    description=order_desc,
                    prescription=presc_locked,
                )

                for line in lines:
                    drug = Drug.objects.select_for_update().get(pk=line.drug_id)
                    drug.stock_quantity -= line.quantity
                    drug.save(update_fields=["stock_quantity", "updated_at"])

                note = (request.POST.get("execution_note") or "").strip()[:255]
                presc_locked.status = Prescription.Status.DISPENSED
                presc_locked.execution_note = note
                presc_locked.executed_at = timezone.now()
                presc_locked.save(
                    update_fields=[
                        "status",
                        "execution_note",
                        "executed_at",
                        "updated_at",
                    ]
                )
                total_charged = total
                desc_parts = parts

        except Prescription.DoesNotExist:
            messages.error(request, "该处方状态已变更，请刷新页面。")
            return redirect("core:nurse_prescriptions")
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("core:nurse_prescriptions")

        drug_label = "、".join(desc_parts[:3]) if desc_parts else "—"
        if len(desc_parts) > 3:
            drug_label += " 等"
        record_operation_log(
            request,
            OperationLog.ActionType.UPDATE,
            "处方执行",
            f"执行了处方 #{presc.pk}，发药：{drug_label}，扣费 ￥{total_charged}",
        )
        messages.success(
            request,
            f"发药完成，已收取药费 ￥{total_charged}，库存已扣减。",
        )
        return redirect("core:nurse_prescriptions")


@method_decorator(nurse_required, name="dispatch")
class NursePurchaseRequestView(FormView):
    """药品采购申请 + 本人申请记录。"""

    template_name = "nurse/purchase_request.html"
    form_class = NursePurchaseRequestForm

    def form_valid(self, form):
        pr = form.save(commit=False)
        pr.requester = self.request.user
        pr.save()
        record_operation_log(
            self.request,
            OperationLog.ActionType.CREATE,
            "药品采购",
            f"发起了药品采购申请：{pr.drug.name}，数量 {pr.quantity}",
        )
        messages.success(self.request, "采购申请已提交，请等待护士长审批。")
        return redirect("core:nurse_purchase_request")

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        if self.request.method == "GET":
            raw = (self.request.GET.get("drug") or self.request.GET.get("drug_id") or "").strip()
            if raw.isdigit():
                did = int(raw)
                if Drug.objects.filter(pk=did).exists():
                    kw.setdefault("initial", {})["drug"] = did
        return kw

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["my_requests"] = (
            PurchaseRequest.objects.filter(requester=self.request.user)
            .select_related("drug", "reviewer")
            .order_by("-created_at")[:50]
        )
        return ctx
