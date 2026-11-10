# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Collecting repository data, without network access."""

import json
from datetime import date

import enrich
import registry

PAGE = 'https://example.org/project/'


def test_svg_then_largest_then_favicon():
    html = '''<head>
      <link rel="icon" href="/favicon-16.png" sizes="16x16">
      <link rel="apple-touch-icon" href="touch.png">
      <link rel="icon" href="/favicon-96.png" sizes="96x96">
      <link rel="icon" type="image/svg+xml" href="/logo.svg">
      <link rel="stylesheet" href="/site.css">
    </head>'''
    assert enrich.icon_candidates(PAGE, html, allow_favicon=True) == [
        'https://example.org/logo.svg',
        'https://example.org/project/touch.png',
        'https://example.org/favicon-96.png',
        'https://example.org/favicon-16.png',
        'https://example.org/favicon.ico',
    ]


def test_no_favicon_fallback_on_documentation_hosts():
    assert enrich.icon_candidates(PAGE, '<html></html>', allow_favicon=False) == []


def test_shortcut_icon_rel():
    html = '<link rel="shortcut icon" href="https://cdn.example.org/i.ico">'
    assert enrich.icon_candidates(PAGE, html, allow_favicon=False) == ['https://cdn.example.org/i.ico']


def test_one_failing_module_does_not_stop_the_run(tmp_path, monkeypatch):
    def fail(url):
        raise RuntimeError('unexpected')

    monkeypatch.setattr(registry, 'ls_remote', fail)
    out = tmp_path / 'enriched.json'
    assert enrich.main(['--no-github', '--out', str(out), str(registry.MODULES_DIR / 'lz4.yml')]) == 0
    assert 'unexpected' in json.loads(out.read_text())['modules']['lz4']['error']


def test_invalid_module_yml_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(registry, 'ls_remote', lambda url: {'refs/heads/zephyr': 'a' * 40})
    monkeypatch.setattr(registry, 'read_module_yml', lambda url, rev: ('zephyr/module.yml', 'name: [\n'))
    entry = registry.load_entry(registry.MODULES_DIR / 'lz4.yml')
    data = enrich.enrich_one(entry, use_github=False, icon_dir=tmp_path)
    assert data['module']['invalid']
    checks = registry.compute_checks(entry, data, date(2026, 11, 9))
    assert any(c['code'] == 'module-yml' and c['level'] == 'warning' for c in checks)
