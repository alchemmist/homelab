HUGO ?= hugo
PYTHON ?= python3
SOURCE_SHA ?= local

.PHONY: frontend build check dev clean image

frontend:
	npm ci --ignore-scripts
	npm run build

build: frontend
	$(HUGO) --minify --cleanDestinationDir --gc --panicOnWarning
	$(PYTHON) scripts/version.py public/version.json "$(SOURCE_SHA)"

check: build
	npm test
	$(PYTHON) scripts/check.py public

dev: frontend
	$(HUGO) server --bind 127.0.0.1 --port 1321 --disableFastRender

clean:
	rm -rf public resources .hugo_build.lock

image:
	docker build --build-arg SOURCE_SHA="$(SOURCE_SHA)" -t socrat-wiki:local .
