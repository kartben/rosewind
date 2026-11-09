# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Entries written from New module issues are well formed and pass validation."""

import pytest
import yaml

import issue_to_entry
import validate

ANSWERS = {
    'name': 'demo-module',
    'title': 'Demo Module',
    'summary': 'A demonstration module that shows how issue answers become an entry.',
    'repository': 'https://github.com/example/demo-module',
    'revision': 'v1.2.0',
    'path': '_No response_',
    'category': 'tools',
    'license': 'Apache-2.0',
    'maintainers': '@alice, bob',
    'documentation': 'https://example.org/docs',
    'homepage': '_No response_',
    'keywords': 'mqtt, TinyML',
    'description': 'First paragraph with `code`.\n\n- one\n- two',
}


def body(answers):
    labels = {v: k for k, v in issue_to_entry.form_labels().items()}
    parts = [f'### {labels[key]}\n\n{value}' for key, value in answers.items()]
    parts.append('### Listing criteria\n\n- [X] The repository is public and reachable over https.')
    return '\n\n'.join(parts) + '\n'


def test_complete_answers_make_a_valid_entry(tmp_path, capsys):
    name, text = issue_to_entry.entry_text(issue_to_entry.parse_body(body(ANSWERS)))
    data = yaml.safe_load(text)
    assert name == 'demo-module'
    assert data['maintainers'] == [{'github': 'alice'}, {'github': 'bob'}]
    assert data['keywords'] == ['mqtt', 'tinyml']
    assert data['west'] == {'revision': 'v1.2.0', 'path': 'modules/lib/demo-module'}
    assert data['links'] == {'repository': 'https://github.com/example/demo-module',
                             'documentation': 'https://example.org/docs'}
    assert data['description'] == 'First paragraph with `code`.\n\n- one\n- two\n'

    path = tmp_path / 'demo-module.yml'
    path.write_text(text)
    report = validate.Report('text')
    validate.offline([path], report)
    assert report.errors == 0, capsys.readouterr().out


def test_hostile_answers_stay_values():
    answers = dict(ANSWERS, title='Demo: x\nwest:\n  import: true', summary='Ends here."\ncategory: ml #')
    _, text = issue_to_entry.entry_text(issue_to_entry.parse_body(body(answers)))
    data = yaml.safe_load(text)
    assert data['title'] == 'Demo: x west: import: true'
    assert data['category'] == 'tools'
    assert 'import' not in data['west']


def test_explicit_path_is_kept():
    answers = dict(ANSWERS, path='modules/crypto/demo-module')
    _, text = issue_to_entry.entry_text(issue_to_entry.parse_body(body(answers)))
    assert yaml.safe_load(text)['west']['path'] == 'modules/crypto/demo-module'


@pytest.mark.parametrize('change,message', [
    ({'name': 'Demo Module!'}, 'not a valid module name'),
    ({'summary': '_No response_'}, '"summary" answer is empty'),
    ({'maintainers': '@'}, 'no maintainer'),
])
def test_unusable_answers_are_reported(change, message):
    with pytest.raises(issue_to_entry.FormError, match=message):
        issue_to_entry.entry_text(issue_to_entry.parse_body(body(dict(ANSWERS, **change))))


def test_cli_writes_the_file_and_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv('ISSUE_BODY', body(ANSWERS))
    out = tmp_path / 'github_output'
    rc = issue_to_entry.main(['--body-env', 'ISSUE_BODY', '--out-dir', str(tmp_path), '--github-output', str(out)])
    assert rc == 0
    assert (tmp_path / 'demo-module.yml').is_file()
    assert 'name=demo-module\n' in out.read_text()
