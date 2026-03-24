from django.db import migrations


def move_transcript_paths(apps, schema_editor):
    CallSession = apps.get_model("pharmacy", "CallSession")
    for session in CallSession.objects.exclude(transcript_file=""):
        current_name = str(session.transcript_file)
        if current_name.startswith("transcripts/"):
            session.transcript_file = "call transcripts/" + current_name.split("/", 1)[1]
            session.save(update_fields=["transcript_file"])


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0004_relocate_session_artifacts"),
    ]

    operations = [
        migrations.RunPython(move_transcript_paths, migrations.RunPython.noop),
    ]
