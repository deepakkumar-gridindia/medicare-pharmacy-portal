from datetime import datetime

from django.utils import timezone
from fpdf import FPDF


def clean_pdf_text(text):
    if not text:
        return ""
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "*",
        "\u2026": "...",
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def generate_pdf_bytes(session):
    class PharmaPDF(FPDF):
        def header(self):
            self.set_fill_color(26, 60, 46)
            self.rect(0, 0, 210, 30, "F")
            self.set_font("Helvetica", "B", 17)
            self.set_text_color(255, 255, 255)
            self.set_y(8)
            self.cell(0, 9, "MediCare Pharmacy", align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_font("Helvetica", "", 9)
            self.cell(
                0,
                5,
                "AI Patient Follow-up Report  |  Channel: " + session.channel,
                align="C",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            self.set_text_color(0, 0, 0)
            self.ln(8)

        def footer(self):
            self.set_y(-14)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(
                0,
                10,
                clean_pdf_text(
                    "Generated: "
                    + datetime.now().strftime("%d %B %Y, %I:%M %p")
                    + "  |  AI-assisted report - pharmacist review required"
                ),
                align="C",
            )

    pdf = PharmaPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=14)

    def section(title):
        pdf.set_fill_color(45, 106, 79)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 10)
        pdf.rect(14, pdf.get_y(), 182, 8, "F")
        pdf.set_xy(16, pdf.get_y() + 1)
        pdf.cell(0, 6, clean_pdf_text(title))
        pdf.ln(10)
        pdf.set_text_color(50, 50, 50)

    patient = session.patient
    pdf.set_fill_color(240, 247, 244)
    pdf.set_draw_color(180, 220, 200)
    pdf.rect(14, pdf.get_y(), 182, 24, "FD")
    pdf.set_xy(16, pdf.get_y() + 3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(26, 60, 46)
    pdf.cell(60, 6, clean_pdf_text("Patient : " + patient.name))
    pdf.cell(40, 6, clean_pdf_text("Age     : " + str(patient.age or "")))
    pdf.cell(70, 6, clean_pdf_text("Date    : " + timezone.localdate().strftime("%d %B %Y")))
    pdf.ln(8)
    pdf.set_x(16)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(60, 6, clean_pdf_text("Phone   : " + patient.phone))
    pdf.cell(60, 6, clean_pdf_text("Channel : " + session.channel))
    pdf.ln(14)

    section("AI Call Summary")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(50, 50, 50)
    for line in (session.summary or "No summary available yet.").splitlines():
        pdf.set_x(16)
        pdf.multi_cell(178, 5, clean_pdf_text(line))
    pdf.ln(4)

    section("Medicine Status Summary")
    fills = {
        "green": (198, 239, 206),
        "red": (255, 199, 206),
        "yellow": (255, 235, 156),
        "unknown": (240, 240, 240),
    }
    labels = {
        "green": "Taking as prescribed",
        "red": "Not taking",
        "yellow": "New medicine",
        "unknown": "Not confirmed",
    }

    for medication in patient.medications.all():
        status_key = medication.status or "unknown"
        pdf.set_fill_color(*fills.get(status_key, (240, 240, 240)))
        pdf.set_draw_color(200, 200, 200)
        pdf.rect(14, pdf.get_y(), 182, 12, "FD")
        pdf.set_xy(16, pdf.get_y() + 2)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(55, 5, clean_pdf_text(f"{medication.drug_name} {medication.dosage}".strip()))
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(50, 5, clean_pdf_text("For: " + medication.indication))
        pdf.cell(45, 5, clean_pdf_text("Status: " + labels.get(status_key, "?")))
        pdf.cell(20, 5, clean_pdf_text("Ind: " + ("Y" if medication.indication_read else "N")))
        pdf.ln(7)
        pdf.set_x(16)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(
            0,
            5,
            clean_pdf_text(
                "Direction: "
                + medication.direction
                + "  |  Refill: "
                + str(medication.refill_due or "")
                + "  |  Dr. "
                + medication.prescriber
                + ("  |  Notes: " + medication.notes if medication.notes else "")
            ),
        )
        pdf.ln(8)
        pdf.set_text_color(50, 50, 50)

    extras = [medication.drug_name for medication in patient.medications.filter(status="yellow")]
    if extras:
        section("New Medicines Mentioned by Patient")
        for med in extras:
            pdf.set_fill_color(255, 235, 156)
            pdf.rect(14, pdf.get_y(), 182, 8, "F")
            pdf.set_xy(16, pdf.get_y() + 1)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 6, clean_pdf_text("+ " + med + "  (not in original prescription - verify with prescriber)"))
            pdf.ln(10)

    section("Full Conversation Transcript")
    pdf.set_font("Courier", "", 8)
    pdf.set_text_color(70, 70, 70)
    for line in session.transcript_text.splitlines():
        if any(line.startswith(prefix) for prefix in ["Agent", "Patient", "System"]):
            pdf.set_x(16)
            pdf.multi_cell(178, 5, clean_pdf_text(line))

    return bytes(pdf.output())
