# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the Rosewind registry scripts."""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT / 'modules'
CATEGORIES_FILE = ROOT / 'categories.yml'
ENTRY_SCHEMA = ROOT / 'schema' / 'entry.schema.json'
INDEX_SCHEMA = ROOT / 'schema' / 'index.schema.json'
SITE_CONFIG = ROOT / 'site.yml'
LOGOS_DIR = ROOT / 'logos'

# Optional west project keys copied verbatim from an entry, in output order.
WEST_OPTIONAL_KEYS = ('submodules', 'west-commands', 'groups')

GIT_TIMEOUT = 120


class GitError(Exception):
    pass


@dataclass
class Entry:
    path: Path
    data: dict
    text: str

    @property
    def name(self) -> str:
        return self.data.get('name', self.path.stem)

    def west_project(self) -> dict:
        """The west project this entry adds, with defaults applied."""
        w = self.data.get('west', {})
        proj = {
            'name': self.name,
            'url': w.get('url') or self.data.get('links', {}).get('repository'),
            'revision': str(w.get('revision')),
            'path': w.get('path'),
        }
        for key in WEST_OPTIONAL_KEYS:
            if key in w:
                proj[key] = w[key]
        return proj


def load_yaml(path: Path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_categories() -> dict:
    return load_yaml(CATEGORIES_FILE)


def load_entry(path: Path) -> Entry:
    text = path.read_text(encoding='utf-8')
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError('top level must be a mapping')
    return Entry(path=path, data=data, text=text)


def entry_paths(paths=None) -> list[Path]:
    if paths:
        return [Path(p).resolve() for p in paths]
    return sorted(MODULES_DIR.glob('*.yml'))


def load_site_config() -> dict:
    if SITE_CONFIG.exists():
        return load_yaml(SITE_CONFIG) or {}
    return {}


# --- logos -------------------------------------------------------------------

LOGO_SUFFIXES = ('.svg', '.png', '.webp', '.jpg', '.jpeg')
LOGO_MAX_BYTES = 100 * 1024


def logo_path(name: str) -> Path | None:
    """The logo a module provides as logos/<name>.<ext>, if any."""
    for suffix in LOGO_SUFFIXES:
        path = LOGOS_DIR / f'{name}{suffix}'
        if path.is_file():
            return path
    return None


def image_type(data: bytes) -> str | None:
    """Sniff an image format from its first bytes: png, jpg, webp, ico or svg."""
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data[:4] == b'\x00\x00\x01\x00':
        return 'ico'
    if b'<svg' in data[:2048]:
        return 'svg'
    return None


def image_size(data: bytes) -> tuple[int, int] | None:
    """Pixel size of a PNG, or of the largest image of an ICO; None otherwise."""
    kind = image_type(data)
    if kind == 'png' and len(data) >= 24:
        return struct.unpack('>II', data[16:24])
    if kind == 'ico' and len(data) >= 6:
        count = struct.unpack('<H', data[4:6])[0]
        sizes = [(data[6 + 16 * i] or 256, data[7 + 16 * i] or 256)
                 for i in range(count) if len(data) >= 8 + 16 * i]
        return max(sizes) if sizes else None
    return None


SVG_NS = 'http://www.w3.org/2000/svg'
# Metadata written by editors, which browsers ignore.
SVG_EDITOR_NS = {
    'http://www.inkscape.org/namespaces/inkscape', 'http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd',
    'http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'http://creativecommons.org/ns#',
    'http://purl.org/dc/elements/1.1/',
}
# Static drawing elements: no script, animation, links, images or foreign content.
SVG_ELEMENTS = {
    'svg', 'g', 'defs', 'symbol', 'use', 'title', 'desc', 'metadata', 'style',
    'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'text', 'tspan',
    'linearGradient', 'radialGradient', 'stop', 'clipPath', 'mask', 'pattern',
    'filter', 'feBlend', 'feColorMatrix', 'feComposite', 'feFlood', 'feGaussianBlur', 'feMerge',
    'feMergeNode', 'feOffset',
}
_CSS_URL = re.compile(r'url\(\s*[\'"]?\s*([^\'")\s]*)', re.I)


def check_svg(data: bytes) -> list[str]:
    """An SVG image must be a static, self-contained drawing.

    Logos and website icons are served from the site's own origin, where an
    SVG opened directly runs its scripts: only known drawing elements are
    accepted, and references must point inside the file.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        return [f'not valid XML: {e}']
    if root.tag not in ('svg', f'{{{SVG_NS}}}svg'):
        return ['root element is not <svg>']
    errors = []

    def check_refs(text: str):
        if 'javascript:' in text.lower() or '@import' in text.lower():
            errors.append('scripts and imports are not allowed')
        for ref in _CSS_URL.findall(text):
            if not ref.startswith('#'):
                errors.append(f'external reference {ref} is not allowed')

    for el in root.iter():
        ns, _, tag = el.tag[1:].partition('}') if el.tag.startswith('{') else ('', '', el.tag)
        if ns in SVG_EDITOR_NS:
            continue
        if ns not in ('', SVG_NS) or tag not in SVG_ELEMENTS:
            errors.append(f'<{tag}> is not allowed')
        if tag == 'style' and el.text:
            check_refs(el.text)
        for attr, value in el.attrib.items():
            name = attr.rsplit('}', 1)[-1]
            if name.lower().startswith('on'):
                errors.append(f'event attribute {name} is not allowed')
            if name == 'href' and not value.startswith('#'):
                errors.append(f'external reference {value} is not allowed')
            check_refs(value)
    return sorted(set(errors))


# --- YAML emission -----------------------------------------------------------

_PLAIN = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9 ._/+@():-]*$')
# Quoted although they read back as strings: they look like numbers or booleans to other parsers.
_RESERVED = re.compile(r'^(true|false|yes|no|on|off|null|~|[0-9][0-9._]*)$', re.I)


def _reads_back(s: str) -> bool:
    """Whether YAML reads the plain scalar `s` as that same string, not a number, date or bool."""
    try:
        return yaml.safe_load(f'k: {s}') == {'k': s}
    except yaml.YAMLError:
        return False


def yaml_scalar(value) -> str:
    """Emit a scalar, quoting only when plain style would change its meaning."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    s = str(value)
    if (_PLAIN.match(s) and not _RESERVED.match(s) and not s.endswith((' ', ':')) and ': ' not in s
            and _reads_back(s)):
        return s
    return json.dumps(s, ensure_ascii=False)


def project_lines(proj: dict, indent: int = 4) -> list[str]:
    """Lines of one west project as a list item, in a fixed key order."""
    pad = ' ' * indent
    lines = [f'{pad}- name: {yaml_scalar(proj["name"])}']
    for key in ('url', 'revision', 'path'):
        lines.append(f'{pad}  {key}: {yaml_scalar(proj[key])}')
    for key in WEST_OPTIONAL_KEYS:
        if key not in proj:
            continue
        val = proj[key]
        if key == 'submodules' and isinstance(val, list):
            lines.append(f'{pad}  submodules:')
            for sub in val:
                first = True
                for k, v in sub.items():
                    lead = '- ' if first else '  '
                    lines.append(f'{pad}    {lead}{k}: {yaml_scalar(v)}')
                    first = False
        elif isinstance(val, list):
            lines.append(f'{pad}  {key}: [{", ".join(yaml_scalar(v) for v in val)}]')
        else:
            lines.append(f'{pad}  {key}: {yaml_scalar(val)}')
    return lines


def submanifest_text(proj: dict, source_url: str | None = None, source: str | None = None) -> str:
    """A complete west submanifest that adds one project, from the site named `source`."""
    head = [f'# {proj["name"]} from {source}' if source else f'# {proj["name"]}']
    if source_url:
        head.append(f'# {source_url}')
    return '\n'.join(head + ['manifest:', '  projects:'] + project_lines(proj, 4)) + '\n'


# --- licenses ----------------------------------------------------------------

_PERMISSIVE = {
    '0BSD', 'Apache-2.0', 'BSD-1-Clause', 'BSD-2-Clause', 'BSD-3-Clause', 'BSD-3-Clause-Clear',
    'BSL-1.0', 'CC0-1.0', 'ISC', 'MIT', 'MIT-0', 'Unlicense', 'Zlib', 'curl', 'PSF-2.0',
}


def _license_rank(ident: str) -> int:
    base = ident.split(' WITH ')[0].strip('() ')
    if base in _PERMISSIVE:
        return 0
    if re.match(r'^(A?GPL|LGPL|MPL|EPL|EUPL|CDDL|OSL|CECILL)', base):
        return 1
    return 2


def license_kind(expr: str) -> str:
    """Classify an SPDX expression: an OR picks the most permissive option,
    an AND the most restrictive part. Parentheses are flattened."""
    flat = expr.replace('(', ' ').replace(')', ' ')
    alternatives = [a for a in re.split(r'\s+OR\s+', flat) if a.strip()]
    rank = min(
        max(_license_rank(p.strip()) for p in re.split(r'\s+AND\s+', alt) if p.strip())
        for alt in alternatives
    )
    return ('permissive', 'copyleft', 'other')[rank]


def license_ids(expr: str) -> list[str]:
    tokens = re.findall(r'[A-Za-z0-9.+-]+(?:-[A-Za-z0-9.+-]+)*', expr.replace('(', ' ').replace(')', ' '))
    return [t for t in tokens if t not in ('AND', 'OR', 'WITH')]


# --- git ---------------------------------------------------------------------

def _git(*args, cwd=None, timeout=GIT_TIMEOUT) -> str:
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'true'}
    try:
        res = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise GitError(f'git {args[0]} timed out') from e
    if res.returncode != 0:
        msg = (res.stderr.strip().splitlines() or ['unknown error'])[-1]
        raise GitError(msg)
    return res.stdout


def ls_remote(url: str) -> dict[str, str]:
    """Map ref names to SHAs; peeled tags replace the tag object SHA."""
    refs = {}
    for line in _git('ls-remote', '--tags', '--heads', url).splitlines():
        sha, ref = line.split('\t', 1)
        if ref.endswith('^{}'):
            refs[ref[:-3]] = sha
        else:
            refs.setdefault(ref, sha)
    return refs


def resolve_revision(refs: dict[str, str], revision: str) -> tuple[str, str | None]:
    """Return (kind, sha) where kind is tag, branch, sha, short-sha or missing.

    A commit is fetched by its full SHA: servers do not resolve abbreviated ones.
    """
    if f'refs/tags/{revision}' in refs:
        return 'tag', refs[f'refs/tags/{revision}']
    if f'refs/heads/{revision}' in refs:
        return 'branch', refs[f'refs/heads/{revision}']
    if re.fullmatch(r'[0-9a-f]{40}', revision):
        return 'sha', revision
    if re.fullmatch(r'[0-9a-f]{7,39}', revision):
        return 'short-sha', None
    return 'missing', None


MODULE_FILES = ('zephyr/module.yml', 'zephyr/module.yaml')
# Without a module file, Zephyr still takes a repository that has both of these files as a module,
# named after its directory (scripts/zephyr_module.py).
BUILD_FILES = ('zephyr/CMakeLists.txt', 'zephyr/Kconfig')


def read_module_yml(url: str, revision: str) -> tuple[str, str | None] | None:
    """Fetch only the commit and trees of a revision, then read its module file.

    Returns (path, text) of the module file, (BUILD_FILES[0], None) when the revision has no module
    file but has BUILD_FILES, or None when Zephyr would not take it as a module.
    """
    with tempfile.TemporaryDirectory(prefix='rosewind-') as tmp:
        _git('init', '-q', cwd=tmp)
        _git('fetch', '-q', '--depth', '1', '--filter=blob:none', url, revision, cwd=tmp)
        for path in MODULE_FILES:
            try:
                return path, _git('show', f'FETCH_HEAD:{path}', cwd=tmp)
            except GitError:
                continue
        listed = _git('ls-tree', '--name-only', 'FETCH_HEAD', '--', *BUILD_FILES, cwd=tmp).split()
        if set(listed) == set(BUILD_FILES):
            return BUILD_FILES[0], None
    return None


def module_names(entries, enriched: dict) -> dict[str, list[str]]:
    """Map each Zephyr module name to the entries whose zephyr/module.yml declares it.

    The names come from upstream repositories, not from reviewed entries: a
    dependency is only linked to an entry when exactly one entry declares it.
    """
    claims: dict[str, list[str]] = {}
    for e in entries:
        name = ((enriched.get(e.name) or {}).get('module') or {}).get('name')
        claims.setdefault(name if isinstance(name, str) and name else e.name, []).append(e.name)
    return claims


PROVIDES_SETTINGS = {
    'board_root': 'boards', 'soc_root': 'socs', 'arch_root': 'archs', 'dts_root': 'dts',
    'snippet_root': 'snippets', 'module_ext_root': 'module-ext',
}


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def module_info(text: str, west_path: str) -> dict:
    """Summarize a zephyr/module.yml: name, dependencies and what it provides.

    The file comes from an upstream repository: values of an unexpected type
    are ignored. Raises yaml.YAMLError when the file is not YAML.
    """
    data = _mapping(yaml.safe_load(text))
    build = _mapping(data.get('build'))
    settings = _mapping(build.get('settings'))
    provides = [label for key, label in PROVIDES_SETTINGS.items() if settings.get(key)]
    for key in ('samples', 'tests'):
        if data.get(key):
            provides.append(key)
    if _mapping(data.get('package-managers')).get('pip'):
        provides.append('pip')
    if data.get('blobs'):
        provides.append('blobs')
    if build.get('sysbuild-cmake'):
        provides.append('sysbuild')
    name, depends = data.get('name'), build.get('depends')
    return {
        'found': True,
        'name': name if isinstance(name, str) and name else Path(west_path).name,
        'depends': [d for d in depends if isinstance(d, str)] if isinstance(depends, list) else [],
        'provides': provides,
    }


# --- versions ----------------------------------------------------------------

_VERSION = re.compile(r'^(?P<prefix>\D*?)(?P<num>\d+(?:\.\d+)*)(?P<suffix>.*)$')
_PRERELEASE = re.compile(r'(rc|alpha|beta|pre|dev|snapshot)', re.I)


def parse_version(tag: str):
    """Split a tag into (prefix, numeric tuple, suffix), or None."""
    m = _VERSION.match(tag)
    if not m:
        return None
    return m['prefix'], tuple(int(x) for x in m['num'].split('.')), m['suffix']


def latest_tag(tags: list[str], like: str | None = None) -> str | None:
    """Highest release tag, preferring the prefix/suffix family of `like`."""
    parsed = [(t, parse_version(t)) for t in tags]
    releases = [(t, v) for t, v in parsed if v and not _PRERELEASE.search(t)]
    if like and (ref := parse_version(like)):
        family = [(t, v) for t, v in releases if v[0] == ref[0] and v[2] == ref[2]]
        releases = family or releases
    if not releases:
        return None
    return max(releases, key=lambda tv: tv[1][1])[0]


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and a[1] > b[1])


# --- checks shown on the site and in the report ------------------------------

# Warnings about the revision an entry lists rather than a problem with the repository: shown on
# the module page, but not flagged on catalog cards or in the report.
PIN_WARNINGS = frozenset({'tracks-branch'})


def flagged(checks: list[dict]) -> list[dict]:
    """Return the warnings and errors to flag on catalog cards and in the report."""
    return [c for c in checks if c['level'] in ('warning', 'error') and c['code'] not in PIN_WARNINGS]


def compute_checks(entry: Entry, enr: dict | None, claims: dict[str, list[str]] | None = None) -> list[dict]:
    """Derive the user-facing checks of one entry from its enrichment data.

    `claims` is the result of module_names() for the whole registry.
    """
    proj = entry.west_project()
    checks = []

    def add(level, code, message):
        checks.append({'level': level, 'code': code, 'message': message})

    if not enr:
        add('info', 'not-enriched', 'Repository checks have not run for this entry yet.')
        return checks
    if enr.get('error'):
        add('error', 'unreachable', enr['error'])
        return checks

    kind = enr['revision']['kind']
    label = {'tag': 'release tag', 'branch': 'branch', 'sha': 'commit'}.get(kind, kind)
    add('pass', 'revision', f'Revision `{proj["revision"]}` resolves ({label}).')
    newer = enr.get('newer_release')
    if newer:
        add('info', 'newer-release', f'Upstream has a newer release: `{newer}`.')

    mod = enr.get('module') or {}
    if mod.get('invalid'):
        add('warning', 'module-yml', '`zephyr/module.yml` is not valid YAML: the Zephyr build will reject '
            'this module.')
    elif mod.get('found'):
        if mod.get('build_files_only'):
            add('info', 'no-module-yml', f'No `zephyr/module.yml`: Zephyr finds the module from '
                f'`zephyr/CMakeLists.txt` and `zephyr/Kconfig`, and names it `{mod["name"]}` after its '
                'directory.')
        else:
            add('pass', 'module-yml', f'`zephyr/module.yml` found (module name `{mod["name"]}`).')
        others = [o for o in (claims or {}).get(mod['name'], []) if o != entry.name]
        if others:
            add('warning', 'module-name', f'Module name `{mod["name"]}` is also used by '
                f'{", ".join(f"`{o}`" for o in others)}: a workspace cannot hold both.')
    elif 'west-commands' in proj:
        add('info', 'no-module-yml', 'No `zephyr/module.yml`: listed for its west extension commands.')
    else:
        add('warning', 'no-module-yml', f'No `zephyr/module.yml` at `{proj["revision"]}`: the Zephyr build '
            'will not pick this repository up as a module.')

    repo = enr.get('repo') or {}
    if repo.get('archived'):
        add('warning', 'archived', 'The repository is archived upstream.')
    if kind == 'branch':
        add('warning', 'tracks-branch', f'Follows branch `{proj["revision"]}`: each `west update` will get '
            'its latest commits. To stay on one version, it is recommended to use a release tag.')

    kind_l = license_kind(entry.data['license'])
    if kind_l == 'other':
        add('info', 'license', f'License `{entry.data["license"]}` includes custom terms: read them '
            'before shipping.')
    else:
        add('pass', 'license', f'License: `{entry.data["license"]}`.')
    return checks
