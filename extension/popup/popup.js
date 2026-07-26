/**
 * Extension Popup Logic
 */
document.addEventListener('DOMContentLoaded', async () => {
  const serverStatusEl = document.getElementById('serverStatus');
  const telegramStatusEl = document.getElementById('telegramStatus');
  const telegramBannerEl = document.getElementById('telegramBanner');
  const connectTelegramBtn = document.getElementById('connectTelegramBtn');
  const productUrlInput = document.getElementById('productUrlInput');
  const watchBtn = document.getElementById('watchBtn');
  const useCurrentTabBtn = document.getElementById('useCurrentTabBtn');
  const feedbackEl = document.getElementById('feedback');
  const productListEl = document.getElementById('productList');
  const emptyStateEl = document.getElementById('emptyState');
  const watchCountEl = document.getElementById('watchCount');
  const watchLimitEl = document.getElementById('watchLimit');
  const offlineCardEl = document.getElementById('offlineCard');
  const retryBtn = document.getElementById('retryBtn');
  const openSettingsBtn = document.getElementById('openSettingsBtn');

  // Check active tab URL
  chrome.tabs?.query({ active: true, currentWindow: true }, (tabs) => {
    const activeUrl = tabs[0]?.url || '';
    if (activeUrl.includes('amazon.in/')) {
      useCurrentTabBtn.classList.remove('hidden');
      useCurrentTabBtn.addEventListener('click', () => {
        productUrlInput.value = activeUrl;
      });
    }
  });

  openSettingsBtn.addEventListener('click', () => {
    if (chrome.runtime.openOptionsPage) {
      chrome.runtime.openOptionsPage();
    } else {
      window.open(chrome.runtime.getURL('options/options.html'));
    }
  });

  connectTelegramBtn.addEventListener('click', async () => {
    try {
      const res = await API.requestTelegramLink();
      if (res.deep_link_url) {
        chrome.tabs.create({ url: res.deep_link_url });
      }
    } catch (err) {
      showFeedback('Error generating Telegram link: ' + err.message, true);
    }
  });

  retryBtn.addEventListener('click', refreshState);

  watchBtn.addEventListener('click', async () => {
    const url = productUrlInput.value.trim();
    if (!url) {
      showFeedback('Please enter an Amazon URL.', true);
      return;
    }

    watchBtn.disabled = true;
    showFeedback('Adding product...');

    try {
      await API.addProduct(url);
      productUrlInput.value = '';
      showFeedback('Product added successfully!', false);
      await refreshState();
    } catch (err) {
      showFeedback(err.message, true);
    } finally {
      watchBtn.disabled = false;
    }
  });

  function showFeedback(msg, isError = false) {
    feedbackEl.textContent = msg;
    feedbackEl.className = 'feedback ' + (isError ? 'error' : 'success');
  }

  async function refreshState() {
    // 1. Health check
    const health = await API.checkHealth();
    if (health.status === 'offline') {
      serverStatusEl.innerHTML = '<span class="dot red">●</span> Server: Offline';
      offlineCardEl.classList.remove('hidden');
      telegramStatusEl.innerHTML = '<span class="dot red">●</span> Telegram: Disconnected';
      telegramBannerEl.classList.add('hidden');
      return;
    }

    serverStatusEl.innerHTML = '<span class="dot green">●</span> Server: Online';
    offlineCardEl.classList.add('hidden');

    // 2. Ensure registered & load profile
    await Auth.ensureRegistered();
    let profile = null;
    try {
      profile = await API.getProfile();
    } catch (err) {
      console.warn('Profile fetch error:', err);
    }

    if (profile) {
      if (profile.telegram_linked) {
        telegramStatusEl.innerHTML = '<span class="dot green">●</span> Telegram: Connected';
        telegramBannerEl.classList.add('hidden');
      } else {
        telegramStatusEl.innerHTML = '<span class="dot red">●</span> Telegram: Not Connected';
        telegramBannerEl.classList.remove('hidden');
      }
      watchCountEl.textContent = profile.watch_count;
      watchLimitEl.textContent = profile.watch_limit;
    }

    // 3. Load product list
    try {
      const data = await API.listProducts();
      renderProducts(data.products || []);
    } catch (err) {
      console.error('List products error:', err);
    }
  }

  function renderProducts(products) {
    productListEl.innerHTML = '';
    if (!products || products.length === 0) {
      productListEl.appendChild(emptyStateEl);
      emptyStateEl.classList.remove('hidden');
      return;
    }
    emptyStateEl.classList.add('hidden');

    products.forEach(p => {
      const card = document.createElement('div');
      card.className = 'product-item';

      const isTurbo = p.mode === 'TURBO';

      card.innerHTML = `
        <div class="prod-header">
          <div class="prod-title">${escapeHtml(p.title || ('ASIN: ' + p.asin))}</div>
          <div class="prod-badge">${p.status_emoji} ${p.status_display}</div>
        </div>
        <div class="prod-details">
          <span class="prod-price">${p.price_display}</span>
          <span>Checked ${p.last_checked_display}</span>
        </div>
        <div class="prod-actions">
          <button class="action-btn ${isTurbo ? 'turbo-active' : ''}" data-action="turbo" data-asin="${p.asin}">
            ${isTurbo ? '⚡ Turbo Active' : '⚡ Turbo'}
          </button>
          <button class="action-btn" data-action="check" data-asin="${p.asin}">🔄 Check</button>
          <button class="action-btn" data-action="open" data-url="${p.url}">🔗 Open</button>
          <button class="action-btn" data-action="remove" data-asin="${p.asin}">🗑 Remove</button>
        </div>
      `;

      card.querySelectorAll('.action-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          const act = btn.dataset.action;
          const asin = btn.dataset.asin;
          const url = btn.dataset.url;

          if (act === 'open') {
            chrome.tabs.create({ url });
          } else if (act === 'remove') {
            await API.removeProduct(asin);
            await refreshState();
          } else if (act === 'check') {
            btn.textContent = '⏳ Checking...';
            await API.checkNow(asin);
            await refreshState();
          } else if (act === 'turbo') {
            if (isTurbo) {
              await API.setNormal(asin);
            } else {
              try {
                await API.setTurbo(asin);
              } catch (err) {
                showFeedback(err.message, true);
              }
            }
            await refreshState();
          }
        });
      });

      productListEl.appendChild(card);
    });
  }

  function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Initial refresh & poll interval
  await refreshState();
  setInterval(refreshState, CONFIG.POPUP_REFRESH_INTERVAL_MS);
});
