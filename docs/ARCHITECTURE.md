# Technical Architecture — Amazon Stock Watcher

```
                     INTERNET

                        │
          ┌─────────────┴─────────────┐
          │                           │
          ▼                           ▼

   Chrome Extension              Telegram
   Public Client                 User Phone

          │                           ▲
          │ HTTPS REST API            │ Alert
          ▼                           │

  ┌──────────────────────────────────────────┐
  │             HOSTED BACKEND               │
  │                                          │
  │ FastAPI REST API                         │
  │ Device Auth & Linking Service            │
  │ Telegram Bot (python-telegram-bot)       │
  │ MonitoringScheduler (asyncio loop)       │
  │ ProductWatcher (Multi-signal parser)     │
  │ Shared Product Repository (SQLite WAL)   │
  └───────────────────┬──────────────────────┘
                      │
                      │ HTTP GET
                      ▼
                  Amazon.in
```

---

## Design Principles

1. **Control Plane vs Monitoring Engine**: The Chrome extension is strictly a UI control plane. It does NOT poll Amazon. The hosted backend owns all monitoring.
2. **Shared ASIN Model**: When 1,000 users watch the same ASIN, the backend polls Amazon ONCE. Stock transitions fan out alerts to all subscribed user Telegram chats independently.
3. **Event-Based Alerting**: Telegram alerts trigger on `OUT_OF_STOCK -> IN_STOCK` state transitions. Persistent `alert_sent_for_current_stock_state` flags prevent duplicate alerts across process restarts.
4. **Adaptive Backoff**: Failed checks or Amazon CAPTCHA pages trigger exponential backoff up to 300s. Blocks do NOT override confirmed in-stock status.
5. **Single Event Loop**: FastAPI, Telegram Bot polling, and the MonitoringScheduler run in a single Python process on one `asyncio` event loop.
