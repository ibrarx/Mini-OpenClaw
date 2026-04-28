.PHONY: install dev test seed export-memory zip clean

install:
	pip install -r requirements.txt
	cd apps/web && npm install

dev:
	python -m uvicorn apps.api.main:app --port 8000 --reload --reload-dir apps --reload-dir scripts &
	cd apps/web && npm run dev

test:
	python -m pytest tests/ -v

seed:
	python scripts/seed_demo.py

export-memory:
	python scripts/export_memory.py

zip:
	zip -r mini-openclaw.zip . \
		-x ".venv/*" \
		-x "venv/*" \
		-x "node_modules/*" \
		-x "apps/web/node_modules/*" \
		-x "apps/web/dist/*" \
		-x "__pycache__/*" \
		-x "*/__pycache__/*" \
		-x "*/*/__pycache__/*" \
		-x ".env" \
		-x "*.db" \
		-x "*.db-journal" \
		-x "*.db-wal" \
		-x "*.db-shm" \
		-x "*.pyc" \
		-x ".git/*" \
		-x "exports/*" \
		-x "workspace/*"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "node_modules" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .venv apps/web/dist
	rm -f *.db *.db-journal *.db-wal *.db-shm
	rm -rf exports/ workspace/
