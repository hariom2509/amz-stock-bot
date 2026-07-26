# Amazon Stock Watcher - Chrome Extension

Chrome Manifest V3 extension for watching Amazon product stock availability.

## How to Load in Chrome (Developer Mode)

1. Open Google Chrome.
2. Navigate to `chrome://extensions`.
3. Enable **Developer mode** toggle in the top-right corner.
4. Click **Load unpacked**.
5. Select the `extension/` directory inside this repository.
6. The Amazon Stock Watcher extension icon will appear in your Chrome toolbar.

## Architecture

- **Manifest V3**: Uses modern background service workers and declarative rules.
- **Client Auth**: Generates a random client token stored in `chrome.storage.local`.
- **Backend Control Plane**: Does NOT scrape Amazon in Chrome. Sends URLs to the hosted backend which handles all continuous background polling.
- **Telegram Linking**: Integrates with Telegram deep-linking (`https://t.me/<bot>?start=<token>`) for seamless mobile alerts.
