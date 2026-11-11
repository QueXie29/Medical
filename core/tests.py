import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.forms import SchedulePublishForm
from core.models import Department, Schedule, User, UserRole
from core.schedule_utils import is_schedule_shift_available


def fixed_local_dt(hour, minute=0):
    return timezone.make_aware(
        datetime.datetime(2026, 5, 14, hour, minute),
        timezone.get_current_timezone(),
    )


class ScheduleShiftAvailabilityTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            name="内科",
            code="internal",
            is_active=True,
        )
        self.doctor = User.objects.create_user(
            username="doc1",
            password="123456",
            role=UserRole.DOCTOR,
            department=self.department,
            is_active=True,
        )
        self.patient = User.objects.create_user(
            username="patient1",
            password="123456",
            role=UserRole.PATIENT,
            balance=Decimal("100.00"),
        )

    @patch("core.schedule_utils.timezone.localtime")
    def test_morning_shift_expires_after_noon(self, mocked_localtime):
        mocked_localtime.return_value = fixed_local_dt(14, 30)

        work_date = datetime.date(2026, 5, 14)

        self.assertFalse(is_schedule_shift_available(work_date, "morning"))
        self.assertTrue(is_schedule_shift_available(work_date, "afternoon"))
        self.assertTrue(
            is_schedule_shift_available(
                datetime.date(2026, 5, 15),
                "morning",
            )
        )

    @patch("core.schedule_utils.timezone.localtime")
    def test_admin_cannot_publish_expired_same_day_morning_shift(
        self,
        mocked_localtime,
    ):
        mocked_localtime.return_value = fixed_local_dt(14, 30)

        form = SchedulePublishForm(
            data={
                "department": str(self.department.pk),
                "doctor": str(self.doctor.pk),
                "work_date": "2026-05-14",
                "shift": Schedule.Shift.MORNING,
                "total_capacity": "20",
                "price": "20.00",
                "is_active": "on",
                "remark": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("12:00", str(form.errors))

    @patch("core.schedule_utils.timezone.localtime")
    def test_patient_cannot_book_expired_same_day_morning_shift(
        self,
        mocked_localtime,
    ):
        mocked_localtime.return_value = fixed_local_dt(14, 30)
        schedule = Schedule.objects.create(
            department=self.department,
            doctor=self.doctor,
            work_date=datetime.date(2026, 5, 14),
            shift=Schedule.Shift.MORNING,
            total_capacity=20,
            price=Decimal("20.00"),
            is_active=True,
        )
        self.client.force_login(self.patient)

        response = self.client.get(
            reverse("core:patient_appointment_book", kwargs={"schedule_id": schedule.pk})
        )

        self.assertContains(response, "该班次已不可预约")
