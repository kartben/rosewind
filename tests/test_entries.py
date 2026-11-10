# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Every entry in modules/ passes the offline checks; each fixture in
fixtures/invalid/ fails with the message named on its '# expect:' line."""

import re
import shutil
from pathlib import Path

import pytest

import registry
import validate

FIXTURES = Path(__file__).parent / 'fixtures' / 'invalid'


def run(paths, capsys):
    report = validate.Report('text')
    validate.offline(paths, report)
    return report, capsys.readouterr().out


def test_all_entries_pass(capsys):
    report, out = run(registry.entry_paths(), capsys)
    assert report.errors == 0, out
    assert report.warnings == 0, out


@pytest.mark.parametrize('path', sorted(FIXTURES.glob('*.yml')), ids=lambda p: p.stem)
def test_invalid_fixture_is_rejected(path, capsys):
    if path.stem == 'unknown-spdx':
        pytest.importorskip('license_expression')
    expected = re.match(r'# expect: (.*)', path.read_text()).group(1)
    report, out = run([path], capsys)
    assert report.errors >= 1
    assert expected in out, out


def test_duplicate_path_is_rejected(tmp_path, capsys):
    src = registry.MODULES_DIR / 'lz4.yml'
    dup = tmp_path / 'lz4-copy.yml'
    dup.write_text(src.read_text().replace('name: lz4', 'name: lz4-copy'))
    report, out = run([src, dup], capsys)
    assert 'already used by lz4.yml' in out
    assert 'repository already listed in lz4.yml' in out
    assert report.errors == 2


def test_entry_checked_alone_is_compared_with_the_registry(tmp_path, capsys):
    dup = tmp_path / 'lz4-copy.yml'
    dup.write_text((registry.MODULES_DIR / 'lz4.yml').read_text().replace('name: lz4', 'name: lz4-copy'))
    report, out = run([dup], capsys)
    assert 'already used by lz4.yml' in out
    assert 'repository already listed in lz4.yml' in out


def test_categories_cover_entries():
    categories = registry.load_categories()
    used = {registry.load_entry(p).data['category'] for p in registry.entry_paths()}
    assert used <= set(categories)
    for c in categories.values():
        assert {'label', 'description', 'hue'} <= set(c)


def test_west_rejects_nothing_we_generate():
    from west.manifest import validate as west_validate
    import yaml

    for p in registry.entry_paths():
        proj = registry.load_entry(p).west_project()
        west_validate(yaml.safe_load(registry.submanifest_text(proj)))


def test_fixture_entries_do_not_leak_into_modules():
    names = {p.stem for p in registry.entry_paths()}
    assert not names & {p.stem for p in FIXTURES.glob('*.yml')}
    assert shutil.which('git'), 'git is needed by the online checks'


def test_redundant_keyword_warns(tmp_path, capsys):
    src = registry.MODULES_DIR / 'zenoh-pico.yml'
    entry = tmp_path / 'zenoh-pico.yml'
    entry.write_text(src.read_text().replace('keywords: [pubsub, ros2]', 'keywords: [ros2, microcontrollers]'))
    report, out = run([entry], capsys)
    assert report.errors == 0
    assert report.warnings == 1
    assert 'keyword "microcontrollers" already appears in the summary' in out
