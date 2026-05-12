from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from core.decorators import admin_or_headnurse_required
from core.forms import ManufacturerForm
from core.models import Manufacturer, OperationLog
from core.utils import record_operation_log

_admin_or_headnurse = method_decorator(admin_or_headnurse_required, name="dispatch")


@_admin_or_headnurse
class ManufacturerListView(ListView):
    model = Manufacturer
    template_name = "manage/manufacturer_list.html"
    context_object_name = "manufacturers"
    queryset = Manufacturer.objects.order_by("name")
    paginate_by = 50


@_admin_or_headnurse
class ManufacturerCreateView(CreateView):
    model = Manufacturer
    form_class = ManufacturerForm
    template_name = "manage/manufacturer_form.html"
    success_url = reverse_lazy("core:manufacturer_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        record_operation_log(
            self.request,
            OperationLog.ActionType.CREATE,
            "生产厂家管理",
            f"新增了生产厂家：{self.object.name}",
        )
        messages.success(self.request, "生产厂家已添加。")
        return response


@_admin_or_headnurse
class ManufacturerUpdateView(UpdateView):
    model = Manufacturer
    form_class = ManufacturerForm
    template_name = "manage/manufacturer_form.html"
    success_url = reverse_lazy("core:manufacturer_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        record_operation_log(
            self.request,
            OperationLog.ActionType.UPDATE,
            "生产厂家管理",
            f"修改了生产厂家：{self.object.name}",
        )
        messages.success(self.request, "生产厂家已更新。")
        return response


@_admin_or_headnurse
class ManufacturerDeleteView(DeleteView):
    model = Manufacturer
    template_name = "manage/manufacturer_confirm_delete.html"
    success_url = reverse_lazy("core:manufacturer_list")
    context_object_name = "manufacturer"

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.drugs.exists():
            raise PermissionDenied(
                "该厂家下仍有关联药品，无法删除。请先调整药品的生产厂家或删除相关药品。"
            )
        self.object.delete()
        messages.success(request, "生产厂家已删除。")
        return redirect(self.get_success_url())

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        obj_info = str(obj)
        try:
            response = super().post(request, *args, **kwargs)
            record_operation_log(
                request,
                "DELETE",
                "生产厂家管理",
                f"删除了: {obj_info}",
            )
            return response
        except Http404:
            raise
        except Exception as e:
            messages.error(request, f"删除失败: {e}")
            return redirect(self.get_success_url())
