#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Write modules/<name>.yml from the body of a New module issue.

GitHub renders each answer of the issue form (.github/ISSUE_TEMPLATE/new-module.yml)
under a "### <label>" heading. This script maps the headings back to the form's
field ids and writes the entry. It only checks what it needs to write a
well-formed file; run validate.py on the result.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

FORM = registry.ROOT / '.github' / 'ISSUE_TEMPLATE' / 'new-module.yml'
NO_RESPONSE = '_No response_'
NAME = re.compile(r'^[a-z0-9][a-z0-9._-]{1,62}$')
HEADER = ('# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors\n'
          '# SPDX-License-Identifier: Apache-2.0\n')


class FormError(Exception):
    pass


def form_labels() -> dict[str, str]:
    """Map each label of the issue form to its field id."""
    form = registry.load_yaml(FORM)
    return {item['attributes']['label']: item['id'] for item in form['body'] if 'id' in item}


def parse_body(body: str) -> dict[str, str]:
    labels = form_labels()
    fields, current, lines = {}, None, []

    def flush():
        if current:
            value = '\n'.join(lines).strip()
            fields[current] = '' if value == NO_RESPONSE else value

    for line in body.replace('\r\n', '\n').split('\n'):
        m = re.match(r'^### (.+?)\s*$', line)
        if m and m.group(1) in labels:
            flush()
            current, lines = labels[m.group(1)], []
        elif current:
            lines.append(line)
    flush()
    return fields


def entry_text(fields: dict[str, str]) -> tuple[str, str]:
    """Return (name, YAML text) of the entry described by the form fields."""
    def one_line(key: str, required: bool = True) -> str:
        value = ' '.join(fields.get(key, '').split())
        if required and not value:
            raise FormError(f'the "{key}" answer is empty')
        return value

    q = registry.yaml_scalar
    name = one_line('name').lower()
    if not NAME.match(name):
        raise FormError(f'"{name}" is not a valid module name: use lowercase letters, digits, ".", "_" and "-"')
    title, summary = one_line('title'), one_line('summary')
    maintainers = [h.lstrip('@') for h in re.split(r'[\s,]+', fields.get('maintainers', '')) if h.lstrip('@')]
    if not maintainers:
        raise FormError('no maintainer GitHub handle given')
    keywords = [k.strip().lower() for k in fields.get('keywords', '').split(',') if k.strip()]
    description = '\n'.join(line.rstrip() for line in fields.get('description', '').strip().splitlines())

    lines = [HEADER, f'name: {q(name)}', f'title: {q(title)}', 'summary: >-', f'  {summary}']
    if description:
        lines.append('description: |')
        lines += [f'  {line}' if line else '' for line in description.splitlines()]
    lines.append(f'category: {q(one_line("category"))}')
    if keywords:
        lines.append(f'keywords: [{", ".join(q(k) for k in keywords)}]')
    lines.append(f'license: {q(one_line("license"))}')
    lines.append('maintainers:')
    lines += [f'  - github: {q(h)}' for h in maintainers]
    lines += ['links:', f'  repository: {q(one_line("repository"))}']
    for key in ('documentation', 'homepage'):
        if one_line(key, required=False):
            lines.append(f'  {key}: {q(one_line(key))}')
    lines += ['west:', f'  revision: {q(one_line("revision"))}',
              f'  path: {q(one_line("path", required=False) or f"modules/lib/{name}")}']
    text = '\n'.join(lines) + '\n'

    # The answers are untrusted: make sure none of them changed the structure.
    data = yaml.safe_load(text)
    expected = {'name': name, 'title': title, 'summary': summary}
    if any(data.get(k) != v for k, v in expected.items()) or set(data) - {
            'name', 'title', 'summary', 'description', 'category', 'keywords', 'license', 'maintainers',
            'links', 'west'}:
        raise FormError('the answers could not be written as a well-formed entry')
    return name, text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--body-file', type=Path, help='file holding the issue body')
    src.add_argument('--body-env', metavar='VAR', help='environment variable holding the issue body')
    ap.add_argument('--out-dir', type=Path, default=registry.MODULES_DIR)
    ap.add_argument('--github-output', type=Path, help='append name= and file= for a workflow step')
    args = ap.parse_args(argv)

    body = args.body_file.read_text() if args.body_file else os.environ.get(args.body_env, '')
    try:
        name, text = entry_text(parse_body(body))
    except FormError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    path = args.out_dir / f'{name}.yml'
    path.write_text(text)
    rel = path.relative_to(registry.ROOT) if path.is_relative_to(registry.ROOT) else path
    print(f'wrote {rel}')
    if args.github_output:
        with open(args.github_output, 'a') as f:
            f.write(f'name={name}\nfile={rel}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
