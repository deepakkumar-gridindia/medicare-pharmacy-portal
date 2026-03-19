# medicare-pharmacy-portal
medicare-pharmacy-portal in django

## Local services

This repo now contains both:

- the Django portal at the repo root
- the WhatsApp bot in `whatsapp_bot/`

Run Django:

```bash
python manage.py runserver 127.0.0.1:8001
```

Run the WhatsApp bot:

```bash
cd whatsapp_bot
python app.py
```

By default, Django uses `http://127.0.0.1:5001` for `WHATSAPP_BOT_URL`.
In production, set `WHATSAPP_BOT_URL` to your deployed WhatsApp bot service URL.
