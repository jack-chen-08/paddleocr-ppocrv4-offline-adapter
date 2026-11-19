check:
	python -m pytest -q

evidence:
	bash tools/make_evidence.sh

dev:
	uvicorn app.main:app --reload --port 8000
