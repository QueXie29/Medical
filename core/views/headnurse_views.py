from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import ListView, TemplateView, View

from core.decorators import headnurse_required
from core.models import Drug, OperationLog, PurchaseRequest
from core.utils import record_operation_log


@method_decorator(headnurse_required, name="dispatch")
class HeadNurseDashboardView(TemplateView):
    """护士长管理看板：采购与药品概览。"""

    template_name = "headnurse/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()

        pending_purchase = PurchaseRequest.objects.filter(
            status=PurchaseRequest.Status.PENDING
        ).count()

        today_reviewed = PurchaseRequest.objects.filter(
            status__in=(
                PurchaseRequest.Status.APPROVED,
                PurchaseRequest.Status.REJECTED,
            ),
            reviewed_at__date=today,
        ).count()

        drug_total = Drug.objects.count()
        drug_low_stock = Drug.objects.filter(stock_quantity__lt=20).count()

        ctx["pending_purchase_count"] = pending_purchase
        ctx["today_reviewed_count"] = today_reviewed
        ctx["drug_total_count"] = drug_total
        ctx["drug_low_stock_count"] = drug_low_stock
        ctx["today"] = today
        return ctx


@method_decorator(headnurse_required, name="dispatch")
class HeadNurseDrugInventoryView(ListView):
    """药品库存盘点与预警（stock < 20 高亮）。"""

    model = Drug
    template_name = "headnurse/drug_inventory.html"
    context_object_name = "drugs"

    def get_queryset(self):
        return Drug.objects.all().order_by("name")


@method_decorator(headnurse_required, name="dispatch")
class HeadNursePurchaseListView(ListView):
    """采购审批中心：待审批 + 审批历史（模板内分 Tab）。"""

    model = PurchaseRequest
    template_name = "headnurse/purchase_list.html"
    context_object_name = "requests"

    def get_queryset(self):
        return (
            PurchaseRequest.objects.filter(status=PurchaseRequest.Status.PENDING)
            .select_related("drug", "requester")
            .order_by("created_at")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["pending_requests"] = ctx["requests"]
        ctx["history_requests"] = (
            PurchaseRequest.objects.filter(
                status__in=(
                    PurchaseRequest.Status.APPROVED,
                    PurchaseRequest.Status.REJECTED,
                )
            )
            .select_related("drug", "requester", "reviewer")
            .order_by("-reviewed_at", "-pk")[:150]
        )
        return ctx


@method_decorator(headnurse_required, name="dispatch")
class HeadNursePurchaseDecideView(View):
    """审批采购：通过则增加库存。"""

    http_method_names = ["post"]

    def post(self, request, *args, pk, **kwargs):
        action = (request.POST.get("action") or "").strip()
        comment = (request.POST.get("review_comment") or "").strip()

        if action not in ("approve", "reject"):
            messages.error(request, "无效操作。")
            return redirect("core:headnurse_purchase")

        try:
            with transaction.atomic():
                pr = PurchaseRequest.objects.select_for_update().get(
                    pk=pk,
                    status=PurchaseRequest.Status.PENDING,
                )
                if action == "approve":
                    drug = Drug.objects.select_for_update().get(pk=pr.drug_id)
                    drug.stock_quantity += pr.quantity
                    drug.save(update_fields=["stock_quantity", "updated_at"])
                    pr.status = PurchaseRequest.Status.APPROVED
                    pr.reviewer = request.user
                    pr.reviewed_at = timezone.now()
                    pr.review_comment = comment or "同意"
                    pr.save(
                        update_fields=[
                            "status",
                            "reviewer",
                            "reviewed_at",
                            "review_comment",
                        ]
                    )
                    record_operation_log(
                        request,
                        OperationLog.ActionType.UPDATE,
                        "采购审批",
                        f"审批了采购申请 #{pr.pk}（{drug.name} ×{pr.quantity}），结果为：同意",
                    )
                    record_operation_log(
                        request,
                        OperationLog.ActionType.UPDATE,
                        "药品管理",
                        f"补充了药品库存：{drug.name} +{pr.quantity}（采购审批入库）",
                    )
                    messages.success(
                        request,
                        f"已批准，{drug.name} 库存 +{pr.quantity}。",
                    )
                else:
                    pr.status = PurchaseRequest.Status.REJECTED
                    pr.reviewer = request.user
                    pr.reviewed_at = timezone.now()
                    pr.review_comment = comment or "已驳回"
                    pr.save(
                        update_fields=[
                            "status",
                            "reviewer",
                            "reviewed_at",
                            "review_comment",
                        ]
                    )
                    drug_name = pr.drug.name
                    record_operation_log(
                        request,
                        OperationLog.ActionType.UPDATE,
                        "采购审批",
                        f"审批了采购申请 #{pr.pk}（{drug_name} ×{pr.quantity}），结果为：驳回",
                    )
                    messages.info(request, "已驳回该申请。")
        except PurchaseRequest.DoesNotExist:
            messages.error(request, "该申请不存在或已处理。")

        return redirect("core:headnurse_purchase")
