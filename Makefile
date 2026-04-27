.PHONY: install dev test zip clean

install:
	pip install -r requirements.txt
	cd apps/web && npm install

dev:
	cd apps/api && python -m uvicorn main:app --reload --port 8000 &
	cd apps/web && npm run dev

test:
	python -m pytest tests/ -v

zip:
	zip -r mini-openclaw.zip . \
		-x "node_modules/*" \
		-x ".venv/*" \
		-x "venv/*" \
		-x "__pycache__/*" \
		-x "*/__pycache__/*" \
		-x ".env" \
		-x "*.db" \
		-x "*.db-journal" \
		-x "exports/*" \
		-x ".git/*" \
		-x "apps/web/dist/*" \
		-x "apps/web/node_modules/*"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "node_modules" -exec rm -rf {} + 2>/dev/null || true
	rm -f *.db
	rm -rf exports/
