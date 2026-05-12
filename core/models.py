from decimal import Decimal

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserRole(models.TextChoices):
    PATIENT = "patient", _("患者")
    DOCTOR = "doctor", _("主治医生")
    NURSE = "nurse", _("护士")
    HEAD_NURSE = "head_nurse", _("护士长")
    ADMIN = "admin", _("超级管理员")


class CustomUserManager(BaseUserManager):
    """保证 createsuperuser 可用；普通用户默认角色为患者，超级用户默认角色为管理员。"""

    use_in_migrations = True

    def create_user(self, username, email=None, password=None, **extra_fields):
        if not username:
            raise ValueError(_("必须设置用户名"))
        email = self.normalize_email(email)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", UserRole.PATIENT)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("超级用户必须 is_staff=True。"))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("超级用户必须 is_superuser=True。"))
        return self.create_user(username, email, password, **extra_fields)


class Gender(models.TextChoices):
    MALE = "M", _("男")
    FEMALE = "F", _("女")


class User(AbstractUser):
    """自定义用户；`User.Role` 与 `UserRole` 等价，便于业务代码书写。"""

    Role = UserRole
    objects = CustomUserManager()

    email = models.EmailField(
        unique=True,
        null=True,
        blank=True,
        verbose_name=_("电子邮箱"),
        error_messages={"unique": _("该电子邮箱已被注册。")},
    )
    role = models.CharField(
        _("角色"),
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.PATIENT,
        db_index=True,
    )
    real_name = models.CharField(_("真实姓名"), max_length=50, blank=True)
    gender = models.CharField(
        _("性别"),
        max_length=1,
        choices=Gender.choices,
        blank=True,
        null=True,
    )
    age = models.PositiveIntegerField(_("年龄"), blank=True, null=True)
    phone = models.CharField(_("联系方式"), max_length=30, blank=True)
    address = models.CharField(_("家庭住址"), max_length=255, blank=True)
    must_change_password = models.BooleanField(_("首次登录须修改密码"), default=False)
    balance = models.DecimalField(
        _("账户余额"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_users",
        verbose_name=_("所属科室"),
    )

    class Meta:
        verbose_name = _("用户")
        verbose_name_plural = _("用户")

    def clean(self):
        super().clean()
        if self.email == "":
            self.email = None

    def save(self, *args, **kwargs):
        if self.email == "":
            self.email = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username


class HospitalSetting(models.Model):
    """医院患者门户单例配置（全局仅一条，pk 固定为 1）。"""

    hospital_name = models.CharField(
        _("医院名称"), max_length=200, default="XXX医院"
    )
    hero_title = models.CharField(
        _("大厅主标题"),
        max_length=200,
        blank=True,
        help_text=_("显示在大厅 Hero 区中央，留空则使用默认文案"),
    )
    hero_image = models.ImageField(
        _("大厅背景图"),
        upload_to="portal/",
        null=True,
        blank=True,
        help_text=_("建议横向宽图；留空则使用渐变背景"),
    )

    class Meta:
        verbose_name = _("医院门户配置")
        verbose_name_plural = _("医院门户配置")

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return None

    def __str__(self):
        return self.hospital_name

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={"hospital_name": "XXX医院"},
        )
        return obj


class EmailVerifyRecord(models.Model):
    """患者注册等场景：邮箱验证码临时记录（无外键）。"""

    email = models.EmailField(_("接收邮箱"), db_index=True)
    code = models.CharField(_("验证码"), max_length=6)
    created_at = models.DateTimeField(_("发送时间"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("邮箱验证码记录")
        verbose_name_plural = _("邮箱验证码记录")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.email} @ {self.created_at:%Y-%m-%d %H:%M}"


class Department(models.Model):
    name = models.CharField(_("科室名称"), max_length=100)
    code = models.CharField(_("科室编码"), max_length=32, unique=True, blank=True)
    description = models.TextField(_("科室简介"), blank=True)
    is_active = models.BooleanField(_("是否启用"), default=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        verbose_name = _("科室")
        verbose_name_plural = _("科室")

    def __str__(self):
        return self.name


class Manufacturer(models.Model):
    """药品生产厂家（供应链）。"""

    name = models.CharField(_("厂家名称"), max_length=100)
    contact_person = models.CharField(
        _("联系人"), max_length=100, blank=True, null=True
    )
    contact_phone = models.CharField(
        _("联系电话"), max_length=50, blank=True, null=True
    )
    address = models.CharField(_("地址"), max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = _("生产厂家")
        verbose_name_plural = _("生产厂家")

    def __str__(self):
        return self.name


class Drug(models.Model):
    name = models.CharField(_("药品名称"), max_length=200)
    generic_name = models.CharField(_("通用名"), max_length=200, blank=True)
    specification = models.CharField(_("规格"), max_length=120)
    unit = models.CharField(_("单位"), max_length=32)
    stock_quantity = models.PositiveIntegerField(_("库存数量"), default=0)
    price = models.DecimalField(
        _("单价"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drugs",
        verbose_name=_("生产厂家"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = _("药品")
        verbose_name_plural = _("药品")

    def __str__(self):
        return f"{self.name} ({self.specification})"


class Schedule(models.Model):
    class Shift(models.TextChoices):
        MORNING = "morning", _("上午 (08:00-12:00)")
        AFTERNOON = "afternoon", _("下午 (14:00-18:00)")

    doctor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="doctor_schedules",
        verbose_name=_("出诊医生"),
        limit_choices_to={"role": UserRole.DOCTOR},
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="schedules",
        verbose_name=_("所属科室"),
    )
    work_date = models.DateField(_("出诊日期"))
    shift = models.CharField(
        _("班次"),
        max_length=20,
        choices=Shift.choices,
        default=Shift.MORNING,
    )
    total_capacity = models.PositiveSmallIntegerField(_("总号源"), default=20)
    is_active = models.BooleanField(_("是否开放预约"), default=True)
    price = models.DecimalField(
        _("挂号费用"),
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    remark = models.CharField(_("备注"), max_length=255, blank=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        verbose_name = _("医生排班")
        verbose_name_plural = _("医生排班")
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "department", "work_date", "shift"],
                name="uniq_schedule_doctor_dept_date_shift",
            )
        ]

    def __str__(self):
        return f"{self.doctor.username} · {self.work_date} · {self.get_shift_display()}"

    def count_effective_appointments(self) -> int:
        """当前排班下非「已取消」的预约数量（用于号源扣减）。"""
        return self.appointments.exclude(
            status=Appointment.Status.CANCELLED
        ).count()

    def get_remaining_capacity(self) -> int:
        """本排班剩余可预约名额（按本排班 total_capacity 计）。"""
        return max(0, int(self.total_capacity) - self.count_effective_appointments())


class AIReport(models.Model):
    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ai_reports",
        verbose_name=_("患者"),
        limit_choices_to={"role": UserRole.PATIENT},
    )
    title = models.CharField(
        _("报告标题"),
        max_length=100,
        null=True,
        blank=True,
    )
    summary = models.TextField(_("摘要"), blank=True)
    patient_summary = models.TextField(
        verbose_name="患者端病情总结",
        null=True,
        blank=True,
    )
    structured_content = models.JSONField(_("结构化内容"), default=dict, blank=True)
    raw_llm_response = models.TextField(_("模型原始回复"), blank=True)
    recommended_department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_recommended_reports",
        verbose_name=_("AI推荐科室"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = _("预问诊报告")
        verbose_name_plural = _("预问诊报告")

    def __str__(self):
        t = (self.title or "").strip()
        return t if t else f"预问诊报告 #{self.pk}"


class Appointment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("待就诊")
        CONFIRMED = "confirmed", _("已确认")
        IN_PROGRESS = "in_progress", _("就诊中")
        COMPLETED = "completed", _("已完成")
        CANCELLED = "cancelled", _("已取消")

    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="patient_appointments",
        verbose_name=_("患者"),
        limit_choices_to={"role": UserRole.PATIENT},
    )
    schedule = models.ForeignKey(
        Schedule,
        on_delete=models.CASCADE,
        related_name="appointments",
        verbose_name=_("对应排班"),
    )
    ai_report = models.ForeignKey(
        AIReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name=_("关联预问诊报告"),
    )
    status = models.CharField(
        _("状态"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    remark = models.CharField(_("患者备注"), max_length=255, blank=True)
    amount_paid = models.DecimalField(
        _("实际支付金额"),
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = _("预约挂号")
        verbose_name_plural = _("预约挂号")

    def __str__(self):
        return f"{self.patient.username} → {self.schedule_id}"


class VitalSign(models.Model):
    """门诊分诊台录入的基础体征（就诊前）。"""

    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name="vital_sign",
        verbose_name=_("关联挂号"),
    )
    temperature = models.FloatField(_("体温"), help_text=_("单位：℃"))
    blood_pressure = models.CharField(_("血压"), max_length=20, help_text=_("如 120/80"))
    heart_rate = models.PositiveIntegerField(_("心率"), help_text=_("次/分钟"))
    recorded_at = models.DateTimeField(_("录入时间"), auto_now=True)

    class Meta:
        verbose_name = _("体征数据")
        verbose_name_plural = _("体征数据")

    def __str__(self):
        return f"体征 #{self.pk} · 挂号 {self.appointment_id}"


class MedicalRecord(models.Model):
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name="medical_record",
        verbose_name=_("关联挂号"),
    )
    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="medical_records_as_patient",
        verbose_name=_("患者"),
        limit_choices_to={"role": UserRole.PATIENT},
    )
    doctor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="medical_records_as_doctor",
        verbose_name=_("接诊医生"),
        limit_choices_to={"role": UserRole.DOCTOR},
    )
    chief_complaint = models.TextField(_("主诉"))
    present_illness = models.TextField(_("现病史"), blank=True)
    diagnosis = models.TextField(_("诊断"))
    treatment_plan = models.TextField(_("处理意见"), blank=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = _("电子病历")
        verbose_name_plural = _("电子病历")

    def __str__(self):
        return f"病历 #{self.pk} · {self.patient.username}"


class Prescription(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("草稿")
        SIGNED = "signed", _("已签署")
        DISPENSED = "dispensed", _("已发药")
        CANCELLED = "cancelled", _("已作废")

    medical_record = models.ForeignKey(
        MedicalRecord,
        on_delete=models.CASCADE,
        related_name="prescriptions",
        verbose_name=_("电子病历"),
    )
    doctor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="prescriptions_as_doctor",
        verbose_name=_("开方医生"),
        limit_choices_to={"role": UserRole.DOCTOR},
    )
    status = models.CharField(
        _("状态"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    notes = models.TextField(_("医嘱说明"), blank=True)
    execution_note = models.CharField(
        _("执行备注"),
        max_length=255,
        blank=True,
        default="",
    )
    executed_at = models.DateTimeField(_("执行时间"), null=True, blank=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = _("处方")
        verbose_name_plural = _("处方")

    def __str__(self):
        return f"处方 #{self.pk}"

    def nurse_stock_sufficient(self) -> bool:
        """护士发药前：所有明细行库存是否充足。"""
        for line in self.lines.all():
            if line.drug.stock_quantity < line.quantity:
                return False
        return True


class PrescriptionLine(models.Model):
    """处方与药品的多对多明细，保证对药品表外键约束。"""

    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("处方"),
    )
    drug = models.ForeignKey(
        Drug,
        on_delete=models.PROTECT,
        related_name="prescription_lines",
        verbose_name=_("药品"),
    )
    quantity = models.PositiveIntegerField(_("数量"))
    dosage_instruction = models.CharField(_("用法用量"), max_length=255)
    remark = models.CharField(_("备注"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("处方明细")
        verbose_name_plural = _("处方明细")

    def __str__(self):
        return f"{self.prescription_id} · {self.drug.name}"


class Order(models.Model):
    """患者侧财务流水（挂号、药费、充值等）。"""

    class OrderType(models.TextChoices):
        REGISTRATION = "REGISTRATION", _("挂号费")
        MEDICINE = "MEDICINE", _("药费")
        RECHARGE = "RECHARGE", _("充值")

    class Status(models.TextChoices):
        PAID = "PAID", _("已支付")
        REFUNDED = "REFUNDED", _("已退款")

    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="orders",
        verbose_name=_("患者"),
        limit_choices_to={"role": UserRole.PATIENT},
    )
    order_type = models.CharField(
        _("订单类型"),
        max_length=20,
        choices=OrderType.choices,
        db_index=True,
    )
    amount = models.DecimalField(_("金额"), max_digits=12, decimal_places=2)
    status = models.CharField(
        _("状态"),
        max_length=20,
        choices=Status.choices,
        default=Status.PAID,
        db_index=True,
    )
    description = models.CharField(_("描述"), max_length=500)
    appointment = models.ForeignKey(
        "Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finance_orders",
        verbose_name=_("关联挂号"),
    )
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finance_orders",
        verbose_name=_("关联处方"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("订单流水")
        verbose_name_plural = _("订单流水")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_order_type_display()} · ￥{self.amount} · {self.patient_id}"


class PurchaseRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("待审批")
        APPROVED = "approved", _("已通过")
        REJECTED = "rejected", _("已驳回")

    drug = models.ForeignKey(
        Drug,
        on_delete=models.CASCADE,
        related_name="purchase_requests",
        verbose_name=_("药品"),
    )
    quantity = models.PositiveIntegerField(_("申请数量"))
    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="purchase_requests_submitted",
        verbose_name=_("申请人"),
        limit_choices_to={"role": UserRole.NURSE},
    )
    reviewer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_requests_reviewed",
        verbose_name=_("审批人"),
        limit_choices_to={"role": UserRole.HEAD_NURSE},
    )
    status = models.CharField(
        _("审批状态"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reason = models.TextField(_("申请原因"), blank=True)
    review_comment = models.TextField(_("审批意见"), blank=True)
    created_at = models.DateTimeField(_("申请时间"), auto_now_add=True)
    reviewed_at = models.DateTimeField(_("审批时间"), null=True, blank=True)

    class Meta:
        verbose_name = _("药品采购申请")
        verbose_name_plural = _("药品采购申请")

    def __str__(self):
        return f"采购申请 #{self.pk} · {self.drug.name}"


class OperationLog(models.Model):
    """管理员等核心操作审计日志。"""

    class ActionType(models.TextChoices):
        CREATE = "CREATE", _("新增")
        UPDATE = "UPDATE", _("修改")
        DELETE = "DELETE", _("删除")
        LOGIN = "LOGIN", _("登录")

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operation_logs",
        verbose_name=_("操作人"),
    )
    action_type = models.CharField(
        _("动作类型"),
        max_length=20,
        choices=ActionType.choices,
        db_index=True,
    )
    module = models.CharField(_("操作模块"), max_length=50)
    description = models.TextField(_("详细描述"))
    ip_address = models.GenericIPAddressField(
        _("IP地址"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("操作时间"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("系统操作日志")
        verbose_name_plural = _("系统操作日志")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_action_type_display()} · {self.module} · {self.created_at}"
