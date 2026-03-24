from django.contrib import admin

from pharmacy.models import CallMessage, CallSession, Medication, Patient


class MedicationInline(admin.TabularInline):
    model = Medication
    extra = 1


class CallMessageInline(admin.TabularInline):
    model = CallMessage
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("patient_id", "name", "age", "phone", "language", "last_call_remark")
    search_fields = ("patient_id", "name", "phone")
    list_filter = ("language",)
    inlines = [MedicationInline]


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    list_display = ("patient", "drug_name", "dosage", "refill_due", "status")
    list_filter = ("status",)
    search_fields = ("patient__name", "patient__patient_id", "drug_name")


@admin.register(CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display = ("patient", "channel", "status", "attention_required", "started_at", "ended_at")
    list_filter = ("channel", "status", "attention_required")
    search_fields = ("patient__name", "patient__patient_id")
    readonly_fields = ("started_at", "ended_at", "transcript_text", "conversation_state", "external_call_sid", "last_error")
    inlines = [CallMessageInline]
