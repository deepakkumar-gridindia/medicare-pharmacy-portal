import requests
from django.conf import settings

from pharmacy.models import CallSession


def sanitized_phone(session: CallSession):
    return session.patient.phone.replace("+", "").replace(" ", "").strip()


def start_whatsapp_session(session: CallSession):
    phone = sanitized_phone(session)
    if not phone:
        raise ValueError("Patient phone number is required for WhatsApp.")

    try:
        requests.post(
            f"{settings.WHATSAPP_BOT_URL}/wa_clear/{phone}",
            params={"session_id": session.id},
            timeout=30,
        )
    except Exception:
        pass

    response = requests.post(
        f"{settings.WHATSAPP_BOT_URL}/wa_send",
        json={
            "phone": phone,
            "message": "",
            "context": "",
            "session_id": session.id,
            "reset": True,
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(_friendly_whatsapp_error(response))

    payload = {}
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if payload.get("status") and payload.get("status") != "sent":
        raise RuntimeError(_friendly_whatsapp_error(response))
    return (payload.get("sent_message") or "").strip()


def refresh_whatsapp_transcript(session: CallSession):
    phone = sanitized_phone(session)
    response = requests.get(
        f"{settings.WHATSAPP_BOT_URL}/wa_transcript/{phone}",
        params={"session_id": session.id},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("lines", [])


def send_whatsapp_closing(session: CallSession):
    phone = sanitized_phone(session)
    closing = f"Thank you {session.patient.name.split()[0]}! Take care and stay healthy. Goodbye!"
    response = requests.post(
        f"{settings.WHATSAPP_BOT_URL}/wa_send",
        json={"phone": phone, "message": closing, "context": "", "session_id": session.id, "reset": False},
        timeout=30,
    )
    response.raise_for_status()
    return closing


def _friendly_whatsapp_error(response):
    details = ""
    try:
        details = (response.json().get("message") or response.text or "").strip()
    except ValueError:
        details = (response.text or "").strip()
    details = " ".join(details.split())

    message = (
        "WhatsApp message could not be sent. "
        "Ask the patient to send 'Hi' to your WhatsApp bot number first, "
        "then try again. Meta may block outbound messages if the patient "
        "has not messaged within the last 24 hours."
    )
    if details:
        message = f"{message} Provider response: {details[:220]}"
    return message
