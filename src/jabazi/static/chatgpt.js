'use strict';
(() => {
  let scannerKey = '', generation = 0;
  const el = id => document.getElementById(id);
  const lock = () => {
    generation++; scannerKey = ''; el('owner-key').value = '';
    el('copy-key').hidden = true; el('lock').hidden = true;
    el('status').textContent = 'Scanner key is locked.';
  };
  async function copy(value) {
    try {await navigator.clipboard.writeText(value); el('status').textContent = 'Copied.';}
    catch {el('status').textContent = 'Clipboard unavailable. Open this page directly in your browser and try again.';}
  }
  el('unlock').onsubmit = async event => {
    event.preventDefault(); const current = ++generation;
    const credential = el('owner-key').value; el('owner-key').value = '';
    scannerKey = ''; el('copy-key').hidden = true; el('lock').hidden = true;
    el('status').textContent = 'Unlocking…';
    try {
      const response = await fetch('/v1/owner/chatgpt-key', {
        method: 'POST', credentials: 'omit', cache: 'no-store',
        headers: {Authorization: `Bearer ${credential}`}
      });
      if (!response.ok) throw new Error('Could not unlock. Check your owner credential and try again.');
      const data = await response.json();
      if (current !== generation) return;
      scannerKey = data.api_key; el('copy-key').hidden = false; el('lock').hidden = false;
      el('status').textContent = 'Ready. Copy the private scanner key into the GPT authentication field.';
    } catch (error) {if (current === generation) el('status').textContent = error.message;}
  };
  el('copy-key').onclick = () => {if (scannerKey) copy(scannerKey);};
  el('copy-schema').onclick = () => copy(`${location.origin}/chatgpt/openapi.json`);
  el('copy-instructions').onclick = () => copy(el('instructions').value);
  el('lock').onclick = lock;
  window.addEventListener('pagehide', lock);
})();
