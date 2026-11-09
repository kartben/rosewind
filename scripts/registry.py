# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the Rosewind registry scripts."""

from __future__ import annotations

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


def check_svg(data: bytes) -> list[str]:
    """An SVG logo must be self-contained and free of script."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        return [f'not valid XML: {e}']
    if not root.tag.endswith('svg'):
        return ['root element is not <svg>']
    errors = []
    for el in root.iter():
        tag = el.tag.rsplit('}', 1)[-1]
        if tag in ('script', 'foreignObject'):
            errors.append(f'<{tag}> is not allowed')
        for attr, value in el.attrib.items():
            name = attr.rsplit('}', 1)[-1]
            if name.lower().startswith('on'):
                errors.append(f'event attribute {name} is not allowed')
            if name == 'href' and not value.startswith(('#', 'data:image/')):
                errors.append(f'external reference {value} is not allowed')
    return sorted(set(errors))


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
    """Return (kind, sha) where kind is tag, branch, sha or missing."""
    if f'refs/tags/{revision}' in refs:
        return 'tag', refs[f'refs/tags/{revision}']
    if f'refs/heads/{revision}' in refs:
        return 'branch', refs[f'refs/heads/{revision}']
    if re.fullmatch(r'[0-9a-f]{7,40}', revision):
        return 'sha', revision
    return 'missing', None


MODULE_FILES = ('zephyr/module.yml', 'zephyr/module.yaml')


def read_module_yml(url: str, revision: str) -> tuple[str, str] | None:
    """Fetch only the commit and trees of a revision, then read its module file."""
    with tempfile.TemporaryDirectory(prefix='rosewind-') as tmp:
        _git('init', '-q', cwd=tmp)
        _git('fetch', '-q', '--depth', '1', '--filter=blob:none', url, revision, cwd=tmp)
        for path in MODULE_FILES:
            try:
                return path, _git('show', f'FETCH_HEAD:{path}', cwd=tmp)
            except GitError:
                continue
    return None


PROVIDES_SETTINGS = {
    'board_root': 'boards', 'soc_root': 'socs', 'arch_root': 'archs', 'dts_root': 'dts',
    'snippet_root': 'snippets', 'module_ext_root': 'module-ext',
}


def module_info(text: str, west_path: str) -> dict:
    """Summarize a zephyr/module.yml: name, dependencies and what it provides."""
    data = yaml.safe_load(text) or {}
    build = data.get('build') or {}
    settings = build.get('settings') or {}
    provides = [label for key, label in PROVIDES_SETTINGS.items() if settings.get(key)]
    for key in ('samples', 'tests'):
        if data.get(key):
            provides.append(key)
    if (data.get('package-managers') or {}).get('pip'):
        provides.append('pip')
    if data.get('blobs'):
        provides.append('blobs')
    if build.get('sysbuild-cmake'):
        provides.append('sysbuild')
    return {
        'found': True,
        'name': data.get('name') or Path(west_path).name,
        'depends': list(build.get('depends') or []),
        'provides': provides,
    }
