<!--
SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
SPDX-License-Identifier: Apache-2.0
-->

# Zephyr Community Modules

A registry of [Zephyr modules](https://docs.zephyrproject.org/latest/develop/modules.html)
maintained outside the Zephyr tree and its default manifest, and the website built from it.

Each module is one YAML file in [`modules/`](modules/) that follows
[`schema/entry.schema.json`](schema/entry.schema.json). From these files, CI publishes:

- a searchable catalog with one page per module;
- `m/<name>.yaml`, a west submanifest ready to drop into a workspace;
- `index.json`, a machine-readable index for tools
  ([`schema/index.schema.json`](schema/index.schema.json)).

Listing a module is not an endorsement by the Zephyr Project. Modules are maintained by their
authors under their own licenses.

Logos in `logos/` belong to their projects and only identify them; the commit that adds each one
names its source.

The initial entries were migrated from the "External Projects/Modules" pages of the Zephyr
documentation (`doc/develop/manifest/external/`), keeping the revisions those pages listed. Until
each module's maintainers confirm their entry, `maintainers` names the owner of the repository.

## Add a module to your workspace

From the root of a workspace created with `west init` (Zephyr's `west.yml` imports every file in
`zephyr/submanifests/`):

```shell
curl -fsSL https://zephyrproject-rtos.github.io/community-modules/m/zenoh-pico.yaml \
     -o zephyr/submanifests/zenoh-pico.yaml
west update zenoh-pico
```

Each module page also shows the project entry to paste into your own `west.yml`, for workspaces
with their own manifest repository. Delete the file to remove the module.

## List a module

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: add `modules/<name>.yml`, run
`python scripts/validate.py --online modules/<name>.yml`, and open a pull request.

## Repository layout

| Path | Content |
| --- | --- |
| `modules/<name>.yml` | One entry per module |
| `logos/<name>.svg` | Optional module logo (also `.png`, `.webp`, `.jpg`) |
| `categories.yml` | Allowed values of `category` |
| `schema/` | JSON Schemas of an entry and of `index.json` |
| `scripts/validate.py` | Offline checks; `--online` also checks the repository and revision |
| `scripts/enrich.py` | Collects revision, `zephyr/module.yml`, activity and release data into `build/enriched.json` |
| `scripts/build_site.py` | Builds `_site/` from the entries and `build/enriched.json` |
| `scripts/issue_to_entry.py` | Writes `modules/<name>.yml` from the answers of a New module issue |
| `site/` | Jinja templates, stylesheet and script of the website |
| `site.yml` | Site settings (base URL, repository, optional west command) |
| `tests/` | pytest suite |

## Build the site locally

```shell
pip install -r requirements.txt
python scripts/validate.py
GITHUB_TOKEN=... python scripts/enrich.py --report build/report.md   # optional, needs network
python scripts/build_site.py --base-url http://localhost:8000
python -m http.server 8000 --directory _site
pytest -q
```

Without `build/enriched.json`, the site still builds; the repository checks show as not run.

## How data is collected

Only the fields of an entry are written by hand. Everything else is derived:

- `git ls-remote` and a shallow, blob-less fetch of the listed revision give the revision kind
  (tag, branch, commit), the newest release tag, and the content of `zephyr/module.yml`: module
  name, `build.depends`, and what it provides (boards, DT bindings, snippets, samples, tests, pip
  requirements, blobs). This works with any git host.
- For repositories on GitHub, the REST API adds stars, last push, archive status and the latest
  release.
- The module's homepage, or its documentation site, gives the icon shown for modules that have
  no logo in `logos/`. SVG icons that contain scripts and raster icons under 32 px are ignored.

The nightly publish job writes a report of entries needing attention (unreachable repositories,
missing `zephyr/module.yml`, no activity for a year, newer releases than the listed tag) to the
workflow summary.
