# Generated manually for AIReport.patient_summary

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_delete_aisetting"),
    ]

    operations = [
        migrations.AddField(
            model_name="aireport",
            name="patient_summary",
            field=models.TextField(blank=True, null=True, verbose_name="患者端病情总结"),
        ),
    ]
