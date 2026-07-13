# Examples

Example stimela recipes using tart_cargo cabs.

## Recipes

### `example_recipe.yml`

Basic TART imaging pipeline. Downloads visibilities from a TART telescope, converts
them to a measurement set with `tart2ms`, then creates images using both `disko`
(discrete operator) and `spotless` (model-fitting) algorithms, rendering the results
to SVG with `disko-draw`.

```
stimela run example_recipe.yml tart=mu-udm
```

### `make-movie.yml`

Downloads archive data over a time range using `tart-get-archive-data`, then loops
over all HDF files to create measurement sets and spotless images for each timestep.
Suitable for generating time-lapse movies of the radio sky.

```
stimela run make-movie.yml tart=mu-udm
```

### `predict_recipe.yml`

Downloads visibilities and creates a measurement set, then runs `tartball` to simulate
TART data from that measurement set — useful for validating telescope models.

```
uv run stimela run predict_recipe.yml tart=bd-iub
```

### `tart-gnss-acquire.yml`

Sets a TART telescope to raw mode, downloads raw samples, then runs `tart-gnss-acquire`
to calculate signal strengths, phases, and Doppler offsets for GNSS constellations. Resets the telescope to vis mode when done.

Requires a TART API password (`pw` input). For the test tart (nz-test), ask on the TART telegram channel for the password.

```
uv run stimela run tart-gnss-acquire.yml tart=nz-test pw=passwd
```
