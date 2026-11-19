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
$ invoke tools-test                                 # build the tools image locally + stimela gates
$ invoke tools-release --dry-run                    # the tools image release plan
$ invoke tools-release --disko-version=1.5.0 --yes  # what disko's chain runs (stage 4)
```

**This one script controls both releases**: the tools image
(`tools-release`) and this package (`release`). The tools release builds the
Docker container locally and gates it with this script's stimela tests
before tagging; CI then publishes the multi-arch image.

It runs standalone, or as the final stages of disko's chain
(`invoke -r ~/tart-telescope/tart_cargo release --level=patch --yes
--tools-tag=<new tag>`; stage 4 is `tools-release` from this same script);
see `~/github/disko/RELEASE.md` for the chain.
The deeper policy — image-version rules, cab-vs-CLI sync, the full release
checklist — lives in `AGENTS.md`; this file is the operational how-to.

## Tasks

```console
$ invoke --list
  bump            Show (or apply) the next package version and its CHANGES
                  section.
  release         base image -> test -> smoke (offline mz-up by default) ->
                  version -> tag -> CI publishes to PyPI.
  smoke           Actually run the radio-imaging basics example end-to-end.
  status          Show package version, tags and the configured tools image.
  test            Parse every cab/recipe YAML and prevalidate each example
                  recipe.
  tools-release   pin -> build the container locally -> stimela gates -> tag ->
                  CI multi-arch -> wait GHCR.
  tools-test      Build the tools image locally and test it with this script's
                  stimela gates.
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

### `smoke`

- runs the radio-imaging `basics` example for real — copies
  `simple_recipe.yml` into a scratch dir and executes it with stimela
  (equivalent to `make TART=<tart>` there): builds a measurement set from
  TART visibilities and images with spotless and disko. Fails unless
  stimela exits 0 and all four expected outputs exist
  (`<tart>-spotless.sphere`, `<tart>-disko.sphere`, `spotless-<tart>.svg`,
  `disko-<tart>.svg`).
- **pre-downloaded data**: `tart=mz-up` (the `release` default) images the
  committed `testdata/mz-up-vis.hdf` — visibilities fetched from the mz-up
  TART (`https://api.elec.ac.nz/tart/mz-up`) with `tart_download_data`.
  The recipe's `download-hdf` step is `skip: =EXISTS(recipe.hdf)`, so a
  `<tart>-vis.hdf` sitting in the working directory is used as-is and the
  TART API is never contacted. `--hdf` points at any other pre-downloaded
  file; it must be named `<tart>-vis.hdf` (any other name would miss the
  recipe's EXISTS check and silently re-download), and a missing
  `testdata/mz-up-vis.hdf` falls back to downloading.
- needs apptainer/singularity (and network only when no pre-downloaded
  data applies); takes several minutes (a one-off image pull on first
  run). This is the check that catches broken image contents (e.g. an
  incompatible dependency inside the tools image) that the `test`
  dry-runs cannot see.
- `--tart` picks the station (default `ghana`; `release` passes `mz-up`),
  `--nvis` overrides the visibility count the recipe images with (as
  shipped: 1000 — on machines with <32 GB RAM the `disko` step is
  OOM-killed, so lower it further if needed), `--hdf` supplies
  pre-downloaded visibilities (see above), `--example-dir` locates the
  radio-imaging basics checkout (default `$RADIO_IMAGING_BASICS` or the
  sibling `../radio-imaging/basics`), `--keep` retains the scratch dir.

### `tools-test`

Builds the tools image **locally** (`docker build -t
ghcr.io/tart-telescope/tools:<next>` in the tools checkout), converts it
into the `.simg` stimela will run (from `docker-daemon:` — without that
step stimela would silently pull the *published* image from GHCR instead of
the build under test), then runs this script's gates against it: the YAML +
dry-run recipe suite, every cab `command` checked inside the local image
(`docker run`), and the end-to-end `smoke` pipeline (offline, on the
committed mz-up data). The genesis image pointer is temporarily set to the
test tag and restored afterwards.

- `--tag` picks the image tag to build/test (default: the next release tag);
- `--quick` skips the build (tests the image already in the local daemon);
- `--skip-smoke` runs only the dry-run + command checks.

### `tools-release`

1. **pin** — with `--disko-version=X.Y.Z`, wait until PyPI really has that
   release (the disko stage of the chain may have only just landed), then
   set the Dockerfile's exact `disko==X.Y.Z` pin. Exact pins, not `>=`: an
   image must be reproducible. Other packages keep their `>=` pins.
2. **build** — `docker build -t ghcr.io/tart-telescope/tools:<next>`
   locally. The build is what proves the (possibly just-changed) pins
   resolve, and it is the image every gate below runs.
3. **gates** — this script's stimela tests against that local build (the
   `tools-test` gates above). `--skip-tests` skips them (the build still
   validated the pins).
4. **tag** — commit (only if the pin changed), annotated tag `v<next>`,
   push with `--follow-tags`. That push triggers the multi-arch image build
   (`docker-publish.yml`, amd64 + arm64 — arm64 on a self-hosted runner).
5. **wait** — poll GHCR until `ghcr.io/tart-telescope/tools:<tag>` exists
   (up to 60 min). tart_cargo must not bump its base image ahead of a
   pushed image tag (AGENTS.md). `--no-wait` skips it.

Then: `invoke release --tools-tag=<new tag>` bumps this package's base
image pointer and releases the package. This is stage 4 of disko's chain
(`invoke -r ../tart_cargo tools-release --level=patch --yes
--disko-version=<new>`).

Flags: `--level`, `--yes`, `--disko-version`, `--skip-tests`, `--dry-run`,
`--wait` / `--no-wait`.

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
3. **smoke** — actually runs the basics example end-to-end (see above) and
   fails the release if it errors or misses an output (`--skip-smoke` to
   bypass; `--smoke-tart` picks the station, **default `mz-up`** — offline
   on the committed `testdata/mz-up-vis.hdf`, so the default release gate
   needs no TART API access; any other station downloads as before).
4. **version** — current-if-untagged, otherwise bump, plus the `CHANGES.md`
   section as described above.
5. **publish** — commit (`pyproject.toml`, `CHANGES.md`, and the genesis file
   if it changed) → annotated tag `v<version>` → `git push --follow-tags`.
   `--wait` (default) then polls `gh run list --workflow deploy_module.yaml`
   until the run on that tag succeeds. **A tag push is what publishes**, so
   never push one casually.

Flags: `--level`, `--yes`, `--tools-tag`, `--wait` / `--no-wait`,
`--skip-tests`, `--skip-smoke`, `--smoke-tart`, `--dry-run`.

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
| `radio-imaging basics checkout not found` | `smoke` couldn't find `simple_recipe.yml`; pass `--example-dir`, set `RADIO_IMAGING_BASICS`, or use `--skip-smoke` |
| `stimela` not found / wrong env | run with `uv run invoke …` from this directory (uv carries the project env) |
| missing executables with `--with-image` | the configured image predates a cab's tool; bump the base image or fix the tools image first |
