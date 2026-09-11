.PHONY: setup dev ui test build
setup:
	uv sync --extra test
	npm --prefix frontend ci
	npm --prefix qa-browser ci
dev:
	uv run uvicorn app.main:app --host 127.0.0.1 --port 8010
ui:
	npm --prefix frontend run dev
test:
	uv run pytest
	npm --prefix frontend test
build:
	npm --prefix frontend run build
