# tart_cargo

Curated cargo of TART radio astronomy packages for stimela 2.0. This allows the use of TART telescope tools as part of the [stimela 2.0](https://github.com/caracal-pipeline/stimela/) radio astronomy pipeline.

Author: Tim Molteno

Based on the [tart_tools](https://github.com/tart-telescope/tools) package which does most of the heavy lifting.

## Installation and Use

Start with a suitable Linux machine, with apptainer installed. 

then create a python virtual environment

    python3 -m venv myvenv
    source myvenv/bin/activate
    pip install tart_cargo

This should install all the necessary dependencies (including stimela).

Then create a stimela recipe. An example is shown below...

```
#!/usr/bin/env -S stimela run -l
# This basic TART Stimela 2.0 processing pipeline
opts:
    log:
        dir: logs/log-{config.run.datetime}
        name: log-{info.fqname}
        nest: 2
        symlink: log

_include:
    - (tartcargo):
        - tart2ms.yml
        - tart-download-data.yml
        - disko.yml
        - disko-draw.yml

tart-image:
    info: TART imaging using stimela

    inputs:
        tart:
            dtype: str
            required: true
            info: "TART name (e.g. mu-udm)"

    outputs:
        ms:
            dtype: MS
            default:  '{current.tart}.ms'
        hdf:
            dtype: File
            default: =STRIPEXT(current.ms) + '-vis.hdf'
        svg:
            dtype: File
            default: =STRIPEXT(current.ms) + '.svg'

    assign:
        api: 'https://api.elec.ac.nz/tart/{recipe.tart}'


    steps:

        download-hdf:
            cab: tart-download-data
            params:
                api: =recipe.api
                vis: true
                file: =recipe.hdf

        create-ms:
            cab: tart2ms
            params:
                hdf: =steps.download-hdf.file
                ms: =recipe.ms
                clobber: true
                single-field: true
                rephase: obs-midpoint

        disko-image:
            cab: disko
            params:
                ms: =recipe.ms
                HDF: '{recipe.tart}.h5'
                healpix: true
                fov: 170deg
                res: 0.5deg
                lasso: true
                alpha: 0.006
                l1-ratio: 0.02

        project-image:
            cab: disko-draw
            params:
                hdf: '{recipe.tart}.h5'
                show-sources: true
                SVG: =recipe.svg
```

You can run this recipe as follows:

    stimela run example_recipe.yml tart=mu-udm
    
This will download data, and form an image from the specified TART telescope.
