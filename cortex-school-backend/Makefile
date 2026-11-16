.PHONY: run run-test

run:
	@ENVIRONMENT=development docker compose -p docker -f docker/docker-compose.yml --env-file docker/.env up -d --build

run-test:
	@ENVIRONMENT=testing docker compose -p backend_test -f docker/docker-compose.yml --env-file docker/.env up -d --build
