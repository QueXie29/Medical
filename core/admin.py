from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import (
    AIReport,
    Appointment,
    Department,
    Drug,
    Manufacturer,
    MedicalRecord,
    OperationLog,
    Order,
    Prescription,
    PrescriptionLine,
    PurchaseRequest,
    Schedule,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "real_name",
        "role",
        "department",
        "is_staff",
        "is_superuser",
        "must_change_password",
    )
    list_filter = (
        *BaseUserAdmin.list_filter,
        "role",
        "department",
        "must_change_password",
    )
    search_fields = ("username", "email", "real_name")

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            _("档案与登录策略"),
            {
                "fields": (
                    "real_name",
                    "gender",
                    "age",
                    "phone",
                    "address",
                    "role",
                    "department",
                    "must_change_password",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "password1",
                    "password2",
                    "email",
                    "real_name",
                    "gender",
                    "age",
                    "phone",
                    "address",
                    "role",
                    "department",
                    "must_change_password",
                ),
            },
        ),
    )


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    search_fields = ("name", "code")


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_person", "contact_phone", "created_at")
    search_fields = ("name", "contact_person", "contact_phone")


@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "specification",
        "manufacturer",
        "unit",
        "stock_quantity",
        "price",
    )
    search_fields = ("name", "generic_name")
    autocomplete_fields = ("manufacturer",)


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("doctor", "department", "work_date", "shift", "total_capacity", "is_active")
    list_filter = ("department", "shift", "is_active")


@admin.register(AIReport)
class AIReportAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "title", "recommended_department", "created_at")
    list_filter = ("created_at", "recommended_department")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "schedule", "status", "created_at")
    list_filter = ("status",)


@admin.register(MedicalRecord)
class MedicalRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "doctor", "diagnosis", "created_at")


class PrescriptionLineInline(admin.TabularInline):
    model = PrescriptionLine
    extra = 0


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "medical_record", "doctor", "status", "created_at")
    inlines = [PrescriptionLineInline]


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "drug", "quantity", "requester", "status", "created_at")
    list_filter = ("status",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "patient",
        "order_type",
        "amount",
        "status",
        "description",
    )
    list_filter = ("order_type", "status", "created_at")
    search_fields = ("description", "patient__username", "patient__real_name")
    raw_id_fields = ("patient", "appointment", "prescription")
    date_hierarchy = "created_at"


@admin.register(OperationLog)
class OperationLogAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "action_type", "module", "user", "ip_address")
    list_filter = ("action_type", "module")
    search_fields = ("description", "user__username")
    readonly_fields = ("user", "action_type", "module", "description", "ip_address", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
