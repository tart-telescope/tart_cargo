# Changelog

## 0.5.4

- `release --tools-tag` now points the base image at the new tag **before**
  the test/smoke gates (restoring it if the gates fail), so a release that
  upgrades away from a broken image is gated on the image it ships, not the
  one it replaces — gating on the old base rejected the very release that
  fixed tools#5 (v1.3.3 died in spotless, v1.3.4 passed).
- Both releases now live in this script: new `tools-release` (and
  `tools-test`) control the tools image release — `tools-release` sets the
  optional exact `disko==` pin, **builds the Docker container locally**,
  gates it with **this script's stimela tests** (recipe dry-runs, every cab
  command inside the local image, and the end-to-end `smoke` on the
  committed mz-up data — the local build is converted into stimela's
  `.simg` cache from `docker-daemon:`, because stimela would otherwise pull
  the published image from GHCR), then tags, waits for GHCR and hands the
  tag to `release --tools-tag`. `tools/tasks.py` is gone — the disko chain's
  tools stage now runs `invoke -r ../tart_cargo tools-release`.
- Release smoke gate runs offline on committed mz-up data: `invoke smoke`
  (and `invoke release`'s smoke stage, now defaulting to `tart=mz-up`)
  images `testdata/mz-up-vis.hdf` — visibilities pre-downloaded from the
  mz-up TART — instead of calling the TART API: the basics recipe's
  download step skips itself when `<tart>-vis.hdf` already exists. New
  `smoke --hdf` accepts any pre-downloaded file; it must be named
  `<tart>-vis.hdf`, the name the recipe's EXISTS check looks for.
- `smoke --nvis` now patches the recipe's `nvis:` value with a regex and
  fails when no such line exists — it previously matched the literal
  `nvis: 10000`, which stopped matching when the recipe moved to 1000
  (radio-imaging `c022044`), so the flag silently did nothing.

## 0.5.3

- Release 0.5.3.

## 0.5.2

- Release 0.5.2.

## 0.5.1

- AGENTS: the tools checkout lives at ./tools; validate against v1.3.0

## 0.5.0

- Release 0.5.0.

## 0.4.13

- Bump tools image to v1.2.4 (tart2ms>=0.9.5, disko>=1.4.4, spotless>=0.8.0, tart_tools>=1.4.6). Fixes #10: the image no longer ships tart2ms 0.9.3, whose `--add-model` wrote an all-zero MODEL_DATA (declination-as-elevation filter plus missing `el` key dropped every GNSS source), nor 0.9.4, which predicted every GNSS satellite at one barycentric position (tart2ms#68). The new image carries tart2ms 0.9.5, whose model sources come from topocentric az/el — verified non-zero MODEL_DATA with model directions spread over the sky.
- Note: tools v1.2.4 still resolves disko from PyPI to 1.4.4, so the `healpix: true` warning below still applies. The planned `disko==1.5.0` exact-pin rebuild moves to the next image tag (v1.2.5); disko 1.5.0 is not on PyPI yet.

- disko cab: drop the inputs current disko rejects — `vis`, `show-sources` and `elevation`. Source overplotting moved to the disko-draw cab (tmolteno/disko#25); no recipe is affected, since none of the examples pass those three to `cab: disko`.
- disko cab: `healpix` is no longer required — disko now defaults to the healpix tiling when neither `--mesh` nor `--healpix` is given (tmolteno/disko#12). **Recipes running against tools v1.2.3 or v1.2.4 (disko 1.4.4 from PyPI) must keep passing `healpix: true`**, because those builds still error without it, until disko ≥1.5.0 ships in an image.
- disko cab: add the new `no-regularization` input — the unregularized solve is opt-in as of tmolteno/disko#12. Only usable once the tools image ships a disko newer than 1.4.4.
- disko cab: document that `alpha` defaults to 0.02 and that Tikhonov is now the default algorithm when no algorithm flag is given.
- disko-draw cab: document `--scale-mad` in the usage header (the input itself was already present).
- Note: as of tools v1.2.4 its `pip install disko>=1.4.4` still resolves to PyPI 1.4.4 (uploaded 2026-07-14). disko's later work — #12 defaults, #23 casacure migration, #24/#25/#26 fixes and the pillow 13 / certifi security bump — is master-only until disko publishes a release. Planned: disko 1.5.0, then rebuild tools with an exact `disko==1.5.0` pin (v1.2.5 or later), then bump `genesis/tart-cargo-base.yml` here.

## 0.4.12

- Bump tools image to v1.2.3 (tart2ms>=0.9.3, spotless>=0.8.0, tart_tools>=1.4.6)
- Add the new tart-gnss-acquire inputs matching the tart-gnss-acquire CLI (rfi, test-antennas, test-min-cn0, simulate and the simulation options, i, j, debug, benchmark)
- Require the healpix input in the disko cab (disko errors unless --healpix or --mesh is given)
- Document tools image propagation and cab dependency maintenance in AGENTS.md

## 0.4.11

- Bump tools image to v1.2.2
- Bump tartball image to 0.3.2
- Fix tartball beam parameter: accept 'tart', 'default', or file path (changed from File to str)

## 0.4.10

- Update tart-cargo-base.yml to tools v1.2.1

## 0.4.9

- Bump tools image to v1.2.1 (adds casacore-data for IERS/leap-second tables)

## 0.4.8

- Remove mesh parameters from disko cab (mesh, adaptive, res-min — no longer built on arm64)
- Add save-model-json, max-steps, and log to spotless cab
- Bump tools image to v1.2.0

## 0.4.7

- Expand disko cab to cover all 38 CLI inputs (up from 12)
- Expand disko-draw cab to cover all 16 CLI inputs (up from 9)
- Remove explicit defaults from spotless, disko, and disko-draw — let CLI defaults apply
- Document image version policy in AGENTS.md

## 0.4.6

- Expand spotless cab definition: add 22 missing CLI inputs (file, vis, ddid, dir, nside, mesh,
  adaptive, res-min, beam, api, catalog, display, fits, PNG, PDF, SVG, show-sources,
  show-model, elevation, title, debug)
- Fix healpix default (true → false) and fov/res from required to defaulted

## 0.4.5

- Bump tools image to v1.1.9

## 0.4.4

- Migrate from Poetry to uv for package management
- Update CI pipeline to use `uv build` instead of `poetry build`
- Replace `poetry-core` build backend with `hatchling`
- Bump tools image to v1.1.8

## 0.4.3

- Fix default for tart2ms rephase option
- Use list example for `prn` parameter in tart-gnss-acquire

## 0.4.2

- Update list parameters to use correct repeat policy
- Update examples

## 0.4.1

- Add tart-set-mode command
- Add tart-cargo base with L1C code
- Update tart-gnss-acquire to latest version
- Fix security issue: require requests >= 2.33




