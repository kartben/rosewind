# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Build the site from the real entries and a frozen enrichment snapshot."""

import html
import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml
from west.manifest import validate as west_validate

import build_site
import registry

ENRICHED = Path(__file__).parent / 'fixtures' / 'enriched.json'
BASE = 'https://modules.example.org'


@pytest.fixture(scope='module')
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp('site')
    rc = build_site.main(['--out', str(out), '--enriched', str(ENRICHED), '--base-url', BASE,
                          '--today', '2026-11-09'])
    assert rc == 0
    return out


def test_layout(site):
    names = [p.stem for p in registry.entry_paths()]
    for n in names:
        assert (site / 'm' / n / 'index.html').is_file()
        assert (site / 'm' / f'{n}.yaml').is_file()
    for f in ('index.html', 'contribute/index.html', 'index.json', '404.html', 'sitemap.xml', 'robots.txt',
              '.nojekyll', 'static/site.css', 'static/site.js'):
        assert (site / f).exists(), f


def test_submanifests_load_in_west(site):
    for f in (site / 'm').glob('*.yaml'):
        west_validate(yaml.safe_load(f.read_text()))


def test_index_json(site):
    index = json.loads((site / 'index.json').read_text())
    assert index['schema-version'] == 1
    mods = {m['name']: m for m in index['modules']}
    assert len(mods) == len(registry.entry_paths())
    assert mods['zenoh-pico']['submanifest_url'] == f'{BASE}/m/zenoh-pico.yaml'
    assert mods['wolftpm']['dependencies'] == [{'module': 'wolfssl', 'entry': 'wolfssl'}]
    assert any(c['code'] == 'no-module-yml' and c['level'] == 'warning' for c in mods['xedge']['checks'])
    assert any(c['code'] == 'inactive' for c in mods['heatshrink']['checks'])
    assert mods['lz4']['checks'][0]['code'] == 'not-enriched'


def test_dependency_installed_alongside(site):
    page = (site / 'm' / 'wolftpm' / 'index.html').read_text()
    assert f'{BASE}/m/wolfssl.yaml' in page
    assert 'west update wolfssl wolftpm' in page


def test_contested_module_name_links_no_dependency(tmp_path):
    def found(name, depends=()):
        return {'revision': {'kind': 'branch', 'sha': None},
                'module': {'found': True, 'name': name, 'depends': list(depends), 'provides': []}}

    entries = [registry.load_entry(registry.MODULES_DIR / f'{n}.yml') for n in ('wolfssh', 'wolfssl', 'zview')]
    enriched = {'wolfssh': found('wolfssh', ['wolfssl']), 'wolfssl': found('wolfssl'), 'zview': found('wolfssl')}
    records = {r['name']: r for r in build_site.build_records(
        entries, registry.load_categories(), enriched, date(2026, 11, 9), BASE, tmp_path)}
    assert records['wolfssh']['dependencies'] == [{'module': 'wolfssl', 'entry': None}]
    assert [r['name'] for r in records['wolfssh']['install_set']] == ['wolfssh']
    assert any(c['code'] == 'module-name' and '`zview`' in c['message'] for c in records['wolfssl']['checks'])


def test_catalog_lists_every_module(site):
    page = (site / 'index.html').read_text()
    for n in (p.stem for p in registry.entry_paths()):
        assert f'data-name="{n}"' in page


def test_contribute_example_is_minimal(site):
    page = (site / 'contribute' / 'index.html').read_text()
    assert 'modules/zenoh-pico.yml' in page
    assert 'description' not in page.split('<pre>', 1)[1].split('</pre>', 1)[0]
    assert 'SPDX-' not in page


def test_detail_hides_passing_checks(site):
    page = (site / 'm' / 'zenoh-pico' / 'index.html').read_text()
    assert 'resolves (' not in page
    assert 'Tracks branch' in page


def test_post_install_commands_on_their_own_line(site):
    page = (site / 'm' / 'dtsh' / 'index.html').read_text()
    assert 'west update dtsh\nwest packages -m dtsh pip --install' in page


def _manifest_tab(site, name):
    page = (site / 'm' / name / 'index.html').read_text()
    return page.split('data-panel="yml"', 1)[1]


def test_manifest_tab_lists_the_same_follow_ups(site):
    tab = _manifest_tab(site, 'dtsh')
    assert ('then run <code>west update dtsh</code> and '
            '<code>west packages -m dtsh pip --install</code>.') in tab


def test_manifest_tab_copies_only_project_entries(site):
    tab = _manifest_tab(site, 'wolftpm')
    snippet = re.sub(r'<[^>]+>', '', tab.split('<pre>', 1)[1].split('</pre>', 1)[0])
    assert 'manifest:' not in snippet and 'projects:' not in snippet
    projects = yaml.safe_load(html.unescape(snippet))
    assert [p['name'] for p in projects] == ['wolfssl', 'wolftpm']
    assert '<code>west update wolfssl wolftpm</code>.' in tab


def test_warnings_come_first_and_flag_the_card(site):
    page = (site / 'm' / 'xedge' / 'index.html').read_text()
    assert page.index('No <code>zephyr/module.yml</code>') < page.index('class="install"') < page.index('Tracks branch')
    catalog = (site / 'index.html').read_text()
    card = catalog.split('data-name="xedge"', 1)[1].split('</article>', 1)[0]
    assert '1 warning' in card
    assert 'warning' not in catalog.split('data-name="zenoh-pico"', 1)[1].split('</article>', 1)[0]


def test_details_list_what_a_module_includes(site):
    page = (site / 'm' / 'dtsh' / 'index.html').read_text()
    assert '<dt>Includes</dt><dd>West commands, Python requirements</dd>' in page
    assert '<dt>Includes</dt>' not in (site / 'm' / 'lz4' / 'index.html').read_text()


def test_submanifest_header_names_the_site(site):
    name = registry.load_site_config()['name']
    head = (site / 'm' / 'zenoh-pico.yaml').read_text().splitlines()[:2]
    assert head == [f'# zenoh-pico from {name}', f'# {BASE}/m/zenoh-pico/']
