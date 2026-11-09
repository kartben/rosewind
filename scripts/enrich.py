#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Collect repository data for every entry and write build/enriched.json.

Uses git for everything that works on any host (revision, tags,
zephyr/module.yml) and the GitHub REST API for stars, activity and releases
when the repository is on github.com. Set GITHUB_TOKEN to raise the API rate
limit. --report writes a Markdown summary of what needs attention.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

GITHUB = re.compile(r'^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$')


def github_api(path: str) -> dict | None:
    req = urllib.request.Request(f'https://api.github.com/{path}',
                                 headers={'Accept': 'application/vnd.github+json',
                                          'User-Agent': 'zephyr-community-modules'})
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed https host)
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def github_info(url: str) -> dict | None:
    m = GITHUB.match(url)
    if not m:
        return None
    owner, name = m.groups()
    repo = github_api(f'repos/{owner}/{name}')
    if repo is None:
        return None
    info = {
        'host': 'github',
        'full_name': repo['full_name'],
        'stars': repo['stargazers_count'],
        'pushed_at': repo['pushed_at'],
        'archived': repo['archived'],
        'default_branch': repo['default_branch'],
        'latest_release': None,
    }
    rel = github_api(f'repos/{owner}/{name}/releases/latest')
    if rel:
        info['latest_release'] = {'tag': rel['tag_name'], 'date': rel['published_at']}
    return info


def enrich_one(entry: registry.Entry, use_github: bool) -> dict:
    proj = entry.west_project()
    out: dict = {}
    try:
        refs = registry.ls_remote(proj['url'])
    except registry.GitError as e:
        return {'error': f'Repository not reachable: {e}'}
    kind, sha = registry.resolve_revision(refs, proj['revision'])
    if kind == 'missing':
        return {'error': f'Revision `{proj["revision"]}` does not exist in the repository.'}
    out['revision'] = {'kind': kind, 'sha': sha}

    try:
        found = registry.read_module_yml(proj['url'], proj['revision'])
    except registry.GitError as e:
        return {'error': f'Cannot fetch revision `{proj["revision"]}`: {e}'}
    out['module'] = registry.module_info(found[1], proj['path']) if found else {'found': False}

    tags = [r.removeprefix('refs/tags/') for r in refs if r.startswith('refs/tags/')]
    out['latest_tag'] = registry.latest_tag(tags, like=proj['revision'] if kind == 'tag' else None)

    if use_github:
        try:
            out['repo'] = github_info(proj['url'])
        except (urllib.error.URLError, TimeoutError) as e:
            out['repo'] = None
            out['github_error'] = str(e)

    latest = ((out.get('repo') or {}).get('latest_release') or {}).get('tag') or out['latest_tag']
    if kind == 'tag' and latest and registry.is_newer(latest, proj['revision']):
        out['newer_release'] = latest
    return out


def write_report(entries, data, path: Path):
    today = date.today()
    sections = {'error': [], 'warning': [], 'newer-release': []}
    for e in entries:
        for c in registry.compute_checks(e, data.get(e.name), today):
            if c['code'] == 'newer-release':
                sections['newer-release'].append(f'- `{e.name}`: `{e.west_project()["revision"]}` → '
                                                 f'`{data[e.name]["newer_release"]}`')
            elif c['level'] in ('error', 'warning'):
                sections[c['level']].append(f'- `{e.name}`: {c["message"]}')
    lines = [f'# Registry report, {today.isoformat()}', '']
    for key, title in (('error', 'Errors'), ('warning', 'Warnings'),
                       ('newer-release', 'Pinned to an older release')):
        lines += [f'## {title} ({len(sections[key])})', ''] + (sections[key] or ['None.']) + ['']
    path.write_text('\n'.join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*', help='entries to refresh (default: all); others keep their data')
    ap.add_argument('--out', type=Path, default=registry.ROOT / 'build' / 'enriched.json')
    ap.add_argument('--report', type=Path, help='write a Markdown report of entries needing attention')
    ap.add_argument('--no-github', action='store_true', help='skip the GitHub API')
    args = ap.parse_args(argv)

    all_entries = [registry.load_entry(p) for p in registry.entry_paths()]
    targets = [registry.load_entry(p) for p in registry.entry_paths(args.files)] if args.files else all_entries

    data = {}
    if args.files and args.out.exists():
        data = json.loads(args.out.read_text()).get('modules', {})

    with ThreadPoolExecutor(max_workers=8) as pool:
        for entry, result in zip(targets, pool.map(lambda e: enrich_one(e, not args.no_github), targets)):
            data[entry.name] = result
            status = result.get('error') or (
                f'{result["revision"]["kind"]}, module.yml {"yes" if result["module"]["found"] else "no"}'
                + (f', newer: {result["newer_release"]}' if result.get('newer_release') else ''))
            print(f'{entry.name:24} {status}', file=sys.stderr)

    known = {e.name for e in all_entries}
    data = {k: v for k, v in sorted(data.items()) if k in known}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'modules': data,
    }, indent=1) + '\n')
    if args.report:
        write_report(all_entries, data, args.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
