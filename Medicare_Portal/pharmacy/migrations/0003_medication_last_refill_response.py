from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0002_callsession_attention_required_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="medication",
            name="last_refill_response",
            field=models.CharField(
                blank=True,
                choices=[("", "Not recorded"), ("yes", "Yes"), ("no", "No")],
                default="",
                max_length=16,
            ),
        ),
    ]
