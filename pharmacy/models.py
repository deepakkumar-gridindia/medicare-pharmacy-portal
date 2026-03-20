from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Patient(TimeStampedModel):
    patient_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    age = models.PositiveIntegerField(null=True, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    language = models.CharField(max_length=64, default="English")
    last_call_remark = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name", "patient_id"]

    def __str__(self):
        return f"{self.patient_id} - {self.name}"

    @property
    def refill_status(self):
        medications = list(self.medications.all())
        if any(m.days_until_refill is not None and m.days_until_refill < 0 for m in medications):
            return "OVERDUE"
        if any(m.days_until_refill is not None and m.days_until_refill <= 3 for m in medications):
            return "URGENT"
        if any(m.days_until_refill is not None and m.days_until_refill <= 7 for m in medications):
            return "DUE SOON"
        return "NORMAL"


class Medication(TimeStampedModel):
    STATUS_CHOICES = [
        ("unknown", "Unknown"),
        ("green", "Taking"),
        ("red", "Not taking"),
        ("yellow", "New medicine"),
    ]
    REFILL_RESPONSE_CHOICES = [
        ("", "Not recorded"),
        ("yes", "Yes"),
        ("no", "No"),
    ]

    patient = models.ForeignKey(
        Patient, related_name="medications", on_delete=models.CASCADE
    )
    drug_name = models.CharField(max_length=255)
    dosage = models.CharField(max_length=128, blank=True)
    indication = models.CharField(max_length=255, blank=True)
    direction = models.CharField(max_length=255, blank=True)
    refill_due = models.DateField(null=True, blank=True)
    indication_read = models.BooleanField(default=False)
    direction_read = models.BooleanField(default=False)
    prescriber = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="unknown")
    last_refill_response = models.CharField(max_length=16, choices=REFILL_RESPONSE_CHOICES, blank=True, default="")
    extra_medicines = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["patient__name", "drug_name", "id"]

    def __str__(self):
        return f"{self.drug_name} {self.dosage}".strip()

    @property
    def days_until_refill(self):
        if not self.refill_due:
            return None
        return (self.refill_due - timezone.localdate()).days


class CallSession(TimeStampedModel):
    CHANNEL_CHOICES = [
        ("Chat", "Chat"),
        ("WhatsApp", "WhatsApp"),
        ("Voice", "Voice"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("escalated", "Escalated"),
    ]

    patient = models.ForeignKey(
        Patient, related_name="call_sessions", on_delete=models.CASCADE
    )
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="draft")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    summary = models.TextField(blank=True)
    transcript_text = models.TextField(blank=True)
    conversation_state = models.JSONField(default=list, blank=True)
    external_call_sid = models.CharField(max_length=64, blank=True)
    last_error = models.TextField(blank=True)
    attention_required = models.BooleanField(default=False)
    report_pdf = models.FileField(upload_to="reports/", blank=True)
    transcript_file = models.FileField(upload_to="transcripts/", blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.patient.name} - {self.channel} - {self.started_at:%d %b %Y %H:%M}"


class CallMessage(TimeStampedModel):
    ROLE_CHOICES = [
        ("agent", "Agent"),
        ("patient", "Patient"),
        ("system", "System"),
    ]

    session = models.ForeignKey(
        CallSession, related_name="messages", on_delete=models.CASCADE
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    message = models.TextField()

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.session_id} - {self.role}"
