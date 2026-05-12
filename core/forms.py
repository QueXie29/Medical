from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    UserCreationForm,
)
from django.forms import formset_factory

from .models import (
    AIReport,
    Appointment,
    Department,
    Drug,
    HospitalSetting,
    Manufacturer,
    MedicalRecord,
    PurchaseRequest,
    Schedule,
    User,
    UserRole,
    VitalSign,
)


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    """登录页：账号框可输入用户名或注册邮箱。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "账号 / 电子邮箱"
        self.fields["username"].widget.attrs.setdefault(
            "placeholder", "请输入您的用户名或注册邮箱"
        )


class HospitalSettingForm(forms.ModelForm):
    class Meta:
        model = HospitalSetting
        fields = ("hospital_name", "hero_title", "hero_image")
        widgets = {
            "hospital_name": forms.TextInput(attrs={"class": "form-control"}),
            "hero_title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "留空则使用默认标题"}
            ),
            "hero_image": forms.ClearableFileInput(
                attrs={"class": "form-control"}
            ),
        }


class PatientPortalPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class PatientProfileForm(forms.ModelForm):
    """患者自助维护的扩展档案（极简注册后可延后填写）。"""

    class Meta:
        model = User
        fields = ("gender", "age", "phone", "address")
        widgets = {
            "gender": forms.Select(attrs={"class": "form-select"}),
            "age": forms.NumberInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("gender", "age", "phone", "address"):
            self.fields[name].required = False


class PatientRegistrationForm(UserCreationForm):
    """患者注册：仅收集账号信息，角色由服务端固定为患者。"""

    real_name = forms.CharField(
        label="真实姓名",
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    email = forms.EmailField(
        label="电子邮箱",
        required=True,
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "id": "id_register_email"}
        ),
    )
    verify_code = forms.CharField(
        label="邮箱验证码",
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(
            attrs={
                "maxlength": "6",
                "pattern": "[0-9]{6}",
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "placeholder": "6位数字",
            }
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "real_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(
            [
                "username",
                "email",
                "verify_code",
                "password1",
                "password2",
                "real_name",
            ]
        )

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if not email:
            return email
        email = email.strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("该邮箱已被注册，请使用其他邮箱。")
        return email.lower()

    def clean(self):
        cleaned = super().clean()
        email = (cleaned.get("email") or "").strip()
        verify_code = (cleaned.get("verify_code") or "").strip()
        if not email:
            self.add_error("email", "请填写电子邮箱。")
            return cleaned
        if not verify_code:
            self.add_error("verify_code", "请填写邮箱验证码。")
            return cleaned

        from datetime import timedelta

        from django.utils import timezone

        from core.models import EmailVerifyRecord

        norm = email.lower()
        latest = (
            EmailVerifyRecord.objects.filter(email=norm).order_by("-created_at").first()
        )
        if not latest:
            self.add_error("verify_code", "请先获取验证码")
            return cleaned
        if latest.code != verify_code:
            self.add_error("verify_code", "验证码不正确")
            return cleaned
        if timezone.now() - latest.created_at > timedelta(minutes=5):
            self.add_error("verify_code", "验证码已过期，请重新获取")
            return cleaned

        cleaned["email"] = norm
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = UserRole.PATIENT
        user.must_change_password = False
        if commit:
            user.save()
            if hasattr(self, "save_m2m"):
                self.save_m2m()
        return user


class AdminEmployeeCreateForm(forms.Form):
    """管理员创建医护账号：姓名、角色；医生须选所属科室，用户名由系统发号。"""

    real_name = forms.CharField(
        label="员工姓名",
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    role = forms.ChoiceField(
        label="角色",
        choices=[
            (UserRole.DOCTOR, "主治医生"),
            (UserRole.NURSE, "护士"),
            (UserRole.HEAD_NURSE, "护士长"),
            (UserRole.ADMIN, "管理员"),
        ],
    )
    department = forms.ModelChoiceField(
        label="所属科室",
        queryset=Department.objects.filter(is_active=True).order_by("name"),
        required=False,
        empty_label="请选择（主治医生必选）",
    )

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        dept = cleaned.get("department")
        if role == UserRole.DOCTOR and not dept:
            self.add_error("department", "主治医生必须选择所属科室。")
        elif role and role != UserRole.DOCTOR:
            cleaned["department"] = None
        return cleaned


class AdminEmployeeUpdateForm(forms.ModelForm):
    """管理员修改员工：姓名、科室；可选重置密码（重置后员工须再次修改密码）。"""

    class Meta:
        model = User
        fields = ("real_name", "department")
        labels = {
            "real_name": "员工姓名",
            "department": "所属科室",
        }
        widgets = {
            "real_name": forms.TextInput(attrs={"class": "form-control"}),
            "department": forms.Select(attrs={"class": "form-control"}),
        }

    new_password = forms.CharField(
        label="重置密码 (不修改请留空)",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "若需重置密码请输入，否则留空",
                "autocomplete": "new-password",
            }
        ),
        help_text="如果不需要修改密码，请不要填写此栏。",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["department"].required = False
        self.fields["department"].empty_label = "请选择（主治医生必选）"
        if self.instance.pk and self.instance.role != UserRole.DOCTOR:
            del self.fields["department"]

    def clean(self):
        cleaned = super().clean()
        if self.instance.role == UserRole.DOCTOR and not cleaned.get("department"):
            self.add_error("department", "主治医生必须选择所属科室。")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if user.role != UserRole.DOCTOR:
            user.department = None
        new_pw = (self.cleaned_data.get("new_password") or "").strip()
        if new_pw:
            user.set_password(new_pw)
            user.must_change_password = True
        if commit:
            user.save()
        return user


class AppointmentBookForm(forms.ModelForm):
    """患者挂号：可选关联本人 AI 预问诊报告。"""

    class Meta:
        model = Appointment
        fields = ("ai_report", "remark")
        widgets = {
            "ai_report": forms.Select(attrs={"class": "form-select"}),
            "remark": forms.TextInput(
                attrs={
                    "placeholder": "选填：补充说明",
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ai_report"].required = False
        self.fields["ai_report"].empty_label = "不关联预问诊报告"
        self.fields["remark"].required = False
        self.fields["remark"].label = "备注"
        self.fields["ai_report"].label = "关联预问诊报告"
        self.fields["ai_report"].help_text = (
            "可选。下拉项为报告标题（含病情关键词与生成时间），按最新在前排序。"
        )
        if patient is not None:
            self.fields["ai_report"].queryset = AIReport.objects.filter(
                patient=patient
            ).order_by("-created_at")


class MedicalRecordForm(forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ("chief_complaint", "present_illness", "diagnosis", "treatment_plan")
        widgets = {
            "chief_complaint": forms.Textarea(
                attrs={"rows": 5, "class": "his-textarea", "placeholder": "主诉"}
            ),
            "present_illness": forms.Textarea(
                attrs={"rows": 5, "class": "his-textarea", "placeholder": "现病史"}
            ),
            "diagnosis": forms.Textarea(
                attrs={"rows": 5, "class": "his-textarea", "placeholder": "诊断结论"}
            ),
            "treatment_plan": forms.Textarea(
                attrs={"rows": 5, "class": "his-textarea", "placeholder": "处理意见"}
            ),
        }


class PrescriptionLineEntryForm(forms.Form):
    drug = forms.ModelChoiceField(
        label="药品",
        queryset=Drug.objects.all().order_by("name"),
        required=False,
    )
    quantity = forms.IntegerField(label="数量", min_value=1, required=False)
    dosage_instruction = forms.CharField(
        label="用法用量",
        max_length=255,
        required=False,
    )


PrescriptionLineFormSet = formset_factory(
    PrescriptionLineEntryForm,
    extra=5,
    min_num=0,
    validate_min=False,
    can_delete=False,
)


class NursePurchaseRequestForm(forms.ModelForm):
    class Meta:
        model = PurchaseRequest
        fields = ("drug", "quantity", "reason")
        widgets = {
            "drug": forms.Select(attrs={"class": "nr-pr-input nr-pr-input--select"}),
            "quantity": forms.NumberInput(
                attrs={"class": "nr-pr-input", "min": 1, "placeholder": "申请数量"}
            ),
            "reason": forms.Textarea(
                attrs={
                    "rows": 5,
                    "class": "nr-pr-input nr-pr-textarea",
                    "placeholder": "如：库存不足，申请补货；请注明科室与紧急程度等",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drug"].queryset = Drug.objects.all().order_by("name")
        self.fields["quantity"].min_value = 1


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ("name", "code", "description", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "code": forms.TextInput(attrs={"placeholder": "选填，唯一"}),
        }


class ManufacturerForm(forms.ModelForm):
    class Meta:
        model = Manufacturer
        fields = ("name", "contact_person", "contact_phone", "address")
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
        }


class DrugForm(forms.ModelForm):
    class Meta:
        model = Drug
        fields = (
            "name",
            "generic_name",
            "specification",
            "unit",
            "stock_quantity",
            "price",
            "manufacturer",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manufacturer"].queryset = Manufacturer.objects.order_by("name")
        self.fields["manufacturer"].required = False
        self.fields["manufacturer"].empty_label = "— 请选择生产厂家（可选）—"


class SchedulePublishForm(forms.ModelForm):
    class Meta:
        model = Schedule
        fields = (
            "department",
            "doctor",
            "work_date",
            "shift",
            "total_capacity",
            "price",
            "is_active",
            "remark",
        )
        widgets = {
            "department": forms.Select(attrs={"id": "id_schedule_department"}),
            "doctor": forms.Select(attrs={"id": "id_schedule_doctor"}),
            "work_date": forms.DateInput(attrs={"type": "date"}),
            "price": forms.NumberInput(
                attrs={"step": "0.01", "min": "0", "placeholder": "0.00"}
            ),
            "remark": forms.TextInput(attrs={"placeholder": "选填"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(
            is_active=True
        ).order_by("name")
        dept_pk = None
        raw_dept = self.data.get("department") if self.data else None
        if raw_dept not in (None, ""):
            try:
                dept_pk = int(raw_dept)
            except (TypeError, ValueError):
                dept_pk = None
        if dept_pk:
            self.fields["doctor"].queryset = (
                User.objects.filter(
                    role=UserRole.DOCTOR,
                    department_id=dept_pk,
                    is_active=True,
                )
                .select_related("department")
                .order_by("username")
            )
        else:
            self.fields["doctor"].queryset = User.objects.none()
        self.fields["doctor"].empty_label = "请先选择科室"

    def clean(self):
        cleaned = super().clean()
        dept = cleaned.get("department")
        doc = cleaned.get("doctor")
        wd = cleaned.get("work_date")
        shift = cleaned.get("shift")
        if dept and not doc:
            self.add_error("doctor", "请选择出诊医生。")
        if dept and doc:
            if not doc.is_active:
                raise forms.ValidationError(
                    "所选医生账号已停用，不能为其发布排班。"
                )
            if doc.department_id is None:
                raise forms.ValidationError(
                    "所选医生尚未分配所属科室，请先在「员工信息」中维护后再排班。"
                )
            if doc.department_id != dept.pk:
                raise forms.ValidationError(
                    "所选医生的所属科室与排班科室不一致，请重新选择。"
                )
        if dept and doc and wd is not None and shift:
            qs = Schedule.objects.filter(
                department=dept, doctor=doc, work_date=wd, shift=shift
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "该医生在此科室、日期与班次已有排班，请勿重复发布。"
                )
        return cleaned


class ScheduleAdminEditForm(forms.ModelForm):
    """管理员修改既有排班：总号源、挂号费、是否开放预约。"""

    class Meta:
        model = Schedule
        fields = ("total_capacity", "price", "is_active")
        labels = {
            "total_capacity": "总号源（本排班可预约人数）",
            "price": "挂号费用（元）",
            "is_active": "是否开放预约",
        }
        widgets = {
            "price": forms.NumberInput(
                attrs={"step": "0.01", "min": "0", "placeholder": "0.00"}
            ),
        }

    def clean_total_capacity(self):
        value = self.cleaned_data["total_capacity"]
        if not self.instance.pk:
            return value
        booked = (
            Appointment.objects.filter(schedule=self.instance)
            .exclude(status=Appointment.Status.CANCELLED)
            .count()
        )
        if value < booked:
            raise forms.ValidationError(
                f"总号源不能少于当前有效预约人数（{booked}）。"
            )
        return value


class VitalSignForm(forms.ModelForm):
    """护士分诊台：体温、血压、心率。"""

    class Meta:
        model = VitalSign
        fields = ("temperature", "blood_pressure", "heart_rate")
        labels = {
            "temperature": "体温（℃）",
            "blood_pressure": "血压（如 120/80）",
            "heart_rate": "心率（次/分钟）",
        }
        widgets = {
            "temperature": forms.NumberInput(
                attrs={
                    "step": "0.1",
                    "min": "30",
                    "max": "45",
                    "class": "nr-vital-input",
                }
            ),
            "blood_pressure": forms.TextInput(
                attrs={"placeholder": "收缩压/舒张压", "class": "nr-vital-input"}
            ),
            "heart_rate": forms.NumberInput(
                attrs={"min": "30", "max": "250", "class": "nr-vital-input"}
            ),
        }
