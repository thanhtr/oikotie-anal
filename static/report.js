function showMode(name, btn) {
  document.querySelectorAll('[id^="mode-"]').forEach(v => v.style.display = 'none');
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('mode-' + name).style.display = 'block';
  btn.classList.add('active');
}

function showTab(tabId, modeId, btn) {
  const mode = document.getElementById(modeId);
  mode.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  mode.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tabId).classList.add('active');
  btn.classList.add('active');
}

const _sortState = {};
function sortTable(tableId, col) {
  const st = _sortState[tableId] || { c: -1, d: 1 };
  if (st.c === col) st.d *= -1; else { st.c = col; st.d = 1; }
  _sortState[tableId] = st;
  const tbl = document.getElementById(tableId);
  const tb = tbl.querySelector('tbody');
  const rows = Array.from(tb.querySelectorAll('tr'));
  tbl.querySelectorAll('th').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
  tbl.querySelectorAll('th')[col].classList.add(st.d === 1 ? 'sort-asc' : 'sort-desc');
  rows.sort((a, b) => {
    const av = a.cells[col].innerText.replace(/[€ \s,%]/g, '');
    const bv = b.cells[col].innerText.replace(/[€ \s,%]/g, '');
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return (an - bn) * st.d;
    return av.localeCompare(bv, 'fi') * st.d;
  });
  rows.forEach(r => tb.appendChild(r));
}

// ── PWA: service worker + install prompt ──────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  });
}

let _deferredInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  _deferredInstallPrompt = e;
  const btn = document.getElementById('install-btn');
  if (btn) btn.hidden = false;
});

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('install-btn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    if (!_deferredInstallPrompt) return;
    _deferredInstallPrompt.prompt();
    await _deferredInstallPrompt.userChoice;
    _deferredInstallPrompt = null;
    btn.hidden = true;
  });
});

window.addEventListener('appinstalled', () => {
  const btn = document.getElementById('install-btn');
  if (btn) btn.hidden = true;
});
