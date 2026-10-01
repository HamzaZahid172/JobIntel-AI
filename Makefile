.PHONY: up down test lint data-up
up:
	docker compose up --build

down:
	docker compose down

test:
	cd backend && pytest -q
	cd frontend && npm test -- --run

data-up:
	docker compose --profile data up --build
