from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from pharmacy.controllers.call_controller import (
    add_patient_message,
    close_remote_session,
    finalize_session,
    refresh_remote_session,
    start_session,
)
from pharmacy.forms import CallMessageForm, ExcelUploadForm, StartCallForm
from pharmacy.models import CallSession, Patient
from pharmacy.services.ai_service import build_summary_from_session
from pharmacy.services.dashboard import dashboard_metrics, workflow_snapshot
from pharmacy.services.excel_sync import export_patients_to_excel, import_patients_from_excel


@login_required
def dashboard(request):
    context = {
        "metrics": dashboard_metrics(),
        "patients": Patient.objects.prefetch_related("medications").all(),
        "recent_sessions": CallSession.objects.select_related("patient")[:6],
        "workflow": workflow_snapshot(),
    }
    return render(request, "pharmacy/dashboard.html", context)


@login_required
def patient_list(request):
    search_query = (request.GET.get("q") or "").strip()
    form = StartCallForm(request.POST or None)
    if request.method == "POST":
        patient = get_object_or_404(Patient, pk=request.POST.get("patient_id"))
        if form.is_valid():
            session = start_session(patient, form.cleaned_data["channel"])
            return redirect("active_call", session_id=session.id)

    patients = Patient.objects.prefetch_related("medications").all()
    if search_query:
        patients = patients.filter(
            Q(name__icontains=search_query)
            | Q(patient_id__icontains=search_query)
            | Q(phone__icontains=search_query)
        )

    context = {
        "patients": patients,
        "start_form": StartCallForm(),
        "search_query": search_query,
    }
    return render(request, "pharmacy/patient_list.html", context)


@login_required
def active_call(request, session_id=None):
    session = None
    if session_id:
        session = get_object_or_404(
            CallSession.objects.select_related("patient").prefetch_related("messages", "patient__medications"),
            pk=session_id,
        )

    form = CallMessageForm(request.POST or None)
    if request.method == "POST" and session:
        if "refresh_remote" in request.POST:
            try:
                refresh_remote_session(session)
                messages.success(request, f"{session.channel} transcript refreshed.")
            except Exception as exc:
                session.last_error = str(exc)
                session.attention_required = True
                session.save(update_fields=["last_error", "attention_required", "updated_at"])
                messages.error(request, str(exc))
            return HttpResponseRedirect(reverse("active_call", args=[session.id]))
        if "end_call" in request.POST:
            finalize_session(session)
            messages.success(request, "Call completed and report files were generated.")
            return HttpResponseRedirect(reverse("active_call", args=[session.id]))
        if "close_remote" in request.POST:
            try:
                close_remote_session(session)
                messages.success(request, f"{session.channel} session closed.")
            except Exception as exc:
                session.last_error = str(exc)
                session.attention_required = True
                session.save(update_fields=["last_error", "attention_required", "updated_at"])
                messages.error(request, str(exc))
            return HttpResponseRedirect(reverse("active_call", args=[session.id]))
        if form.is_valid():
            try:
                add_patient_message(session, form.cleaned_data["message"])
            except Exception as exc:
                session.last_error = str(exc)
                session.attention_required = True
                session.save(update_fields=["last_error", "attention_required", "updated_at"])
                messages.error(request, str(exc))
            return HttpResponseRedirect(reverse("active_call", args=[session.id]))

    return render(
        request,
        "pharmacy/active_call.html",
        {"session": session, "message_form": CallMessageForm(), "chat_channel": session.channel == "Chat" if session else False},
    )


@login_required
def history_reports(request):
    search_query = (request.GET.get("q") or "").strip()
    session_queryset = CallSession.objects.select_related("patient")
    if search_query:
        session_queryset = session_queryset.filter(
            Q(patient__name__icontains=search_query)
            | Q(patient__patient_id__icontains=search_query)
            | Q(patient__phone__icontains=search_query)
        )

    sessions = list(session_queryset)
    grouped_sessions = {}
    for session in sessions:
        grouped_sessions.setdefault(
            session.patient_id,
            {"patient": session.patient, "sessions": []},
        )
        grouped_sessions[session.patient_id]["sessions"].append(session)

    selected_session = None
    selected_session_id = request.GET.get("session")
    if selected_session_id:
        selected_session = get_object_or_404(
            CallSession.objects.select_related("patient").prefetch_related("messages", "patient__medications"),
            pk=selected_session_id,
        )
    elif sessions:
        selected_session = sessions[0]

    if selected_session and not selected_session.summary:
        selected_session.summary = build_summary_from_session(selected_session)
        selected_session.save(update_fields=["summary", "updated_at"])

    patient_history = []
    for item in grouped_sessions.values():
        patient_sessions = item["sessions"]
        patient_history.append(
            {
                "patient": item["patient"],
                "latest_session": patient_sessions[0],
                "older_sessions": patient_sessions[1:],
            }
        )
    patient_history.sort(key=lambda item: item["patient"].name.lower())

    return render(
        request,
        "pharmacy/history_reports.html",
        {
            "patient_history": patient_history,
            "selected_session": selected_session,
            "search_query": search_query,
        },
    )


@login_required
def excel_sync(request):
    form = ExcelUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if "import_default" in request.POST:
            result = import_patients_from_excel()
            messages.success(request, f"Imported {result['rows']} rows from the default Patient_List file.")
            return redirect("excel_sync")
        if "export_default" in request.POST:
            path = export_patients_to_excel()
            messages.success(request, f"Exported current database to {path.name}.")
            return redirect("excel_sync")
        if form.is_valid():
            upload = form.cleaned_data["excel_file"]
            temp_path = Path(__file__).resolve().parent.parent.parent / Path(upload.name).name
            with open(temp_path, "wb") as file_handle:
                for chunk in upload.chunks():
                    file_handle.write(chunk)
            result = import_patients_from_excel(temp_path)
            temp_path.unlink(missing_ok=True)
            messages.success(request, f"Imported {result['rows']} rows from uploaded Patient_List file.")
            return redirect("excel_sync")

    return render(request, "pharmacy/excel_sync.html", {"form": ExcelUploadForm()})


@login_required
def download_report(request, session_id):
    session = get_object_or_404(CallSession, pk=session_id)
    if not session.report_pdf:
        messages.error(request, "No PDF report is available for this call.")
        return redirect("history_reports")
    return FileResponse(
        session.report_pdf.open("rb"),
        as_attachment=True,
        filename=session.report_pdf.name.split("/")[-1],
    )


@login_required
def download_transcript(request, session_id):
    session = get_object_or_404(CallSession, pk=session_id)
    if not session.transcript_file:
        messages.error(request, "No transcript file is available for this call.")
        return redirect("history_reports")
    return FileResponse(
        session.transcript_file.open("rb"),
        as_attachment=True,
        filename=session.transcript_file.name.split("/")[-1],
    )
