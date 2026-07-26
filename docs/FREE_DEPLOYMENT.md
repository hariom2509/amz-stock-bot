# 🚀 100% Free 24/7 Deployment Guide (No Credit Card Required)

This guide shows how to host your **Amazon Stock Watcher Telegram Bot** for **$0 forever** without needing a credit card.

---

## How It Works (The 24/7 $0 Trick)

1. **Host on Render (Free Plan)**: Render builds and runs your Docker container for $0.
2. **Keep-Alive via UptimeRobot (Free Plan)**: Render free apps normally pause after 15 minutes of inactivity. We set up UptimeRobot to ping `https://your-app.onrender.com/health` every 4 minutes.
3. **Result**: Render **NEVER sleeps**. Your bot stays online 24/7/365, checking Amazon stock every 3 seconds, even when your PC is turned off!

---

## Step-by-Step Instructions (Takes 3 Minutes)

### Step 1: Push Code to GitHub (or Git)
Make sure your repository is on GitHub.

### Step 2: Deploy on Render ($0)
1. Go to [render.com](https://render.com) and sign up for a **Free Account** (Log in with GitHub — no credit card needed).
2. Click **New +** -> Select **Web Service**.
3. Connect your `amazon-stock-watcher` GitHub repository.
4. Set the following details:
   - **Name**: `amazon-stock-watcher`
   - **Environment**: `Docker`
   - **Instance Type**: `Free` ($0/mo)
5. Scroll down to **Environment Variables** and add:
   - `TELEGRAM_BOT_TOKEN`: `<YOUR_TELEGRAM_BOT_TOKEN>`
   - `BOT_USERNAME`: `price_tracker_by_hari_bot`
   - `FAST_CHECK_INTERVAL_SECONDS`: `3`
6. Click **Create Web Service**.

Render will build your Docker image and deploy it. Within 2 minutes, you will get a free URL like:
`https://amazon-stock-watcher.onrender.com`

---

### Step 3: Enable 24/7 Always-On Mode (No Sleeping)

1. Go to [uptimerobot.com](https://uptimerobot.com) and sign up for a **Free Account** (No credit card needed).
2. Click **Add New Monitor**:
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `Amazon Stock Bot`
   - **URL**: `https://your-app.onrender.com/health` (replace with your Render URL)
   - **Monitoring Interval**: `Every 5 minutes`
3. Click **Create Monitor**.

---

## 🎉 Done!

Your Telegram Bot is now **running 24/7 in the cloud**.
- You can turn off your PC, shut down your laptop, and turn off your Wi-Fi.
- [@price_tracker_by_hari_bot](https://t.me/price_tracker_by_hari_bot) will continue monitoring Amazon every 3 seconds and send alerts directly to your phone!
