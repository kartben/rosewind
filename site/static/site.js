/*
 * SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * Theme toggle, install tabs, shell switch and copy buttons on every page;
 * live search, category and license filters and the detail panel on the
 * catalog. The catalog is fully rendered by the generator; this script
 * filters, reorders and highlights it.
 */
(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* theme */
  const root = document.documentElement;
  $('#theme')?.addEventListener('click', () => {
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('cm-theme', root.dataset.theme); } catch (e) { /* storage unavailable */ }
  });

  /* shell preference: Windows visitors see PowerShell first */
  let shell = /Win/.test(navigator.platform || navigator.userAgent) ? 'windows' : 'unix';
  try { shell = localStorage.getItem('cm-shell') || shell; } catch (e) { /* storage unavailable */ }
  function applyShell(scope) {
    $$('.os-switch button', scope).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.os === shell)));
    $$('pre[data-os]', scope).forEach(p => { p.hidden = p.dataset.os !== shell; });
  }
  applyShell(document);

  /* toast + clipboard */
  let toastTimer;
  function toast(text) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = text;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 1800);
  }
  function copyText(text) {
    const done = () => toast('Copied');
    const fallback = () => {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { toast('Select the text and copy it manually'); }
      ta.remove();
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  }

  /* tabs, shell switch and copy buttons, delegated so they also work inside the panel */
  document.addEventListener('click', e => {
    const tab = e.target.closest('[role="tab"][data-tab]');
    if (tab) {
      const box = tab.closest('.install');
      $$('[role="tab"]', box).forEach(b => b.setAttribute('aria-selected', String(b === tab)));
      $$('.tabpanel', box).forEach(p => { p.hidden = p.dataset.panel !== tab.dataset.tab; });
      return;
    }
    const os = e.target.closest('.os-switch button');
    if (os) {
      shell = os.dataset.os;
      try { localStorage.setItem('cm-shell', shell); } catch (err) { /* storage unavailable */ }
      applyShell(document);
      return;
    }
    const btn = e.target.closest('button.copy');
    if (btn) {
      const src = btn.closest('.codebox')?.querySelector('pre:not([hidden])') || btn.closest('.cmd')?.querySelector('code');
      if (src) copyText(src.textContent.replace(/\n+$/, '') + '\n');
    }
  });

  /* catalog */
  const grid = $('#grid');
  const cardsEl = $('#cards');
  if (!grid || !cardsEl) return;

  const CARDS = JSON.parse(cardsEl.textContent);
  const TAX = JSON.parse($('#taxonomy').textContent);
  const byName = new Map(CARDS.map(c => [c.name, c]));
  const elByName = new Map($$('.card', grid).map(el => [el.dataset.name, el]));
  for (const c of CARDS) {
    c.hay = [c.name, c.title, c.summary, c.tags.join(' '), TAX.categories[c.category].label, c.owner, c.license].join(' ').toLowerCase();
    const el = elByName.get(c.name);
    c.titleEl = el.querySelector('h2 a');
    c.summaryEl = el.querySelector('p');
  }
  const FIELD = { category: 'category', license: 'license_kind' };

  const params = new URLSearchParams(location.search);
  const state = { q: params.get('q') || '', category: params.get('category') || null, license: params.get('license') || null };
  const q = $('#q');
  q.value = state.q;
  q.closest('form').addEventListener('submit', e => e.preventDefault());

  const terms = () => state.q.toLowerCase().split(/\s+/).filter(Boolean);
  function score(c, ts) {
    let s = 0;
    for (const t of ts) {
      if (!c.hay.includes(t)) return 0;
      const title = c.title.toLowerCase();
      if (c.name.startsWith(t) || title.startsWith(t)) s += 10;
      else if (c.name.includes(t) || title.includes(t)) s += 6;
      if (c.tags.some(g => g.startsWith(t))) s += 5;
      if (c.summary.toLowerCase().includes(t)) s += 2;
      s += 1;
    }
    return ts.length ? s : 1;
  }
  function passes(c, skip) {
    if (skip !== 'category' && state.category && c.category !== state.category) return false;
    if (skip !== 'license' && state.license && c.license_kind !== state.license) return false;
    return true;
  }
  function highlight(text, ts) {
    const out = esc(text);
    if (!ts.length) return out;
    const re = new RegExp('(' + ts.map(t => esc(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
    return out.replace(re, '<mark>$1</mark>');
  }

  /* filters: update counts, hide options with no match unless selected; "" means all */
  function updateFacets(ts) {
    for (const a of $$('a[data-facet]')) {
      const key = a.dataset.facet;
      const v = a.dataset.v;
      const n = CARDS.filter(c => (!v || c[FIELD[key]] === v) && passes(c, key) && score(c, ts) > 0).length;
      const on = (state[key] || '') === v;
      const count = a.querySelector('.n');
      if (count) count.textContent = n;
      a.hidden = Boolean(v) && !n && !on;
      if (on) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    }
  }
  document.addEventListener('click', e => {
    const a = e.target.closest('a[data-facet]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    const key = a.dataset.facet;
    const v = a.dataset.v || null;
    state[key] = state[key] === v ? null : v;
    render(true);
  });

  function syncUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set('q', state.q);
    if (state.category) p.set('category', state.category);
    if (state.license) p.set('license', state.license);
    const qs = p.toString();
    try { history.replaceState(history.state, '', location.pathname + (qs ? '?' + qs : '') + location.hash); } catch (e) { /* ignore */ }
  }

  function render(updateUrl) {
    const ts = terms();
    updateFacets(ts);
    const scored = CARDS.map(c => [c, score(c, ts)]).filter(([c, s]) => s > 0 && passes(c));
    scored.sort((a, b) => b[1] - a[1] || a[0].title.localeCompare(b[0].title));
    const shown = new Set(scored.map(([c]) => c.name));
    for (const c of CARDS) {
      elByName.get(c.name).hidden = !shown.has(c.name);
      c.titleEl.innerHTML = highlight(c.title, ts);
      c.summaryEl.innerHTML = highlight(c.summary, ts);
    }
    for (const [c] of scored) grid.appendChild(elByName.get(c.name));
    grid.appendChild($('#empty'));
    $('#empty').hidden = scored.length > 0;
    $('#count').innerHTML = `<b>${scored.length}</b> module${scored.length === 1 ? '' : 's'}`;

    $('#reset').hidden = !(state.q || state.category || state.license);
    if (updateUrl) syncUrl();
  }

  q.addEventListener('input', () => { state.q = q.value.trim(); render(true); });
  $('#reset').addEventListener('click', () => {
    Object.assign(state, { q: '', category: null, license: null });
    q.value = '';
    render(true);
  });

  /* detail panel: loads the module page and shows its #module-detail */
  const panel = $('#panel');
  const scrim = $('#scrim');
  let lastFocus = null;
  let loading = 0;

  async function openPanel(name, push) {
    if (!byName.has(name)) return;
    const href = `m/${encodeURIComponent(name)}/`;
    const ticket = ++loading;
    let detail;
    try {
      const res = await fetch(href);
      if (!res.ok) throw new Error(res.status);
      detail = new DOMParser().parseFromString(await res.text(), 'text/html').querySelector('#module-detail');
      if (!detail) throw new Error('no detail');
    } catch (err) {
      location.href = href;
      return;
    }
    if (ticket !== loading) return;
    // links in the fetched page are relative to m/<name>/
    $$('a[href]', detail).forEach(a => { a.href = new URL(a.getAttribute('href'), new URL(href, location.href)).href; });
    const body = $('#panel-body');
    body.replaceChildren(document.importNode(detail, true));
    applyShell(body);
    $('#panel-page').href = href;
    lastFocus = lastFocus || document.activeElement;
    panel.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    scrim.classList.add('open');
    panel.scrollTop = 0;
    $('#close').focus();
    if (push && location.hash !== '#' + name) history.pushState({ panel: name }, '', '#' + name);
  }
  function closePanel(fromHistory) {
    if (!panel.classList.contains('open')) return;
    panel.classList.remove('open');
    panel.setAttribute('aria-hidden', 'true');
    scrim.classList.remove('open');
    if (!fromHistory && location.hash) {
      if (history.state && history.state.panel) history.back();
      else try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* ignore */ }
    }
    lastFocus?.focus?.();
    lastFocus = null;
  }

  document.addEventListener('click', e => {
    const a = e.target.closest('a[data-module]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0 || !byName.has(a.dataset.module)) return;
    e.preventDefault();
    if (!panel.contains(a)) lastFocus = a;
    openPanel(a.dataset.module, true);
  });
  $('#close').addEventListener('click', () => closePanel(false));
  scrim.addEventListener('click', () => closePanel(false));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && panel.classList.contains('open')) closePanel(false);
    const tag = document.activeElement?.tagName || '';
    if (e.key === '/' && document.activeElement !== q && !/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) { e.preventDefault(); q.focus(); }
  });
  window.addEventListener('popstate', () => {
    const name = decodeURIComponent(location.hash.slice(1));
    if (byName.has(name)) openPanel(name, false);
    else closePanel(true);
  });

  render(false);
  const initial = decodeURIComponent(location.hash.slice(1));
  if (byName.has(initial)) openPanel(initial, false);
})();
