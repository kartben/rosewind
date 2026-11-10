# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

import json

import pytest
import yaml

import build_site
import registry


@pytest.mark.parametrize('expr,kind', [
    ('Apache-2.0', 'permissive'),
    ('ISC AND Apache-2.0', 'permissive'),
    ('EPL-2.0 OR Apache-2.0', 'permissive'),
    ('Apache-2.0 WITH LLVM-exception', 'permissive'),
    ('GPL-3.0-or-later', 'copyleft'),
    ('(Apache-2.0 OR GPL-2.0-only)', 'permissive'),
    ('MIT AND LGPL-2.1-only', 'copyleft'),
    ('Apache-2.0 AND LicenseRef-NXP', 'other'),
])
def test_license_kind(expr, kind):
    assert registry.license_kind(expr) == kind


@pytest.mark.parametrize('tags,like,latest', [
    (['v1.4.0', 'v1.5.1', 'v1.6.0-rc1', 'v1.10.0-rc2'], 'v1.4.0', 'v1.5.1'),
    (['1.33.0', '1.46.0', '1.9.0'], '1.33.0', '1.46.0'),
    (['v5.9.4-stable', 'v5.9.4', 'v5.10.0-stable'], 'v5.9.4-stable', 'v5.10.0-stable'),
    (['WAMR-2.4.5', 'WAMR-2.10.0', 'release-1.0'], None, 'WAMR-2.10.0'),
    (['main-snapshot', 'nightly'], None, None),
])
def test_latest_tag(tags, like, latest):
    assert registry.latest_tag(tags, like) == latest


def test_is_newer():
    assert registry.is_newer('v1.10.0', 'v1.9.3')
    assert not registry.is_newer('v1.4.0', 'v1.4.0')
    assert not registry.is_newer('main', 'v1.0.0')


@pytest.mark.parametrize('value,expected', [
    ('main', 'main'),
    ('1.10.2', '"1.10.2"'),
    ('https://github.com/a/b', 'https://github.com/a/b'),
    ('yes', '"yes"'),
    ('a: b', '"a: b"'),
])
def test_yaml_scalar(value, expected):
    assert registry.yaml_scalar(value) == expected
    assert yaml.safe_load(f'k: {registry.yaml_scalar(value)}')['k'] == value


def test_submanifest_round_trip():
    proj = {'name': 'demo', 'url': 'https://example.com/demo', 'revision': '2.0', 'path': 'modules/lib/demo',
            'submodules': [{'path': 'third_party/x'}], 'west-commands': 'scripts/west-commands.yml'}
    data = yaml.safe_load(registry.submanifest_text(proj))
    assert data == {'manifest': {'projects': [proj]}}


def test_markdown_subset_escapes_html():
    out = str(build_site.markdown('Use `<b>` and [docs](https://x.org).\n\n- one *two*\n- **three**'))
    assert '<code>&lt;b&gt;</code>' in out
    assert '<a href="https://x.org" rel="noopener">docs</a>' in out
    assert '<ul><li>one <em>two</em></li><li><strong>three</strong></li></ul>' in out
    assert '<script' not in str(build_site.markdown('<script>alert(1)</script>'))


def test_markdown_link_urls_are_escaped_once():
    out = str(build_site.markdown('See [the *docs*](https://x.org/a?b=1&c=2) and [x](https://x.org/*a*).'))
    assert '<a href="https://x.org/a?b=1&amp;c=2" rel="noopener">the <em>docs</em></a>' in out
    assert '<a href="https://x.org/*a*" rel="noopener">x</a>' in out


def test_script_json_cannot_end_its_element():
    value = [{'title': 'Foo <!--<script>', 'summary': '</script> & more'}]
    text = str(build_site.script_json(value))
    assert not set('<>&') & set(text)
    assert json.loads(text) == value


def test_module_info():
    text = 'name: foo\nbuild:\n  depends: [bar]\n  settings:\n    board_root: .\n    dts_root: .\n' \
           'samples: [samples]\npackage-managers:\n  pip:\n    requirement-files: [r.txt]\n'
    info = registry.module_info(text, 'modules/lib/foo')
    assert info == {'found': True, 'name': 'foo', 'depends': ['bar'], 'provides': ['boards', 'dts', 'samples', 'pip']}
    assert registry.module_info('build:\n  cmake: .\n', 'modules/lib/baz')['name'] == 'baz'


@pytest.mark.parametrize('text,depends', [
    ('- a\n- b\n', []),
    ('build: [1]\n', []),
    ('name: [x]\nbuild:\n  depends: [{a: b}, 1, wolfssl]\n  settings: x\npackage-managers: pip\n', ['wolfssl']),
    ('build:\n  depends: wolfssl\n', []),
])
def test_module_info_ignores_unexpected_types(text, depends):
    info = registry.module_info(text, 'modules/lib/foo')
    assert info['name'] == 'foo'
    assert info['depends'] == depends
