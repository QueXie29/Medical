# Generated manually for AIReport.recommended_department

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_schedule_shift_two_only"),
    ]

    operations = [
        migrations.AddField(
            model_name="aireport",
            name="recommended_department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ai_recommended_reports",
                to="core.department",
                verbose_name="AI推荐科室",
            ),
        ),
    ]
