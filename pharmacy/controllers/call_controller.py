from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from pharmacy.models import CallMessage, CallSession, Patient
from pharmacy.services.ai_service import build_summary_from_session, parse_tags
from pharmacy.services.groq_service import opening_message, request_agent_reply
from pharmacy.services.reporting import generate_pdf_bytes
from pharmacy.services.voice_service import refresh_voice_transcript, start_voice_call
from pharmacy.services.whatsapp_service import (
    refresh_whatsapp_transcript,
    send_whatsapp_closing,
    start_whatsapp_session,
)


def start_session(patient: Patient, channel: str):
    session = CallSession.objects.create(patient=patient, channel=channel, status="active")
    try:
        if channel == "Chat":
            raw_reply = opening_message(session)
            clean_reply = _clean_agent_message(raw_reply, patient)
            CallMessage.objects.create(session=session, role="agent", message=clean_reply)
        elif channel == "WhatsApp":
            opening = start_whatsapp_session(session)
            clean_reply = _clean_agent_message(opening, patient)
            CallMessage.objects.create(session=session, role="agent", message=clean_reply)
        elif channel == "Voice":
            sid = start_voice_call(session)
            CallMessage.objects.create(
                session=session,
                role="system",
                message="Voice call initiated to +" + patient.phone + f" with SID {sid}",
            )
        _refresh_transcript(session)
    except Exception as exc:
        session.status = "draft"
        session.last_error = str(exc)
        session.attention_required = True
        session.save(update_fields=["status", "last_error", "attention_required", "updated_at"])
        raise
    return session


def add_patient_message(session: CallSession, message: str):
    if session.channel != "Chat":
        raise ValueError("Manual patient replies are only supported for Chat sessions.")

    CallMessage.objects.create(session=session, role="patient", message=message)
    raw_reply = request_agent_reply(session, message)
    clean_reply = _clean_agent_message(raw_reply, session.patient)
    CallMessage.objects.create(session=session, role="agent", message=clean_reply)
    if "[END CALL]" in raw_reply or "END CALL" in raw_reply.upper():
        finalize_session(session, status="completed")
    else:
        _refresh_transcript(session)
    return clean_reply


def refresh_remote_session(session: CallSession):
    if session.channel == "WhatsApp":
        lines = refresh_whatsapp_transcript(session)
    elif session.channel == "Voice":
        lines = refresh_voice_transcript(session)
    else:
        return session

    _replace_messages_from_lines(session, lines)
    _refresh_transcript(session)
    return session


def close_remote_session(session: CallSession):
    if session.channel == "WhatsApp":
        closing = send_whatsapp_closing(session)
        CallMessage.objects.create(session=session, role="agent", message=closing)
    finalize_session(session, status="completed")
    return session


def finalize_session(session: CallSession, status="completed"):
    session.status = status
    session.ended_at = timezone.now()
    _refresh_transcript(session)
    session.summary = build_summary_from_session(session)
    _save_artifacts(session)
    session.patient.last_call_remark = (
        f"AI {session.channel} done at {timezone.localtime(session.ended_at):%d-%b-%Y %H:%M}"
    )
    session.patient.save(update_fields=["last_call_remark", "updated_at"])
    session.save(
        update_fields=[
            "status",
            "ended_at",
            "summary",
            "transcript_text",
            "report_pdf",
            "transcript_file",
            "updated_at",
        ]
    )
    return session


def _refresh_transcript(session: CallSession):
    lines = []
    for item in session.messages.order_by("created_at", "id"):
        lines.append(f"{item.role.title():<8}: {item.message}")
    session.transcript_text = "\n".join(lines)
    session.save(update_fields=["transcript_text", "updated_at"])


@transaction.atomic
def _replace_messages_from_lines(session: CallSession, lines):
    session.messages.all().delete()
    for raw_line in lines:
        if raw_line.startswith("Agent"):
            clean = _clean_agent_message(
                raw_line.replace("Agent   : ", "").replace("Agent  : ", ""),
                session.patient,
            )
            CallMessage.objects.create(session=session, role="agent", message=clean)
        elif raw_line.startswith("Patient"):
            CallMessage.objects.create(
                session=session,
                role="patient",
                message=raw_line.replace("Patient : ", ""),
            )
        elif raw_line.startswith("System"):
            CallMessage.objects.create(
                session=session,
                role="system",
                message=raw_line.replace("System  : ", "").replace("System : ", ""),
            )


def _save_artifacts(session: CallSession):
    timestamp = timezone.localtime(session.started_at).strftime("%Y%m%d_%H%M%S")
    transcript_name = f"transcript_{session.patient.patient_id}_{session.channel}_{timestamp}.txt"
    report_name = f"report_{session.patient.patient_id}_{session.channel}_{timestamp}.pdf"
    transcript = (
        f"PATIENT : {session.patient.name}\n"
        f"CHANNEL : {session.channel}\n"
        f"DATE    : {timezone.localdate():%d %B %Y}\n"
        + "=" * 45
        + "\n\n"
        + session.transcript_text
    )
    session.transcript_file.save(transcript_name, ContentFile(transcript.encode("utf-8")), save=False)
    session.report_pdf.save(report_name, ContentFile(generate_pdf_bytes(session)), save=False)


def _clean_agent_message(raw_text, patient):
    clean_text, _ = parse_tags(raw_text, patient)
    return clean_text.strip()
