# Changelog

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
