import json

from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from pharmacy.controllers.call_controller import (
    add_patient_message,
    close_remote_session,
    end_session_now,
    finalize_session,
    _refresh_transcript,
    refresh_remote_session,
    start_session,
)
from pharmacy.forms import CallMessageForm, ExcelUploadForm, StartCallForm
from pharmacy.models import CallMessage, CallSession, Patient
from pharmacy.services.ai_service import build_summary_from_session, parse_tags
from pharmacy.services.dashboard import dashboard_metrics, workflow_snapshot
from pharmacy.services.excel_sync import (
    excel_file_path,
    export_patients_to_excel,
    import_patients_from_excel,
    save_uploaded_excel,
)


def dashboard(request):
    context = {
        "metrics": dashboard_metrics(),
        "patients": Patient.objects.prefetch_related("medications").all(),
        "recent_sessions": CallSession.objects.select_related("patient")[:6],
        "workflow": workflow_snapshot(),
    }
    return render(request, "pharmacy/dashboard.html", context)


def patient_list(request):
    search_query = (request.GET.get("q") or "").strip()
    form = StartCallForm(request.POST or None)
    if request.method == "POST":
        patient = get_object_or_404(Patient, pk=request.POST.get("patient_id"))
        if form.is_valid():
            try:
                session = start_session(patient, form.cleaned_data["channel"])
            except Exception as exc:
                messages.error(request, str(exc))
                return redirect("patient_list")
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
            end_session_now(session)
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


def excel_sync(request):
    form = ExcelUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if "import_default" in request.POST:
            result = import_patients_from_excel()
            messages.success(
                request,
                f"Imported {result['rows']} rows across {result['patients']} patients. "
                f"Removed {result['removed_medications']} stale medication rows and {result['deleted']} stale patients. "
                f"Source file: {excel_file_path().name}.",
            )
            return redirect("excel_sync")
        if "export_default" in request.POST:
            path = export_patients_to_excel()
            messages.success(request, f"Exported current database to {path.name}.")
            return redirect("excel_sync")
        if form.is_valid():
            upload = form.cleaned_data["excel_file"]
            saved_path = save_uploaded_excel(upload)
            result = import_patients_from_excel(saved_path)
            messages.success(
                request,
                f"Imported {result['rows']} rows across {result['patients']} patients. "
                f"Removed {result['removed_medications']} stale medication rows and {result['deleted']} stale patients. "
                f"Updated source file: {saved_path.name}.",
            )
            return redirect("excel_sync")

    return render(request, "pharmacy/excel_sync.html", {"form": ExcelUploadForm()})


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


@csrf_exempt
def whatsapp_reply_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    session_id = payload.get("session_id")
    patient_message = (payload.get("message") or "").strip()
    if not session_id or not patient_message:
        return JsonResponse({"error": "session_id and message are required"}, status=400)

    session = get_object_or_404(CallSession.objects.select_related("patient"), pk=session_id)
    try:
        reply = add_patient_message(session, patient_message)
    except Exception as exc:
        session.last_error = str(exc)
        session.attention_required = True
        session.save(update_fields=["last_error", "attention_required", "updated_at"])
        return JsonResponse({"error": str(exc)}, status=500)

    session.refresh_from_db()
    return JsonResponse(
        {
            "reply": reply,
            "status": session.status,
            "ended": session.status == "completed",
        }
    )


@csrf_exempt
def whatsapp_session_details_api(request, session_id):
    if request.method != "GET":
        return JsonResponse({"error": "GET required"}, status=405)

    session = get_object_or_404(
        CallSession.objects.select_related("patient").prefetch_related("patient__medications"),
        pk=session_id,
    )
    medications = []
    for medication in session.patient.medications.order_by("id"):
        medications.append(
            {
                "name": medication.drug_name,
                "dosage": medication.dosage,
                "indication": medication.indication,
                "direction": medication.direction,
                "refill_due": medication.refill_due.isoformat() if medication.refill_due else "",
                "status": medication.status,
                "recently_added": "patient mentioned" in (medication.indication or "").lower(),
                "last_refill_response": medication.last_refill_response,
            }
        )

    return JsonResponse(
        {
            "session_id": session.id,
            "patient": {
                "patient_id": session.patient.patient_id,
                "name": session.patient.name,
                "phone": session.patient.phone,
                "language": session.patient.language,
                "medications": medications,
            },
        }
    )


@csrf_exempt
def whatsapp_event_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    session_id = payload.get("session_id")
    role = (payload.get("role") or "").strip().lower()
    message = (payload.get("message") or "").strip()
    medication_name = (payload.get("medication_name") or "").strip()
    indication_read = bool(payload.get("indication_read"))
    direction_read = bool(payload.get("direction_read"))
    status_value = (payload.get("status") or "").strip().lower()
    refill_response = (payload.get("refill_response") or "").strip().lower()
    finalize = bool(payload.get("finalize"))

    if not session_id:
        return JsonResponse({"error": "session_id is required"}, status=400)
    if role not in {"agent", "patient", "system", ""}:
        return JsonResponse({"error": "Unsupported role"}, status=400)

    session = get_object_or_404(CallSession.objects.select_related("patient"), pk=session_id)

    if message and role:
        CallMessage.objects.create(session=session, role=role, message=message)

    tag_parts = []
    if medication_name:
        if indication_read:
            tag_parts.append(f"[IND_READ:{medication_name}]")
        if direction_read:
            tag_parts.append(f"[DIR_READ:{medication_name}]")
        if status_value in {"green", "red", "yellow"}:
            tag_parts.append(f"[{status_value.upper()}:{medication_name}]")
    if tag_parts:
        parse_tags(" ".join(tag_parts), session.patient)

    if medication_name and refill_response in {"yes", "no"}:
        medication = session.patient.medications.filter(drug_name__iexact=medication_name).order_by("id").first()
        if medication:
            medication.last_refill_response = refill_response
            medication.save(update_fields=["last_refill_response", "updated_at"])

    _refresh_transcript(session)
    if finalize and session.status != "completed":
        finalize_session(session)
        session.refresh_from_db()

    return JsonResponse(
        {
            "status": session.status,
            "completed": session.status == "completed",
            "message_count": session.messages.count(),
        }
    )
