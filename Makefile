DOCKER=
TS=$(shell date +%Y%m%d%H%M)

.PHONY: build

all: run

workdir:
	mkdir -p data/postgres

build:
	docker-compose build --pull

services:
	docker-compose up -d --remove-orphans db

shell: build workdir services
	docker-compose run --rm app bash

run: build workdir services
	docker-compose run --rm app opensanctions run

stop:
	docker-compose down --remove-orphans

clean:
	rm -rf data/datasets build dist .mypy_cache .pytest_cache
