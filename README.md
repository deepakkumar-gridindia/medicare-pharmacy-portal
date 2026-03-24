# medicare-pharmacy-portal

Project structure:

- `Medicare_Portal/` for the Django portal
- `whatsapp_bot/` for the WhatsApp bot
- `reports/` for generated PDF reports
- `call transcripts/` for generated call transcripts

## Local run

Run Django:

```bash
cd Medicare_Portal
python manage.py runserver 127.0.0.1:8001
```

Run the WhatsApp bot:

```bash
cd whatsapp_bot
python app.py
```

## Deployment

Use the root-level `render.yaml` for Render deployment. It is configured for:

- `Medicare_Portal` as the Django service root
- `whatsapp_bot` as the bot service root
