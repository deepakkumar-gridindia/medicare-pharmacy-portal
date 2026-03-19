import requests
from django.conf import settings

from pharmacy.models import CallSession
from pharmacy.services.ai_service import build_prompt
from pharmacy.services.groq_service import opening_message


def sanitized_phone(session: CallSession):
    return session.patient.phone.replace("+", "").replace(" ", "").strip()


def start_whatsapp_session(session: CallSession):
    phone = sanitized_phone(session)
    if not phone:
        raise ValueError("Patient phone number is required for WhatsApp.")

    try:
        requests.post(f"{settings.WHATSAPP_BOT_URL}/wa_clear/{phone}", timeout=30)
    except Exception:
        pass

    opening = opening_message(session)
    clean_opening = opening.replace("[END CALL]", "").strip()
    response = requests.post(
        f"{settings.WHATSAPP_BOT_URL}/wa_send",
        json={"phone": phone, "message": clean_opening, "context": build_prompt(session.patient)},
        timeout=30,
    )
    response.raise_for_status()
    return clean_opening


def refresh_whatsapp_transcript(session: CallSession):
    phone = sanitized_phone(session)
    response = requests.get(f"{settings.WHATSAPP_BOT_URL}/wa_transcript/{phone}", timeout=30)
    response.raise_for_status()
    return response.json().get("lines", [])


def send_whatsapp_closing(session: CallSession):
    phone = sanitized_phone(session)
    closing = f"Thank you {session.patient.name.split()[0]}! Take care and stay healthy. Goodbye!"
    response = requests.post(
        f"{settings.WHATSAPP_BOT_URL}/wa_send",
        json={"phone": phone, "message": closing, "context": ""},
        timeout=30,
    )
    response.raise_for_status()
    return closing
