# Changelog

## 0.4.4 (unreleased)

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
