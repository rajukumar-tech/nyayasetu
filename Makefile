.PHONY: up seed test test-backend test-frontend coverage train eval

up:
	docker compose up -d --build

seed:
	docker compose exec api python -m app.seed --reset

test: test-backend

test-backend:
	cd backend && python -m pytest

coverage:
	cd backend && python -m pytest --cov=app.eligibility --cov=app.timeline --cov-branch --cov-report=term-missing

test-frontend:
	cd frontend && npx playwright test

train:
	python ml/train_er.py && python ml/train_delay_model.py

eval:
	cd backend && python -m app.evaluation
