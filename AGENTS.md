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

## Release process

1. Bump the version in `pyproject.toml`
2. Add an entry to `CHANGES.md`
3. Commit all changes
4. Tag with `v*.*.*` matching the version number (e.g. `v0.4.5`)
5. Push both the commit and the tag — the CI workflow publishes to PyPI on tag pushes
