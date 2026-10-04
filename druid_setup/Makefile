ENV_FILE=.env
ENV_COMMON=environment/common.env
CLUSTER_ENV=$(CURDIR)/cluster/cluster.env

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

# Druid has no authentication, so its ports must never listen on every
# interface. $(1) is the address variable. Like Compose, take it from the
# environment first and from the env file $(2) otherwise.
define check_bind_address
	@value="$${$(1)-$$(sed -n 's/^$(1)=//p' $(2) | tail -n 1)}"; \
	case "$$(printf '%s' "$$value" | tr -d '[:space:]')" in \
		''|0.0.0.0|::|'[::]') \
			echo "$(1) is empty or a wildcard address; set it to this host's private IP, and firewall Druid's ports to the hosts that call them" >&2; \
			exit 1;; \
	esac
endef

check_single_bind_address:
	$(call check_bind_address,DRUID_BIND_ADDRESS,/dev/null)

check_cluster_bind_addresses:
	$(call check_bind_address,DRUID_MASTER_HOST,$(CLUSTER_ENV))
	$(call check_bind_address,DRUID_DATA_HOST,$(CLUSTER_ENV))
	$(call check_bind_address,DRUID_QUERY_HOST,$(CLUSTER_ENV))

single_server_up: check_secrets check_single_bind_address
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

cluster_server_up: check_secrets check_cluster_bind_addresses
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_MASTER_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-master.yml \
		--env-file $(CLUSTER_ENV) up -d
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_DATA_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-data.yml \
		--env-file $(CLUSTER_ENV) up -d
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_QUERY_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-query.yml \
		--env-file $(CLUSTER_ENV) up -d

cluster_server_down:
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_MASTER_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-master.yml \
		--env-file $(CLUSTER_ENV) down
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_DATA_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-data.yml \
		--env-file $(CLUSTER_ENV) down
	@cd cluster && \
		DOCKER_HOST=$(CLUSTER_QUERY_SERVER_DOCKER_HOST) \
		docker compose --project-name $(PROJECT_NAME) \
		-f docker-compose-query.yml \
		--env-file $(CLUSTER_ENV) down
