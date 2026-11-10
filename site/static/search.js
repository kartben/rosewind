/*
 * SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * Catalog search: every term must start a word of the name, title, summary,
 * keywords, category, owner or license, or appear in the name or title, as
 * "ssl" in wolfSSL. Matches in the name and title rank first. Loaded by the
 * catalog page and by the tests (node).
 */
((root, factory) => {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.rosewindSearch = factory();
})(typeof self !== 'undefined' ? self : this, () => {
  'use strict';

  const BOUNDARY = '(^|[^\\p{L}\\p{N}])';
  const quote = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const cache = new Map();
  function wordStart(t) {
    if (!cache.has(t)) cache.set(t, new RegExp(BOUNDARY + quote(t), 'u'));
    return cache.get(t);
  }

  /* lower-cased search terms of a query */
  const terms = q => q.toLowerCase().split(/\s+/).filter(Boolean);

  /* the searchable fields of a card; `extra` is text such as the category label */
  function prepare(c, extra = []) {
    return {
      name: c.name.toLowerCase(),
      title: c.title.toLowerCase(),
      summary: c.summary.toLowerCase(),
      keywords: c.keywords.join(' · ').toLowerCase(),
      extra: [c.owner, c.license, ...extra].join(' · ').toLowerCase(),
    };
  }

  /* 0 when a term matches nowhere, else higher for better matches */
  function score(f, ts) {
    let s = 0;
    for (const t of ts) {
      const re = wordStart(t);
      let m = 0;
      if (f.name.startsWith(t) || f.title.startsWith(t)) m += 10;
      else if (re.test(f.name) || re.test(f.title)) m += 6;
      else if (f.name.includes(t) || f.title.includes(t)) m += 4;
      if (re.test(f.keywords)) m += 5;
      if (re.test(f.summary)) m += 2;
      if (!m && re.test(f.extra)) m = 1;
      if (!m) return 0;
      s += m;
    }
    return ts.length ? s : 1;
  }

  /* a global pattern whose second group is a term at a word start, or
     anywhere for titles, or null */
  function pattern(ts, anywhere = false) {
    if (!ts.length) return null;
    return new RegExp((anywhere ? '()' : BOUNDARY) + '(' + [...ts].sort((a, b) => b.length - a.length).map(quote).join('|') + ')', 'giu');
  }

  return { terms, prepare, score, pattern };
});
