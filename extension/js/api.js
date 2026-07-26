/**
 * REST API Client for Extension
 */
const API = {
  async fetchWithAuth(endpoint, options = {}) {
    const token = await Auth.getClientToken();
    const baseUrl = await Storage.getBackendUrl();

    const headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...(options.headers || {})
    };

    const config = {
      ...options,
      headers
    };

    try {
      const response = await fetch(`${baseUrl}${endpoint}`, config);

      if (response.status === 401) {
        // Re-register if token unassigned
        await Auth.ensureRegistered();
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(errorData.detail || 'API request failed');
      }

      return await response.json();
    } catch (err) {
      if (err.name === 'TypeError' && err.message.includes('fetch')) {
        throw new Error('SERVICE_OFFLINE');
      }
      throw err;
    }
  },

  async checkHealth() {
    const baseUrl = await Storage.getBackendUrl();
    const res = await fetch(`${baseUrl}/health`).catch(() => null);
    if (!res || !res.ok) return { status: 'offline' };
    return await res.json();
  },

  async getProfile() {
    return await this.fetchWithAuth('/api/v1/me');
  },

  async requestTelegramLink() {
    return await this.fetchWithAuth('/api/v1/telegram/link', { method: 'POST' });
  },

  async getTelegramStatus() {
    return await this.fetchWithAuth('/api/v1/telegram/status');
  },

  async disconnectTelegram() {
    return await this.fetchWithAuth('/api/v1/telegram/link', { method: 'DELETE' });
  },

  async listProducts() {
    return await this.fetchWithAuth('/api/v1/products');
  },

  async addProduct(url) {
    return await this.fetchWithAuth('/api/v1/products', {
      method: 'POST',
      body: JSON.stringify({ url })
    });
  },

  async removeProduct(asin) {
    return await this.fetchWithAuth(`/api/v1/products/${asin}`, { method: 'DELETE' });
  },

  async checkNow(asin) {
    return await this.fetchWithAuth(`/api/v1/products/${asin}/check`, { method: 'POST' });
  },

  async setTurbo(asin) {
    return await this.fetchWithAuth(`/api/v1/products/${asin}/turbo`, { method: 'POST' });
  },

  async setNormal(asin) {
    return await this.fetchWithAuth(`/api/v1/products/${asin}/normal`, { method: 'POST' });
  }
};
