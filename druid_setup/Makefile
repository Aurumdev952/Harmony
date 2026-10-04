ENV_FILE=.env
ENV_COMMON=environment/common.env

PROJECT_NAME=druid
LOGS_ARGS ?= -f -n 1000

include $(ENV_FILE)
# Secrets live in $(ENV_FILE) only; Compose reads them from the environment.
export DRUID_POSTGRES_PASSWORD DRUID_POSTGRES_IMAGE DRUID_BIND_ADDRESS

default:
	@echo "Please specify a target to make"

# Runs before anything starts. Compose's ${VAR:?} only catches an empty value,
# and the old default password is public.
check_secrets:
	@case "$$(printf '%s' "$$DRUID_POSTGRES_PASSWORD" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')" in \
		''|foolishpassword) \
			echo "DRUID_POSTGRES_PASSWORD in $(ENV_FILE) is empty or the old default; set a random value (openssl rand -hex 32) and change it in Postgres with ALTER USER first" >&2; \
			exit 1;; \
	esac
	@if [ -n "$$DRUID_POSTGRES_IMAGE" ] && ! printf '%s\n' "$$DRUID_POSTGRES_IMAGE" | \
		grep -Eqx '[a-z0-9./_-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}'; then \
		echo "DRUID_POSTGRES_IMAGE in $(ENV_FILE) must be pinned as name:tag@sha256:<digest>; copy a line from the comment in the Compose file" >&2; \
		exit 1; \
	fi

single_server_up: check_secrets
	@cd single && \
		DOCKER_HOST=$(SINGLE_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		--env-file environment/common.env up -d

single_server_down:
	@cd single && \
		DOCKER_HOST=$(SINGLE_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		--env-file environment/common.env down

single_server_logs:
	@cd single && \
		DOCKER_HOST=$(SINGLE_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		--env-file environment/common.env logs $(LOGS_ARGS)

cluster_server_up: check_secrets
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_MASTER_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-master.yml \
		--env-file cluster.env up -d
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_DATA_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-data.yml \
		--env-file cluster.env up -d
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_QUERY_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-query.yml \
		--env-file cluster.env up -d

cluster_server_down:
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_MASTER_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-master.yml \
		--env-file cluster.env down
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_DATA_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-data.yml \
		--env-file cluster.env down
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_QUERY_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-query.yml \
		--env-file cluster.env down
