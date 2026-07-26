# Chrome Web Store Submission Guide

This document outlines the preparation steps for submitting the Amazon Stock Watcher extension to the Chrome Web Store.

---

## 1. Extension Packaging

To build a zip file for submission:

```bash
cd extension
zip -r ../amazon-stock-watcher-extension.zip . -x "*.DS_Store"
```

---

## 2. Permissions & Justification

When submitting to the Chrome Web Store, you must justify requested permissions:

| Permission | Purpose & Justification |
|------------|-------------------------|
| `storage` | Storing anonymous client device token and user preferences locally on the browser. |
| `activeTab` | Reading current Amazon.in tab URL when user clicks "Watch Current Page" in popup. |

### Host Permissions Rationale
- `https://api.yourdomain.com/*`: Communicating with the backend control plane to manage watches and connect Telegram.
- **No `<all_urls>` permission is requested.**

---

## 3. Privacy Policy Requirements

Your privacy policy must disclose:

- **Data Collected**: Anonymous device identifier, Telegram chat ID (when linked), watched Amazon product ASINs and URLs.
- **Data Not Collected**: No browsing history outside active tab URL on user trigger, no personal identity, no passwords, no financial info.
- **Third-Party Data Sharing**: Zero data shared with third parties or advertisers.
- **Data Retention**: Watches remain on backend server until deleted by user or disconnected.

---

## 4. Required Assets

Before publishing, prepare:
- **Icon**: 128x128 PNG (included in `extension/icons/icon128.png`).
- **Store Screenshots**: At least 1 screenshot (1280x800 or 640x400 PNG).
- **Small Tile Icon**: 440x280 PNG.
- **Marquee Promo Tile** (Optional): 1400x560 PNG.
