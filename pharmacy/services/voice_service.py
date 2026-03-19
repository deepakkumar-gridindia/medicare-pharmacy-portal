import requests
from django.conf import settings
from twilio.rest import Client as TwilioClient

from pharmacy.models import CallSession


def start_voice_call(session: CallSession):
    if not session.patient.phone:
        raise ValueError("Patient phone number is required for voice calls.")
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_PHONE_NUMBER:
        raise ValueError("Twilio settings are missing in the environment.")

    client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    call = client.calls.create(
        to="+" + session.patient.phone.lstrip("+"),
        from_=settings.TWILIO_PHONE_NUMBER,
        url=settings.VOICE_BOT_URL + "/call",
        status_callback=settings.VOICE_BOT_URL + "/status",
    )
    session.external_call_sid = call.sid
    session.save(update_fields=["external_call_sid", "updated_at"])
    return call.sid


def refresh_voice_transcript(session: CallSession):
    if not session.external_call_sid:
        return []
    response = requests.get(
        settings.VOICE_BOT_URL + "/transcript/" + session.external_call_sid[-6:],
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("lines", [])
