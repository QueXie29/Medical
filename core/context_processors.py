from core.models import HospitalSetting


def hospital_portal(request):
    return {"hospital_portal": HospitalSetting.load()}
