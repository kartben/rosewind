# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Module logos: logos/<name>.<ext> must belong to a module and be a safe,
reasonably sized image."""

import struct
import zlib

import pytest

import registry
import validate

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="30"/></svg>'


def png(width, height):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
    rows = b''.join(b'\x00' + b'\x00' * width for _ in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


@pytest.fixture
def logos(tmp_path, monkeypatch):
    d = tmp_path / 'logos'
    d.mkdir()
    monkeypatch.setattr(registry, 'LOGOS_DIR', d)
    return d


def check(capsys):
    report = validate.Report('text')
    validate.check_logos({p.stem for p in registry.entry_paths()}, report)
    return report, capsys.readouterr().out


def test_valid_logos_pass(logos, capsys):
    (logos / 'lz4.svg').write_bytes(SVG)
    (logos / 'dtsh.png').write_bytes(png(128, 128))
    report, out = check(capsys)
    assert report.errors == 0 and report.warnings == 0, out


def test_image_sniffing():
    assert registry.image_type(png(64, 64)) == 'png'
    assert registry.image_size(png(64, 48)) == (64, 48)
    ico = b'\x00\x00\x01\x00\x02\x00' + bytes([16, 16]) + b'\x00' * 14 + bytes([0, 0]) + b'\x00' * 14
    assert registry.image_type(ico) == 'ico'
    assert registry.image_size(ico) == (256, 256)
    assert registry.image_type(SVG) == 'svg'
    assert registry.image_type(b'GIF89a') is None


@pytest.mark.parametrize('name,data,expected', [
    ('zview.svg', SVG.replace(b'<circle', b'<script>alert(1)</script><circle'), '<script> is not allowed'),
    ('zview.svg', SVG.replace(b'<circle', b'<circle onload="x()"'), 'event attribute onload'),
    ('zview.svg', SVG.replace(b'<circle', b'<image href="https://example.com/a.png"/><circle'), 'external reference'),
    ('dtsh.png', png(32, 32), 'at least 64 px'),
    ('dtsh.png', b'GIF89a' + b'\x00' * 40, 'not a PNG file'),
    ('nope.svg', SVG, 'no module named "nope"'),
    ('lz4.gif', b'GIF89a', 'unsupported logo format'),
    ('lz4.svg', SVG + b'<!--' + b'x' * (registry.LOGO_MAX_BYTES) + b'-->', 'logos must be at most'),
])
def test_invalid_logo_is_rejected(logos, capsys, name, data, expected):
    (logos / name).write_bytes(data)
    report, out = check(capsys)
    assert report.errors >= 1
    assert expected in out, out


def test_non_square_png_warns(logos, capsys):
    (logos / 'dtsh.png').write_bytes(png(256, 96))
    report, out = check(capsys)
    assert report.errors == 0 and report.warnings == 1, out

