# targets that aren't filenames
.PHONY: all clean deploy build serve update-pubs

all: build

BIBBLE = bibble
PYTHON = .venv/bin/python
VENV = .venv/bin/python

$(VENV): requirements.txt
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

bib/pubs.bib: scripts/update_pubs.py _data/people.yml _data/scholar.yml | $(VENV)
	$(PYTHON) scripts/update_pubs.py

update-pubs:
	$(PYTHON) scripts/update_pubs.py --refresh

_includes/pubs.html: bib/pubs.bib bib/publications.tmpl _data/people.yml scripts/render_pubs.py | $(VENV)
	mkdir -p _includes
	$(PYTHON) scripts/render_pubs.py > $@

build: _includes/pubs.html
	bundle exec jekyll build

# you can configure these at the shell, e.g.:
# SERVE_PORT=5001 make serve
SERVE_HOST ?= 127.0.0.1
SERVE_PORT ?= 5000

serve: _includes/pubs.html
	bundle exec jekyll serve --port $(SERVE_PORT) --host $(SERVE_HOST) --livereload --force_polling

clean:
	$(RM) -r _site _includes/pubs.html

DEPLOY_HOST ?= yourwebpage.com
DEPLOY_PATH ?= www/
RSYNC := rsync --compress --recursive --checksum --itemize-changes --delete -e ssh

deploy: clean build
	$(RSYNC) _site/ $(DEPLOY_HOST):$(DEPLOY_PATH)
