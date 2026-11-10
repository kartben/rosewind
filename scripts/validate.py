#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Validate registry entries.

Offline checks (always): schema, file name, category, license expression,
west project validity, unique names and paths, description markup.

Online checks (--online): repository reachable, revision resolves,
zephyr/module.yml present at that revision, no clash with the projects of
Zephyr's own manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

ZEPHYR_MANIFESTS = (
    'https://raw.githubusercontent.com/zephyrproject-rtos/zephyr/main/west.yml',
    'https://raw.githubusercontent.com/zephyrproject-rtos/zephyr/main/submanifests/optional.yaml',
)


class Report:
    def __init__(self, fmt: str):
        self.fmt = fmt
        self.errors = 0
        self.warnings = 0

    def add(self, level: str, path: Path, msg: str):
        if level == 'error':
            self.errors += 1
        elif level == 'warning':
            self.warnings += 1
        rel = path.relative_to(registry.ROOT) if path.is_relative_to(registry.ROOT) else path
        if self.fmt == 'github' and level in ('error', 'warning'):
            print(f'::{level} file={rel}::{msg}')
        else:
            print(f'{rel}: {level}: {msg}')


def check_license(expr: str, links: dict) -> list[tuple[str, str]]:
    out = []
    try:
        from license_expression import ExpressionError, get_spdx_licensing
    except ImportError:
        get_spdx_licensing = None
    if get_spdx_licensing:
        licensing = get_spdx_licensing()
        try:
            info = licensing.validate(expr)
            unknown = [k for k in info.invalid_symbols if not k.startswith('LicenseRef-')]
            if unknown:
                out.append(('error', f'unknown SPDX identifier(s) in license: {", ".join(unknown)}'))
            errors = [e for e in info.errors if not e.startswith('Unknown license key')]
            if errors:
                out.append(('error', f'invalid license expression: {"; ".join(errors)}'))
        except ExpressionError as e:
            out.append(('error', f'invalid license expression: {e}'))
    if any(i.startswith('LicenseRef-') for i in registry.license_ids(expr)) and 'license' not in links:
        out.append(('error', 'a LicenseRef-* license needs links.license pointing to the license text'))
    return out


def check_keywords(data: dict, category_label: str) -> list[tuple[str, str]]:
    """Keywords add search terms; flag those the entry already contains."""
    fields = {'name': data['name'], 'title': data['title'], 'summary': data['summary'],
              'description': data.get('description', ''), 'category': category_label}
    out = []
    for kw in data.get('keywords', []):
        variants = {kw, kw.replace('-', ' '), kw.replace('_', ' ')}
        for where, text in fields.items():
            if any(re.search(rf'\b{re.escape(v)}\b', text, re.I) for v in variants):
                out.append(('warning', f'keyword "{kw}" already appears in the {where}; keywords are for '
                            'search terms the entry does not contain'))
                break
    return out


def check_description(text: str) -> list[tuple[str, str]]:
    out = []
    stripped = re.sub(r'`[^`]*`', '', text)
    if re.search(r'<[A-Za-z/!][^>]*>', stripped):
        out.append(('error', 'description must not contain HTML; use Markdown or inline code'))
    for url in re.findall(r'\]\(([^)]+)\)', stripped):
        if not url.startswith('https://'):
            out.append(('error', f'description link must use https: {url}'))
    return out


def check_west(proj: dict) -> list[tuple[str, str]]:
    try:
        from west.manifest import MalformedManifest, validate
    except ImportError:
        return [('note', 'west not installed: west project validation skipped')]
    try:
        validate({'manifest': {'projects': [proj]}})
    except MalformedManifest as e:
        return [('error', f'west rejects the project: {e}')]
    return []


def repo_key(url: str) -> str:
    return url.lower().removesuffix('.git').rstrip('/')


def listed_projects(skip: set[str]) -> tuple[dict, dict]:
    """West paths and repositories of the entries in modules/, except those named in `skip`."""
    paths, urls = {}, {}
    for path in registry.entry_paths():
        if path.stem in skip:
            continue
        try:
            proj = registry.load_entry(path).west_project()
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if isinstance(proj['path'], str):
            paths[proj['path']] = path.name
        if isinstance(proj['url'], str):
            urls[repo_key(proj['url'])] = path.name
    return paths, urls


def offline(paths: list[Path], report: Report) -> list[registry.Entry]:
    schema = json.loads(registry.ENTRY_SCHEMA.read_text())
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    categories = registry.load_categories()
    # Entries checked on their own still have to fit with the rest of the registry.
    seen_paths, seen_urls = listed_projects({p.stem for p in paths})
    entries = []

    for path in paths:
        try:
            entry = registry.load_entry(path)
        except (OSError, ValueError, yaml.YAMLError) as e:
            report.add('error', path, f'cannot load: {e}')
            continue
        data = entry.data
        errs = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        for err in errs:
            where = '.'.join(str(p) for p in err.path) or '(top level)'
            report.add('error', path, f'{where}: {err.message}')
        if errs:
            continue

        if data['name'] != path.stem:
            report.add('error', path, f'name "{data["name"]}" must match the file name "{path.stem}"')
        if data['category'] not in categories:
            report.add('error', path, f'unknown category "{data["category"]}"; '
                       f'use one of: {", ".join(categories)}')
        if not data['summary'].rstrip().endswith('.'):
            report.add('error', path, 'summary must be one sentence ending with a period')
        for level, msg in check_license(data['license'], data['links']):
            report.add(level, path, msg)
        if 'description' in data:
            for level, msg in check_description(data['description']):
                report.add(level, path, msg)
        if data['category'] in categories:
            for level, msg in check_keywords(data, categories[data['category']]['label']):
                report.add(level, path, msg)

        proj = entry.west_project()
        for level, msg in check_west(proj):
            report.add(level, path, msg)
        if proj['path'] in seen_paths:
            report.add('error', path, f'west path {proj["path"]} already used by {seen_paths[proj["path"]]}')
        seen_paths[proj['path']] = path.name
        url = repo_key(proj['url'])
        if url in seen_urls:
            report.add('error', path, f'repository already listed in {seen_urls[url]}')
        seen_urls[url] = path.name
        if 'url' in data['west'] and data['west']['url'] == data['links']['repository']:
            report.add('warning', path, 'west.url equals links.repository; drop it, it is the default')
        entries.append(entry)
    return entries


def check_logo(path: Path) -> list[tuple[str, str]]:
    data = path.read_bytes()
    out = []
    if len(data) > registry.LOGO_MAX_BYTES:
        out.append(('error', f'{len(data) // 1024} KiB; logos must be at most '
                    f'{registry.LOGO_MAX_BYTES // 1024} KiB'))
    suffix = path.suffix.lower()
    if suffix == '.svg':
        out += [('error', f'SVG {msg}') for msg in registry.check_svg(data)]
    elif suffix == '.png':
        if registry.image_type(data) != 'png':
            out.append(('error', 'not a PNG file'))
        else:
            width, height = registry.image_size(data)
            if min(width, height) < 64:
                out.append(('error', f'{width}x{height} px; logos must be at least 64 px wide and high'))
            elif not 0.8 <= width / height <= 1.25:
                out.append(('warning', f'{width}x{height} px; a square logo displays best'))
    elif suffix in ('.jpg', '.jpeg') and registry.image_type(data) != 'jpg':
        out.append(('error', 'not a JPEG file'))
    elif suffix == '.webp' and registry.image_type(data) != 'webp':
        out.append(('error', 'not a WebP file'))
    return out


def check_logos(names: set[str], report: Report, only: set[str] | None = None):
    """Check logos/<name>.<ext>: known module, one per module, allowed format."""
    if not registry.LOGOS_DIR.is_dir():
        return
    seen = {}
    for path in sorted(registry.LOGOS_DIR.iterdir()):
        if path.name.startswith('.') or (only is not None and path.stem not in only):
            continue
        if path.suffix.lower() not in registry.LOGO_SUFFIXES:
            report.add('error', path, f'unsupported logo format; use one of {", ".join(registry.LOGO_SUFFIXES)}')
            continue
        if path.stem not in names:
            report.add('error', path, f'no module named "{path.stem}" in modules/')
        if path.stem in seen:
            report.add('error', path, f'"{path.stem}" already has a logo: {seen[path.stem]}')
        seen[path.stem] = path.name
        for level, msg in check_logo(path):
            report.add(level, path, msg)


def zephyr_projects(local: list[str] | None) -> dict[str, str]:
    """Names and paths of the projects in Zephyr's manifest."""
    texts = []
    if local:
        texts = [Path(p).read_text() for p in local]
    else:
        for url in ZEPHYR_MANIFESTS:
            with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 (fixed https URL)
                texts.append(r.read().decode())
    out = {}
    for text in texts:
        man = (yaml.safe_load(text) or {}).get('manifest', {})
        for p in man.get('projects', []):
            out[p['name']] = p.get('path', p['name'])
    return out


def online_one(entry: registry.Entry) -> list[tuple[str, str]]:
    proj = entry.west_project()
    out = []
    try:
        refs = registry.ls_remote(proj['url'])
    except registry.GitError as e:
        return [('error', f'repository not reachable: {proj["url"]}: {e}')]
    kind, _ = registry.resolve_revision(refs, proj['revision'])
    if kind == 'missing':
        return [('error', f'revision "{proj["revision"]}" is not a branch, tag or SHA of {proj["url"]}')]
    if kind == 'branch':
        out.append(('note', f'tracks branch "{proj["revision"]}"; a release tag gives reproducible builds'))
    try:
        found = registry.read_module_yml(proj['url'], proj['revision'])
    except registry.GitError as e:
        return out + [('error', f'cannot fetch revision "{proj["revision"]}": {e}')]
    if found is None:
        if 'west-commands' in proj:
            out.append(('note', 'no zephyr/module.yml; listed for its west extension commands'))
        else:
            out.append(('warning', f'no zephyr/module.yml at "{proj["revision"]}": the Zephyr build '
                        'will not detect this repository as a module'))
    else:
        try:
            info = registry.module_info(found[1], proj['path'])
        except yaml.YAMLError as e:
            out.append(('error', f'{found[0]} is not valid YAML: {e}'))
        else:
            out.append(('note', f'{found[0]}: module "{info["name"]}"'
                        + (f', depends on {", ".join(info["depends"])}' if info['depends'] else '')))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*', help='entries to check (default: all of modules/)')
    ap.add_argument('--online', action='store_true', help='also check repositories over the network')
    ap.add_argument('--zephyr-manifest', action='append', metavar='PATH',
                    help="local copy of Zephyr's west.yml or a submanifest (repeatable); "
                         'default with --online: fetch them from GitHub')
    ap.add_argument('--format', choices=('text', 'github'), default='text')
    ap.add_argument('-q', '--quiet', action='store_true', help='hide notes')
    args = ap.parse_args(argv)

    report = Report(args.format)
    paths = registry.entry_paths(args.files)
    entries = offline(paths, report)
    names = {p.stem for p in registry.entry_paths()}
    check_logos(names, report, {e.name for e in entries} if args.files else None)

    if args.online or args.zephyr_manifest:
        try:
            zp = zephyr_projects(args.zephyr_manifest)
        except OSError as e:
            report.add('warning', registry.ROOT, f"cannot read Zephyr's manifest: {e}")
            zp = {}
        zpaths = {v: k for k, v in zp.items()}
        for entry in entries:
            proj = entry.west_project()
            if proj['name'] in zp:
                report.add('error', entry.path, f'"{proj["name"]}" is already a project in Zephyr\'s manifest')
            if proj['path'] in zpaths:
                report.add('error', entry.path, f'path {proj["path"]} is used by Zephyr\'s "{zpaths[proj["path"]]}"')

    if args.online:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for entry, results in zip(entries, pool.map(online_one, entries)):
                for level, msg in results:
                    if level == 'note' and args.quiet:
                        continue
                    report.add(level, entry.path, msg)

    print(f'{len(paths)} entries checked: {report.errors} error(s), {report.warnings} warning(s)',
          file=sys.stderr)
    return 1 if report.errors else 0


if __name__ == '__main__':
    sys.exit(main())
