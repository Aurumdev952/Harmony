ENV_FILE?=.env
-include $(ENV_FILE)

COMMIT?=main
DOCKER_HOST?=ssh://$(WEB_REMOTE)
SERVICE?=
PROJECT_NAME?=harmony-web

ACTIVATE_VENV := $(if $(DEV), -c "source venv/bin/activate && /bin/bash",)
DEV_OVERRIDE := $(if $(DEV), -f docker-compose.dev.yaml,)
DB_OVERRIDE := $(if $(DB), -f docker-compose.db.yaml,)
LOCAL_OVERRIDE := $(if $(LOCAL), -f docker-compose.local.yaml,)
PROD_OVERRIDE := $(if $(PROD), -f docker-compose.prod.yaml,)
OVERRIDES := $(DB_OVERRIDE)$(LOCAL_OVERRIDE)$(DEV_OVERRIDE)$(PROD_OVERRIDE)
COMPOSE_COMMAND := DOCKER_HOST=$(DOCKER_HOST) docker compose -p $(PROJECT_NAME) --env-file $(ENV_FILE) -f docker-compose.yaml $(OVERRIDES)

# help command copied from https://dwmkerr.com/makefile-help-command/
help: # Show help for each of the Makefile recipes.
	@grep -E '^[a-zA-Z0-9 -_]+:.*#'  Makefile | sort | while read -r l; do printf "\033[1;32m$$(echo $$l | cut -f 1 -d':')\033[00m:$$(echo $$l | cut -f 2- -d'#')\n"; done

configure:	
	scp ./prod/nginx/nginx_vhost_default_location $(WEB_REMOTE):${NGINX_VHOST}

lint-python: # Ruff: the whole tree for syntax errors and undefined names, plus lint and format checks on the Python files changed with respect to main (`make lint-python COMMIT=HEAD~1` for the last commit).
	ci/lint_python.sh $(COMMIT)

lint-js: # Lint only the js and jsx files that have changed on this branch, with respect to main. (You can run `make lint-js COMMIT=<my-commit>` e.g. `make lint-js COMMIT=my-other-branch` to lint the files that have changed with respect to my-other-branch.)
	COMMIT=$(COMMIT) ./scripts/lint_js.sh

lint: lint-python lint-js # Lint only the python, js and jsx files that have changed on this branch, with respect to main. (You can run `make lint COMMIT=<my-commit>` e.g. `make lint COMMIT=HEAD~1` to lint the files that have changed on the last commit.)
	
format-python: # Ruff: fix and format the Python files changed with respect to main (`make format-python COMMIT=origin/main`).
	ci/lint_python.sh --fix $(COMMIT)

build: # Build docker images (for development and production) using docker compose.
	docker compose --env-file $(ENV_FILE) -f docker-compose.build.yaml build $(SERVICE)


push: # Push the images built by `make build` to $DOCKER_NAMESPACE (default ghcr.io/zenysis).
	docker compose --env-file $(ENV_FILE) -f docker-compose.build.yaml push $(or $(SERVICE),web-client web-server web etl-pipeline)

convert: # Use the "docker compose config" command to render the compose file. (Useful to see the impact of environment variables.) 
	$(COMPOSE_COMMAND) config

create-db-setup-script: # Create the db setup script.
	$(COMPOSE_COMMAND) run --rm web /bin/bash -c "ZEN_DB_LOG_ONLY=1 ./scripts/create_deployment_database.sh ${POSTGRES_HOST} ${POSTGRES_USER} ${INSTANCE_DB_NAME}"

create-admin-user: # Create an admin user.
	$(COMPOSE_COMMAND) run --rm web /bin/bash -c "./scripts/create_user.py --username=${ADMIN_USERNAME} --password=${ADMIN_PASSWORD} --first_name=${ADMIN_FIRSTNAME} --last_name=${ADMIN_LASTNAME} --site_admin"

dev-prepare-database: # Prepare database. Not something you can run in production. This is only for local development.
	docker compose --env-file $(ENV_FILE) -f docker-compose.yaml -f docker-compose.dev.yaml run --rm web /bin/bash -c "source venv/bin/activate && yarn init-db $(ZEN_ENV) --populate_indicators"

exec-bash: # Connect to a running container
	$(COMPOSE_COMMAND) exec $(SERVICE) /bin/bash

down: # Stop all containers.
	$(COMPOSE_COMMAND) down $(SERVICE)

logs: # Tail the logs of all containers.
	$(COMPOSE_COMMAND) logs $(SERVICE) -f --tail 100

minio-server-up: # Start the minio server container.
	DOCKER_HOST=$(DOCKER_HOST) docker compose --env-file $(ENV_FILE) -f docker-compose.minio.yaml up --detach

minio-server-down: # Stop the minio server container.
	DOCKER_HOST=$(DOCKER_HOST) docker compose --env-file $(ENV_FILE) -f docker-compose.minio.yaml down

mypy: # Type-check with the [tool.mypy] settings in pyproject.toml.
	uv run --locked mypy

test: # Run the Python suites as CI does: each tests/ suite in its own process on the uv.lock environment.
	ci/pytest_suites.sh

postgres-psql:
	$(COMPOSE_COMMAND) exec postgres psql -h ${POSTGRES_HOST} -U ${POSTGRES_USER} ${POSTGRES_DB}

ps:
	$(COMPOSE_COMMAND) ps

restart: # Restart a container.
	$(COMPOSE_COMMAND) restart $(SERVICE)

stop: # Stop a container.
	$(COMPOSE_COMMAND) stop $(SERVICE)

up: # Start all containers.
	$(COMPOSE_COMMAND) up $(SERVICE) --detach

up-no-detach: # Start all containers, but don't detach.
	$(COMPOSE_COMMAND) up $(SERVICE)

up-dev-pipeline: # Start the dev pipeline.
	COMMAND=$(COMMAND) $(COMPOSE_COMMAND) up pipeline

up-pipeline:
	DOCKER_HOST=$(DOCKER_HOST) docker compose --env-file $(ENV_FILE) -f docker-compose.pipeline.yaml up

bash-pipeline:
	DOCKER_HOST=$(DOCKER_HOST) docker compose --env-file $(ENV_FILE) -f docker-compose.pipeline.yaml run --rm etl-pipeline /bin/bash -c "source venv/bin/activate && /bin/bash"

bash-dev-pipeline:
	$(COMPOSE_COMMAND) run --rm pipeline /bin/bash -c "source venv/bin/activate && /bin/bash"

bash-web:
	$(COMPOSE_COMMAND) run --rm web /bin/bash $(ACTIVATE_VENV)

upgrade-database:
	$(COMPOSE_COMMAND) run --rm web /bin/bash -c "./scripts/upgrade_database.sh"

populate-query-models:
	$(COMPOSE_COMMAND) run --rm web /bin/bash -c "./scripts/data_catalog/populate_query_models_from_config.py"

run-bash: # Bash into a container
	$(COMPOSE_COMMAND) run --rm $(SERVICE) /bin/bash
