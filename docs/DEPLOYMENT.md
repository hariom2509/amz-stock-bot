# Deployment Guide — Amazon Stock Watcher

This guide explains how to deploy the hosted FastAPI backend + Telegram Bot + Scheduler service.

---

## 1. Environment Variables

Create a production `.env` file on your server:

```env
# Required
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHI...
BOT_USERNAME=YourBotUsername

# Database
DATABASE_PATH=data/watcher.db

# API Settings
API_HOST=0.0.0.0
API_PORT=8000
CORS_ALLOWED_ORIGINS=chrome-extension://<EXTENSION_ID>,https://yourdomain.com

# Monitoring Limits
MAX_WATCHES_PER_USER=5
MAX_TURBO_WATCHES_PER_USER=1
NORMAL_CHECK_INTERVAL_SECONDS=30
TURBO_CHECK_INTERVAL_SECONDS=5
MAX_CONCURRENT_CHECKS=3
```

---

## 2. Docker Deployment (Recommended)

### Local / Server Docker Run

```bash
# Build Docker image
docker build -t amazon-stock-watcher .

# Run container with volume persistence
docker run -d \
  --name amazon-watcher \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  --env-file .env \
  amazon-stock-watcher
```

### Docker Compose Run

```bash
docker compose up -d
```

---

## 3. Critical Architecture Constraint

> [!CAUTION]
> **Single Worker Constraint**: The FastAPI application MUST run with `--workers 1` (or `workers=1` in `run.py`).
> Running multiple Uvicorn worker processes will instantiate multiple `MonitoringScheduler` background tasks, resulting in duplicate checks against Amazon.

---

## 4. HTTPS & Reverse Proxy (Nginx + Certbot)

Chrome extensions require HTTPS for host permissions in production.

Nginx configuration snippet:

```nginx
server {
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Obtain SSL certificate via Certbot:
```bash
sudo certbot --nginx -d api.yourdomain.com
```

---

## 5. Free / Low-Cost Hosting Options

1. **Oracle Cloud Always Free (Recommended)**: Ampere A1 Compute VM (4 OCPU, 24 GB RAM, 200 GB Storage) permanently free.
2. **Fly.io**: Free shared instance tier with persistent volume support.
3. **Self-Hosted Raspberry Pi**: 24/7 low-power home server.
