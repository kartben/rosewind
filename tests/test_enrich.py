# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Collecting repository data, without network access."""

import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

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


def test_only_a_few_https_candidates():
    links = ''.join(f'<link rel="icon" href="/i{n}.png" sizes="{n}x{n}">' for n in range(100, 110))
    html = '<link rel="icon" href="file:///etc/hosts"><link rel="icon" href="http://127.0.0.1/x.png">' + links
    urls = enrich.icon_candidates(PAGE, html, allow_favicon=True)
    assert urls == [f'https://example.org/i{n}.png' for n in range(109, 104, -1)]


def test_fetch_refuses_other_schemes():
    with pytest.raises(ValueError, match='not an https URL'):
        enrich.fetch('file:///etc/hosts', 100, deadline=float('inf'))
    with pytest.raises(urllib.error.HTTPError, match='non-https'):
        enrich.HttpsOnlyRedirects().redirect_request(None, None, 302, 'Found', {}, 'http://127.0.0.1/')


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
    checks = registry.compute_checks(entry, data)
    assert any(c['code'] == 'module-yml' and c['level'] == 'warning' for c in checks)


def test_report_leaves_out_branch_tracking(tmp_path):
    enriched = json.loads((Path(__file__).parent / 'fixtures' / 'enriched.json').read_text())['modules']
    report = tmp_path / 'report.md'
    enrich.write_report([registry.load_entry(registry.MODULES_DIR / 'xedge.yml')], enriched, report)
    text = report.read_text()
    assert 'zephyr/module.yml' in text
    assert 'Follows branch' not in text


def git_repo(path, files):
    """Commit `files` (path: text) to a new repository on branch main and return its URL."""
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    git = ['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@example.org']
    subprocess.run(git[:3] + ['init', '-q', '-b', 'main'], check=True)
    subprocess.run(git + ['add', '.'], check=True)
    subprocess.run(git + ['commit', '-q', '-m', 'files'], check=True)
    return path.as_uri()


def test_build_files_make_a_module(tmp_path):
    both = git_repo(tmp_path / 'both', {'zephyr/CMakeLists.txt': '', 'zephyr/Kconfig': ''})
    assert registry.read_module_yml(both, 'main') == ('zephyr/CMakeLists.txt', None)
    one = git_repo(tmp_path / 'one', {'zephyr/CMakeLists.txt': ''})
    assert registry.read_module_yml(one, 'main') is None


def test_build_files_only_is_a_note(monkeypatch, tmp_path):
    monkeypatch.setattr(registry, 'ls_remote', lambda url: {'refs/heads/zephyr': 'a' * 40})
    monkeypatch.setattr(registry, 'read_module_yml', lambda url, rev: (registry.BUILD_FILES[0], None))
    entry = registry.load_entry(registry.MODULES_DIR / 'lz4.yml')
    data = enrich.enrich_one(entry, use_github=False, icon_dir=tmp_path)
    name = Path(entry.west_project()['path']).name
    assert data['module']['name'] == name and data['module']['build_files_only']
    checks = registry.compute_checks(entry, data)
    assert any(c['code'] == 'no-module-yml' and c['level'] == 'info' and f'`{name}`' in c['message']
               for c in checks)
