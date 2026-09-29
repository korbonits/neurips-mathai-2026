FCREPO ?= artifact
PYTHON ?= python3

.PHONY: verify-artifact tables figures paper check supplement release arxiv
verify-artifact:
	FCREPO=$(FCREPO) $(PYTHON) scripts/verify_artifact.py

tables: verify-artifact
	FCREPO=$(FCREPO) $(PYTHON) scripts/make_paper_tables.py
	FCREPO=$(FCREPO) $(PYTHON) scripts/make_camera_tables.py

figures: verify-artifact
	FCREPO=$(FCREPO) $(PYTHON) scripts/make_paper_figure.py

paper: tables figures
	mkdir -p build
	cd paper && tectonic -X compile main.tex --outdir ../build --keep-logs

check: paper
	$(PYTHON) scripts/verify_pdf.py

supplement: tables figures
	$(PYTHON) scripts/make_camera_supplement.py

release: check supplement
	$(PYTHON) scripts/package_outputs.py

arxiv: tables figures
	$(PYTHON) scripts/make_arxiv_variant.py
	cd paper && tectonic -X compile main-arxiv.tex --outdir ../build --keep-logs
