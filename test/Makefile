TART=mu-udm

test:
	APPTAINER_TMPDIR=~/tmp stimela run example_recipe.yml tart=${TART}

movie:
	APPTAINER_TMPDIR=~/tmp stimela run make-movie.yml tart-movie tart=${TART}

clean:
	rm -f *.svg
	rm -f *.hdf
	rm -rf *.ms
	rm -f *.h5 *.txt *.deps *.full
