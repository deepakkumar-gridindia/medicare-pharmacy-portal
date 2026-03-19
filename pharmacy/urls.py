from django.urls import path

from pharmacy.views.pages import (
    active_call,
    dashboard,
    download_report,
    download_transcript,
    excel_sync,
    history_reports,
    patient_list,
    whatsapp_reply_api,
)

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("patients/", patient_list, name="patient_list"),
    path("calls/", active_call, name="active_call"),
    path("calls/<int:session_id>/", active_call, name="active_call"),
    path("history/", history_reports, name="history_reports"),
    path("excel-sync/", excel_sync, name="excel_sync"),
    path("reports/<int:session_id>/download/", download_report, name="download_report"),
    path("transcripts/<int:session_id>/download/", download_transcript, name="download_transcript"),
    path("api/whatsapp/reply/", whatsapp_reply_api, name="whatsapp_reply_api"),
]
