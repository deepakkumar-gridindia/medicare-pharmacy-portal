from pharmacy.models import CallSession, Patient


def dashboard_metrics():
    patients = Patient.objects.prefetch_related("medications")
    total_patients = patients.count()
    refill_due = sum(
        1 for patient in patients if patient.refill_status in {"DUE SOON", "URGENT", "OVERDUE"}
    )
    calls_made = CallSession.objects.count()
    reports_generated = CallSession.objects.exclude(report_pdf="").count()
    return {
        "total_patients": total_patients,
        "refill_due": refill_due,
        "calls_made": calls_made,
        "reports_generated": reports_generated,
    }


def workflow_snapshot():
    due_patients = [
        patient
        for patient in Patient.objects.prefetch_related("medications")
        if patient.refill_status in {"DUE SOON", "URGENT", "OVERDUE"}
    ][:5]
    active_sessions = CallSession.objects.select_related("patient").filter(status="active")[:5]
    attention_sessions = CallSession.objects.select_related("patient").filter(attention_required=True)[:5]
    return {
        "due_patients": due_patients,
        "active_sessions": active_sessions,
        "attention_sessions": attention_sessions,
    }
