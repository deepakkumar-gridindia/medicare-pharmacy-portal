import os
import re
import json
import requests
from flask import Flask, request, jsonify
from groq import Groq
from dotenv import load_dotenv
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
STATE_FILE = os.path.join(BASE_DIR, "wa_state.json")

app = Flask(__name__)

VERIFY_TOKEN    = os.getenv("VERIFY_TOKEN",    "medicarebot123")
ACCESS_TOKEN    = os.getenv("WHATSAPP_TOKEN",  "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY",    "")
DJANGO_APP_URL  = os.getenv("DJANGO_APP_URL",  "http://127.0.0.1:8001")

client = Groq(api_key=GROQ_API_KEY)

def normalize_phone(phone):
    return str(phone or "").replace("+", "").replace(" ", "").strip()

# ── Load patient data ─────────────────────────────────────
def load_patients():
    try:
        with open(os.path.join(BASE_DIR, "patients.json"), encoding="utf-8") as f:
            raw_patients = json.load(f)
            return {
                normalize_phone(phone): {
                    **details,
                    "phone": details.get("phone", phone),
                }
                for phone, details in raw_patients.items()
            }
    except:
        return {}


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            payload = json.load(handle)
            return (
                payload.get("conversations", {}),
                payload.get("wa_transcripts", {}),
                set(payload.get("ended_calls", [])),
                payload.get("active_sessions", {}),
            )
    except:
        return {}, {}, set(), {}


def save_state():
    payload = {
        "conversations": conversations,
        "wa_transcripts": wa_transcripts,
        "ended_calls": sorted(ended_calls),
        "active_sessions": active_sessions,
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except:
        pass

# ── In-memory stores ──────────────────────────────────────
conversations, wa_transcripts, ended_calls, active_sessions = load_state()


def conversation_key(phone, session_id=""):
    phone = normalize_phone(phone)
    session_id = str(session_id or "").strip()
    return f"{phone}__session_{session_id}" if session_id else phone


def resolve_active_key(phone, session_id=""):
    phone = normalize_phone(phone)
    if session_id:
        key = conversation_key(phone, session_id)
        active_sessions[phone] = key
        return key
    return active_sessions.get(phone, phone)


def session_id_from_key(key):
    marker = "__session_"
    if marker not in str(key):
        return ""
    return str(key).split(marker, 1)[1]

# ── Build structured prompt (same as dashboard) ───────────
def build_prompt(patient):
    first_name = patient["name"].split()[0]
    last_name = " ".join(patient["name"].split()[1:])
    salutation = "Mr. " + last_name if last_name else first_name
    medications = patient["drugs"]

    drug_reference = ""
    for index, med in enumerate(medications, start=1):
        drug_reference += (
            f"\nDRUG {index}:"
            f"\n  Name       : {med['drug_name']} {med['dosage']}"
            f"\n  Indication : {med['indication']}"
            f"\n  Direction  : {med['direction']}"
            f"\n  Refill due : {med['refill_due'] or ''}"
            f"\n  Prescriber : Dr. {med['prescriber']}"
        )

    steps = (
        f'STEP 1 - GREETING:\n'
        f'Say: "Hello {patient["name"]}, thank you for taking the time to speak with me today from '
        f'MediCare Pharmacy. How have you been doing lately?"\n'
        "=> STOP. Wait for patient reply. Then go to STEP 2.\n\n"
    )

    step_number = 2
    for index, med in enumerate(medications, start=1):
        steps += (
            f"STEP {step_number} - DRUG {index} CONFIRMATION:\n"
            f'Say: "{salutation}, I am here to go over your medications with you today. '
            f'Are you still taking {med["drug_name"]} {med["dosage"]} as directed - {med["direction"]} - '
            f'as prescribed by Dr. {med["prescriber"]}, which is used to help manage your {med["indication"]}?"\n'
            f'=> Add tags: [IND_READ:{med["drug_name"]}] [DIR_READ:{med["drug_name"]}]\n'
            f'=> If YES -> add [GREEN:{med["drug_name"]}]\n'
            f'=> If NO  -> add [RED:{med["drug_name"]}]\n'
            f"=> STOP. Wait for patient reply. Then go to STEP {step_number + 1}.\n\n"
            f"STEP {step_number + 1} - DRUG {index} REFILL:\n"
            f"=> If patient said YES to taking drug:\n"
            f'   Say: "Your refill for {med["drug_name"]} {med["dosage"]} is due on {med["refill_due"] or ""}. '
            f'Would you like us to arrange the refill for you?"\n'
            f"   STOP. Wait for patient reply.\n"
            f"=> If patient said NO to taking drug:\n"
            f'   Say: "Since you are not currently taking {med["drug_name"]}, a refill may not be needed '
            f'right now. However, its refill was due on {med["refill_due"] or ""} - if you do need it in '
            f'future, we can arrange it. Would you like us to keep it on hold?"\n'
            f"   STOP. Wait for patient reply.\n"
            f"=> DO NOT mention any other drug in this message.\n"
            f"=> Then go to STEP {step_number + 2}.\n\n"
        )
        step_number += 2

    steps += (
        f"STEP {step_number} - GENERAL HEALTH:\n"
        f'Say: "Now that we have covered all your medications, how has your overall health been lately, {first_name}?"\n'
        f"=> STOP. Wait for patient reply. Then go to STEP {step_number + 1}.\n\n"
        f"STEP {step_number + 1} - CLOSING:\n"
        'Say: "Is there anything else you would like to discuss or any questions you have for me today?"\n'
        "=> STOP. Wait for patient reply.\n"
        '=> After patient replies with NO / OK / nothing / any short reply:\n'
        '   Close with: "Thank you [first_name]! It was a pleasure speaking with you. Take care and stay healthy. Goodbye!" [END CALL]\n'
        "=> Do NOT ask the health question again.\n"
        "=> Do NOT loop back to any previous step.\n"
        "=> IMMEDIATELY add [END CALL] after closing statement.\n"
    )

    return (
        f'You are a warm pharmacy assistant from MediCare Pharmacy calling {patient["name"]}.\n\n'
        f"PATIENT MEDICATIONS:\n{drug_reference}\n\n"
        f"FOLLOW THIS EXACT SEQUENCE - ONE STEP PER MESSAGE:\n{steps}\n\n"
        "ABSOLUTE RULES:\n"
        "1. Send ONLY ONE STEP per message - never combine two steps\n"
        "2. ALWAYS wait for patient reply before next step\n"
        "3. NEVER ask about Drug 2 until Drug 1 refill is answered\n"
        "4. NEVER jump to health question until ALL drug refills done\n"
        "5. Serious symptoms -> say pharmacist calls back -> [END CALL]\n"
        f'6. Language: {patient["language"]}\n\n'
        'SPECIAL RULE FOR "NOT TAKING" A DRUG:\n'
        "If patient says they are NOT taking a drug:\n"
        '- Reply: "Since you are not currently taking [drug_name], a refill may not be needed right now.\n'
        "  However, your refill was due on [refill_due] - if you do need it in future, please let us know\n"
        '  and we can arrange it for you."\n'
        "- Add [RED:drug_name] tag\n"
        "- Then move to next drug WITHOUT asking separate refill question\n\n"
        "NEW MEDICINE RULE:\n"
        "If patient mentions ANY medicine not in list:\n"
        "- Add [YELLOW:medicine_name] tag in your response\n"
        '- Say: "I have noted that you are taking [medicine_name].\n'
        '  I will make sure our pharmacist is aware of this."\n'
        "- DO NOT treat new medicine as serious symptom unless it's an emergency\n\n"
        "FEVER RULE:\n"
        "Fever alone is NOT a serious symptom - do not escalate.\n"
        "Just note the medicine they are using for it and add [YELLOW:medicine_name].\n\n"
        "TAGS - include silently in your response:\n"
        "[GREEN:drug_name] when patient confirms taking drug\n"
        "[RED:drug_name] when patient says NOT taking drug\n"
        "[YELLOW:drug_name] when patient mentions any new medicine not in list\n"
        "[IND_READ:drug_name] when YOU mention the indication\n"
        "[DIR_READ:drug_name] when YOU mention the direction\n"
        "NEVER show any other tag format."
    )

# ── Clean tags from text ──────────────────────────────────
def clean_message(text):
    if not text: return ""
    clean = re.sub(r'\[[^\]]*\]', '', text).strip()
    clean = re.sub(r'\b(GREEN|RED|YELLOW|IND_READ|DIR_READ|LISTEN)[:\s]*\S*', '', clean).strip()
    clean = clean.replace("END CALL","").strip()
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def has_end_call(text):
    return "[END CALL]" in text or "END CALL" in text.upper()

# ── Transcript helpers ────────────────────────────────────
def save_wa_transcript(key, role, message):
    if key not in wa_transcripts:
        wa_transcripts[key] = []
    line = role + " : " + message
    wa_transcripts[key].append(line)
    try:
        with open(transcript_file(key), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass
    save_state()

# ── Send WhatsApp message ─────────────────────────────────
def send_whatsapp_message(to_number, message):
    to_number = normalize_phone(to_number)
    url     = "https://graph.facebook.com/v18.0/" + PHONE_NUMBER_ID + "/messages"
    headers = {"Authorization":"Bearer "+ACCESS_TOKEN,"Content-Type":"application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to":   to_number,
        "type": "text",
        "text": {"body": message}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        print("Send status:", r.status_code)
        if r.status_code != 200:
            print("Error:", r.text[:200])
        return r.status_code == 200, r.text[:500]
    except Exception as e:
        print("Send error:", e)
        return False, str(e)

# ── Get AI response ───────────────────────────────────────
def get_ai_response(phone, patient_message, key=""):
    phone = normalize_phone(phone)
    key = key or resolve_active_key(phone)
    if key not in conversations:
        # Auto-load patient from patients.json using phone number
        patients = load_patients()
        patient  = patients.get(phone)
        if patient:
            print("✅ Loaded patient from JSON:", patient["name"])
            conversations[key] = [{"role":"system","content":build_prompt(patient)}]
        else:
            print("⚠️ Patient not found for:", phone)
            conversations[key] = [{"role":"system","content":(
                "You are a warm pharmacy assistant from MediCare Pharmacy. "
                "Follow up with the patient about their medications warmly."
            )}]

    conversations[key].append({"role":"user","content":patient_message})
    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=conversations[key],
        temperature=0.7,
        max_tokens=200
    )
    ai_reply = resp.choices[0].message.content
    conversations[key].append({"role":"assistant","content":ai_reply})
    save_state()
    return ai_reply


def get_django_reply(session_id, patient_message):
    response = requests.post(
        DJANGO_APP_URL.rstrip("/") + "/api/whatsapp/reply/",
        json={"session_id": session_id, "message": patient_message},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def transcript_file(key):
    safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", str(key))
    return os.path.join(BASE_DIR, "wa_transcript_" + safe_key + ".txt")

# ── Serious symptoms ──────────────────────────────────────
SERIOUS = ["chest pain","breathless","unconscious","faint","bleeding",
           "severe","emergency","hospital","heart attack","stroke"]

def check_serious(text):
    return any(s in text.lower() for s in SERIOUS)

# ══════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════
@app.route("/", methods=["GET"])
def home():
    return "MediCare WhatsApp Bot is running! 💊"

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook verified!")
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()
    try:
        entry   = data["entry"][0]
        changes = entry["changes"][0]
        value   = changes["value"]
        if "messages" not in value:
            return jsonify({"status":"no message"}), 200

        message      = value["messages"][0]
        from_number  = normalize_phone(message["from"])
        key = resolve_active_key(from_number)
        message_type = message["type"]

        if message_type != "text":
            send_whatsapp_message(from_number,
                "Hi! Please send a text message and I will be happy to assist you.")
            return jsonify({"status":"non-text"}), 200

        patient_text = message["text"]["body"]
        print("From", from_number, ":", patient_text)
        save_wa_transcript(key, "Patient", patient_text)

        if key in ended_calls:
            print("Call already ended for:", from_number)
            return jsonify({"status":"call_ended"}), 200

        if check_serious(patient_text):
            alert = (
                "I am very concerned to hear that! "
                "I am alerting our pharmacist RIGHT NOW — "
                "they will call you back within 15 minutes. "
                "Please stay safe and calm. Goodbye!"
            )
            send_whatsapp_message(from_number, alert)
            save_wa_transcript(key, "Agent  ", alert+" [ESCALATED]")
            conversations.pop(key, None)
            ended_calls.add(key)
            active_sessions.pop(from_number, None)
            save_state()
            return jsonify({"status":"escalated"}), 200

        session_id = session_id_from_key(key)
        if session_id:
            django_payload = get_django_reply(session_id, patient_text)
            ai_reply_clean = (django_payload.get("reply") or "").strip()
            is_end = bool(django_payload.get("ended"))
        else:
            ai_reply_raw   = get_ai_response(from_number, patient_text, key)
            is_end         = has_end_call(ai_reply_raw)
            ai_reply_clean = clean_message(ai_reply_raw)

        send_whatsapp_message(from_number, ai_reply_clean)
        save_wa_transcript(key, "Agent  ", ai_reply_clean)

        if is_end:
            print("Conversation ended for:", from_number)
            conversations.pop(key, None)
            ended_calls.add(key)
            active_sessions.pop(from_number, None)
            save_state()

    except Exception as e:
        print("Error:", e)
        import traceback; traceback.print_exc()

    return jsonify({"status":"ok"}), 200

@app.route("/wa_send", methods=["POST"])
def send_opening_message():
    data    = request.get_json()
    phone   = normalize_phone(data.get("phone", ""))
    message = data.get("message","")
    context = (data.get("context") or "").strip()
    session_id = str(data.get("session_id") or "").strip()
    reset = bool(data.get("reset"))
    key = resolve_active_key(phone, session_id)

    print("wa_send for:", phone)

    if reset:
        conversations.pop(key, None)
        wa_transcripts.pop(key, None)
        ended_calls.discard(key)
        try: open(transcript_file(key), "w").close()
        except: pass
        save_state()

    # Load patient from JSON and set structured prompt
    patients = load_patients()
    patient  = patients.get(phone)
    if context:
        print("✅ Using Django-provided context for:", phone)
        conversations[key] = [{"role":"system","content":context}]
        clean_msg = clean_message(message)
        if clean_msg:
            conversations[key].append({"role":"assistant","content":clean_msg})
    elif patient:
        print("✅ Setting structured prompt for:", patient["name"])
        conversations[key] = [{"role":"system","content":build_prompt(patient)}]
        # Store opening as first assistant turn so bot continues from STEP 2
        clean_msg = clean_message(message)
        if clean_msg:
            conversations[key].append({"role":"assistant","content":clean_msg})
    else:
        print("⚠️ Patient not found for phone:", phone)
        conversations[key] = [{"role":"system","content":(
            "You are a warm pharmacy assistant from MediCare Pharmacy."
        )}]
        clean_msg = clean_message(message)

    success, provider_message = send_whatsapp_message(phone, clean_msg)
    if success:
        save_wa_transcript(key, "Agent  ", clean_msg)
        save_state()
        return jsonify({"status":"sent","phone":phone,"patient":patient["name"] if patient else "unknown","session_key":key})
    else:
        return jsonify({"status":"failed","message":provider_message}), 500

@app.route("/wa_transcript/<phone>", methods=["GET"])
def get_wa_transcript(phone):
    phone = normalize_phone(phone)
    session_id = request.args.get("session_id", "").strip()
    key = resolve_active_key(phone, session_id)
    lines = wa_transcripts.get(key, [])
    if not lines:
        try:
            with open(transcript_file(key), encoding="utf-8") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            if lines:
                wa_transcripts[key] = lines
        except: lines = []
    return jsonify({
        "phone":    phone,
        "session_key": key,
        "lines":    lines,
        "count":    len(lines),
        "is_ended": key in ended_calls
    })

@app.route("/wa_clear/<phone>", methods=["POST"])
def clear_transcript(phone):
    phone = normalize_phone(phone)
    session_id = request.args.get("session_id", "").strip()
    key = resolve_active_key(phone, session_id)
    wa_transcripts.pop(key, None)
    conversations.pop(key, None)
    ended_calls.discard(key)
    if session_id:
        active_sessions[phone] = key
    else:
        active_sessions.pop(phone, None)
    try: open(transcript_file(key), "w").close()
    except: pass
    save_state()
    return jsonify({"status":"cleared","phone":phone,"session_key":key})

@app.route("/conversations", methods=["GET"])
def view_conversations():
    summary = {}
    for key, history in conversations.items():
        summary[key] = {"messages":len(history)-1,"ended":key in ended_calls}
    return jsonify(summary)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print("Starting MediCare WhatsApp Bot on port", port)
    app.run(host="0.0.0.0", port=port, debug=False)
