include Makefile.test
.PHONY: apply-migrations auto-migrations

apply-migrations:
	@alembic upgrade head

auto-migrations:
	@echo "Enter migration name:" && read name && alembic revision --autogenerate -m "$$name"
