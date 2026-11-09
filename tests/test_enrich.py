# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Choosing the icon a module's website declares, without network access."""

import enrich

PAGE = 'https://example.org/project/'


def test_svg_then_largest_then_favicon():
    html = '''<head>
      <link rel="icon" href="/favicon-16.png" sizes="16x16">
      <link rel="apple-touch-icon" href="touch.png">
      <link rel="icon" href="/favicon-96.png" sizes="96x96">
      <link rel="icon" type="image/svg+xml" href="/logo.svg">
      <link rel="stylesheet" href="/site.css">
    </head>'''
    assert enrich.icon_candidates(PAGE, html, allow_favicon=True) == [
        'https://example.org/logo.svg',
        'https://example.org/project/touch.png',
        'https://example.org/favicon-96.png',
        'https://example.org/favicon-16.png',
        'https://example.org/favicon.ico',
    ]


def test_no_favicon_fallback_on_documentation_hosts():
    assert enrich.icon_candidates(PAGE, '<html></html>', allow_favicon=False) == []


def test_shortcut_icon_rel():
    html = '<link rel="shortcut icon" href="https://cdn.example.org/i.ico">'
    assert enrich.icon_candidates(PAGE, html, allow_favicon=False) == ['https://cdn.example.org/i.ico']
