/**
 * Authentication Helper - Client Token management
 */
const Auth = {
  /**
   * Get or initialize client token stored locally
   */
  async getClientToken() {
    let token = await Storage.get('client_token');
    if (!token) {
      token = this.generateRandomToken();
      await Storage.set('client_token', token);
    }
    return token;
  },

  /**
   * Generate cryptographically random token string
   */
  generateRandomToken() {
    const array = new Uint8Array(24);
    crypto.getRandomValues(array);
    return Array.from(array, b => b.toString(16).padStart(2, '0')).join('');
  },

  /**
   * Register token with backend server
   */
  async ensureRegistered() {
    const token = await this.getClientToken();
    const baseUrl = await Storage.getBackendUrl();

    try {
      const resp = await fetch(`${baseUrl}/api/v1/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_token: token })
      });
      if (resp.ok) {
        const data = await resp.json();
        await Storage.set('public_id', data.public_id);
        return data;
      }
    } catch (err) {
      console.warn('Backend registration failed, will retry on next call:', err);
    }
    return null;
  }
};
