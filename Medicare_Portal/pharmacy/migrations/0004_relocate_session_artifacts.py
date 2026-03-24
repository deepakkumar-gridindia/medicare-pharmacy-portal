from django.db import migrations, models

import pharmacy.storage


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0003_medication_last_refill_response"),
    ]

    operations = [
        migrations.AlterField(
            model_name="callsession",
            name="report_pdf",
            field=models.FileField(blank=True, storage=pharmacy.storage.ProjectRootStorage(), upload_to="reports/"),
        ),
        migrations.AlterField(
            model_name="callsession",
            name="transcript_file",
            field=models.FileField(blank=True, storage=pharmacy.storage.ProjectRootStorage(), upload_to="call transcripts/"),
        ),
    ]
