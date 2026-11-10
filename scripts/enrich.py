#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Collect repository data for every entry and write build/enriched.json.

Uses git for everything that works on any host (revision, tags,
zephyr/module.yml) and the GitHub REST API for stars, activity and releases
when the repository is on github.com. It also saves the icon that the
module's homepage (or documentation site) declares, next to the output, as
the image of modules without a logo in logos/. Set GITHUB_TOKEN to raise the
API rate limit. --report writes a Markdown summary of what needs attention.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

GITHUB = re.compile(r'^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$')
# URLError, timeouts and dropped connections are OSErrors; bad responses raise
# HTTPException; bad URLs and bad JSON raise ValueError.
NETWORK_ERRORS = (OSError, http.client.HTTPException, ValueError)


def github_api(path: str) -> dict | None:
    req = urllib.request.Request(f'https://api.github.com/{path}',
                                 headers={'Accept': 'application/vnd.github+json',
                                          'User-Agent': 'rosewind'})
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


ICON_MIN_PX = 32
ICON_MAX_BYTES = 200 * 1024
ICON_CANDIDATES = 5
ICON_TIME_BUDGET = 60  # seconds per module for its pages and icons
# Sites whose favicon is the host's, not the project's.
GENERIC_HOSTS = ('github.com', 'gitlab.com', 'readthedocs.io', 'readthedocs.org', 'github.io')


class IconLinks(HTMLParser):
    """Collect <link rel="icon"> and <link rel="apple-touch-icon"> declarations."""

    def __init__(self):
        super().__init__()
        self.icons = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        rel = (a.get('rel') or '').lower().split()
        if tag == 'link' and a.get('href') and ('icon' in rel or 'apple-touch-icon' in rel):
            self.icons.append(a)


class HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise urllib.error.HTTPError(newurl, code, 'redirect to a non-https URL', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(HttpsOnlyRedirects)


def fetch(url: str, limit: int, deadline: float) -> bytes:
    """GET an https URL, reading at most limit + 1 bytes before `deadline` (time.monotonic())."""
    if urlsplit(url).scheme != 'https':
        raise ValueError(f'not an https URL: {url}')
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError('time budget spent')
    req = urllib.request.Request(url, headers={'User-Agent': 'rosewind'})
    data = b''
    with _OPENER.open(req, timeout=min(20, left)) as r:
        while len(data) <= limit:
            if time.monotonic() > deadline:
                raise TimeoutError('time budget spent')
            chunk = r.read(min(64 * 1024, limit + 1 - len(data)))
            if not chunk:
                break
            data += chunk
    return data


def icon_candidates(page_url: str, html: str, allow_favicon: bool) -> list[str]:
    """Icon URLs declared by a page, best first: SVG, then the largest size."""
    parser = IconLinks()
    parser.feed(html)

    def rank(a):
        href = a['href'].lower()
        if a.get('type') == 'image/svg+xml' or href.split('?')[0].endswith('.svg'):
            return 10000
        sizes = [int(s.split('x')[0]) for s in (a.get('sizes') or '').lower().split() if 'x' in s and s.split('x')[0].isdigit()]
        if sizes:
            return max(sizes)
        return 180 if 'apple-touch-icon' in a.get('rel', '').lower() else 16

    urls = [urljoin(page_url, a['href']) for a in sorted(parser.icons, key=rank, reverse=True)]
    if allow_favicon:
        urls.append(urljoin(page_url, '/favicon.ico'))
    urls = [u for u in urls if urlsplit(u).scheme == 'https']
    return list(dict.fromkeys(urls))[:ICON_CANDIDATES]


def fetch_site_icon(entry: registry.Entry, dest: Path) -> tuple[str, str] | None:
    """Save the icon of the module's homepage or documentation site.

    Returns (file name, source URL). Raster icons under ICON_MIN_PX and SVG
    files that fail the logo checks are skipped.
    """
    links = entry.data.get('links', {})
    deadline = time.monotonic() + ICON_TIME_BUDGET
    for key in ('homepage', 'documentation'):
        page = links.get(key)
        if not page:
            continue
        host = urlsplit(page).hostname or ''
        if any(host == g or host.endswith('.' + g) for g in GENERIC_HOSTS) and key == 'homepage':
            continue
        try:
            html = fetch(page, 2 * 1024 * 1024, deadline).decode('utf-8', 'replace')
        except NETWORK_ERRORS:
            continue
        generic = any(host == g or host.endswith('.' + g) for g in GENERIC_HOSTS)
        for url in icon_candidates(page, html, allow_favicon=key == 'homepage' and not generic):
            try:
                data = fetch(url, ICON_MAX_BYTES, deadline)
            except NETWORK_ERRORS:
                continue
            kind = registry.image_type(data)
            if not kind or len(data) > ICON_MAX_BYTES:
                continue
            if kind == 'svg' and registry.check_svg(data):
                continue
            size = registry.image_size(data)
            if kind != 'svg' and (size is None and kind in ('png', 'ico') or size and min(size) < ICON_MIN_PX):
                continue
            dest.mkdir(parents=True, exist_ok=True)
            name = f'{entry.name}.{kind}'
            (dest / name).write_bytes(data)
            return name, url
    return None


def enrich_one(entry: registry.Entry, use_github: bool, icon_dir: Path) -> dict:
    proj = entry.west_project()
    out: dict = {}
    try:
        refs = registry.ls_remote(proj['url'])
    except registry.GitError as e:
        return {'error': f'Repository not reachable: {e}'}
    kind, sha = registry.resolve_revision(refs, proj['revision'])
    if kind == 'short-sha':
        return {'error': f'Revision `{proj["revision"]}` is an abbreviated commit SHA: use all 40 characters.'}
    if kind == 'missing':
        return {'error': f'Revision `{proj["revision"]}` does not exist in the repository.'}
    out['revision'] = {'kind': kind, 'sha': sha}

    try:
        found = registry.read_module_yml(proj['url'], proj['revision'])
    except registry.GitError as e:
        return {'error': f'Cannot fetch revision `{proj["revision"]}`: {e}'}
    try:
        out['module'] = registry.module_info(found[1], proj['path']) if found else {'found': False}
    except yaml.YAMLError:
        out['module'] = {'found': True, 'invalid': True, 'name': Path(proj['path']).name, 'depends': [],
                         'provides': []}

    tags = [r.removeprefix('refs/tags/') for r in refs if r.startswith('refs/tags/')]
    out['latest_tag'] = registry.latest_tag(tags, like=proj['revision'] if kind == 'tag' else None)

    if use_github:
        try:
            out['repo'] = github_info(proj['url'])
        except NETWORK_ERRORS as e:
            out['repo'] = None
            out['github_error'] = str(e)
        icon = fetch_site_icon(entry, icon_dir)
        if icon:
            out['icon'], out['icon_source'] = icon

    latest = ((out.get('repo') or {}).get('latest_release') or {}).get('tag') or out['latest_tag']
    if kind == 'tag' and latest and registry.is_newer(latest, proj['revision']):
        out['newer_release'] = latest
    return out


def enrich_entry(entry: registry.Entry, use_github: bool, icon_dir: Path) -> dict:
    """enrich_one(), reporting any failure as the entry's error: one module must not stop the run."""
    try:
        return enrich_one(entry, use_github, icon_dir)
    except Exception as e:  # noqa: BLE001
        return {'error': f'Collecting repository data failed: {type(e).__name__}: {e}'}


def write_report(entries, data, path: Path):
    today = date.today()
    sections = {'error': [], 'warning': [], 'newer-release': []}
    claims = registry.module_names(entries, data)
    for e in entries:
        for c in registry.compute_checks(e, data.get(e.name), today, claims):
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
        icon_dir = args.out.parent / 'icons'
        results = pool.map(lambda e: enrich_entry(e, not args.no_github, icon_dir), targets)
        for entry, result in zip(targets, results):
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
