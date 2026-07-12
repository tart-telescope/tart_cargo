# Examples

Example stimela recipes using tart_cargo cabs.

## Recipes

### `example_recipe.yml`

Basic TART imaging pipeline. Downloads visibilities from a TART telescope, converts
them to a measurement set with `tart2ms`, then creates images using both `disko`
(discrete operator) and `spotless` (model-fitting) algorithms, rendering the results
to SVG with `disko-draw`.

```
make test TART=mu-udm
```

### `make-movie.yml`

Downloads archive data over a time range using `tart-get-archive-data`, then loops
over all HDF files to create measurement sets and spotless images for each timestep.
Suitable for generating time-lapse movies of the radio sky.

```
make movie TART=mu-udm
```

### `predict_recipe.yml`

Downloads visibilities and creates a measurement set, then runs `tartball` to simulate
TART data from that measurement set — useful for validating telescope models.

### `tart-gnss-acquire.yml`

Sets a TART telescope to raw mode, downloads raw samples, then runs `tart-gnss-acquire`
to calculate signal strengths, phases, and Doppler offsets for GNSS constellations
(Beidou in this example). Resets the telescope to vis mode when done.

Requires a TART API password (`pw` input).
