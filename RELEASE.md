# Releasing tart_cargo

tart_cargo is a package of Stimela cabs plus the image-version pointer they
share. A release is: version + changelog + base image, committed, tagged
`vMAJOR.MINOR.PATCH`, pushed — `.github/workflows/deploy_module.yaml` builds
the distributions and publishes them to PyPI with **Trusted Publishing** (OIDC
via the `pypi` environment, no API token to manage).

```console
$ invoke release --dry-run                          # print the plan, change nothing
$ invoke release --tools-tag=v1.2.4                 # image bump + package release
$ invoke release --level=patch --yes                # package only
```

It runs standalone, or as the final stage of disko's chain
(`invoke -r ~/tart-telescope/tart_cargo release --level=patch --yes
--tools-tag=<new image tag>`); see `~/github/disko/RELEASE.md` for the chain.
The deeper policy — image-version rules, cab-vs-CLI sync, the full release
checklist — lives in `AGENTS.md`; this file is the operational how-to.

## Tasks

```console
$ invoke --list
  bump      Show (or apply) the next package version and its CHANGES section.
  release   base image -> test -> version -> tag -> CI publishes to PyPI.
  status    Show package version, tags and the configured tools image.
  test      Parse every cab/recipe YAML and prevalidate each example recipe.
```

`invoke` and `plumbum` must be importable by whichever interpreter runs them
(both installed globally today; disko's dev group carries them for the chain).

### `test`

- every `tartcargo/*.yml` and `examples/**/*.yml` (excluding `logs/`) parses;
- each runnable example recipe prevalidates with `stimela run -d …` — nothing
  executes, but stimela type-checks every parameter against its cab. Files
  that define more than one recipe are selected by name (`make-movie.yml`
  holds `tart-movie` and `loop-make-images`), and recipes whose required
  inputs have no dry-run value are listed and skipped — currently
  `loop-make-images`, which is driven by `tart-movie` through a GLOB rather
  than run standalone;
- `--with-image` additionally runs every cab's `command` inside
  `ghcr.io/tart-telescope/tools:<configured tag>` and fails if any executable
  is missing (the check documented in `AGENTS.md`).

### `bump`

Shows `0.4.13 -> …` and applies it: **if the current `pyproject` version has
no tag yet, it is released as-is** — entries are written into `CHANGES.md` as
the work lands, so re-bumping would skip the changelog you already curated.
Only when the current version *is* tagged does it bump
(`--level patch|minor|major`), drafting a `## <version>` section from
`git log <last tag>..HEAD` if none exists — and warning you to review the
draft. `--dry-run` previews either path.

### `status`

Package version, last tag, the configured tools image, and the count of
modified tracked files.

### `release`

1. **base image** — with `--tools-tag=vX.Y.Z`, **poll GHCR until that image
   really exists** (up to 60 min; the arm64 leg of the image build runs on a
   self-hosted runner), then point `tartcargo/genesis/tart-cargo-base.yml`
   (`vars.tart-cargo.images.version`) at it. This enforces the `AGENTS.md`
   rule: *never bump the version ahead of a tag that already exists on GHCR*.
   With `--no-wait` it refuses instead of waiting if the image is absent.
   Without `--tools-tag`, a package-only release leaves the base image alone.
2. **test** — the YAML + dry-run suite above (`--skip-tests` to bypass).
3. **version** — current-if-untagged, otherwise bump, plus the `CHANGES.md`
   section as described above.
4. **publish** — commit (`pyproject.toml`, `CHANGES.md`, and the genesis file
   if it changed) → annotated tag `v<version>` → `git push --follow-tags`.
   `--wait` (default) then polls `gh run list --workflow deploy_module.yaml`
   until the run on that tag succeeds. **A tag push is what publishes**, so
   never push one casually.

Flags: `--level`, `--yes`, `--tools-tag`, `--wait` / `--no-wait`,
`--skip-tests`, `--dry-run`.

## Safety

| Guard | Behaviour |
|---|---|
| prompt | one confirmation, or `--yes` |
| `--dry-run` | prints the plan, including whether `--tools-tag` already exists on GHCR, and exits |
| clean tree | refuses if tracked files are modified (untracked scratch, e.g. `.qwen/`, is only reported) |
| image existence | polls GHCR, or refuses with `--no-wait` when the tag is missing |
| no re-tag | publishing a tag that already exists is refused by the version/tag logic |

## Versioning and changelog

- Tags are `v0.4.x` and match `pyproject.toml`'s version exactly (the workflow
  publishes whatever the tag names — keep them in step).
- `CHANGES.md` uses one section per release, **no dates**, and entries are
  written while the work lands under the version that will carry them
  (e.g. the `0.4.13` section already exists and is currently unreleased).
- Tools image version and package version are independent numbers
  (`tools v1.2.3` ↔ `tart_cargo 0.4.12` historically); only the base-image
  pointer links them.

## Manual fallback

The same steps, per `AGENTS.md`:

```console
$ vim tartcargo/genesis/tart-cargo-base.yml     # only after the image exists:
$ docker manifest inspect ghcr.io/tart-telescope/tools:vX.Y.Z
$ vim pyproject.toml ; vim CHANGES.md
$ git commit -am "Release A.B.C"
$ git tag -a vA.B.C -m "Release A.B.C"
$ git push --follow-tags origin main
$ gh run list --workflow deploy_module.yaml --watch
```

## After the release

1. PyPI: <https://pypi.org/project/tart_cargo/>.
2. `invoke status` — clean, correct tags, correct base image.
3. If the base image moved, re-run `invoke test --with-image` so the cab
   commands are checked against the new image.
4. Dependabot's weekly `uv` run (see `.github/dependabot.yml`) will keep the
   lock current from here.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `… is not on GHCR yet — refusing to bump ahead of the image` | the image build has not finished (or `--no-wait` was used earlier); check `docker-publish.yml`, wait, re-run |
| `CHANGES.md: drafted a … section — please review` | you released a version with no curated entries; review the generated bullets before anyone reads them |
| `publish workflow failed: <url>` | the tag is pushed — **do not re-tag**; fix forward and release the next version |
| a recipe is skipped in `test` | its required input has no dry-run value in `_DRY_RUN_INPUTS`; add one if you want it covered |
| `stimela` not found / wrong env | run with `uv run invoke …` from this directory (uv carries the project env) |
| missing executables with `--with-image` | the configured image predates a cab's tool; bump the base image or fix the tools image first |
