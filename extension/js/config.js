/**
 * Amazon Stock Watcher - Extension Configuration
 */
const CONFIG = {
  // Backend API Base URL
  // Development: http://localhost:8000
  // Production:  https://api.yourdomain.com
  BACKEND_URL: 'http://localhost:8000',

  // Polling interval for popup status updates (ms)
  POPUP_REFRESH_INTERVAL_MS: 5000,
};

if (typeof module !== 'undefined') {
  module.exports = CONFIG;
}
