UV ?= uv
APP ?= main:app
HOST ?= 0.0.0.0
PORT ?= 8000

.PHONY: help install run dev docs health check clean docker-build docker-up docker-down docker-logs

help:
	@echo "Targets:"
	@echo "  install      Install Python dependencies with uv"
	@echo "  run          Run the app"
	@echo "  dev          Run the app with reload"
	@echo "  docs         Print documentation URLs"
	@echo "  health       Check the local health endpoint"
	@echo "  check        Compile-check the Python sources"
	@echo "  clean        Remove Python cache directories"
	@echo "  docker-build Build the Docker Compose image"
	@echo "  docker-up    Start the Docker Compose stack"
	@echo "  docker-down  Stop the Docker Compose stack"
	@echo "  docker-logs  Tail Docker Compose logs"

install:
	$(UV) sync

run:
	$(UV) run uvicorn $(APP) --host $(HOST) --port $(PORT)

dev:
	$(UV) run uvicorn $(APP) --host 127.0.0.1 --port $(PORT) --reload

docs:
	@echo "Swagger UI: http://127.0.0.1:$(PORT)/docs"
	@echo "ReDoc:      http://127.0.0.1:$(PORT)/redoc"
	@echo "OpenAPI:    http://127.0.0.1:$(PORT)/openapi.json"

health:
	$(UV) run python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:$(PORT)/api/healthz').read().decode())"

check:
	$(UV) run python -m compileall main.py app

clean:
	$(UV) run python -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"

docker-build:
	docker compose build

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f
