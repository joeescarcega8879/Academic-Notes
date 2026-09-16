// ---------- TWEAKS (persisted via host postMessage) ----------
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "primary": "#1e3a5f",
  "theme": "light",
  "density": "normal",
  "gradeStyle": "pill"
}/*EDITMODE-END*/;

const PRIMARY_OPTIONS = [
  { hex: '#1e3a5f', name: 'Azul institucional' },
  { hex: '#2d4a8c', name: 'Azul real' },
  { hex: '#0f766e', name: 'Verde profundo' },
  { hex: '#7c3aed', name: 'Violeta académico' },
  { hex: '#b91c1c', name: 'Granate' },
];

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16) };
}

function shade(hex, amt) {
  const { r, g, b } = hexToRgb(hex);
  const c = v => Math.max(0, Math.min(255, Math.round(v + amt))).toString(16).padStart(2, '0');
  return '#' + c(r) + c(g) + c(b);
}

function tintBg(hex) {
  const { r, g, b } = hexToRgb(hex);
  return `rgb(${Math.round(r + (255 - r) * 0.92)} ${Math.round(g + (255 - g) * 0.92)} ${Math.round(b + (255 - b) * 0.92)})`;
}

const tweaks = { ...TWEAK_DEFAULTS };

let resolvedVars = {};

// El tema y el color viven en localStorage para sobrevivir a las recargas.
function loadTweaks() {
  try {
    const saved = JSON.parse(localStorage.getItem('gl-tweaks') || 'null');
    if (saved) Object.assign(tweaks, saved);
  } catch (_) { }
}

function applyTweaks() {
  document.documentElement.classList.toggle('theme-dark', tweaks.theme === 'dark');
  document.body.classList.remove('density-compact', 'density-spacious');
  if (tweaks.density === 'compact') document.body.classList.add('density-compact');
  if (tweaks.density === 'spacious') document.body.classList.add('density-spacious');
  document.body.setAttribute('data-grade-style', tweaks.gradeStyle);
  const p = tweaks.primary;
  resolvedVars = {
    '--brand-primary': p,
    '--brand-primary-700': shade(p, -20),
    '--brand-primary-50': tweaks.theme === 'dark' ? shade(p, -40) : tintBg(p),
  };
  Object.keys(resolvedVars).forEach(k => document.documentElement.style.setProperty(k, resolvedVars[k]));
}

function persistTweaks() {
  try {
    localStorage.setItem('gl-tweaks', JSON.stringify({ ...tweaks, resolved: resolvedVars }));
  } catch (_) { }
  try { window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { ...tweaks } }, '*'); } catch (_) { }
}

function setTweak(key, val) {
  tweaks[key] = val;
  applyTweaks();
  renderTweaksPanel();
  persistTweaks();
}

function renderTweaksPanel() {
  const body = document.getElementById('tweaks-body');
  if (!body) return;
  body.innerHTML = `
    <div class="tweak-group">
      <div class="lbl">Color primario</div>
      <div class="swatches">
        ${PRIMARY_OPTIONS.map(opt => `
          <button class="swatch ${tweaks.primary === opt.hex ? 'is-selected' : ''}"
                  title="${opt.name}"
                  style="background:${opt.hex}"
                  data-act="primary" data-val="${opt.hex}"></button>
        `).join('')}
      </div>
    </div>
    <div class="tweak-group">
      <div class="lbl">Tema</div>
      <div class="seg">
        <button class="${tweaks.theme === 'light' ? 'is-selected' : ''}" data-act="theme" data-val="light">Claro</button>
        <button class="${tweaks.theme === 'dark' ? 'is-selected' : ''}" data-act="theme" data-val="dark">Oscuro</button>
      </div>
    </div>
    <div class="tweak-group">
      <div class="lbl">Densidad</div>
      <div class="seg">
        <button class="${tweaks.density === 'compact' ? 'is-selected' : ''}" data-act="density" data-val="compact">Compacta</button>
        <button class="${tweaks.density === 'normal' ? 'is-selected' : ''}" data-act="density" data-val="normal">Normal</button>
        <button class="${tweaks.density === 'spacious' ? 'is-selected' : ''}" data-act="density" data-val="spacious">Amplia</button>
      </div>
    </div>
    <div class="tweak-group">
      <div class="lbl">Estilo de calificación</div>
      <div class="seg">
        <button class="${tweaks.gradeStyle === 'pill' ? 'is-selected' : ''}" data-act="gradeStyle" data-val="pill">Pill</button>
        <button class="${tweaks.gradeStyle === 'bar' ? 'is-selected' : ''}" data-act="gradeStyle" data-val="bar">Barra</button>
        <button class="${tweaks.gradeStyle === 'ring' ? 'is-selected' : ''}" data-act="gradeStyle" data-val="ring">Círculo</button>
      </div>
    </div>
  `;
  body.querySelectorAll('[data-act]').forEach(btn => {
    btn.addEventListener('click', () => setTweak(btn.dataset.act, btn.dataset.val));
  });
}

function setupTweaksPanelProtocol() {
  const panel = document.getElementById('tweaks-panel');
  const fab = document.getElementById('tweaks-fab');
  const closeBtn = document.getElementById('tweaks-close');
  if (!panel) return;

  function open() { panel.classList.add('is-open'); panel.classList.add('was-opened'); }
  function close() {
    panel.classList.remove('is-open');
    try { window.parent.postMessage({ type: '__edit_mode_dismissed' }, '*'); } catch (_) { }
  }

  window.addEventListener('message', (e) => {
    const data = e.data || {};
    if (data.type === '__activate_edit_mode') {
      document.body.classList.add('tweaks-on');
      open();
    } else if (data.type === '__deactivate_edit_mode') {
      document.body.classList.remove('tweaks-on');
      panel.classList.remove('is-open');
      panel.classList.remove('was-opened');
    }
  });
  try { window.parent.postMessage({ type: '__edit_mode_available' }, '*'); } catch (_) { }

  fab.addEventListener('click', open);
  closeBtn.addEventListener('click', close);
}

// ---------- Modals ----------
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add('is-open');
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove('is-open');
}

// ---------- Login interactions ----------
function setupLogin() {
  // El login en Django es un POST normal: el servidor valida credenciales,
  // comprueba el rol (input oculto 'role') y redirige por user.role.
  // El role-picker visual lo gestiona el script inline de login.html.
  const roleCards = document.querySelectorAll('.role-card[data-role]');
  if (!roleCards.length) return;
  roleCards.forEach(c => {
    c.addEventListener('click', () => {
      roleCards.forEach(x => x.classList.toggle('is-selected', x === c));
    });
  });
}

// ---------- Eval table ----------
let editingRow = null;
let pendingDeleteRow = null;

function setupEvalTable() {
  const tbody = document.getElementById('evals-tbody');
  if (!tbody) return;

  tbody.addEventListener('click', (e) => {
    const delBtn = e.target.closest('[data-action="del"]');
    const editBtn = e.target.closest('[data-action="edit"]');
    if (delBtn) {
      const row = delBtn.closest('tr');
      const name = row.dataset.name || 'esta evaluación';
      document.getElementById('confirm-text').textContent =
        `¿Eliminar la evaluación "${name}"? Esta acción no se puede deshacer.`;
      pendingDeleteRow = row;
      openModal('modal-confirm');
    } else if (editBtn) {
      const row = editBtn.closest('tr');
      document.getElementById('eval-modal-title').textContent = 'Editar evaluación';
      document.getElementById('eval-name').value = row.dataset.name || '';
      document.getElementById('eval-grade').value = row.dataset.grade || '';
      document.getElementById('eval-date').value = row.dataset.date || '';
      editingRow = row;
      openModal('modal-eval');
    }
  });

  const addBtn = document.getElementById('add-eval');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      document.getElementById('eval-modal-title').textContent = 'Nueva evaluación';
      document.getElementById('eval-name').value = '';
      document.getElementById('eval-grade').value = '';
      document.getElementById('eval-date').value = '';
      editingRow = null;
      openModal('modal-eval');
    });
  }

  const saveBtn = document.getElementById('eval-save');
  if (saveBtn) {
    saveBtn.addEventListener('click', () => {
      const name = document.getElementById('eval-name').value.trim() || 'Sin título';
      const grade = parseFloat(document.getElementById('eval-grade').value);
      const date = document.getElementById('eval-date').value || '—';
      const g = isNaN(grade) ? '—' : grade.toFixed(1);
      const cls = isNaN(grade) ? '' : (grade >= 7 ? 'ok' : grade >= 5 ? 'warn' : 'bad');

      if (editingRow) {
        editingRow.dataset.name = name;
        editingRow.dataset.grade = isNaN(grade) ? '' : grade;
        editingRow.dataset.date = date;
        editingRow.querySelector('.col-name').textContent = name;
        editingRow.querySelector('.col-grade').innerHTML = `<span class="grade ${cls}">${g}</span>`;
        editingRow.querySelector('.col-date').textContent = date;
      } else {
        const tr = document.createElement('tr');
        tr.dataset.name = name;
        tr.dataset.grade = isNaN(grade) ? '' : grade;
        tr.dataset.date = date;
        tr.innerHTML = `
          <td class="col-name">${escapeHtml(name)}</td>
          <td class="col-grade"><span class="grade ${cls}">${g}</span></td>
          <td class="col-date">${escapeHtml(date)}</td>
          <td>
            <div class="row-actions">
              <button class="btn-ico" data-action="edit" title="Editar"><i data-icon="edit"></i></button>
              <button class="btn-ico danger" data-action="del" title="Eliminar"><i data-icon="trash"></i></button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
        hydrateIcons(tr);
      }
      closeModal('modal-eval');
    });
  }

  const confirmDel = document.getElementById('confirm-delete');
  if (confirmDel) {
    confirmDel.addEventListener('click', () => {
      if (pendingDeleteRow) pendingDeleteRow.remove();
      pendingDeleteRow = null;
      closeModal('modal-confirm');
    });
  }
}

// ---------- Modal close ----------
function setupModalClose() {
  document.querySelectorAll('.modal-backdrop').forEach(b => {
    b.addEventListener('click', (e) => {
      if (e.target === b) b.classList.remove('is-open');
    });
  });
  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.close));
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-backdrop.is-open').forEach(m => m.classList.remove('is-open'));
    }
  });
}

// ---------- Tabs (materia detail) ----------
function setupTabs() {
  document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      document.querySelectorAll('[data-tab]').forEach(t => t.classList.toggle('is-active', t === btn));
      document.querySelectorAll('[data-tab-panel]').forEach(p => {
        p.classList.toggle('is-active', p.dataset.tabPanel === target);
      });
    });
  });
}

// ---------- Utilidades ----------
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---------- Notificaciones (campana del topbar) ----------
function setupNotifications() {
  const roots = document.querySelectorAll('[data-notif]');
  if (!roots.length) return;
  const closeAll = () => roots.forEach(r => r.classList.remove('is-open'));

  roots.forEach(root => {
    const btn = root.querySelector('[data-notif-toggle]');
    if (!btn) return;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const wasOpen = root.classList.contains('is-open');
      closeAll();
      if (!wasOpen) root.classList.add('is-open');
    });
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('[data-notif]')) closeAll();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAll();
  });
}

// ---------- Navegacion movil (cajon lateral) ----------
function setupNavToggle() {
  const btn = document.getElementById('nav-toggle');
  if (!btn) return;
  const scrim = document.getElementById('nav-scrim');
  const close = () => document.body.classList.remove('nav-open');

  btn.addEventListener('click', () => document.body.classList.toggle('nav-open'));
  if (scrim) scrim.addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });
}

// ---------- Init ----------
document.addEventListener('DOMContentLoaded', () => {
  hydrateIcons();
  loadTweaks();
  applyTweaks();
  renderTweaksPanel();
  setupTweaksPanelProtocol();
  setupLogin();
  setupEvalTable();
  setupModalClose();
  setupTabs();
  setupNotifications();
  setupNavToggle();
});
