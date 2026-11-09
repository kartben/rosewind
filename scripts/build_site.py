#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Build the static site and index.json from the registry entries.

Output layout (default _site/):
  index.html            searchable catalog
  m/<name>/index.html   one page per module
  m/<name>.yaml         ready-to-use west submanifest
  index.json            machine-readable index (schema/index.schema.json)
  404.html, sitemap.xml, robots.txt, .nojekyll, static/
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jsonschema import Draft202012Validator
from markupsafe import Markup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

SITE_DIR = registry.ROOT / 'site'
INDEX_SCHEMA_VERSION = 1

PROVIDES_LABELS = {
    'west-commands': 'West commands', 'boards': 'Boards', 'socs': 'SoCs', 'archs': 'Architectures',
    'dts': 'DT bindings', 'snippets': 'Snippets', 'samples': 'Samples', 'tests': 'Tests',
    'pip': 'Python requirements', 'blobs': 'Binary blobs', 'sysbuild': 'Sysbuild', 'module-ext': 'Module extensions',
}
LICENSE_LABELS = {'permissive': 'Permissive', 'copyleft': 'Copyleft', 'other': 'Custom terms'}


# --- text rendering ----------------------------------------------------------

def _inline(text: str, links: bool = True) -> str:
    """Escape text and render `code`, [links](https://…), **strong** and *em*."""
    parts = re.split(r'(`[^`]+`)', text)
    out = []
    for part in parts:
        if part.startswith('`') and part.endswith('`') and len(part) > 1:
            out.append(f'<code>{html.escape(part[1:-1])}</code>')
            continue
        s = html.escape(part, quote=False)
        if links:
            s = re.sub(r'\[([^\]]+)\]\((https://[^)\s]+)\)',
                       lambda m: f'<a href="{html.escape(m[2])}" rel="noopener">{m[1]}</a>', s)
        s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])', r'<em>\1</em>', s)
        out.append(s)
    return ''.join(out)


def markdown(text: str) -> Markup:
    """The Markdown subset allowed in descriptions: paragraphs, lists, inline markup."""
    blocks = []
    for block in re.split(r'\n\s*\n', (text or '').strip()):
        lines = block.splitlines()
        if not lines:
            continue
        if re.match(r'^\s*[-*] ', lines[0]):
            items = []
            for line in lines:
                if re.match(r'^\s*[-*] ', line):
                    items.append(line.strip()[2:])
                elif items:
                    items[-1] += ' ' + line.strip()
            blocks.append('<ul>' + ''.join(f'<li>{_inline(i)}</li>' for i in items) + '</ul>')
        else:
            blocks.append(f'<p>{_inline(" ".join(line.strip() for line in lines))}</p>')
    return Markup('\n'.join(blocks))


def inline_code(text: str) -> Markup:
    return Markup(_inline(text, links=False))


def yaml_highlight(src: str) -> Markup:
    out = []
    for line in src.splitlines():
        if re.match(r'^\s*#', line):
            out.append(f'<span class="y-c">{html.escape(line)}</span>')
            continue
        m = re.match(r'^(\s*-?\s*)([\w.-]+)(:)(.*)$', line)
        if m:
            lead, key, colon, val = m.groups()
            val_html = f'<span class="y-s">{html.escape(val)}</span>' if val.strip() else html.escape(val)
            out.append(f'{html.escape(lead)}<span class="y-k">{html.escape(key)}</span>{colon}{val_html}')
        else:
            out.append(html.escape(line))
    return Markup('\n'.join(out))


def ago(days: int | None) -> str:
    if days is None:
        return 'unknown'
    if days < 1:
        return 'today'
    if days < 30:
        return f'{days} day{"s" if days > 1 else ""} ago'
    if days < 365:
        return f'{round(days / 30)} mo ago'
    return f'{days / 365:.1f} yr ago'


def fmt_stars(n) -> str:
    if n is None:
        return ''
    return f'{n / 1000:.1f}k'.replace('.0k', 'k') if n >= 1000 else str(n)


# --- model -------------------------------------------------------------------

def build_records(entries, categories, enriched, today: date, base_url: str):
    by_module_name = {}
    for e in entries:
        mod = (enriched.get(e.name) or {}).get('module') or {}
        by_module_name[mod.get('name') or e.name] = e.name
        by_module_name.setdefault(e.name, e.name)

    records = []
    for e in entries:
        d = e.data
        enr = enriched.get(e.name) or {}
        proj = e.west_project()
        mod = enr.get('module') or {}
        repo = enr.get('repo') or {}

        provides = list(mod.get('provides') or [])
        if 'west-commands' in proj:
            provides.insert(0, 'west-commands')
        deps = []
        for dep in mod.get('depends') or []:
            target = by_module_name.get(dep)
            deps.append({'module': dep, 'entry': target})

        pushed = repo.get('pushed_at')
        days = (today - date.fromisoformat(pushed[:10])).days if pushed else None
        activity = None if days is None else 'active' if days <= 90 else 'quiet' if days <= 365 else 'inactive'

        records.append({
            'name': e.name,
            'title': d['title'],
            'summary': d['summary'].strip(),
            'description': d.get('description', '').strip(),
            'category': d['category'],
            'category_label': categories[d['category']]['label'],
            'hue': categories[d['category']]['hue'],
            'tags': d.get('tags', []),
            'license': d['license'],
            'license_kind': registry.license_kind(d['license']),
            'maintainers': d['maintainers'],
            'links': d['links'],
            'status': d.get('status', 'active'),
            'west': proj,
            'revision_kind': (enr.get('revision') or {}).get('kind'),
            'module': {'found': bool(mod.get('found')), 'name': mod.get('name'),
                       'depends': mod.get('depends') or []} if mod else None,
            'provides': provides,
            'dependencies': deps,
            'repo': {k: repo.get(k) for k in ('stars', 'pushed_at', 'archived', 'latest_release')} if repo else None,
            'newer_release': enr.get('newer_release'),
            'checks': registry.compute_checks(e, enr or None, today),
            'days': days,
            'activity': activity,
            'owner': proj['url'].split('://', 1)[-1].split('/')[1],
            'page_url': f'{base_url}/m/{e.name}/',
            'submanifest_url': f'{base_url}/m/{e.name}.yaml',
            'entry_text': e.text,
            'entry_file': f'modules/{e.path.name}',
        })
    records.sort(key=lambda r: r['title'].lower())
    by_name = {r['name']: r for r in records}
    for r in records:
        r['install_set'] = [by_name[d['entry']] for d in r['dependencies']
                            if d['entry'] and d['entry'] != r['name']] + [r]
    return records


def index_json(records, categories, generated: str, base_url: str) -> dict:
    mods = []
    for r in records:
        m = {k: r[k] for k in ('name', 'title', 'summary', 'category', 'tags', 'license', 'license_kind',
                               'maintainers', 'links', 'status', 'west', 'provides', 'page_url',
                               'submanifest_url')}
        m['description'] = r['description']
        m['revision_kind'] = r['revision_kind']
        m['dependencies'] = r['dependencies']
        m['repo'] = r['repo']
        m['newer_release'] = r['newer_release']
        m['checks'] = [{k: c[k] for k in ('level', 'code', 'message')} for c in r['checks']]
        mods.append(m)
    return {
        'schema-version': INDEX_SCHEMA_VERSION,
        'generated': generated,
        'site': base_url,
        'categories': [{'id': k, 'label': v['label'], 'description': v['description']}
                       for k, v in categories.items()],
        'modules': mods,
    }


def card_data(records) -> list[dict]:
    """The subset of fields the catalog script filters and searches on."""
    return [{
        'name': r['name'], 'title': r['title'], 'summary': r['summary'], 'category': r['category'],
        'tags': r['tags'], 'license': r['license'], 'license_kind': r['license_kind'], 'owner': r['owner'],
    } for r in records]


def minimal_entry(text: str) -> str:
    """An entry without its license header and description, as a short example."""
    out, skipping = [], False
    for line in text.splitlines():
        if line.startswith('# SPDX-') or (not out and not line.strip()):
            continue
        if line.startswith('description:'):
            skipping = True
            continue
        if skipping and (line.startswith(' ') or not line.strip()):
            continue
        skipping = False
        out.append(line)
    return '\n'.join(out) + '\n'


# --- main --------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=registry.ROOT / '_site')
    ap.add_argument('--enriched', type=Path, default=registry.ROOT / 'build' / 'enriched.json')
    ap.add_argument('--base-url', help='absolute site URL without trailing slash (default: site.yml)')
    ap.add_argument('--repository', help='registry repository URL used for edit and issue links '
                    '(default: site.yml)')
    ap.add_argument('--today', type=date.fromisoformat, help='reference date for activity (testing)')
    args = ap.parse_args(argv)

    config = registry.load_site_config()
    if args.repository:
        config['repository'] = args.repository.rstrip('/')
    base_url = (args.base_url or config.get('base_url', '')).rstrip('/')
    categories = registry.load_categories()
    entries = [registry.load_entry(p) for p in registry.entry_paths()]
    enriched_doc = json.loads(args.enriched.read_text()) if args.enriched.exists() else {}
    enriched = enriched_doc.get('modules', {})
    if not enriched:
        print('note: no enrichment data; run scripts/enrich.py for repository checks', file=sys.stderr)
    today = args.today or date.today()
    generated = datetime.now(timezone.utc).isoformat(timespec='seconds')

    records = build_records(entries, categories, enriched, today, base_url)

    env = Environment(loader=FileSystemLoader(SITE_DIR / 'templates'),
                      autoescape=select_autoescape(['html']), trim_blocks=True, lstrip_blocks=True)
    env.filters.update(markdown=markdown, inline_code=inline_code, yaml_highlight=yaml_highlight,
                       ago=ago, stars=fmt_stars)
    env.globals.update(config=config, base_url=base_url, categories=categories,
                       provides_labels=PROVIDES_LABELS, license_labels=LICENSE_LABELS,
                       submanifest_text=registry.submanifest_text, project_lines=registry.project_lines,
                       enriched_at=enriched_doc.get('generated'), generated=generated,
                       category_counts=Counter(r['category'] for r in records),
                       license_counts=Counter(r['license_kind'] for r in records), current_category=None)

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    (out / 'm').mkdir(parents=True)
    shutil.copytree(SITE_DIR / 'static', out / 'static')
    (out / '.nojekyll').write_text('')

    index = index_json(records, categories, generated, base_url)
    schema = json.loads(registry.INDEX_SCHEMA.read_text())
    errors = list(Draft202012Validator(schema).iter_errors(index))
    if errors:
        for err in errors[:10]:
            print(f'index.json: {"/".join(map(str, err.path))}: {err.message}', file=sys.stderr)
        return 1
    (out / 'index.json').write_text(json.dumps(index, indent=1, ensure_ascii=False) + '\n')

    (out / 'index.html').write_text(env.get_template('index.html').render(
        records=records, cards_json=Markup(json.dumps(card_data(records)).replace('</', '<\\/')), depth=''))
    sample = next((r for r in records if r['name'] == 'zenoh-pico'), records[0] if records else None)
    (out / 'contribute').mkdir()
    (out / 'contribute' / 'index.html').write_text(env.get_template('contribute.html').render(
        sample=sample, sample_entry=minimal_entry(sample['entry_text']) if sample else '', depth='../'))
    for r in records:
        page = out / 'm' / r['name']
        page.mkdir()
        (page / 'index.html').write_text(env.get_template('module.html').render(
            m=r, depth='../../', current_category=r['category']))
        (out / 'm' / f'{r["name"]}.yaml').write_text(registry.submanifest_text(r['west'], r['page_url']))
    (out / '404.html').write_text(env.get_template('404.html').render(depth=base_url + '/' if base_url else '/'))

    urls = [f'{base_url}/', f'{base_url}/contribute/'] + [r['page_url'] for r in records]
    (out / 'sitemap.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + ''.join(f'  <url><loc>{html.escape(u)}</loc></url>\n' for u in urls) + '</urlset>\n')
    (out / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n')
    print(f'built {len(records)} module pages into {out}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
