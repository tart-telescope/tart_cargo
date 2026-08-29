# tart_cargo developer notes

## Validating yml commands against Docker images

The `tartcargo/*.yml` files reference executable commands that must exist inside the
corresponding Docker images. When bumping image versions, verify every `command` field
resolves:

```bash
# tools image (v1.1.8)
docker run --rm --entrypoint "" ghcr.io/tart-telescope/tools:v1.1.8 sh -c \
  'for cmd in tart_download_data tart_get_archive_data tart_set_mode tart2ms \
              tart-gnss-acquire disko disko_draw spotless; do
     printf "%-30s " "$cmd"; which "$cmd" 2>&1 || echo "MISSING"
   done'

# tartball image (0.1.1)
docker run --rm --entrypoint "" ghcr.io/tart-telescope/tartball:0.1.1 sh -c \
  'which tartball'
```

Last validated: 2026-07-07 against tools:v1.1.8 and tartball:0.1.1 — all present.

## Image version policy

The tart_cargo cabs run the Docker image `ghcr.io/tart-telescope/tools`, which is
defined in the `~/tart-telescope/tools` repository (see its `Dockerfile` /
`tart_tools.def`). A new version of the tools image is required for any change to the
cabs' code to propagate to tart_cargo — the image is the only way the executables reach
the cabs.

`tartcargo/genesis/tart-cargo-base.yml` sets the default image version for all cabs
(`vars.tart-cargo.images.version`), currently `v1.2.2`. Its `version` field must only
be bumped to a tag that already exists on `ghcr.io/tart-telescope/tools`; never bump
ahead of a pushed image tag. After bumping, re-run the validation commands above to
confirm all executables are present in the new image.

### How cab code reaches the image

- **Python cabs** (`tart2ms`, `disko`, `disko_draw`, `spotless`, `tart_tools`) are
  installed from PyPI in `~/tart-telescope/tools/Dockerfile` with `>=` minimum pins
  (e.g. `"tart2ms>=0.9.2"`). A change that needs a newer release requires raising the
  pin in the Dockerfile.
- **The Rust cab `tart-gnss-acquire`** is installed with unpinned
  `cargo install tart-gnss-acquire`, which picks up the latest crate from crates.io.
  New crates are published by tagging `~/github/tart-gnss` with a `v*` tag (its
  `publish.yml` workflow publishes to crates.io).

### Incorporating a cab change into tart_cargo

1. **Ship the cab change upstream** — commit and release it in the cab's own repo
   first (for tart-gnss: `git tag vX.Y.Z && git push origin vX.Y.Z`, e.g. `v0.4.0`,
   which publishes the crate to crates.io).
2. **Build a new tools image** — in `~/tart-telescope/tools`, commit any Dockerfile
   changes (e.g. raised pins) and tag the *tools* repo with its own next version:
   `git tag v1.2.3 && git push origin v1.2.3`. The `docker-publish.yml` workflow then
   builds and pushes `ghcr.io/tart-telescope/tools:v1.2.3` (multi-arch amd64/arm64).
   Pick the next version after the latest tools tag (`git tag --sort=-v:refname`),
   currently `v1.2.2` → `v1.2.3`. The tools image version is independent of the cab
   versions it bundles.
3. **Verify the new image** — once the workflow completes, re-run the validation
   commands from the section above against the new tag, plus any newly added
   commands.
4. **Bump the tart_cargo base image** — set `vars.tart-cargo.images.version` in
   `tartcargo/genesis/tart-cargo-base.yml` to the new tag (e.g. `v1.2.3`).
5. **Publish tart_cargo with a matching new version** — follow the release process
   below: bump `pyproject.toml` (e.g. `0.4.11` → `0.4.12`), add a `CHANGES.md` entry,
   commit, tag `v0.4.12`, push. The tart_cargo version and the tools image version
   are different numbers but have been bumped in lockstep (tools `v1.2.2` ↔ tart_cargo
   `0.4.11`).

Worked example — incorporating tart-gnss-acquire v0.4.0 (adds `--rfi`):

```bash
# 1. tart-gnss is already tagged v0.4.0 → crate on crates.io

# 2. tools repo: rebuild the image with the new crate
cd ~/tart-telescope/tools
git tag v1.2.3 && git push origin v1.2.3        # → ghcr.io/tart-telescope/tools:v1.2.3

# 3. validate: re-run the docker checks in "Validating yml commands" against v1.2.3

# 4. tart_cargo: point at the new image
#    tartcargo/genesis/tart-cargo-base.yml → version: v1.2.3
#    tart-gnss-acquire.yml now exposes rfi/simulate/... inputs (they fail with
#    "unknown argument" until the new image is in place)

# 5. tart_cargo: release a matching version (pyproject 0.4.11 → 0.4.12, CHANGES.md,
#    commit, tag v0.4.12, push) — see release process below
```

## tart-gnss-acquire cab

The `tart-gnss-acquire` cab is based on the tool of the same name from the
`~/github/tart-gnss` repository (github.com/tmolteno/tart-gnss — note: `targ-gnss`
is a common misspelling). Pushing a `v*` tag to that repo triggers its `publish.yml`
workflow, which builds and publishes the crate to crates.io. The tools image then
installs it from crates.io via `cargo install tart-gnss-acquire` (see
`~/tart-telescope/tools/Dockerfile`), so a new tag flows into tart_cargo only once
the tools image is rebuilt and the base version bumped per the section above.

The cab's YML (`tartcargo/tart-gnss-acquire.yml`) should be generated from the tool's
command-line options: run `tart-gnss-acquire --help` and map every flag/argument to
an `inputs` entry, keeping each input's `dtype` and `info` in sync with the tool's
actual CLI.

## disko and disko-draw cabs

The `disko` and `disko-draw` cabs both come from the `disko` package
(github.com/tmolteno/disko, local checkout `~/github/disko`). The package defines the
`disko` and `disko_draw` console scripts (see its `pyproject.toml` entry points), and
the tools image installs it from PyPI via `pip install "disko>=1.4.4"` (raise the pin
in `~/tart-telescope/tools/Dockerfile` for newer releases; a new version propagates to
tart_cargo only via a tools image bump per the section above).

The cab YMLs must be generated from the disko package's CLI options:

- `tartcargo/disko.yml` should match the command-line options of the `disko` CLI
  (`disko --help`), i.e. the `disko.cli:main` argument parser.
- `tartcargo/disko-draw.yml` should be modified in line with the disko package too:
  its `disko_draw` command is the `disko.draw_cli:main` entry point, so regenerate the
  inputs from `disko_draw --help` whenever the package's options change.

Keep each input's `dtype` and `info` in sync with the actual CLI. Note that
`disko-draw.yml` already carries a generated help block in its header comments — keep
that pattern when updating.

## Release process

1. Bump the version in `pyproject.toml`
2. Add an entry to `CHANGES.md`
3. Commit all changes
4. Tag with `v*.*.*` matching the version number (e.g. `v0.4.5`)
5. Push both the commit and the tag — the CI workflow publishes to PyPI on tag pushes
