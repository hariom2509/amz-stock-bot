# 🛒 Amazon Stock Watcher (Chrome Extension + Hosted Backend)

A public Amazon.in stock monitoring service with a **Chrome Extension UI** and **Telegram Alerting**.

- **No Python required for end users.**
- **No Docker required for end users.**
- **Chrome does NOT need to remain open.**
- **PC does NOT need to remain on.**
- **Monitoring runs 24/7 on the hosted backend.**

---

## 🚀 Quick Start (Development)

### 1. Start Hosted Backend

```bash
# Clone repo & activate venv
cd amazon-stock-watcher
.venv\Scripts\activate

# Configure environment
cp .env.example .env
# Set TELEGRAM_BOT_TOKEN and BOT_USERNAME in .env

# Run FastAPI backend + Telegram Bot + Monitoring Scheduler
python run.py
```

Backend starts on `http://localhost:8000`. Health check: `http://localhost:8000/health`.

### 2. Load Chrome Extension

1. Open Google Chrome -> `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** -> select `extension/` directory
4. Click extension icon -> Click **Connect Telegram** -> send `/start` to bot in Telegram
5. Paste Amazon product link -> click **Watch**

---

## 🛠 Project Structure

```
amazon-stock-watcher/
├── app/
│   ├── main.py              # FastAPI app + Lifespan context
│   ├── config.py            # Settings validation
│   ├── api/                 # REST API routes & schemas
│   ├── auth/                # Device token registration & auth
│   ├── telegram/            # Deep-link token linking
│   ├── amazon/              # HTTP client & multi-signal parser
│   ├── monitoring/          # Async scheduler & shared watcher
│   ├── alerts/              # Telegram alert manager
│   ├── bot/                 # Telegram bot handlers
│   └── database/            # SQLite schema & repository
├── extension/               # Chrome Manifest V3 extension
│   ├── manifest.json
│   ├── popup/
│   ├── options/
│   └── js/
├── migrations/              # SQL schema migration scripts
├── docs/                    # Architecture & Deployment guides
├── tests/                   # 84 passing pytest suite
├── Dockerfile
├── docker-compose.yml
├── run.py
└── README.md
```

---

## 🧪 Testing

```bash
.venv\Scripts\python -m pytest tests/ -v
```

All 84 tests run locally with 0 failures.
