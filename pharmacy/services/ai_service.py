import re

from pharmacy.models import Medication, Patient

SERIOUS_KEYWORDS = [
    "chest pain",
    "breathless",
    "unconscious",
    "faint",
    "bleeding",
    "severe",
    "emergency",
    "hospital",
    "heart attack",
    "stroke",
]


def is_serious(text):
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in SERIOUS_KEYWORDS)


def build_prompt(patient: Patient):
    first_name = patient.name.split()[0]
    last_name = " ".join(patient.name.split()[1:])
    salutation = "Mr. " + last_name if last_name else first_name
    medications = list(patient.medications.all())

    drug_reference = ""
    for index, med in enumerate(medications, start=1):
        drug_reference += (
            f"\nDRUG {index}:"
            f"\n  Name       : {med.drug_name} {med.dosage}"
            f"\n  Indication : {med.indication}"
            f"\n  Direction  : {med.direction}"
            f"\n  Refill due : {med.refill_due or ''}"
            f"\n  Prescriber : Dr. {med.prescriber}"
        )

    steps = (
        f'STEP 1 - GREETING:\n'
        f'Say: "Hello {patient.name}, thank you for taking the time to speak with me today from '
        f'MediCare Pharmacy. How have you been doing lately?"\n'
        "=> STOP. Wait for patient reply. Then go to STEP 2.\n\n"
    )

    step_number = 2
    for index, med in enumerate(medications, start=1):
        steps += (
            f"STEP {step_number} - DRUG {index} CONFIRMATION:\n"
            f'Say: "{salutation}, I am here to go over your medications with you today. '
            f'Are you still taking {med.drug_name} {med.dosage} as directed - {med.direction} - '
            f'as prescribed by Dr. {med.prescriber}, which is used to help manage your {med.indication}?"\n'
            f"=> Add tags: [IND_READ:{med.drug_name}] [DIR_READ:{med.drug_name}]\n"
            f"=> If YES -> add [GREEN:{med.drug_name}]\n"
            f"=> If NO  -> add [RED:{med.drug_name}]\n"
            f"=> STOP. Wait for patient reply. Then go to STEP {step_number + 1}.\n\n"
            f"STEP {step_number + 1} - DRUG {index} REFILL:\n"
            f"=> If patient said YES to taking drug:\n"
            f'   Say: "Your refill for {med.drug_name} {med.dosage} is due on {med.refill_due or ""}. '
            f'Would you like us to arrange the refill for you?"\n'
            f"   STOP. Wait for patient reply.\n"
            f"=> If patient said NO to taking drug:\n"
            f'   Say: "Since you are not currently taking {med.drug_name}, a refill may not be needed '
            f'right now. However, its refill was due on {med.refill_due or ""} - if you do need it in '
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
        f"You are a warm pharmacy assistant from MediCare Pharmacy calling {patient.name}.\n\n"
        f"PATIENT MEDICATIONS:\n{drug_reference}\n\n"
        f"FOLLOW THIS EXACT SEQUENCE - ONE STEP PER MESSAGE:\n{steps}\n\n"
        "ABSOLUTE RULES:\n"
        "1. Send ONLY ONE STEP per message - never combine two steps\n"
        "2. ALWAYS wait for patient reply before next step\n"
        "3. NEVER ask about Drug 2 until Drug 1 refill is answered\n"
        "4. NEVER jump to health question until ALL drug refills done\n"
        "5. Serious symptoms -> say pharmacist calls back -> [END CALL]\n"
        f"6. Language: {patient.language}\n\n"
        'SPECIAL RULE FOR "NOT TAKING" A DRUG:\n'
        "If patient says they are NOT taking a drug:\n"
        '- Reply: "Since you are not currently taking [drug_name], a refill may not be needed right now.\n'
        "  However, your refill was due on [refill_due] - if you do need it in future, please let us know\n"
        '  and we can arrange it for you."\n'
        "- Add [RED:drug_name] tag\n"
        "- Then move to next drug WITHOUT asking separate refill question\n\n"
        "NEW MEDICINE RULE:\n"
        "If patient mentions ANY medicine not in their prescription list:\n"
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


def parse_tags(text, patient: Patient):
    updated = False
    normalized_text = _normalize_text(text)

    def find_tags(tag_name):
        bracketed = re.findall(r"\[" + tag_name + r":([^\]]+)\]", text or "", flags=re.IGNORECASE)
        inline = re.findall(r"\b" + tag_name + r":([^\]\n]+)", text or "", flags=re.IGNORECASE)
        values = bracketed or inline
        cleaned = []
        for value in values:
            normalized = re.sub(r"\s+", " ", value).strip(" \t\r\n,.;:-")
            if normalized:
                cleaned.append(normalized)
        return cleaned

    cleanup_new_medicine_artifacts(patient)

    for tag_name, status in [("GREEN", "green"), ("RED", "red")]:
        for drug_name in find_tags(tag_name):
            for medication in patient.medications.all():
                if drug_name.lower() in medication.drug_name.lower() or medication.drug_name.lower() in drug_name.lower():
                    medication.status = status
                    medication.save(update_fields=["status", "updated_at"])
                    updated = True

    for drug_name in find_tags("IND_READ"):
        for medication in patient.medications.all():
            if drug_name.lower() in medication.drug_name.lower() or medication.drug_name.lower() in drug_name.lower():
                medication.indication_read = True
                medication.save(update_fields=["indication_read", "updated_at"])
                updated = True

    for drug_name in find_tags("DIR_READ"):
        for medication in patient.medications.all():
            if drug_name.lower() in medication.drug_name.lower() or medication.drug_name.lower() in drug_name.lower():
                medication.direction_read = True
                medication.save(update_fields=["direction_read", "updated_at"])
                updated = True

    for medication in patient.medications.exclude(status="yellow"):
        drug_mentioned = _normalize_text(medication.drug_name) in normalized_text if medication.drug_name else False
        if drug_mentioned and medication.indication and _normalize_text(medication.indication) in normalized_text:
            if not medication.indication_read:
                medication.indication_read = True
                medication.save(update_fields=["indication_read", "updated_at"])
                updated = True
        if drug_mentioned and medication.direction and _normalize_text(medication.direction) in normalized_text:
            if not medication.direction_read:
                medication.direction_read = True
                medication.save(update_fields=["direction_read", "updated_at"])
                updated = True

    for medication_name in find_tags("YELLOW"):
        normalized_name = re.sub(r"\s+", " ", medication_name).strip()
        existing_yellow = patient.medications.filter(
            status="yellow",
            drug_name__iexact=normalized_name,
        ).first()
        if existing_yellow is None:
            Medication.objects.create(
                patient=patient,
                drug_name=normalized_name.title(),
                dosage="",
                indication="Patient mentioned a new medicine during follow-up",
                direction="Patient-reported",
                prescriber="",
                notes=f"New medicine: {normalized_name.title()}",
                status="yellow",
                extra_medicines=[normalized_name.title()],
            )
            updated = True

    clean = re.sub(r"\[?(GREEN|RED|YELLOW|IND_READ|DIR_READ):[^\]\s\n,\.]+\]?", "", text or "")
    clean = re.sub(r"\[(GREEN|RED|YELLOW|IND_READ|DIR_READ):[^\]]+\]", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\[[A-Z_\s]+:[^\]]*\]", "", clean)
    clean = re.sub(r"\[END\s+CALL\]", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bEND\s+CALL\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\[[A-Z_]+\]", "", clean)
    clean = re.sub(r"\s{2,}", " ", clean)
    return clean.strip(), updated


def fallback_reply(patient: Patient, latest_message: str):
    if is_serious(latest_message):
        return (
            "I am very concerned. I am flagging this for our pharmacist, who will call you back "
            "within 15 minutes. Please stay safe. [END CALL]"
        )

    medication = patient.medications.filter(status="unknown").order_by("id").first()
    if medication is None:
        medication = patient.medications.order_by("id").first()

    first_name = patient.name.split()[0]
    if medication:
        return (
            f"Hello {first_name}, are you still taking {medication.drug_name} {medication.dosage} as directed "
            f"for {medication.indication}? [IND_READ:{medication.drug_name}] [DIR_READ:{medication.drug_name}]"
        )
    return f"Thank you {first_name}. We have covered your medications for today. [END CALL]"


def build_summary_from_session(session):
    patient = session.patient
    taking = []
    not_taking = []
    new_medicines = []
    open_issues = []

    for medication in patient.medications.all():
        label = f"{medication.drug_name} {medication.dosage}".strip()
        if medication.status == "green":
            taking.append(label)
        elif medication.status == "red":
            not_taking.append(label)
        elif medication.status == "yellow":
            new_medicines.append(label)

    for line in session.transcript_text.splitlines():
        lowered = line.lower()
        if line.startswith("Patient") and any(keyword in lowered for keyword in ["fever", "pain", "weak", "cough", "issue", "problem"]):
            open_issues.append(line.replace("Patient :", "").strip())

    summary_lines = [
        "Call Details",
        f"Patient: {patient.name} ({patient.patient_id})",
        f"Call Type: {session.channel}",
        f"Started: {session.started_at:%d %b %Y %H:%M}",
        f"Completed: {session.ended_at:%d %b %Y %H:%M}" if session.ended_at else "Completed: In progress",
        "",
        "Patient Details",
        f"Age: {patient.age or '-'}",
        f"Phone: {patient.phone or '-'}",
        f"Language: {patient.language or '-'}",
        "",
        "Previously Prescribed Medicines",
    ]

    medications = list(patient.medications.exclude(status="yellow"))
    if medications:
        for medication in medications:
            summary_lines.append(
                f"- {medication.drug_name} {medication.dosage}".strip()
                + f" | Direction: {medication.direction or '-'}"
                + f" | Prescriber: Dr. {medication.prescriber or '-'}"
                + f" | Status after call: {medication.get_status_display()}"
            )
    else:
        summary_lines.append("- No prescribed medicines recorded")

    summary_lines.extend(["", "Medicine Use Status"])
    summary_lines.append("- Using: " + (", ".join(taking) if taking else "None confirmed"))
    summary_lines.append("- Not using: " + (", ".join(not_taking) if not_taking else "None reported"))
    summary_lines.append("- New medicines: " + (", ".join(new_medicines) if new_medicines else "None"))

    summary_lines.extend(["", "New Issues or Patient Updates"])
    if open_issues:
        for issue in open_issues:
            summary_lines.append(f"- {issue}")
    else:
        summary_lines.append("- No new issue was clearly mentioned.")

    return "\n".join(summary_lines)


def cleanup_new_medicine_artifacts(patient: Patient):
    for medication in patient.medications.exclude(status="yellow"):
        original_notes = medication.notes or ""
        cleaned_parts = [
            part.strip()
            for part in original_notes.split("|")
            if part.strip()
            and not part.strip().lower().startswith("new medicine:")
            and not part.strip().lower().startswith("new medicine mentioned:")
        ]
        cleaned_notes = " | ".join(cleaned_parts)
        if cleaned_notes != original_notes or medication.extra_medicines:
            medication.notes = cleaned_notes
            medication.extra_medicines = []
            medication.save(update_fields=["notes", "extra_medicines", "updated_at"])


def _normalize_text(value):
    cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()
