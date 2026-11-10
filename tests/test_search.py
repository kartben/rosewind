# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""The catalog search (site/static/search.js), run with node."""

import json
import shutil
import subprocess

import pytest

import registry

NODE = shutil.which('node')
SEARCH_JS = registry.ROOT / 'site' / 'static' / 'search.js'

CARDS = [
    {'name': 'clutgen', 'title': 'CLUTGen', 'summary': 'Generates color lookup tables.', 'keywords': ['lut'],
     'owner': 'acme', 'license': 'MIT'},
    {'name': 'canopennode', 'title': 'CANopenNode', 'summary': 'CANopen protocol stack.', 'keywords': ['can'],
     'owner': 'canopennode', 'license': 'Apache-2.0'},
    {'name': 'canlib', 'title': 'Canlib', 'summary': 'Bus drivers.', 'keywords': [], 'owner': 'acme',
     'license': 'MIT'},
    {'name': 'helper', 'title': 'Helper', 'summary': 'You can use it with a CAN bus.', 'keywords': ['ble'],
     'owner': 'acme', 'license': 'MIT'},
    {'name': 'wolfssl', 'title': 'wolfSSL', 'summary': 'TLS library.', 'keywords': [], 'owner': 'wolfssl',
     'license': 'GPL-3.0-only'},
    {'name': 'ai-kit', 'title': 'AI Kit', 'summary': 'Run models on device.', 'keywords': [],
     'owner': 'acme', 'license': 'MIT'},
]

SCRIPT = '''
const s = require(process.argv[1]);
const cards = JSON.parse(process.argv[2]);
const out = {};
for (const q of JSON.parse(process.argv[3])) {
  const ts = s.terms(q);
  out[q] = cards.map(c => [c.name, s.score(s.prepare(c, ['Category']), ts)])
    .filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([n]) => n);
}
const re = s.pattern(s.terms('can'));
out.highlight = Array.from('CANopen and scan'.matchAll(re), m => m.index + m[1].length);
out.titleHighlight = Array.from('wolfSSL'.matchAll(s.pattern(s.terms('ssl'), true)), m => m.index + m[1].length);
console.log(JSON.stringify(out));
'''


@pytest.fixture(scope='module')
def results():
    if not NODE:
        pytest.skip('node is not installed')
    queries = ['ble', 'ai', 'can', 'can bus', 'tables', 'acme', 'category', 'xyz', 'ssl', 'ables']
    proc = subprocess.run([NODE, '-e', SCRIPT, str(SEARCH_JS), json.dumps(CARDS), json.dumps(queries)],
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def test_terms_match_at_word_starts(results):
    assert results['ble'] == ['helper']
    assert results['ai'] == ['ai-kit']
    assert results['tables'] == ['clutgen']
    assert results['xyz'] == []
    assert results['ables'] == []


def test_name_and_title_match_anywhere(results):
    assert results['ssl'] == ['wolfssl']


def test_title_matches_rank_first(results):
    assert results['can'] == ['canopennode', 'canlib', 'helper']


def test_every_term_must_match(results):
    assert results['can bus'] == ['canlib', 'helper']


def test_owner_and_category_match(results):
    assert set(results['acme']) == {'clutgen', 'canlib', 'helper', 'ai-kit'}
    assert len(results['category']) == len(CARDS)


def test_highlight_only_at_word_starts(results):
    assert results['highlight'] == [0]
    assert results['titleHighlight'] == [4]
