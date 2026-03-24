from groq import Groq
from django.conf import settings

from pharmacy.models import CallSession
from pharmacy.services.ai_service import build_prompt, fallback_reply


def _client():
    if not settings.GROQ_API_KEY:
        return None
    return Groq(api_key=settings.GROQ_API_KEY)


def _ensure_history(session: CallSession):
    if session.conversation_state:
        return list(session.conversation_state)
    return [{"role": "system", "content": build_prompt(session.patient)}]


def request_agent_reply(session: CallSession, user_message: str):
    history = _ensure_history(session)
    history.append({"role": "user", "content": user_message})
    client = _client()

    if client is None:
        reply = fallback_reply(session.patient, user_message)
    else:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=history,
            temperature=0.7,
            max_tokens=200,
        )
        reply = response.choices[0].message.content

    history.append({"role": "assistant", "content": reply})
    session.conversation_state = history
    session.save(update_fields=["conversation_state", "updated_at"])
    return reply


def opening_message(session: CallSession):
    return request_agent_reply(session, "Start now with STEP 1 greeting only. Nothing else.")
