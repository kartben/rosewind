<!--
SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
SPDX-License-Identifier: Apache-2.0
-->

# Rosewind

Rosewind is a catalog of third-party [Zephyr modules](https://docs.zephyrproject.org/latest/develop/modules.html):
modules maintained outside the Zephyr tree and its default manifest. This repository holds the
registry and the website built from it.

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

When the workspace manifest is Zephyr's `west.yml` (`west config manifest.path` prints `zephyr`),
which imports every file in `zephyr/submanifests/`, run from the workspace root:

```shell
curl -fsSL https://zephyrproject-rtos.github.io/rosewind/m/zenoh-pico.yaml \
     -o zephyr/submanifests/zenoh-pico.yaml
west update zenoh-pico
```

Delete the file to remove the module. When `zephyr` is a project of your own manifest, west reads
Zephyr's manifest from git and ignores that directory: paste the project entry shown on each module
page into your `west.yml` instead.

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

## Turning issues into pull requests

The New module issue form gives contributors a way in without git. The `New module` workflow
writes the entry from the answers, checks it with `validate.py --online`, opens or updates a pull
request from the `new-module/<issue number>` branch, and comments on the issue with the result.
It only adds modules: a name that is already listed is refused. It needs:

- a `new-module` label, which the issue form applies;
- **Allow GitHub Actions to create and approve pull requests**, under Settings > Actions >
  General;
- a rule on `main` that dismisses approvals when new commits are pushed, since editing the issue
  force-pushes the pull request branch.

On pull requests opened by the workflow, GitHub holds the `Validate` workflow until a maintainer
approves the run; the `New module` workflow has already run the same checks. Its commits carry no
`Signed-off-by`, so the maintainer who merges adds one.

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
