"""Realistic, hand-written documents of the kinds people actually format.

Each document is written into the work directory, formatted in place
(`yamark format <file>`), and compared byte-for-byte with the reference
output. A second `--check` pass then asserts the formatter accepts its own
output unchanged (idempotence), and a `--diff` run on the original input pins
the exact unified diff a reviewer would see.
"""

import pytest

from conftest import read_tree, resources_for, write_tree

RES = resources_for(__file__)

GITHUB_WORKFLOW = """\
name:   CI
on:
  push:
    branches: [ main,'release/**' ]
  pull_request:
     types: [opened,synchronize]
env:
    CARGO_TERM_COLOR: "always"
    RUST_BACKTRACE: '1'
jobs:
  test:
    name: "Test (${{ matrix.os }})"
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: False
      matrix:
        os: [ubuntu-latest, macos-latest,   windows-latest]
        toolchain: [stable,  "1.80"]
    steps:
      - uses: actions/checkout@v4
      - name:   Install toolchain
        uses: dtolnay/rust-toolchain@master
        with: { toolchain: "${{ matrix.toolchain }}", components: "clippy, rustfmt" }
      - name: Run tests
        run: |
          cargo test --all-features
          cargo clippy -- -D warnings
      - name: "Upload coverage report to the coverage service so that pull requests show a coverage delta comment"
        if: ${{ matrix.os == 'ubuntu-latest' }}
        run: bash <(curl -s https://example.com/upload.sh)   # upload
"""

DOCKER_COMPOSE = """\
version: "3.9"
x-common: &common
  restart: unless-stopped
  logging:
      driver: "json-file"
      options: {max-size: "10m", max-file: "3"}
services:
  web:
    <<: *common
    image: "nginx:1.25"
    ports:
      - "80:80"
      - '443:443'
    volumes: [ "./site:/usr/share/nginx/html:ro", "./nginx.conf:/etc/nginx/nginx.conf:ro" ]
    depends_on: [api]
  api:
    <<: *common
    build:
      context: ./api
      args:
        - NODE_ENV=production
    environment:
      DATABASE_URL: postgres://app:secret@db:5432/app
      FEATURE_FLAGS: "yes"
      TIMEOUT: "30"
  db:
    image: postgres:16
    environment:
       POSTGRES_PASSWORD: secret
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 10s
volumes:
  data: {}
"""

KUBERNETES = """\
# Deployment and service for the demo app
apiVersion: apps/v1
kind: Deployment
metadata:
  name:  demo
  labels: {app: demo, tier: "backend"}
spec:
  replicas: 3
  selector:
    matchLabels:
      app: demo
  template:
    metadata:
      labels:
        app: demo
    spec:
      containers:
      - name: demo
        image: "registry.example.com/demo:1.4.2"
        args: ["--port", "8080", "--log-level",   "info"]
        resources:
          limits: {cpu: 500m, memory: "256Mi"}
        env:
        - name: GREETING
          value: "Hello, world"
        - name: ENABLED
          value: "true"
---
apiVersion: v1
kind: Service
metadata:
  name: demo
spec:
  ports:
  - port: 80
    targetPort: 8080
  selector: { app: demo }
...
"""

OPENAPI = """\
openapi: 3.0.3
info:
  title: Pet Store
  version: '1.0.0'
  description: "A sample API that uses a petstore as an example to demonstrate features in the OpenAPI specification."
paths:
  /pets/{petId}:
    get:
      summary: Info for a specific pet
      operationId: showPetById
      parameters:
        - name: petId
          in: path
          required: true
          schema: { type: string }
      responses:
        '200':
          description: Expected response to a valid request
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Pet"
        default:
          description: unexpected error
components:
  schemas:
    Pet:
      type: object
      required: [id,name]
      properties:
        id: {type: integer, format: int64}
        name: {type: string}
        tag:  {type: string, nullable: True}
"""

ANSIBLE = """\
---
- hosts: webservers
  become: yes
  vars:
    http_port:    80
    packages: ['nginx','git']
  tasks:
  - name: ensure packages are installed
    ansible.builtin.apt:
      name: "{{ packages }}"
      state: present
  - name: write the nginx config file
    ansible.builtin.template: src=templates/nginx.j2 dest=/etc/nginx/nginx.conf
    notify:
    - restart nginx
  handlers:
    - name: restart nginx
      ansible.builtin.service: name=nginx state=restarted
"""

MKDOCS = """\
site_name: My Docs
site_description: 'Project documentation with Markdown, written so that the description runs past the configured prose width.'
theme:
  name: material
  features: [navigation.tabs,   search.suggest]
nav:
    - Home: index.md
    - 'User Guide':
        - 'Writing your docs': user-guide/writing-your-docs.md
        - Styling: user-guide/styling-your-docs.md
    - About: about.md
markdown_extensions:
  - toc:
      permalink: true
  - admonition
plugins: [search]
extra:
  version: ~
  analytics: null
  social: []
"""

README = """\
#  Widget   Factory ##

[![CI](https://github.com/example/widget/actions/workflows/ci.yml/badge.svg)](https://github.com/example/widget/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Widget Factory builds widgets.   It is fast, small, and has no runtime dependencies, which makes it a good fit for embedded targets and command-line tools alike.

## Install

```sh
cargo install widget-factory
```

## Usage

*   `widget new <name>` creates a widget.
*   `widget build` compiles every widget in the current directory and writes the results to `target/widgets`.
    *   Pass `--release` for optimised output.
*   `widget clean`

| Command | Description |
|---|---|
| `new` | Create a widget |
| `build` | Build all widgets in the workspace |
| `clean` | Remove build output |

1)  First, read the [contributing guide](CONTRIBUTING.md).
2)  Then open an issue describing the change you want to make before sending a pull request.

> **Note**
> Widgets are not gadgets.

---
Licensed under MIT.
"""

CHANGELOG = """\
# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- New `--compact` flag that collapses short block collections into flow style when they fit within the configured line width.
- Support for `.qmd` files.
### Fixed
+ Crash when the input ended without a trailing newline ([#123](https://github.com/example/widget/issues/123)).

## [1.0.0] - 2024-01-15
### Changed
- __Breaking:__ renamed `widget make` to `widget build`.

[Unreleased]: https://github.com/example/widget/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/example/widget/releases/tag/v1.0.0
"""

QUARTO = """\
---
title: "Penguin   analysis"
author: Jane Doe
format:
  html:
    toc: true
    code-fold: True
execute: {echo: false, warning: false}
---

## Introduction

This report explores the [Palmer penguins](https://allisonhorst.github.io/palmerpenguins/) data set.   We look at bill length and flipper length across three species, using the `ggplot2` package for plotting.

::: {.callout-note}
The data were collected   by Dr. Kristen Gorman.
:::

```{r}
#| label: fig-bills
#| fig-cap:   "Bill length by species"
#| echo:  false
library(ggplot2)
ggplot(penguins, aes(species, bill_length_mm)) + geom_boxplot()
```

```{python}
#| label: summary
#|  echo: true
import pandas as pd
```

See @fig-bills for details[^1].

[^1]: Penguins with missing measurements were dropped before plotting, which removes eleven rows from the original data.
"""

RMARKDOWN = """\
---
title: Report
output:
  html_document:
     toc: yes
editor_options:
  markdown:
    wrap: sentence
---

# Setup

This document shows the analysis. It uses several packages. Each package is loaded in the first chunk.

```{r setup, include=FALSE}
knitr::opts_chunk$set(echo = TRUE)
```

## Results

The mean is `r mean(x)`. That is larger than expected! Is it significant? We test it below.
"""

CONTRIBUTING = """\
# Contributing

Thanks for your interest in contributing!   Please follow these steps:

1. Fork the repository and create a branch from `main`.
2. If you've added code that should be tested, add tests.
   - Unit tests go next to the code.
   - Integration tests go in `tests/`, and each file there is compiled as its own crate.
3. Ensure the test suite passes.

## Code of conduct

Term
:   Definition of the term, which is long enough that it needs to wrap onto a second line at column seventy-two.

- [ ] Run the formatter
- [x] Update the changelog
"""

PYTHON_SCRIPT = '''\
#| title:    Data cleaning
#| tags: [etl,daily]
#| retries:  3

import pandas as pd

# fmt: markdown
HELP = """
# clean-data

Reads the raw CSV export,   drops duplicate rows, and writes a parquet file that downstream jobs read every morning.

*   `--input`: path to the CSV file
*   `--output`: destination
"""


def main():
    df = pd.read_csv("raw.csv")
    return df.drop_duplicates()
'''

R_SCRIPT = """\
#| name: model-fit
#| depends:   [data-prep, features]
#| cache: TRUE

fit <- lm(y ~ x, data = df)

# fmt: markdown
# ##  Model notes
#
# The linear model is fitted on the cleaned data.   Residual plots are saved under `figures/` for review by the analysis team.
summary(fit)
"""

DOCUMENTS = {
    "github_workflow": (".github-ci.yml", GITHUB_WORKFLOW),
    "docker_compose": ("docker-compose.yml", DOCKER_COMPOSE),
    "kubernetes_multi_document": ("deploy.yaml", KUBERNETES),
    "openapi": ("openapi.yaml", OPENAPI),
    "ansible_playbook": ("site.yml", ANSIBLE),
    "mkdocs_config": ("mkdocs.yml", MKDOCS),
    "readme": ("README.md", README),
    "changelog": ("CHANGELOG.md", CHANGELOG),
    "quarto_report": ("report.qmd", QUARTO),
    "rmarkdown_sentence_wrap": ("report.Rmd", RMARKDOWN),
    "contributing": ("CONTRIBUTING.md", CONTRIBUTING),
    "python_script": ("clean_data.py", PYTHON_SCRIPT),
    "r_script": ("model.R", R_SCRIPT),
}

CATCHES = {
    "github_workflow": "flow-sequence spacing, False->false normalisation, quote simplification, a long quoted step name "
                       "folding, a commented `run:` line or the literal `run: |` block being mishandled in a CI workflow",
    "docker_compose": "anchors and `<<: *common` merge keys, quoted strings that must stay quoted (`\"yes\"`, `\"30\"`, "
                      "port mappings), over-indented maps, and wide flow sequences expanding to block style",
    "kubernetes_multi_document": "multi-document streams with `---`/`...`, unindented sequences under mappings, a "
                                 "leading comment, flow mappings with quoted values, and `\"true\"` staying a string",
    "openapi": "quoted response codes like '200', `$ref` strings starting with `#`, long description folding, "
               "True->true inside flow mappings and `required: [id,name]` spacing",
    "ansible_playbook": "an explicit `---` start, `yes` (a YAML 1.2 string), `{{ packages }}` template strings and "
                        "key=value shorthand lines in a playbook",
    "mkdocs_config": "a long single-quoted description, mixed nav indentation, `~`/`null` spellings, empty flow "
                     "collections and nested block sequences",
    "readme": "ATX heading cleanup, badge lines, paragraph wrapping at 72 columns, `*` bullet normalisation with "
              "nested items, `1)` ordered lists, pipe-table alignment, blockquotes and a thematic break",
    "changelog": "a heading directly followed by text, keep-a-changelog headings, `+` bullets, `__strong__`, long "
                 "list items wrapping under their marker and reference definitions left in place",
    "quarto_report": "front matter quoting/flow spacing, Quarto callout divs, `#|` chunk options in R and Python "
                     "chunks, cross-references, and footnote definitions wrapping under their marker",
    "rmarkdown_sentence_wrap": "front-matter `editor_options.markdown.wrap: sentence` applying to the body, an "
                               "R Markdown chunk header with options and inline `r` code",
    "contributing": "ordered lists with nested bullets, a Pandoc definition list wrapping under `:`, and GFM task "
                    "list markers",
    "python_script": "hashpipe YAML at the top of a Python file, a `# fmt: markdown` docstring-style string being "
                     "rewrapped while the surrounding Python code stays byte-identical",
    "r_script": "hashpipe YAML in an R script (TRUE stays an R-style plain scalar), and a `# fmt: markdown` comment "
                "block rewrapped with its `# ` prefix preserved",
}


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_realistic_document_formats_in_place_and_is_idempotent(run, workdir, name):
    """CATCHES: reimplementations that differ from the reference on realistic files (CI workflows, compose files,
    multi-document manifests, OpenAPI, playbooks, READMEs, changelogs, Quarto/R Markdown reports, Python/R scripts
    with hashpipe YAML; the per-document constructs are listed in CATCHES above), or whose output is not a fixed
    point: the in-place bytes, the write-mode summary, and a clean second `--check` pass must all match."""
    filename, content = DOCUMENTS[name]
    write_tree(workdir, {filename: content})
    result = run(["format", filename])
    expected = (RES / f"{name}.golden").read_bytes()
    assert result.stdout.decode() == (RES / f"{name}.summary").read_text()
    assert result.stderr == b""
    assert result.returncode == 0
    assert read_tree(workdir) == {filename: expected}
    second = run(["format", "--check", filename])
    assert second.stdout == b""
    assert second.stderr.decode() == "1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n"
    assert second.returncode == 0
    assert read_tree(workdir) == {filename: expected}


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_realistic_document_diff_matches_reference(run, workdir, name):
    """CATCHES: reimplementations whose `--diff` output for a realistic document differs (hunk boundaries, context
    lines, headers, ordering) or that write the file in diff mode; exit status 1 signals pending changes."""
    filename, content = DOCUMENTS[name]
    write_tree(workdir, {filename: content})
    result = run(["format", "--diff", filename])
    assert result.stdout == (RES / f"{name}.diff").read_bytes()
    assert result.stderr.decode() == (RES / f"{name}.diff_stderr").read_text()
    assert result.returncode == 1
    assert read_tree(workdir) == {filename: content.encode()}


def test_realistic_documents_formatted_together_from_directory(run, workdir):
    """CATCHES: directory traversal that misses supported extensions (.yml/.yaml/.md/.qmd/.Rmd/.py/.R), formats
    hidden paths, miscounts the summary, or produces different bytes than formatting each file alone."""
    files = {f"project/{filename}": content for filename, content in DOCUMENTS.values()}
    files["project/notes.txt"] = "Plain   text is not formatted.\n"
    write_tree(workdir, files)
    result = run(["format", "project"])
    assert result.stdout == b"13 files scanned, 12 formatted, 0 unchanged, 1 skipped, 0 failed\n"
    assert result.stderr == b""
    assert result.returncode == 0
    expected = {f"project/{filename}": (RES / f"{name}.golden").read_bytes()
                for name, (filename, _) in DOCUMENTS.items()}
    expected["project/notes.txt"] = b"Plain   text is not formatted.\n"
    expected["project/.github-ci.yml"] = GITHUB_WORKFLOW.encode()
    assert read_tree(workdir) == expected
