/**
 * Storage utility wrapping chrome.storage.local
 */
const Storage = {
  async get(key) {
    return new Promise((resolve) => {
      chrome.storage.local.get([key], (result) => {
        resolve(result[key] || null);
      });
    });
  },

  async set(key, value) {
    return new Promise((resolve) => {
      chrome.storage.local.set({ [key]: value }, () => {
        resolve();
      });
    });
  },

  async remove(key) {
    return new Promise((resolve) => {
      chrome.storage.local.remove([key], () => {
        resolve();
      });
    });
  },

  async getBackendUrl() {
    const custom = await this.get('custom_backend_url');
    return custom || CONFIG.BACKEND_URL;
  }
};
