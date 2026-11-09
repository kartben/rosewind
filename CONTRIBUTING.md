<!--
SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
SPDX-License-Identifier: Apache-2.0
-->

# Listing a module

One pull request adds or changes one module. Prefer a form? Open a **New module** issue and a
registry maintainer writes the entry for you.

## Listing criteria

A module is listed when:

- its repository is public and can be cloned over https without credentials;
- it contains `zephyr/module.yml` at the listed revision, or it provides west extension commands
  (`west.west-commands`);
- its license is declared as an [SPDX expression](https://spdx.org/licenses/). Licenses with
  custom terms are accepted with a `LicenseRef-*` identifier and `links.license` pointing to the
  text; the site marks them "Custom terms";
- its README or documentation explains how to use it with Zephyr;
- at least one maintainer can be reached through the listed GitHub handle;
- it is not already a project of Zephyr's own `west.yml` or `submanifests/`.

Listing is not an endorsement and does not review the module's code.

## Writing the entry

Create `modules/<name>.yml`. `<name>` is lowercase, unique, and becomes the west project name and
the page URL.

```yaml
# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

name: zenoh-pico
title: zenoh-pico
summary: >-
  Eclipse Zenoh for microcontrollers: pub/sub, queries and storage over UDP, TCP and serial.
description: |
  Optional. Paragraphs, `-` lists, `inline code`, *emphasis*, **strong** and
  [https links](https://zenoh.io). No HTML, no headings, at most 2000 characters.
category: communication
tags: [pubsub, zenoh, ros2]
license: EPL-2.0 OR Apache-2.0
maintainers:
  - github: eclipse-zenoh
links:
  repository: https://github.com/eclipse-zenoh/zenoh-pico
  documentation: https://zenoh-pico.readthedocs.io/en/latest/
  homepage: https://zenoh.io
west:
  revision: 1.10.2
  path: modules/lib/zenoh-pico
```

Field rules (enforced by `scripts/validate.py`):

| Field | Rule |
| --- | --- |
| `name` | Matches the file name; `[a-z0-9][a-z0-9._-]*` |
| `title` | 2 to 60 characters |
| `summary` | One sentence, 40 to 160 characters, ending with a period |
| `category` | A key of [`categories.yml`](categories.yml) |
| `tags` | Up to 8, lowercase, `-` or `_` as separators |
| `license` | SPDX expression; `LicenseRef-*` needs `links.license` |
| `links.repository` | Required; every link uses https |
| `west.revision` | A release tag (preferred), a branch or a commit SHA |
| `west.path` | Starts with `modules/`, then an area such as `lib`, `crypto`, `tools`, `lang`, `debug`, `safety`; unique in the registry |
| `west.url` | Optional, defaults to `links.repository` |
| `west.submodules`, `west.west-commands`, `west.groups` | Optional, same meaning as in a west manifest |
| `status` | Set by registry maintainers: `active`, `deprecated` or `unmaintained` |

`west.import` is not accepted: an entry adds exactly one project. Dependencies between modules are
read from `build.depends` in the module's own `zephyr/module.yml`, and the site installs listed
dependencies along with the module.

## Adding a logo

A module can add its logo as `logos/<name>.svg` (preferred), `.png`, `.webp` or `.jpg`,
where `<name>` is the entry name. Keep it square, at most 100 KiB and, for PNG files, at least
64 px wide. SVG files must not contain scripts, event handlers or references to other files.

Without a logo, the site shows the icon that the module's `homepage` (or `documentation`
site) declares, or the module's initials when there is none.

## Checking it

```shell
pip install -r requirements.txt
python scripts/validate.py --online modules/<name>.yml
pytest -q
```

CI runs the same checks on the pull request and uploads a preview of the site.

## Review and lifecycle

- One approval from a registry maintainer merges a pull request. Changes proposed by a listed
  maintainer of the module itself are reviewed for format only.
- Pinning a release tag is preferred. When a newer release appears, the nightly report lists the
  entry; update `west.revision` with a pull request.
- If a repository becomes unreachable or archived, or the listed revision disappears, a registry
  maintainer opens an issue and mentions the module's maintainers. Without a fix after 90 days the
  entry is marked `status: unmaintained`, and it can be removed later.
- Entries are removed on request of their maintainers.
