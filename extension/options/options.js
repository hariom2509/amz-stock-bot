document.addEventListener('DOMContentLoaded', async () => {
  const backendUrlInput = document.getElementById('backendUrlInput');
  const saveBtn = document.getElementById('saveBtn');
  const feedbackEl = document.getElementById('feedback');
  const publicIdVal = document.getElementById('publicIdVal');

  const currentUrl = await Storage.getBackendUrl();
  backendUrlInput.value = currentUrl;

  const publicId = await Storage.get('public_id');
  publicIdVal.textContent = publicId || 'Not registered yet';

  saveBtn.addEventListener('click', async () => {
    const val = backendUrlInput.value.trim().replace(/\/$/, '');
    if (!val) return;
    await Storage.set('custom_backend_url', val);
    feedbackEl.textContent = 'Settings saved successfully!';
    setTimeout(() => { feedbackEl.textContent = ''; }, 3000);
  });
});
