# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Build the site from the real entries and a frozen enrichment snapshot."""

import json
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
