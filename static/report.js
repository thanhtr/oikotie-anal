var _activeMode = 'tram';

function showMode(name, btn) {
  document.querySelectorAll('[id^="mode-"]').forEach(v => v.style.display = 'none');
  document.querySelectorAll('.topbar-modes .seg-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('mode-' + name).style.display = 'block';
  btn.classList.add('active');
  document.querySelectorAll('.crit-panel').forEach(p => p.classList.remove('active'));
  var cp = document.getElementById('crit-' + name);
  if (cp) cp.classList.add('active');
  _activeMode = name;
}

function showTab(tabId, modeId, btn) {
  const mode = document.getElementById(modeId);
  mode.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  mode.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tabId).classList.add('active');
  btn.classList.add('active');
}

function openFilters() {
  document.getElementById('filters-scrim').style.display = 'block';
  document.getElementById('filters-sheet').style.display = 'block';
  document.querySelectorAll('.crit-panel').forEach(p => p.classList.remove('active'));
  var cp = document.getElementById('crit-' + _activeMode);
  if (cp) cp.classList.add('active');
}

function closeFilters() {
  document.getElementById('filters-scrim').style.display = 'none';
  document.getElementById('filters-sheet').style.display = 'none';
}

function toggleDark() {
  var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('oikotie-theme', next);
}

function toggleRisks(mode) {
  var btn = document.getElementById('risks-btn-' + mode);
  var body = document.getElementById('risks-body-' + mode);
  if (!btn || !body) return;
  var opening = body.hidden;
  body.hidden = !opening;
  if (opening) btn.classList.add('open'); else btn.classList.remove('open');
  btn.setAttribute('aria-expanded', opening ? 'true' : 'false');
}

function toggleDetails(id) {
  var body = document.getElementById(id);
  var btn  = document.getElementById('btn-' + id);
  var open = !body.hidden;
  body.hidden = open;
  btn.querySelector('.details-label').textContent = open ? 'Details' : 'Hide details';
  if (open) btn.classList.remove('open'); else btn.classList.add('open');
}

const _sortState = {};
function sortTable(tableId, col) {
  const st = _sortState[tableId] || { c: -1, d: 1 };
  if (st.c === col) st.d *= -1; else { st.c = col; st.d = 1; }
  _sortState[tableId] = st;
  const tbl = document.getElementById(tableId);
  const tb  = tbl.querySelector('tbody');
  const rows = Array.from(tb.querySelectorAll('tr'));
  tbl.querySelectorAll('th').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
  tbl.querySelectorAll('th')[col].classList.add(st.d === 1 ? 'sort-asc' : 'sort-desc');
  rows.sort((a, b) => {
    const av = a.cells[col].innerText.replace(/[€\s#·,%]/g, '');
    const bv = b.cells[col].innerText.replace(/[€\s#·,%]/g, '');
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return (an - bn) * st.d;
    return av.localeCompare(bv, 'fi') * st.d;
  });
  rows.forEach(r => tb.appendChild(r));
}

// Default to table view on wide screens (user can still toggle back to cards)
(function () {
  if (window.innerWidth < 880) return;
  var tabMap = {
    tram:     { modeId: 'mode-tram',     tableTabId: 'tab-tram-table' },
    uusimaa:  { modeId: 'mode-uusimaa',  tableTabId: 'tab-uu-table'  },
    newbuild: { modeId: 'mode-newbuild', tableTabId: 'tab-nb-table'  },
  };
  Object.values(tabMap).forEach(function (t) {
    var modeEl = document.getElementById(t.modeId);
    if (!modeEl) return;
    modeEl.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    modeEl.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
    var tp = document.getElementById(t.tableTabId);
    if (tp) tp.classList.add('active');
    modeEl.querySelectorAll('.view-btn[data-view="table"]').forEach(b => b.classList.add('active'));
  });
})();

// ── PWA ───────────────────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  });
}
