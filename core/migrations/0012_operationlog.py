# Generated manually for OperationLog

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_aireport_recommended_department"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "action_type",
                    models.CharField(
                        choices=[
                            ("CREATE", "新增"),
                            ("UPDATE", "修改"),
                            ("DELETE", "删除"),
                            ("LOGIN", "登录"),
                        ],
                        db_index=True,
                        max_length=20,
                        verbose_name="动作类型",
                    ),
                ),
                (
                    "module",
                    models.CharField(max_length=50, verbose_name="操作模块"),
                ),
                ("description", models.TextField(verbose_name="详细描述")),
                (
                    "ip_address",
                    models.GenericIPAddressField(
                        blank=True, null=True, verbose_name="IP地址"
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, db_index=True, verbose_name="操作时间"
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="operation_logs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="操作人",
                    ),
                ),
            ],
            options={
                "verbose_name": "系统操作日志",
                "verbose_name_plural": "系统操作日志",
                "ordering": ("-created_at",),
            },
        ),
    ]
